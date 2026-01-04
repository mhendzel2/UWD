from __future__ import annotations

from datetime import date, datetime
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Tuple

from sqlalchemy.orm import Session

from app.db import models
from app.features.build_v0 import compute_from_aggregates
from app.ingest import bot_eod
from app.utils.underlying import derive_underlying

PERSISTENCE_WINDOW = 3
RANGE_WINDOW = 5
SWITCH_WINDOW = 10


def _recent_sessions(db: Session, asof_date: date, limit: int) -> List[models.Session]:
    return (
        db.query(models.Session)
        .filter(models.Session.date <= asof_date)
        .order_by(models.Session.date.desc())
        .limit(limit)
        .all()
    )


def _rows_for_session(db: Session, session_id: str, source: models.RawSource) -> List[Dict[str, Any]]:
    rf = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == source)
        .order_by(models.RawFile.imported_at.desc())
        .first()
    )
    if rf and rf.extras and "rows" in rf.extras:
        return rf.extras["rows"]
    return []


def _collect_rows(
    db: Session, asof_date: date, source: models.RawSource, limit: int
) -> List[Tuple[date, List[Dict[str, Any]]]]:
    sessions = _recent_sessions(db, asof_date, limit)
    collected: list[Tuple[date, List[Dict[str, Any]]]] = []
    for sess in sessions:
        rows = _rows_for_session(db, str(sess.session_id), source)
        if rows:
            collected.append((sess.date, rows))
    return list(reversed(collected))


def _top_symbols_from_oi(rows: List[Dict[str, Any]], underlying: str, top_n: int = 5) -> set[str]:
    filtered = []
    for row in rows:
        if (row.get("underlying_symbol") or row.get("ticker") or row.get("underlying")) not in (underlying, underlying.upper()):
            continue
        try:
            curr_oi = float(row.get("curr_oi", 0) or row.get("curr_open_interest", 0) or row.get("open_interest", 0) or 0)
        except (ValueError, TypeError):
            continue
        filtered.append((row.get("option_symbol") or row.get("symbol"), curr_oi))
    filtered.sort(key=lambda x: x[1] or 0, reverse=True)
    return {sym for sym, _ in filtered[:top_n] if sym}


def _top_symbols_from_hot(rows: List[Dict[str, Any]], underlying: str, top_n: int = 5) -> set[str]:
    filtered = []
    for row in rows:
        symbol = row.get("option_symbol") or row.get("symbol")
        sym_under = (row.get("ticker") or derive_underlying(row)).upper()
        if sym_under != underlying.upper():
            continue
        try:
            premium = float(row.get("premium", 0) or 0)
            vol = float(row.get("volume", 0) or 0)
        except (ValueError, TypeError):
            continue
        filtered.append((symbol, premium if premium else vol))
    filtered.sort(key=lambda x: x[1] or 0, reverse=True)
    return {sym for sym, _ in filtered[:top_n] if sym}


def _intent_bucket_from_hot(rows: List[Dict[str, Any]], underlying: str) -> str | None:
    ask = 0.0
    bid = 0.0
    for row in rows:
        sym_under = (row.get("ticker") or derive_underlying(row)).upper()
        if sym_under != underlying.upper():
            continue
        ask += float(row.get("ask_side_volume", 0) or 0)
        bid += float(row.get("bid_side_volume", 0) or 0)
    if ask == bid == 0:
        return None
    if ask > bid * 1.2:
        return "ASK_DOM"
    if bid > ask * 1.2:
        return "BID_DOM"
    return "BALANCED"


def _intent_bucket_from_bot(rows: List[Dict[str, Any]], underlying: str) -> str | None:
    ask = 0
    bid = 0
    for row in rows:
        sym_under = (row.get("underlying_symbol") or row.get("ticker") or derive_underlying(row)).upper()
        if sym_under != underlying.upper():
            continue
        side = str(row.get("side") or "").lower()
        if side == "ask":
            ask += 1
        elif side == "bid":
            bid += 1
    if ask == bid == 0:
        return None
    if ask > bid * 1.2:
        return "ASK_DOM"
    if bid > ask * 1.2:
        return "BID_DOM"
    return "BALANCED"


