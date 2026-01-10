import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request
from sqlalchemy.orm import Session

from app.anomalies import compute_anomalies_for_session, ScoredAnomaly, TickerRollup
from app.analysis.correlations_v1 import compute_and_persist_correlations_v1
from app.api.auth import (
    AuthenticatedUser,
    Capability,
    capabilities_for_user,
    get_current_user,
    require_capability,
)
from app.api.ws import notify_decision, notify_log
from app.briefs.generate_v1 import generate_briefs
from app.db.engine import SessionLocal
from app.db import models
from app.settings import get_settings
from app.ecology.compute_v0 import compute_ecology_state
from app.features.build_v0 import build_feature_row
from app.features.build_v1 import build_feature_row_v1
from app.ingest import oi_diff, bot_eod, hot_chains, darkpool_eod, stock_screener_eod, options_flow
from app.ingest.types import ParsedCSV
from app.regime.classify_v1_ensemble import classify_ensemble
from app.regime.classify_v0 import classify
from app.plans.build_plan_v0 import build_plan
from app.stability.report_v1 import build_stability_snapshot
from app.utils.hashing import sha256_file
from app.utils.time import parse_date
from app.ingest.local_files import import_local_options_flow_file
from app.options_signals import service as options_signals_service
from app.backtest.config import BacktestConfig
from app.backtest.engine import OptionsBacktester
from app.backtest.data_provider import MockDataProvider
from app.db.models import BacktestRun, SimulatedTrade, DailyEquityCurve

router = APIRouter()


def _parse_csv_ints(value: str | None, *, default: list[int]) -> list[int]:
    if not value:
        return default
    out: list[int] = []
    for part in str(value).split(","):
        part = part.strip()
        if not part:
            continue
        try:
            v = int(part)
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return out or default


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/dev/local-file-text")
def dev_local_file_text(
    request: Request,
    path: str = Query(..., description="Absolute path to a local file (dev-only)"),
):
    """Dev-only helper to load CSV/text files from the backend machine.

    Disabled by default. Enable with env var `UW_DEV_LOCAL_FILE_READ_ENABLED=true`.
    Also restricted to localhost clients to avoid accidental exposure.
    """

    settings = get_settings()
    if not getattr(settings, "dev_local_file_read_enabled", False):
        raise HTTPException(status_code=403, detail="Dev local file read is disabled")

    client_host = getattr(getattr(request, "client", None), "host", None)
    if client_host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Dev local file read is restricted to localhost")

    p = Path(path)
    if not p.is_absolute():
        raise HTTPException(status_code=400, detail="Path must be absolute")
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    # Only allow reading small CSV/text files.
    suffix = p.suffix.lower()
    if suffix not in {".csv", ".txt"}:
        raise HTTPException(status_code=400, detail="Only .csv or .txt files are allowed")

    max_bytes = int(getattr(settings, "dev_local_file_read_max_bytes", 2_000_000) or 2_000_000)
    try:
        size = p.stat().st_size
    except OSError:
        raise HTTPException(status_code=400, detail="Could not stat file")
    if size > max_bytes:
        raise HTTPException(status_code=413, detail=f"File too large (>{max_bytes} bytes)")

    try:
        # utf-8-sig handles BOM; errors=replace keeps it robust.
        text = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        raise HTTPException(status_code=400, detail="Could not read file")

    return {"path": str(p), "bytes": size, "text": text}


