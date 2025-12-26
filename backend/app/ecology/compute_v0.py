from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Tuple

from sqlalchemy.orm import Session

from app.analysis.strike_analysis import build_strike_levels_for_session
from app.db import models
from app.utils.underlying import derive_underlying

ECOLOGY_VERSION = "v0"
TAIL_RISK_FACTORS = ("hc_liquidity_churn", "hc_sweep_dominant", "oi_concentrated", "ss_implied_move_high")
DRAW_MIN_DROP = -0.02
DRAW_VOLUME_MULT = 1.2
PROXY_UNDERLYINGS = {"SPY", "QQQ", "SPX", "SPXW"}


def _load_rows(session_id: str, db: Session, source: models.RawSource) -> List[Dict[str, Any]]:
    files = (
        db.query(models.RawFile)
        .filter(models.RawFile.session_id == session_id, models.RawFile.source == source)
        .all()
    )
    rows: list[dict[str, Any]] = []
    for rf in files:
        if rf.extras and "rows" in rf.extras:
            rows.extend(rf.extras["rows"])
    return rows


def _parse_float(val: Any) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _drawdown_flag(rows: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
    context: dict[str, Any] = {}
    for row in rows:
        ticker = (row.get("ticker") or derive_underlying(row)).upper()
        if ticker not in PROXY_UNDERLYINGS:
            continue
        close = _parse_float(row.get("close"))
        prev_close = _parse_float(row.get("prev_close"))
        total_volume = _parse_float(row.get("total_volume"))
        avg30_volume = _parse_float(row.get("avg30_volume"))
        if not prev_close or not close:
            continue
        pct = (close - prev_close) / prev_close
        volume_ratio = total_volume / avg30_volume if avg30_volume else 0.0
        context[ticker] = {"close_vs_prev_close_pct": pct, "volume_ratio": volume_ratio}
        if pct <= DRAW_MIN_DROP and volume_ratio >= DRAW_VOLUME_MULT:
            return True, context
    return False, context


def _bucket_from_ts(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    hhmm = dt.hour + dt.minute / 60
    if 9.5 <= hhmm < 11:
        return "MORNING"
    if 11 <= hhmm < 15:
        return "MIDDAY"
    if 15 <= hhmm <= 16.1:
        return "AFTERNOON"
    return None


def _timing_profile(hot_rows: List[Dict[str, Any]], bot_rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    buckets: dict[str, dict[str, float]] = {
        "MORNING": {"premium": 0.0, "sweeps": 0.0},
        "MIDDAY": {"premium": 0.0, "sweeps": 0.0},
        "AFTERNOON": {"premium": 0.0, "sweeps": 0.0},
    }
    for row in hot_rows:
        bucket = _bucket_from_ts(row.get("tape_time") or row.get("timestamp"))
        if not bucket or bucket not in buckets:
            continue
        buckets[bucket]["premium"] += _parse_float(row.get("premium"))
        buckets[bucket]["sweeps"] += _parse_float(row.get("sweep_volume"))
    for row in bot_rows:
        bucket = _bucket_from_ts(row.get("executed_at") or row.get("timestamp"))
        if not bucket or bucket not in buckets:
            continue
        buckets[bucket]["premium"] += _parse_float(row.get("premium"))
    # choose dominant timing profile
    dominant = max(buckets.items(), key=lambda kv: kv[1]["premium"])[0]
    profile = f"{dominant}_MOMENTUM" if buckets[dominant]["premium"] > 0 else "NONE"
    buckets["timing_profile"] = {"label": profile}
    return buckets


def _dominant_horizon(feature: models.FeaturesUnderlyingDay) -> models.DominantHorizonHint:
    short_hits = sum(
        1
        for cond in (
            feature.hc_sweep_dominant,
            feature.bot_aggressive_present,
            feature.bot_overpay_present,
            feature.hc_liquidity_churn,
        )
        if cond
    )
    long_hits = sum(
        1
        for cond in (feature.oi_symmetric, feature.oi_multileg_dominant, feature.hc_multileg_dominant, feature.dp_meaningful)
        if cond
    )
    if short_hits >= 2 and long_hits == 0:
        return models.DominantHorizonHint.SHORT
    if long_hits >= 2 and short_hits == 0:
        return models.DominantHorizonHint.LONG
    if short_hits >= 1 and long_hits >= 1:
        return models.DominantHorizonHint.MIXED
    return models.DominantHorizonHint.MEDIUM


def _volatility_ecology(regime: models.RegimeLabel, feature: models.FeaturesUnderlyingDay) -> str:
    if regime == models.RegimeLabel.PIN_RANGE and not feature.hc_liquidity_churn:
        return "STABLE"
    if feature.hc_high_turnover or feature.hc_liquidity_churn:
        return "CHURN"
    if regime == models.RegimeLabel.TREND_RISK and (feature.hc_sweep_dominant or feature.bot_overpay_present):
        return "AMPLIFY"
    return "UNSURE"


def _disagreement_intensity(feature: models.FeaturesUnderlyingDay) -> str:
    high = feature.hc_high_turnover and feature.hc_balanced_flow and (feature.oi_concentrated or feature.oi_symmetric)
    low = not any([feature.hc_high_turnover, feature.hc_sweep_dominant, feature.hc_liquidity_churn])
    if high:
        return "HIGH"
    if low:
        return "LOW"
    return "MED"


def _positioning_structure(regime: models.RegimeLabel, feature: models.FeaturesUnderlyingDay) -> str:
    if feature.oi_symmetric and feature.oi_concentrated:
        return "PIN_REINFORCED"
    if regime == models.RegimeLabel.TREND_RISK and not feature.oi_concentrated:
        return "FRAGILE"
    return "UNCLEAR"


def _intent_profile(feature: models.FeaturesUnderlyingDay) -> str:
    hedge = (feature.oi_multileg_dominant or feature.hc_multileg_dominant) and feature.hc_balanced_flow
    spec = feature.hc_sweep_dominant and (feature.bot_aggressive_present or feature.bot_overpay_present)
    if hedge:
        return "HEDGE_DOMINANT"
    if spec:
        return "SPEC_CONVEXITY"
    return "MIXED"


def _explanation(feature: models.FeaturesUnderlyingDay, regime: models.RegimeLabel, tail_risk: bool, drawdown: bool) -> List[str]:
    bullets: list[str] = []
    if feature.hc_sweep_dominant:
        bullets.append("Sweep-dominant flow present.")
    if feature.hc_multileg_dominant:
        bullets.append("Multi-leg flow reinforcing pinned strikes.")
    if feature.oi_concentrated:
        bullets.append("OI concentrated at a few strikes.")
    if feature.bot_overpay_present:
        bullets.append("Aggressive bot overpay detected.")
    if feature.dp_meaningful:
        bullets.append("Dark pool size is meaningful.")
    if tail_risk:
        bullets.append("Tail-risk factors clustered.")
    if drawdown:
        bullets.append("Macro drawdown shock active on proxies.")
    if regime == models.RegimeLabel.TREND_RISK:
        bullets.append("Trend risk regime; permissions conditional only.")
    return bullets[:7] if bullets else ["Mixed evidence; monitor only."]


def _market_sentiment(stock_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    sector_totals: dict[str, dict[str, float]] = defaultdict(lambda: {"call_premium": 0.0, "put_premium": 0.0})
    call_prem = 0.0
    put_prem = 0.0
    for row in stock_rows:
        sector = (row.get("sector") or "UNKNOWN").upper()
        cp = _parse_float(row.get("call_premium"))
        pp = _parse_float(row.get("put_premium"))
        call_prem += cp
        put_prem += pp
        sector_totals[sector]["call_premium"] += cp
        sector_totals[sector]["put_premium"] += pp
    sentiment = {
        "call_premium": call_prem,
        "put_premium": put_prem,
        "net_premium": call_prem - put_prem,
        "put_call_ratio": (put_prem / call_prem) if call_prem else None,
    }
    sectors = {
        k: {
            "call_premium": v["call_premium"],
            "put_premium": v["put_premium"],
            "net_premium": v["call_premium"] - v["put_premium"],
        }
        for k, v in sector_totals.items()
    }
    return {"market_sentiment": sentiment, "sector_flows": sectors}


def compute_ecology_state(
    db: Session, session: models.Session, asof_date: date | None = None
) -> list[models.RegimeDecision]:
    asof_date = asof_date or session.date
    stock_rows = _load_rows(str(session.session_id), db, models.RawSource.STOCK_SCREENER)
    hot_rows = _load_rows(str(session.session_id), db, models.RawSource.HOT_CHAINS)
    bot_rows = _load_rows(str(session.session_id), db, models.RawSource.BOT_EOD)
    drawdown_flag, drawdown_context = _drawdown_flag(stock_rows)
    timing = _timing_profile(hot_rows, bot_rows)
    strike_levels = build_strike_levels_for_session(db, str(session.session_id))
    overlays = _market_sentiment(stock_rows)

    decisions = (
        db.query(models.RegimeDecision)
        .filter(models.RegimeDecision.session_id == str(session.session_id), models.RegimeDecision.asof_date == asof_date)
        .all()
    )

    updated: list[models.RegimeDecision] = []
    for decision in decisions:
        feature = decision.feature
        if not feature:
            continue
        tail_risk = sum(1 for name in TAIL_RISK_FACTORS if getattr(feature, name, False)) >= 2
        dom = _dominant_horizon(feature)
        ecology = {
            "dominant_horizon_hint": dom.value,
            "volatility_ecology": _volatility_ecology(decision.regime_label, feature),
            "disagreement_intensity": _disagreement_intensity(feature),
            "positioning_structure": _positioning_structure(decision.regime_label, feature),
            "intent_profile": _intent_profile(feature),
            "tail_risk_flag": tail_risk,
            "drawdown_shock_active": drawdown_flag,
            "drawdown_inputs": drawdown_context,
            "timing_profile": timing,
            "strike_levels": strike_levels.get(decision.underlying.upper()) if strike_levels else None,
            "market_overlays": overlays,
            "explanation_bullets": _explanation(feature, decision.regime_label, tail_risk, drawdown_flag),
            "plan_modifiers": {
                "confidence_adjustment": "DOWN" if tail_risk or drawdown_flag else "NONE",
                "trade_permission": "CONDITIONAL_ONLY" if decision.regime_label == models.RegimeLabel.TREND_RISK else "NO_TRADE",
                "sizing_cap": "LOW" if tail_risk else "NORMAL",
            },
        }
        decision.dominant_horizon_hint = dom
        decision.ecology_state = ecology
        decision.ecology_version = ECOLOGY_VERSION
        decision.computed_at = datetime.utcnow()
        updated.append(decision)

    db.commit()
    return updated
