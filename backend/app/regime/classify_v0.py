from datetime import datetime, date
from typing import Dict, Any

from app.db.models import FeaturesUnderlyingDay, RegimeDecision, RegimeLabel, ConfidenceTier


def _confidence(supports: int) -> ConfidenceTier:
    if supports >= 3:
        return ConfidenceTier.HIGH
    if supports == 2:
        return ConfidenceTier.MED
    return ConfidenceTier.LOW


def classify(feature: FeaturesUnderlyingDay, computed_at: datetime | None = None) -> RegimeDecision:
    computed_at = computed_at or datetime.utcnow()
    reasons = []
    conflicts = []

    pin_supports = [
        ("hc_balanced_flow", feature.hc_balanced_flow),
        ("hc_multileg_dominant", feature.hc_multileg_dominant),
        ("oi_multileg_dominant", feature.oi_multileg_dominant),
        ("hc_high_turnover", feature.hc_high_turnover),
    ]
    trend_supports = [
        ("hc_sweep_dominant", feature.hc_sweep_dominant),
        ("bot_overpay_present", feature.bot_overpay_present),
        ("bot_aggressive_present", feature.bot_aggressive_present),
        ("ss_directional_skew", feature.ss_directional_skew),
        ("hc_liquidity_churn", feature.hc_liquidity_churn),
    ]

    pin_range = feature.oi_symmetric and sum(1 for _, v in pin_supports if v) >= 2
    risk_block = feature.hc_sweep_dominant and feature.bot_overpay_present and feature.oi_one_sided
    trend_risk = feature.oi_one_sided and sum(1 for _, v in trend_supports if v) >= 2 and (
        feature.ss_implied_move_high or (not feature.ss_iv_high)
    )

    if pin_range and not risk_block:
        regime = RegimeLabel.PIN_RANGE
        reasons = [name for name, val in pin_supports if val]
        confidence = _confidence(len(reasons))
    elif trend_risk:
        regime = RegimeLabel.TREND_RISK
        reasons = [name for name, val in trend_supports if val]
        confidence = _confidence(len(reasons))
    else:
        regime = RegimeLabel.MIXED_NO_TRADE
        reasons = [name for name, val in pin_supports + trend_supports if val]
        confidence = ConfidenceTier.LOW

    if risk_block:
        conflicts.append("sweep+overpay+one_sided risk block")

    return RegimeDecision(
        session_id=feature.session_id,
        underlying=feature.underlying,
        asof_date=feature.asof_date,
        regime_label=regime,
        confidence_tier=confidence,
        reasons={"features": reasons},
        conflicts={"items": conflicts} if conflicts else None,
        decision_version="v0",
        computed_at=computed_at,
        feature=feature,
    )