def _intent_bucket_from_bot_metrics(metrics: Dict[str, Any] | None) -> str | None:
    if not metrics:
        return None
    try:
        ask = float(metrics.get("ask_count", 0) or 0)
        bid = float(metrics.get("bid_count", 0) or 0)
    except (ValueError, TypeError):
        return None
    if ask == bid == 0:
        return None
    if ask > bid * 1.2:
        return "ASK_DOM"
    if bid > ask * 1.2:
        return "BID_DOM"
    return "BALANCED"


def _bot_metrics_for_session(db: Session, session_id: str) -> Dict[str, Dict[str, Any]]:
    """Return per-underlying bot/flow metrics for a session.

    Prefer pre-aggregated metrics stored in RawFile.extras['agg'].
    Fall back to aggregating from stored rows if present.
    """

    for source in (models.RawSource.OPTIONS_FLOW, models.RawSource.BOT_EOD):
        rf = (
            db.query(models.RawFile)
            .filter(models.RawFile.session_id == session_id, models.RawFile.source == source)
            .order_by(models.RawFile.imported_at.desc())
            .first()
        )
        if not rf or not rf.extras:
            continue

        if isinstance(rf.extras, dict) and isinstance(rf.extras.get("agg"), dict):
            return rf.extras["agg"]

        rows = rf.extras.get("rows") if isinstance(rf.extras, dict) else None
        if isinstance(rows, list) and rows:
            return bot_eod.aggregate(rows)

    return {}


def _collect_bot_metrics(db: Session, asof_date: date, limit: int) -> List[Tuple[date, Dict[str, Dict[str, Any]]]]:
    sessions = _recent_sessions(db, asof_date, limit)
    collected: list[Tuple[date, Dict[str, Dict[str, Any]]]] = []
    for sess in sessions:
        metrics = _bot_metrics_for_session(db, str(sess.session_id))
        if metrics:
            collected.append((sess.date, metrics))
    return list(reversed(collected))


def _intent_persistence(buckets: List[str]) -> float | None:
    if not buckets:
        return None
    latest = buckets[-1]
    matches = sum(1 for b in buckets if b == latest)
    return matches / len(buckets)


def _persistence_fraction(sets: List[set[str]]) -> float | None:
    if len(sets) < 2:
        return None
    current = sets[-1]
    previous_union: set[str] = set().union(*sets[:-1])
    return len(current & previous_union) / max(len(current) or 1, 1)


def _range_pct(row: Dict[str, Any]) -> float | None:
    try:
        high = float(row.get("high", 0) or 0)
        low = float(row.get("low", 0) or 0)
        close = float(row.get("close", 0) or 0)
    except (ValueError, TypeError):
        return None
    if not close:
        return None
    return (high - low) / close if close else None


def _range_stats(stock_history: List[Dict[str, Any]], underlying: str) -> Tuple[float | None, float | None]:
    ranges: list[float] = []
    for row in stock_history[-RANGE_WINDOW:]:
        ticker = (row.get("ticker") or derive_underlying(row)).upper()
        if ticker != underlying.upper():
            continue
        rpct = _range_pct(row)
        if rpct is not None:
            ranges.append(rpct)
    if not ranges:
        return None, None
    return mean(ranges), (pstdev(ranges) if len(ranges) > 1 else 0.0)


def _volume_to_avg30(stock_rows: List[Dict[str, Any]], underlying: str) -> float | None:
    for row in reversed(stock_rows):
        ticker = (row.get("ticker") or derive_underlying(row)).upper()
        if ticker != underlying.upper():
            continue
        try:
            total = float(row.get("total_volume", 0) or 0)
            avg30 = float(row.get("avg30_volume", 0) or 0)
        except (ValueError, TypeError):
            return None
        return (total / avg30) if avg30 else None
    return None