@router.post("/sessions")
def create_session(
    session_date: str = Form(...),
    strategy_mode: models.StrategyMode = Form(models.StrategyMode.INDEX_EOD),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        parsed_date = parse_date(session_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session = models.Session(date=parsed_date, strategy_mode=strategy_mode, notes=notes)
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"session_id": str(session.session_id), "date": session.date}


@router.get("/sessions/latest")
def get_latest_session(db: Session = Depends(get_db)):
    session = db.query(models.Session).order_by(models.Session.date.desc()).first()
    if not session:
        raise HTTPException(status_code=404, detail="No sessions found")
    return {"session_id": str(session.session_id), "date": session.date, "strategy_mode": session.strategy_mode}


@router.get("/sessions/{session_id}/capabilities")
def get_session_capabilities(
    session_id: str,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(get_current_user),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "role": user.role.value,
        "capabilities": capabilities_for_user(user),
    }


@router.post("/sessions/ensure")
def ensure_session(
    session_date: str = Form(...),
    strategy_mode: models.StrategyMode = Form(models.StrategyMode.INDEX_EOD),
    db: Session = Depends(get_db),
):
    try:
        parsed_date = parse_date(session_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session = db.query(models.Session).filter(models.Session.date == parsed_date).first()
    if not session:
        session = models.Session(date=parsed_date, strategy_mode=strategy_mode)
        db.add(session)
        db.commit()
        db.refresh(session)
    
    return {"session_id": str(session.session_id), "date": session.date}


def _dispatch_parser(source: models.RawSource, path: Path) -> ParsedCSV:
    if source == models.RawSource.OI_DIFF:
        return oi_diff.parse_oi_diff(path)
    if source == models.RawSource.BOT_EOD:
        return bot_eod.parse_bot_eod(path)
    if source == models.RawSource.OPTIONS_FLOW:
        return options_flow.parse_options_flow(path)
    if source == models.RawSource.HOT_CHAINS:
        return hot_chains.parse_hot_chains(path)
    if source == models.RawSource.DARKPOOL_EOD:
        return darkpool_eod.parse_darkpool(path)
    if source == models.RawSource.STOCK_SCREENER:
        return stock_screener_eod.parse_stock_screener(path)
    raise HTTPException(status_code=400, detail=f"Unsupported source {source}")


@router.post("/import/{source}")
def import_csv(
    source: models.RawSource,
    session_id: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    parsed = _dispatch_parser(source, tmp_path)
    checksum = sha256_file(tmp_path)
    raw_file = models.RawFile(
        session_id=session_id,
        source=source,
        filename=file.filename,
        sha256=checksum,
        rows=len(parsed.rows),
        extras={"headers": parsed.headers, "rows": parsed.rows},
        parse_status=models.ParseStatus.OK if not parsed.errors else models.ParseStatus.ERROR,
        error_message=";".join(parsed.errors) if parsed.errors else None,
    )
    db.add(raw_file)
    db.add(models.LogMessage(session_id=session_id, level=models.LogLevel.INFO, message=f"Imported {file.filename}", context={"source": source.value, "rows": len(parsed.rows)}))
    db.commit()
    db.refresh(raw_file)
    tmp_path.unlink(missing_ok=True)
    return {"file_id": str(raw_file.file_id), "rows": raw_file.rows}


@router.post("/import_local/options_flow")
def import_local_options_flow(payload: Dict[str, Any], db: Session = Depends(get_db)):
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="filename is required")
    try:
        result = import_local_options_flow_file(db=db, filename=filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"sessions_touched": result.sessions_touched, "rows_imported": result.rows_imported}


def _options_signals_quality(db: Session, trade_date: date) -> Dict[str, Any] | None:
    row = (
        db.query(models.OptionsSignalsDataQualityDaily)
        .filter(models.OptionsSignalsDataQualityDaily.trade_date == trade_date)
        .first()
    )
    if not row:
        return None
    return {
        "trade_date": row.trade_date.isoformat(),
        "total_trades": row.total_trades,
        "canceled_filtered": row.canceled_filtered,
        "trades_missing_nbbo": row.trades_missing_nbbo,
        "symbols_missing_ohlcv": row.symbols_missing_ohlcv,
        "symbols_missing_news": row.symbols_missing_news,
        "freshness": row.freshness_json,
    }


def _aggregate_for_session(session_id: str, db: Session) -> Dict[str, Dict[str, Dict[str, float]]]:
    per_underlying: Dict[str, Dict[str, Dict[str, float]]] = {}
    # Users may import the same CSV multiple times (e.g., reruns, retries). To keep
    # aggregation stable and avoid double-counting, only consider the most recent
    # import for each (source, filename) pair.
    files = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.parse_status == models.ParseStatus.OK)
        .order_by(models.RawFile.imported_at.desc())
        .all()
    )
    seen: set[tuple[models.RawSource, str]] = set()
    deduped: list[models.RawFile] = []
    for rf in files:
        key = (rf.source, rf.filename)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(rf)

    files = deduped
    for rf in files:
        if not rf.extras:
            continue
        # Large-file imports may store precomputed aggregates to avoid huge JSON payloads.
        if isinstance(rf.extras, dict) and "agg" in rf.extras and isinstance(rf.extras.get("agg"), dict):
            agg = rf.extras["agg"]
            key = ""
            if rf.source == models.RawSource.OI_DIFF:
                key = "oi"
            elif rf.source in (models.RawSource.BOT_EOD, models.RawSource.OPTIONS_FLOW):
                key = "bot"
            elif rf.source == models.RawSource.HOT_CHAINS:
                key = "hot_chains"
            elif rf.source == models.RawSource.DARKPOOL_EOD:
                key = "darkpool"
            elif rf.source == models.RawSource.STOCK_SCREENER:
                key = "stock_screener"
            else:
                continue

            for underlying, metrics in agg.items():
                per_underlying.setdefault(underlying, {})
                if key in per_underlying[underlying] and isinstance(per_underlying[underlying][key], dict):
                    existing = per_underlying[underlying][key]
                    merged = dict(existing)
                    for mk, mv in metrics.items():
                        try:
                            merged[mk] = float(merged.get(mk, 0) or 0) + float(mv or 0)
                        except (ValueError, TypeError):
                            merged[mk] = mv
                    per_underlying[underlying][key] = merged
                else:
                    per_underlying[underlying][key] = metrics
            continue

        if "rows" not in rf.extras:
            continue
        rows = rf.extras["rows"]
        agg_fn = None
        key = ""
        if rf.source == models.RawSource.OI_DIFF:
            agg_fn = oi_diff.aggregate
            key = "oi"
        elif rf.source == models.RawSource.BOT_EOD:
            agg_fn = bot_eod.aggregate
            key = "bot"
        elif rf.source == models.RawSource.OPTIONS_FLOW:
            agg_fn = options_flow.aggregate
            # Map into the existing 'bot' aggregate bucket so features don't need to change.
            key = "bot"
        elif rf.source == models.RawSource.HOT_CHAINS:
            agg_fn = hot_chains.aggregate
            key = "hot_chains"
        elif rf.source == models.RawSource.DARKPOOL_EOD:
            agg_fn = darkpool_eod.aggregate
            key = "darkpool"
        elif rf.source == models.RawSource.STOCK_SCREENER:
            agg_fn = stock_screener_eod.aggregate
            key = "stock_screener"
        else:
            continue

        agg = agg_fn(rows)
        for underlying, metrics in agg.items():
            per_underlying.setdefault(underlying, {})
            # If multiple sources map into the same logical bucket (e.g. BOT_EOD + OPTIONS_FLOW),
            # merge numeric metrics instead of overwriting.
            if key in per_underlying[underlying] and isinstance(per_underlying[underlying][key], dict):
                existing = per_underlying[underlying][key]
                merged = dict(existing)
                for mk, mv in metrics.items():
                    try:
                        merged[mk] = float(merged.get(mk, 0) or 0) + float(mv or 0)
                    except (ValueError, TypeError):
                        merged[mk] = mv
                per_underlying[underlying][key] = merged
            else:
                per_underlying[underlying][key] = metrics
    return per_underlying


