import tempfile
from datetime import date
from pathlib import Path
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from app.db.engine import SessionLocal
from app.db import models
from app.ingest import oi_diff, bot_eod, hot_chains, darkpool_eod, stock_screener_eod
from app.ingest.types import ParsedCSV
from app.features.build_v0 import build_feature_row
from app.regime.classify_v0 import classify
from app.plans.build_plan_v0 import build_plan
from app.utils.hashing import sha256_file
from app.utils.time import parse_date

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
