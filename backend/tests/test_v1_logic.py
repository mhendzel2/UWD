from datetime import date

from app.briefs import generate_v1 as briefs
from app.analysis import strike_analysis
from app.ecology import compute_v0 as ecology
from app.features import build_v1
from app.regime import classify_v1_ensemble as ensemble
from app.db import models


def test_flow_brief_bullish_and_empty_bearish():
    rows = [
        {"ticker": "AAA", "issue_type": "Common Stock", "call_volume": 1000, "put_volume": 100, "call_premium": 500000, "put_premium": 20000, "implied_move_perc": 0.02, "iv_rank": 0.3},
        {"ticker": "BBB", "issue_type": "Common Stock", "call_volume": 50, "put_volume": 900, "call_premium": 10000, "put_premium": 80000, "implied_move_perc": 0.01, "iv_rank": 0.2},
    ]
    bullish, bearish, note = briefs._build_flow_entries(rows, date(2024, 1, 5))
    assert bullish and all(e["bias"] == "BULLISH" for e in bullish)
    assert not bearish
    assert "No bearish" in note


def test_vol_briefs_sorting():
    rows = [
        {"ticker": "X", "issue_type": "ETF", "iv_rank": 0.9, "iv30d": 0.3, "implied_move_perc": 0.02, "total_volume": 600000},
        {"ticker": "Y", "issue_type": "ETF", "iv_rank": 0.5, "iv30d": 0.25, "implied_move_perc": 0.01, "total_volume": 700000},
        {"ticker": "Z", "issue_type": "ETF", "iv_rank": 0.05, "iv30d": 0.2, "implied_move_perc": 0.01, "total_volume": 700000},
    ]
    vol_sell, _ = briefs._build_vol_sell(rows, date(2024, 1, 5))
    assert vol_sell[0]["ticker"] == "X"
    vol_buy, _ = briefs._build_vol_buy(rows, date(2024, 1, 5))
    assert vol_buy and vol_buy[0]["ticker"] == "Z"


def test_ecology_dominant_horizon_and_bullets():
    feature = models.FeaturesUnderlyingDay(
        session_id="sid",
        underlying="SPX",
        asof_date=date(2024, 1, 5),
        hc_sweep_dominant=True,
        bot_aggressive_present=True,
        oi_concentrated=True,
        hc_liquidity_churn=True,
        hc_balanced_flow=False,
    )
    dom = ecology._dominant_horizon(feature)
    assert dom == models.DominantHorizonHint.SHORT
    bullets = ecology._explanation(feature, models.RegimeLabel.TREND_RISK, tail_risk=True, drawdown=False)
    assert bullets and any("tail" in b.lower() for b in bullets)


def test_persistence_fraction_overlap():
    sets = [{"A", "B"}, {"B", "C"}, {"B", "D"}]
    frac = build_v1._persistence_fraction(sets)
    assert frac == 0.5


def test_micro_classifiers_and_combine():
    feature = models.FeaturesUnderlyingDay(
        session_id="sid",
        underlying="SPX",
        asof_date=date(2024, 1, 5),
        hc_sweep_dominant=True,
        bot_overpay_present=True,
        bot_aggressive_present=True,
        hc_liquidity_churn=True,
        oi_symmetric=True,
        oi_multileg_dominant=True,
        hc_multileg_dominant=True,
        dp_meaningful=True,
        oi_persistence_3d=0.7,
        hot_chain_persistence_3d=0.2,
        intent_persistence_3d=0.2,
        regime_switch_rate_10d=0.5,
    )
    short_vote = ensemble._short_classifier(feature)
    long_vote = ensemble._long_classifier(feature)
    mixed_vote = ensemble._mixed_classifier(feature)
    assert short_vote.label == models.RegimeLabel.TREND_RISK
    assert long_vote.label == models.RegimeLabel.PIN_RANGE
    assert mixed_vote.label in {models.RegimeLabel.MIXED_NO_TRADE, models.RegimeLabel.TREND_RISK}
    label, confidence, _payload = ensemble._combine_votes({"short": short_vote, "long": long_vote, "mixed": mixed_vote}, ensemble.DEFAULT_WEIGHTS)
    assert label in models.RegimeLabel
    assert 0 <= confidence <= 1


def test_migration_revision_present():
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    path = backend_root / "app" / "db" / "migrations" / "versions" / "0002_v1_upgrade.py"
    content = path.read_text(encoding="utf-8")
    assert "daily_briefs" in content
    assert "ensemble_decisions" in content


def test_strike_analysis_top_levels():
    oi_rows = [
        {"underlying_symbol": "SPX", "strike": "4800", "option_type": "call", "curr_oi": "10000"},
        {"underlying_symbol": "SPX", "strike": "4700", "option_type": "put", "curr_oi": "9000"},
    ]
    hot_rows = [
        {"ticker": "SPX", "strike": "4800", "option_type": "call", "premium": "500000"},
    ]
    bot_rows = [
        {"underlying_symbol": "SPX", "strike": "4700", "option_type": "put", "premium": "250000", "gamma": "1.2", "delta": "-0.4", "side": "bid"},
    ]
    levels = strike_analysis.compute_strike_levels(oi_rows, hot_rows, bot_rows, top_n=3)
    spx_levels = levels.get("SPX")
    assert spx_levels
    assert spx_levels["oi_walls"][0]["strike"] == 4800.0
    assert spx_levels["premium_pockets"][0]["strike"] == 4800.0