def _serialize_brief(brief: models.DailyBrief) -> Dict[str, Any]:
    return {
        "brief_id": str(brief.brief_id),
        "session_id": str(brief.session_id),
        "date": str(brief.date),
        "brief_type": brief.brief_type.value if brief.brief_type else None,
        "underlying_universe": brief.underlying_universe.value if brief.underlying_universe else None,
        "entries": brief.entries,
        "generated_at": brief.generated_at.isoformat() if brief.generated_at else None,
        "brief_version": brief.brief_version,
    }


def _serialize_ensemble(decision: models.EnsembleDecision) -> Dict[str, Any]:
    return {
        "ensemble_id": str(decision.ensemble_id),
        "session_id": str(decision.session_id),
        "underlying": decision.underlying,
        "asof_date": str(decision.asof_date),
        "ensemble_label": decision.ensemble_label.value if decision.ensemble_label else None,
        "ensemble_confidence": float(decision.ensemble_confidence) if decision.ensemble_confidence is not None else None,
        "horizon_weights": decision.horizon_weights,
        "component_votes": decision.component_votes,
        "stability_metrics": decision.stability_metrics,
        "ensemble_version": decision.ensemble_version,
        "computed_at": decision.computed_at.isoformat() if decision.computed_at else None,
    }


def _copy_attrs(source: Any, target: Any):
    for key, value in source.__dict__.items():
        if key.startswith("_"):
            continue
        setattr(target, key, value)


def _serialize_anomaly_scored(ev: ScoredAnomaly) -> Dict[str, Any]:
    return {
        "source": ev.source.value,
        "ticker": ev.ticker,
        "event_key": ev.event_key,
        "severity_score": ev.severity_score,
        "ensemble_score": ev.ensemble_score,
        "reason_codes": ev.reason_codes,
        "feature_payload": ev.feature_payload,
        "raw_ref": ev.raw_ref,
    }


def _serialize_anomaly_model(ev: models.AnomalyEvent) -> Dict[str, Any]:
    return {
        "source": ev.source.value if ev.source else None,
        "ticker": ev.ticker,
        "event_key": ev.event_key,
        "severity_score": float(ev.severity_score) if ev.severity_score is not None else None,
        "ensemble_score": float(ev.ensemble_score) if ev.ensemble_score is not None else None,
        "reason_codes": ev.reason_codes or [],
        "feature_payload": ev.feature_payload,
        "raw_ref": ev.raw_ref,
        "computed_at": ev.computed_at.isoformat() if ev.computed_at else None,
    }


def _serialize_rollup(ru: TickerRollup | models.AnomalyTickerRollup) -> Dict[str, Any]:
    if isinstance(ru, TickerRollup):
        return {
            "ticker": ru.ticker,
            "severity_score": ru.severity_score,
            "ensemble_score": ru.ensemble_score,
            "reason_codes": ru.reason_codes,
            "feature_payload": ru.feature_payload,
            "raw_ref": ru.raw_ref,
        }
    return {
        "ticker": ru.ticker,
        "severity_score": float(ru.severity_score) if ru.severity_score is not None else None,
        "ensemble_score": float(ru.ensemble_score) if ru.ensemble_score is not None else None,
        "reason_codes": ru.reason_codes or [],
        "feature_payload": ru.feature_payload,
        "raw_ref": ru.raw_ref,
        "computed_at": ru.computed_at.isoformat() if ru.computed_at else None,
    }