def _regime_last(db: Session, underlying: str, asof_date: date) -> models.RegimeLabel | None:
    prev = (
        db.query(models.RegimeDecision, models.Session)
        .join(models.Session, models.RegimeDecision.session_id == models.Session.session_id)
        .filter(models.Session.date < asof_date, models.RegimeDecision.underlying == underlying)
        .order_by(models.Session.date.desc())
        .first()
    )
    return prev[0].regime_label if prev else None


def _regime_switch_rate(db: Session, underlying: str, asof_date: date) -> float | None:
    rows = (
        db.query(models.RegimeDecision, models.Session)
        .join(models.Session, models.RegimeDecision.session_id == models.Session.session_id)
        .filter(models.Session.date <= asof_date, models.RegimeDecision.underlying == underlying)
        .order_by(models.Session.date.desc())
        .limit(SWITCH_WINDOW)
        .all()
    )
    if len(rows) < 2:
        return None
    labels = [row[0].regime_label for row in reversed(rows)]
    switches = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
    return switches / (len(labels) - 1)


def build_feature_row_v1(
    db: Session,
    session_id: str,
    underlying: str,
    asof_date: date,
    aggregates: Dict[str, Dict[str, float]],
    computed_at: datetime | None = None,
) -> models.FeaturesUnderlyingDay:
    computed_at = computed_at or datetime.utcnow()
    base = compute_from_aggregates(aggregates)

    oi_history = _collect_rows(db, asof_date, models.RawSource.OI_DIFF, PERSISTENCE_WINDOW)
    hot_history = _collect_rows(db, asof_date, models.RawSource.HOT_CHAINS, PERSISTENCE_WINDOW)
    bot_metrics_history = _collect_bot_metrics(db, asof_date, PERSISTENCE_WINDOW)
    stock_history = [row for _, rows in _collect_rows(db, asof_date, models.RawSource.STOCK_SCREENER, RANGE_WINDOW) for row in rows]

    oi_sets = [_top_symbols_from_oi(rows, underlying) for _, rows in oi_history]
    hot_sets = [_top_symbols_from_hot(rows, underlying) for _, rows in hot_history]

    intent_buckets = []
    for _, rows in hot_history:
        bucket = _intent_bucket_from_hot(rows, underlying)
        if bucket:
            intent_buckets.append(bucket)
    if not intent_buckets:
        for _, metrics_by_under in bot_metrics_history:
            bucket = _intent_bucket_from_bot_metrics(metrics_by_under.get(underlying.upper()) or metrics_by_under.get(underlying))
            if bucket:
                intent_buckets.append(bucket)

    oi_persistence = _persistence_fraction(oi_sets) if oi_sets else None
    hot_persistence = _persistence_fraction(hot_sets) if hot_sets else None
    intent_persistence = _intent_persistence(intent_buckets) if intent_buckets else None
    regime_last = _regime_last(db, underlying, asof_date)
    regime_switch_rate = _regime_switch_rate(db, underlying, asof_date)
    range_mean, range_std = _range_stats(stock_history, underlying)
    vol_to_avg30 = _volume_to_avg30(stock_history, underlying)

    feature = (
        db.query(models.FeaturesUnderlyingDay)
        .filter_by(session_id=session_id, underlying=underlying, asof_date=asof_date, feature_version="v1")
        .one_or_none()
    )
    payload = {
        "session_id": session_id,
        "underlying": underlying,
        "asof_date": asof_date,
        "feature_version": "v1",
        "computed_at": computed_at,
        "numeric_context": base.numeric_context,
        **base.booleans,
        "oi_persistence_3d": oi_persistence,
        "hot_chain_persistence_3d": hot_persistence,
        "intent_persistence_3d": intent_persistence,
        "regime_last": regime_last,
        "regime_switch_rate_10d": regime_switch_rate,
        "range_pct_5d_mean": range_mean,
        "range_pct_5d_std": range_std,
        "volume_to_avg30": vol_to_avg30,
    }
    if feature:
        for key, value in payload.items():
            setattr(feature, key, value)
        return feature
    return models.FeaturesUnderlyingDay(**payload)
