from datetime import date

from app.db.models import FeaturesUnderlyingDay, RegimeLabel
from app.regime.classify_v0 import classify


def test_classify_pin_range():
    feature = FeaturesUnderlyingDay(
        session_id="00000000-0000-0000-0000-000000000000",
        underlying="SPX",
        asof_date=date(2024, 1, 5),
        oi_symmetric=True,
        hc_balanced_flow=True,
        hc_multileg_dominant=True,
        oi_multileg_dominant=True,
    )
    decision = classify(feature)
    assert decision.regime_label == RegimeLabel.PIN_RANGE
    assert decision.confidence_tier.value in {"MED", "HIGH"}


def test_classify_trend_risk():
    feature = FeaturesUnderlyingDay(
        session_id="00000000-0000-0000-0000-000000000000",
        underlying="SPX",
        asof_date=date(2024, 1, 5),
        oi_one_sided=True,
        hc_sweep_dominant=True,
        bot_overpay_present=True,
        ss_directional_skew=True,
        ss_implied_move_high=True,
    )
    decision = classify(feature)
    assert decision.regime_label == RegimeLabel.TREND_RISK
    assert decision.confidence_tier.value in {"MED", "HIGH"}


def test_classify_mixed():
    feature = FeaturesUnderlyingDay(
        session_id="00000000-0000-0000-0000-000000000000",
        underlying="SPX",
        asof_date=date(2024, 1, 5),
    )
    decision = classify(feature)
    assert decision.regime_label == RegimeLabel.MIXED_NO_TRADE
