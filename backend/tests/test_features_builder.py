from datetime import date

from app.features.build_v0 import build_feature_row


def test_feature_builder_boolean_flags():
    aggregates = {
        "oi": {"call_oi": 7000, "put_oi": 6500, "multileg_oi": 4000},
        "hot_chains": {"turnover_notional": 2_000_000, "buy_volume": 600000, "sell_volume": 500000, "sweep_count": 10, "multileg_count": 12},
        "bot": {"overpay_count": 3, "aggressive_count": 2, "gamma_exposure": 6_000_000},
        "stock_screener": {"implied_move": 3.0, "directional_skew": 0.8, "iv_percentile": 0.8},
        "darkpool": {"notional": 800000, "buy_notional": 600000, "sell_notional": 200000},
    }
    feature = build_feature_row("00000000-0000-0000-0000-000000000000", "SPX", date(2024, 1, 5), aggregates)
    assert feature.oi_concentrated is True
    assert feature.hc_high_turnover is True
    assert feature.bot_gamma_concentrated is True
    assert feature.dp_meaningful is True
