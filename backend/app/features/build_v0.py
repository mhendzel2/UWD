from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Any

from app.db.models import FeaturesUnderlyingDay
from app.features import constants_v0 as c


@dataclass
class FeatureComputation:
    booleans: Dict[str, bool]
    numeric_context: Dict[str, Any]


def _safe_ratio(num: float, den: float) -> float:
    return num / den if den not in (0, None) else 0.0


def compute_from_aggregates(aggregates: Dict[str, Dict[str, float]]) -> FeatureComputation:
    oi = aggregates.get("oi", {})
    hc = aggregates.get("hot_chains", {})
    bot = aggregates.get("bot", {})
    ss = aggregates.get("stock_screener", {})
    dp = aggregates.get("darkpool", {})

    call_oi = float(oi.get("call_oi", 0) or 0)
    put_oi = float(oi.get("put_oi", 0) or 0)
    multileg_oi = float(oi.get("multileg_oi", 0) or 0)
    total_oi = call_oi + put_oi + multileg_oi
    oi_symmetric = False
    if call_oi and put_oi:
        symmetry_ratio = abs(call_oi - put_oi) / max(call_oi, put_oi)
        oi_symmetric = symmetry_ratio <= c.OI_SYMMETRY_RATIO_TOL

    oi_one_sided = False
    if total_oi:
        max_side = max(call_oi, put_oi)
        oi_one_sided = (max_side / (call_oi + put_oi)) >= c.OI_ONE_SIDED_RATIO_MIN

    oi_multileg_dominant = _safe_ratio(multileg_oi, total_oi) >= c.OI_MULTILEG_SHARE_MIN if total_oi else False
    oi_concentrated = total_oi >= c.OI_CONCENTRATION_MIN

    turnover = float(hc.get("turnover_notional", 0) or 0)
    buy_vol = float(hc.get("buy_volume", 0) or 0)
    sell_vol = float(hc.get("sell_volume", 0) or 0)
    sweep_count = float(hc.get("sweep_count", 0) or 0)
    multileg_count = float(hc.get("multileg_count", 0) or 0)
    hc_total_orders = sweep_count + multileg_count if (sweep_count + multileg_count) else max(sweep_count, multileg_count, 1)

    hc_high_turnover = turnover >= c.HC_TURNOVER_MIN
    flow_ratio = abs(buy_vol - sell_vol) / max(buy_vol + sell_vol, 1)
    hc_balanced_flow = flow_ratio <= c.HC_BALANCE_TOL
    hc_sweep_dominant = _safe_ratio(sweep_count, hc_total_orders) >= c.HC_SWEEP_SHARE_MIN
    hc_multileg_dominant = _safe_ratio(multileg_count, hc_total_orders) >= c.HC_MULTILEG_SHARE_MIN
    churn_ratio = _safe_ratio(min(buy_vol, sell_vol), max(buy_vol, sell_vol) or 1)
    hc_liquidity_churn = churn_ratio >= c.HC_LIQUIDITY_CHURN_MIN and turnover > 0

    bot_overpay_present = float(bot.get("overpay_count", 0) or 0) >= c.BOT_OVERPAY_MIN
    bot_aggressive_present = float(bot.get("aggressive_count", 0) or 0) >= c.BOT_AGGRESSIVE_MIN
    bot_gamma_concentrated = float(bot.get("gamma_exposure", 0) or 0) >= c.BOT_GAMMA_MIN

    ss_implied_move_high = float(ss.get("implied_move", 0) or 0) >= c.SS_IMPLIED_MOVE_HIGH
    ss_directional_skew = float(ss.get("directional_skew", 0) or 0) >= c.SS_DIRECTIONAL_SKEW_MIN
    ss_iv_high = float(ss.get("iv_percentile", 0) or 0) >= c.SS_IV_HIGH_PERCENTILE

    dp_notional = float(dp.get("notional", 0) or 0)
    dp_meaningful = dp_notional >= c.DP_MIN_NOTIONAL
    dp_buy_ratio = _safe_ratio(float(dp.get("buy_notional", 0) or 0), dp_notional or 1)
    dp_sell_ratio = _safe_ratio(float(dp.get("sell_notional", 0) or 0), dp_notional or 1)
    dp_accumulation_bias = dp_meaningful and dp_buy_ratio >= c.DP_BIAS_RATIO_MIN
    dp_distribution_bias = dp_meaningful and dp_sell_ratio >= c.DP_BIAS_RATIO_MIN

    booleans = {
        "oi_concentrated": oi_concentrated,
        "oi_symmetric": oi_symmetric,
        "oi_one_sided": oi_one_sided,
        "oi_multileg_dominant": oi_multileg_dominant,
        "hc_high_turnover": hc_high_turnover,
        "hc_balanced_flow": hc_balanced_flow,
        "hc_sweep_dominant": hc_sweep_dominant,
        "hc_multileg_dominant": hc_multileg_dominant,
        "hc_liquidity_churn": hc_liquidity_churn,
        "bot_overpay_present": bot_overpay_present,
        "bot_aggressive_present": bot_aggressive_present,
        "bot_gamma_concentrated": bot_gamma_concentrated,
        "ss_implied_move_high": ss_implied_move_high,
        "ss_directional_skew": ss_directional_skew,
        "ss_iv_high": ss_iv_high,
        "dp_meaningful": dp_meaningful,
        "dp_accumulation_bias": dp_accumulation_bias,
        "dp_distribution_bias": dp_distribution_bias,
    }

    numeric_context = {
        "oi": {"call_oi": call_oi, "put_oi": put_oi, "multileg_oi": multileg_oi, "total_oi": total_oi},
        "hot_chains": {
            "turnover_notional": turnover,
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "sweep_count": sweep_count,
            "multileg_count": multileg_count,
        },
        "bot": bot,
        "stock_screener": ss,
        "darkpool": dp,
    }
    return FeatureComputation(booleans=booleans, numeric_context=numeric_context)


def build_feature_row(
    session_id,
    underlying: str,
    asof_date: date,
    aggregates: Dict[str, Dict[str, float]],
    computed_at: datetime | None = None,
) -> FeaturesUnderlyingDay:
    computed_at = computed_at or datetime.utcnow()
    result = compute_from_aggregates(aggregates)
    return FeaturesUnderlyingDay(
        session_id=session_id,
        underlying=underlying,
        asof_date=asof_date,
        computed_at=computed_at,
        feature_version="v0",
        numeric_context=result.numeric_context,
        **result.booleans,
    )
