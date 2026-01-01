import tempfile
from datetime import date
from pathlib import Path
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.api.ws import notify_decision, notify_log
from app.briefs.generate_v1 import generate_briefs
from app.db.engine import SessionLocal
from app.db import models
from app.ecology.compute_v0 import compute_ecology_state
from app.features.build_v0 import build_feature_row
from app.features.build_v1 import build_feature_row_v1
from app.ingest import oi_diff, bot_eod, hot_chains, darkpool_eod, stock_screener_eod
from app.ingest.types import ParsedCSV
from app.regime.classify_v1_ensemble import classify_ensemble
from app.regime.classify_v0 import classify
from app.plans.build_plan_v0 import build_plan
from app.stability.report_v1 import build_stability_snapshot
from app.utils.hashing import sha256_file
from app.utils.time import parse_date
from app.backtest.config import BacktestConfig
from app.backtest.engine import OptionsBacktester
from app.backtest.data_provider import MockDataProvider
from app.db.models import BacktestRun, SimulatedTrade, DailyEquityCurve

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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


def _aggregate_for_session(session_id: str, db: Session) -> Dict[str, Dict[str, Dict[str, float]]]:
    per_underlying: Dict[str, Dict[str, Dict[str, float]]] = {}
    files = db.query(models.RawFile).filter(models.RawFile.session_id == session_id).all()
    for rf in files:
        if not rf.extras or "rows" not in rf.extras:
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


@router.post("/compute/v0")
def compute_v0(
    session_id: str = Form(...),
    asof_date: str = Form(...),
    db: Session = Depends(get_db),
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