def _parse_optional_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {value}") from exc


@router.post("/compute/v0")
def compute_v0(
    session_id: str = Form(...),
    asof_date: str = Form(...),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_capability(Capability.COMPUTE_V0)),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        parsed_date = parse_date(asof_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    per_underlying = _aggregate_for_session(session_id, db)
    decisions = []
    for underlying, aggregates in per_underlying.items():
        feature = (
            db.query(models.FeaturesUnderlyingDay)
            .filter_by(session_id=session_id, underlying=underlying, asof_date=parsed_date)
            .one_or_none()
        )
        feature_row = build_feature_row(session_id, underlying, parsed_date, aggregates)
        if feature:
            for key, value in feature_row.__dict__.items():
                if key.startswith("_"):
                    continue
                setattr(feature, key, value)
        else:
            feature = feature_row
            db.add(feature)
        decision = (
            db.query(models.RegimeDecision)
            .filter_by(session_id=session_id, underlying=underlying, asof_date=parsed_date)
            .one_or_none()
        )
        decision_row = classify(feature)
        if decision:
            for key, value in decision_row.__dict__.items():
                if key.startswith("_"):
                    continue
                setattr(decision, key, value)
        else:
            decision = decision_row
            db.add(decision)
        plan = (
            db.query(models.Plan)
            .filter_by(session_id=session_id, underlying=underlying, trade_date=parsed_date)
            .one_or_none()
        )
        plan_row = build_plan(decision, trade_date=parsed_date)
        if plan:
            for key, value in plan_row.__dict__.items():
                if key.startswith("_"):
                    continue
                setattr(plan, key, value)
        else:
            plan = plan_row
            db.add(plan)
        decisions.append(
            {
                "underlying": underlying,
                "regime": decision.regime_label.value,
                "confidence": decision.confidence_tier.value,
            }
        )

    db.add(
        models.LogMessage(
            session_id=session_id,
            level=models.LogLevel.INFO,
            message="Computed v0 features/regimes",
            context={"count": len(per_underlying)},
        )
    )
    db.commit()
    return {"decisions": decisions}


@router.post("/compute/ecology_v0")
def compute_ecology_v0(
    session_id: str = Form(...),
    asof_date: str = Form(...),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_capability(Capability.COMPUTE_ECOLOGY)),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        parsed_date = parse_date(asof_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    updated = compute_ecology_state(db, session, parsed_date)
    payload = [
        {
            "underlying": d.underlying,
            "dominant_horizon_hint": d.dominant_horizon_hint.value if d.dominant_horizon_hint else None,
            "ecology_state": d.ecology_state,
        }
        for d in updated
    ]
    if updated:
        notify_decision({"type": "ecology", "session_id": session_id, "count": len(updated)})
    return {"updated": len(updated), "ecology": payload}


@router.post("/briefs/generate_v1")
def generate_briefs_v1(
    session_id: str = Form(...),
    asof_date: str | None = Form(None),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_capability(Capability.GENERATE_BRIEFS)),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        parsed_date = parse_date(asof_date) if asof_date else session.date
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        briefs = generate_briefs(db, session, parsed_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.add(
        models.LogMessage(
            session_id=session_id,
            level=models.LogLevel.INFO,
            message="Generated v1 briefs",
            context={"count": len(briefs), "date": str(parsed_date)},
        )
    )
    db.commit()
    payload = [_serialize_brief(b) for b in briefs]
    notify_decision({"type": "briefs", "session_id": session_id, "count": len(briefs)})
    return {"briefs": payload}


@router.post("/compute/v1")
def compute_v1(
    session_id: str = Form(...),
    asof_date: str = Form(...),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_capability(Capability.COMPUTE_V1)),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    try:
        parsed_date = parse_date(asof_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    per_underlying = _aggregate_for_session(session_id, db)
    ensembles: list[Dict[str, Any]] = []
    for underlying, aggregates in per_underlying.items():
        feature_row = build_feature_row_v1(db, session_id, underlying, parsed_date, aggregates)
        existing_feature = (
            db.query(models.FeaturesUnderlyingDay)
            .filter_by(session_id=session_id, underlying=underlying, asof_date=parsed_date, feature_version="v1")
            .one_or_none()
        )
        if existing_feature:
            _copy_attrs(feature_row, existing_feature)
            feature_row = existing_feature
        else:
            db.add(feature_row)

        ensemble_row = classify_ensemble(db, feature_row, parsed_date)
        existing_ensemble = (
            db.query(models.EnsembleDecision)
            .filter_by(session_id=session_id, underlying=underlying, asof_date=parsed_date)
            .one_or_none()
        )
        if existing_ensemble:
            _copy_attrs(ensemble_row, existing_ensemble)
            ensemble_row = existing_ensemble
        else:
            db.add(ensemble_row)
        ensembles.append(
            {
                "underlying": underlying,
                "ensemble_label": ensemble_row.ensemble_label.value,
                "ensemble_confidence": ensemble_row.ensemble_confidence,
                "horizon_weights": ensemble_row.horizon_weights,
            }
        )

    db.add(
        models.LogMessage(
            session_id=session_id,
            level=models.LogLevel.INFO,
            message="Computed v1 features/ensemble",
            context={"count": len(per_underlying)},
        )
    )
    db.commit()
    notify_decision({"type": "ensemble", "session_id": session_id, "count": len(ensembles)})
    return {"ensembles": ensembles}


@router.post("/compute/anomalies_v1")
def compute_anomalies_v1(
    session_id: str = Form(...),
    lookback_sessions: int = Form(30),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_capability(Capability.COMPUTE_ANOMALIES)),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    lookback = max(0, min(lookback_sessions, 180))
    result = compute_anomalies_for_session(db, session, lookback_sessions=lookback)
    events_payload = [_serialize_anomaly_scored(ev) for ev in result["events"][:100]]
    rollups_payload = [_serialize_rollup(r) for r in result["rollups"]]

    db.add(
        models.LogMessage(
            session_id=session_id,
            level=models.LogLevel.INFO,
            message="Computed anomaly review queue v1",
            context={"counts": result["summary"], "lookback_sessions": lookback},
        )
    )
    db.commit()
    notify_decision({"type": "anomalies_v1_complete", "session_id": session_id, "counts": result["summary"]})
    return {
        "summary": result["summary"],
        "events": events_payload,
        "rollups": rollups_payload,
    }


@router.post("/compute/correlations_v1")
def compute_correlations_v1(
    session_id: str = Form(...),
    lookback_sessions: int = Form(60),
    horizons: str = Form("1,3,5"),
    method: str = Form("spearman"),
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_capability(Capability.COMPUTE_CORRELATIONS)),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    lookback = max(0, min(int(lookback_sessions), 180))
    horizon_list = _parse_csv_ints(horizons, default=[1, 3, 5])

    try:
        payload = compute_and_persist_correlations_v1(
            db,
            session,
            lookback_sessions=lookback,
            horizons=horizon_list,
            method=method,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.add(
        models.LogMessage(
            session_id=session_id,
            level=models.LogLevel.INFO,
            message="Computed correlations v1",
            context={"lookback_sessions": lookback, "horizons": horizon_list, "method": method},
        )
    )
    db.commit()
    notify_decision({"type": "correlations_v1_complete", "session_id": session_id, "horizons": horizon_list})
    return payload


@router.get("/sessions/{session_id}/correlations")
def get_correlations(
    session_id: str,
    version: str = "v1",
    db: Session = Depends(get_db),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    q = db.query(models.CorrelationRun).filter(models.CorrelationRun.session_id == session_id)
    if version:
        q = q.filter(models.CorrelationRun.version == version)
    run = q.order_by(models.CorrelationRun.computed_at.desc()).first()
    if not run:
        return {"run": None}
    return {
        "run": {
            "run_id": str(run.run_id),
            "session_id": str(run.session_id),
            "asof_date": str(run.asof_date),
            "version": run.version,
            "computed_at": run.computed_at.isoformat() if run.computed_at else None,
            "params": run.params,
            "results": run.results,
        }
    }


@router.get("/sessions/{session_id}/anomalies")
def get_anomalies(
    session_id: str,
    ticker: str | None = None,
    source: models.RawSource | None = None,
    min_score: float = 0.0,
    start_time: str | None = None,
    end_time: str | None = None,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    query = db.query(models.AnomalyEvent).filter(models.AnomalyEvent.session_id == session_id)
    if ticker:
        query = query.filter(models.AnomalyEvent.ticker == ticker.upper())
    if source:
        query = query.filter(models.AnomalyEvent.source == source)
    if min_score:
        query = query.filter(models.AnomalyEvent.severity_score >= min_score)
    start_ts = _parse_optional_ts(start_time)
    end_ts = _parse_optional_ts(end_time)
    if start_ts:
        query = query.filter(models.AnomalyEvent.computed_at >= start_ts)
    if end_ts:
        query = query.filter(models.AnomalyEvent.computed_at <= end_ts)
    events = query.order_by(models.AnomalyEvent.severity_score.desc()).limit(limit).all()

    rollups = (
        db.query(models.AnomalyTickerRollup)
        .filter(models.AnomalyTickerRollup.session_id == session_id)
        .order_by(models.AnomalyTickerRollup.severity_score.desc())
        .all()
    )
    return {
        "events": [_serialize_anomaly_model(e) for e in events],
        "rollups": [_serialize_rollup(r) for r in rollups],
    }


@router.get("/sessions/{session_id}/summary")
def get_summary(session_id: str, db: Session = Depends(get_db)):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    features = db.query(models.FeaturesUnderlyingDay).filter_by(session_id=session_id).all()
    regimes = db.query(models.RegimeDecision).filter_by(session_id=session_id).all()
    plans = db.query(models.Plan).filter_by(session_id=session_id).all()
    return {
        "session": {"session_id": str(session.session_id), "date": str(session.date), "mode": session.strategy_mode.value},
        "features": [f"{f.underlying}:{f.feature_version}" for f in features],
        "regimes": [r.regime_label.value for r in regimes],
        "plans": [p.plan_type.value for p in plans],
    }


@router.get("/sessions/{session_id}/briefs")
def get_briefs(session_id: str, db: Session = Depends(get_db)):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    briefs = (
        db.query(models.DailyBrief)
        .filter(models.DailyBrief.session_id == session_id)
        .order_by(models.DailyBrief.date.desc(), models.DailyBrief.generated_at.desc())
        .all()
    )
    return {"briefs": [_serialize_brief(b) for b in briefs]}


@router.get("/sessions/{session_id}/ensemble")
def get_ensemble(session_id: str, db: Session = Depends(get_db)):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    decisions = (
        db.query(models.EnsembleDecision)
        .filter(models.EnsembleDecision.session_id == session_id)
        .order_by(models.EnsembleDecision.asof_date.desc(), models.EnsembleDecision.underlying.asc())
        .all()
    )
    return {"ensembles": [_serialize_ensemble(d) for d in decisions]}


@router.get("/sessions/{session_id}/regimes")
def get_regimes(session_id: str, db: Session = Depends(get_db)):
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    decisions = (
        db.query(models.RegimeDecision)
        .filter(models.RegimeDecision.session_id == session_id)
        .order_by(models.RegimeDecision.asof_date.desc(), models.RegimeDecision.underlying.asc())
        .all()
    )
    return {
        "regimes": [
            {
                "underlying": d.underlying,
                "asof_date": str(d.asof_date),
                "regime_label": d.regime_label.value if d.regime_label else None,
                "confidence_tier": d.confidence_tier.value if d.confidence_tier else None,
                "decision_version": d.decision_version,
                "dominant_horizon_hint": d.dominant_horizon_hint.value if d.dominant_horizon_hint else None,
                "ecology_state": d.ecology_state,
            }
            for d in decisions
        ]
    }


@router.post("/outcomes")
def post_outcome(
    trade_date: str = Form(...),
    underlying: str = Form(...),
    realized_label_manual: models.OutcomeLabel | None = Form(None),
    range_pct: float | None = Form(None),
    close_vs_open_pct: float | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
):
    try:
        parsed_date = parse_date(trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    outcome = (
        db.query(models.OutcomeDay)
        .filter_by(trade_date=parsed_date, underlying=underlying)
        .one_or_none()
    )
    if outcome:
        outcome.realized_label_manual = realized_label_manual
        outcome.range_pct = range_pct
        outcome.close_vs_open_pct = close_vs_open_pct
        outcome.notes = notes
    else:
        outcome = models.OutcomeDay(
            trade_date=parsed_date,
            underlying=underlying,
            realized_label_manual=realized_label_manual,
            range_pct=range_pct,
            close_vs_open_pct=close_vs_open_pct,
            notes=notes,
        )
        db.add(outcome)
    db.commit()
    return {"outcome_id": str(outcome.outcome_id)}


# Backtesting Routes

@router.post("/backtest/run")
def run_backtest(
    config: dict,
    db: Session = Depends(get_db)
):
    """
    Run a backtest with the provided configuration.
    """
    try:
        # Convert dict to BacktestConfig
        # We need to handle date parsing from strings
        if 'start_date' in config and isinstance(config['start_date'], str):
            config['start_date'] = parse_date(config['start_date'])
        if 'end_date' in config and isinstance(config['end_date'], str):
            config['end_date'] = parse_date(config['end_date'])
            
        bt_config = BacktestConfig.from_dict(config)
        
        # Initialize engine with mock data for now
        # In production, we'd choose provider based on config
        data_provider = MockDataProvider()
        
        engine = OptionsBacktester(bt_config, data_provider, db)
        run_record = engine.run()
        
        return {"run_id": str(run_record.run_id), "status": run_record.status}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/backtest/{run_id}")
def get_backtest_results(
    run_id: str,
    db: Session = Depends(get_db)
):
    """Get summary results for a backtest run."""
    run = db.query(BacktestRun).filter(BacktestRun.run_id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
        
    return {
        "id": str(run.run_id),
        "strategy": run.strategy_version,
        "status": run.status,
        "metrics": run.performance_summary,
        "dates": {
            "start": run.start_date,
            "end": run.end_date
        }
    }


@router.get("/backtest/{run_id}/trades")
def get_backtest_trades(
    run_id: str,
    db: Session = Depends(get_db)
):
    """Get list of trades for a backtest run."""
    trades = db.query(SimulatedTrade).filter(SimulatedTrade.backtest_run_id == run_id).all()
    return [
        {
            "symbol": t.symbol,
            "entry_date": t.entry_date,
            "exit_date": t.exit_date,
            "type": t.option_type,
            "strike": float(t.strike),
            "pnl": float(t.pnl),
            "pnl_pct": float(t.pnl_pct),
            "reason": t.exit_reason.value
        }
        for t in trades
    ]


@router.get("/backtest/{run_id}/equity")
def get_backtest_equity(
    run_id: str,
    db: Session = Depends(get_db)
):
    """Get daily equity curve for a backtest run."""
    curve = db.query(DailyEquityCurve).filter(DailyEquityCurve.backtest_run_id == run_id).order_by(DailyEquityCurve.date).all()
    return [
        {
            "date": c.date,
            "equity": float(c.portfolio_value),
            "drawdown_pct": float(c.drawdown_pct)
        }
        for c in curve
    ]


# ─────────────────────────────────────────────────────────────────────────────
# OUTLIER DETECTION ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────

from app.analysis.outlier_detection import (
    analyze_from_session_data,
    detect_zscore_outliers,
    detect_iqr_outliers,
    detect_preevent_manipulation,
    get_distribution_stats,
    load_oi_data,
)
from pydantic import BaseModel
from typing import Optional


class OutlierDetectionParams(BaseModel):
    zscore_threshold: float = 3.0
    iqr_multiplier: float = 1.5
    earnings_days: int = 14
    chain_pct: float = 0.20


@router.post("/analysis/outliers/detect")
def detect_outliers_from_session(
    session_id: str = Form(...),
    zscore_threshold: float = Form(3.0),
    iqr_multiplier: float = Form(1.5),
    earnings_days: int = Form(14),
    chain_pct: float = Form(0.20),
    baseline_days: int = Form(0),
    db: Session = Depends(get_db),
):
    """
    Run all outlier detection methods on OI data from a session.
    
    Methods:
    1. Z-Score: Flags OI changes >3σ from mean (99.7% confidence)
    2. IQR: Robust to skewed distributions, flags 1.5×IQR extremes  
    3. Pre-Event: OI spike + low volume + earnings proximity signals
    """
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    def _get_oi_rows_for_session(sid: str) -> list[dict]:
        files_local = db.query(models.RawFile).filter(
            models.RawFile.session_id == sid,
            models.RawFile.source == models.RawSource.OI_DIFF,
        ).all()
        rows_local: list[dict] = []
        for rf in files_local:
            if rf.extras and "rows" in rf.extras:
                rows_local.extend(rf.extras["rows"])
        return rows_local

    # Get OI data from session's raw files
    files = db.query(models.RawFile).filter(
        models.RawFile.session_id == session_id,
        models.RawFile.source == models.RawSource.OI_DIFF
    ).all()
    
    if not files:
        raise HTTPException(status_code=404, detail="No OI data found for session")
    
    # Aggregate all OI rows
    all_rows = _get_oi_rows_for_session(session_id)
    
    if not all_rows:
        raise HTTPException(status_code=404, detail="No OI rows found in session data")
    
    baseline_rows: list[dict] = []
    baseline_session_count = 0
    if baseline_days and baseline_days > 0:
        start = session.date - timedelta(days=baseline_days)
        baseline_sessions = (
            db.query(models.Session)
            .filter(models.Session.date >= start, models.Session.date < session.date)
            .order_by(models.Session.date.asc())
            .all()
        )
        baseline_session_count = len(baseline_sessions)
        for bs in baseline_sessions:
            baseline_rows.extend(_get_oi_rows_for_session(str(bs.session_id)))

    # Run analysis
    results = analyze_from_session_data(
        all_rows,
        zscore_threshold=zscore_threshold,
        iqr_multiplier=iqr_multiplier,
        earnings_days=earnings_days,
        chain_pct=chain_pct,
        baseline_oi_data=baseline_rows if baseline_rows else None,
    )

    if baseline_rows:
        results["baseline"] = {
            "days": baseline_days,
            "sessions": baseline_session_count,
            "rows": len(baseline_rows),
        }
    
    return results


@router.get("/analysis/outliers/available-dates")
def get_available_dates_for_outliers(db: Session = Depends(get_db)):
    """Get list of dates that have OI data available for outlier analysis."""
    sessions = db.query(models.Session).order_by(models.Session.date.desc()).all()
    
    available = []
    for session in sessions:
        oi_files = db.query(models.RawFile).filter(
            models.RawFile.session_id == session.session_id,
            models.RawFile.source == models.RawSource.OI_DIFF
        ).count()
        
        if oi_files > 0:
            available.append({
                "session_id": str(session.session_id),
                "date": str(session.date),
                "oi_file_count": oi_files
            })
    
    return {"available_dates": available}


@router.post("/analysis/outliers/upload-analyze")
def upload_and_analyze_outliers(
    file: UploadFile = File(...),
    zscore_threshold: float = Form(3.0),
    iqr_multiplier: float = Form(1.5),
    earnings_days: int = Form(14),
    chain_pct: float = Form(0.20),
):
    """
    Upload a CSV file and run outlier detection directly (without session).
    
    Accepts chain-oi-changes format CSV files.
    """
    import tempfile
    from pathlib import Path
    import pandas as pd
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.csv') as tmp:
        content = file.file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)
    
    try:
        df = load_oi_data(tmp_path)
        
        from app.analysis.outlier_detection import run_all_detection_methods
        results = run_all_detection_methods(
            df,
            zscore_threshold=zscore_threshold,
            iqr_multiplier=iqr_multiplier,
            earnings_days=earnings_days,
            chain_pct=chain_pct
        )
        
        return results
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get("/analysis/outliers/symbols/{session_id}")
def get_outlier_symbols_detail(
    session_id: str,
    symbol: str,
    db: Session = Depends(get_db),
):
    """Get detailed OI data for a specific symbol from session."""
    session = db.get(models.Session, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    files = db.query(models.RawFile).filter(
        models.RawFile.session_id == session_id,
        models.RawFile.source == models.RawSource.OI_DIFF
    ).all()
    
    symbol_rows = []
    for rf in files:
        if rf.extras and "rows" in rf.extras:
            for row in rf.extras["rows"]:
                if row.get("underlyingsymbol", "").strip().upper() == symbol.upper():
                    symbol_rows.append(row)
    
    return {"symbol": symbol, "rows": symbol_rows, "count": len(symbol_rows)}


# ─────────────────────────────────────────────────────────────────────────────
# OPTIONS SIGNALS DASHBOARD ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/options-signals/registry/features")
def options_signals_features_registry():
    return options_signals_service.get_feature_registry()


@router.get("/options-signals/registry/signals")
def options_signals_signals_registry():
    return options_signals_service.get_signal_registry()


@router.get("/options-signals/screener")
def options_signals_screener(
    date: str,
    signal: str = "BULL_FLOW",
    sector: str | None = None,
    min_liquidity: float | None = None,
    alerts_only: bool = False,
    db: Session = Depends(get_db),
):
    try:
        trade_date = parse_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = options_signals_service.screener_rows(
        db,
        trade_date=trade_date,
        signal_name=signal,
        sector=sector,
        min_liquidity=min_liquidity,
        alerts_only=alerts_only,
    )
    return {
        "rows": rows,
        "data_quality": _options_signals_quality(db, trade_date),
    }


@router.get("/options-signals/symbol/{ticker}/timeseries")
def options_signals_symbol_timeseries(
    ticker: str,
    from_date: str = Query(..., alias="from"),
    to: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
):
    try:
        start_date = parse_date(from_date)
        end_date = parse_date(to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = options_signals_service.symbol_timeseries(
        db,
        symbol=ticker.upper(),
        start_date=start_date,
        end_date=end_date,
    )
    return {"rows": rows, "data_quality": _options_signals_quality(db, end_date)}


@router.get("/options-signals/symbol/{ticker}/uoa")
def options_signals_symbol_uoa(
    ticker: str,
    date: str,
    db: Session = Depends(get_db),
):
    try:
        trade_date = parse_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = options_signals_service.symbol_uoa(db, symbol=ticker.upper(), trade_date=trade_date)
    return {"rows": rows, "data_quality": _options_signals_quality(db, trade_date)}


@router.get("/options-signals/symbol/{ticker}/alerts")
def options_signals_symbol_alerts(
    ticker: str,
    from_date: str = Query(..., alias="from"),
    to: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
):
    try:
        start_date = parse_date(from_date)
        end_date = parse_date(to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = options_signals_service.symbol_alerts(
        db,
        symbol=ticker.upper(),
        start_date=start_date,
        end_date=end_date,
    )
    return {"rows": rows, "data_quality": _options_signals_quality(db, end_date)}


@router.get("/options-signals/alerts")
def options_signals_alerts_range(
    from_date: str = Query(..., alias="from"),
    to: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
):
    try:
        start_date = parse_date(from_date)
        end_date = parse_date(to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = options_signals_service.alerts_range(db, start_date=start_date, end_date=end_date)
    return {"rows": rows, "data_quality": _options_signals_quality(db, end_date)}


@router.get("/options-signals/data-quality")
def options_signals_data_quality(
    from_date: str = Query(..., alias="from"),
    to: str = Query(..., alias="to"),
    db: Session = Depends(get_db),
):
    try:
        start_date = parse_date(from_date)
        end_date = parse_date(to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    rows = options_signals_service.data_quality_range(db, start_date=start_date, end_date=end_date)
    return {"rows": rows}
