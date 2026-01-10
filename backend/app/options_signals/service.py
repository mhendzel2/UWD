from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.orm import Session

from app.db import models
from app.options_signals.registry import load_feature_registry, load_signal_registry


def get_feature_registry() -> dict[str, Any]:
    return load_feature_registry()


def get_signal_registry() -> dict[str, Any]:
    return load_signal_registry()


def screener_rows(
    db: Session,
    *,
    trade_date: date,
    signal_name: str,
    sector: str | None = None,
    min_liquidity: float | None = None,
    alerts_only: bool = False,
) -> list[dict[str, Any]]:
    stmt = (
        select(
            models.FeaturesUnderlyingDaily,
            models.SignalsUnderlyingDaily.score,
            models.SignalsUnderlyingDaily.rank,
        )
        .join(
            models.SignalsUnderlyingDaily,
            and_(
                models.SignalsUnderlyingDaily.trade_date == models.FeaturesUnderlyingDaily.trade_date,
                models.SignalsUnderlyingDaily.underlying_symbol == models.FeaturesUnderlyingDaily.underlying_symbol,
            ),
        )
        .where(
            models.FeaturesUnderlyingDaily.trade_date == trade_date,
            models.SignalsUnderlyingDaily.signal_name == signal_name,
        )
    )
    if sector:
        stmt = stmt.where(models.FeaturesUnderlyingDaily.sector == sector)
    if min_liquidity is not None:
        stmt = stmt.where(
            (models.FeaturesUnderlyingDaily.call_volume + models.FeaturesUnderlyingDaily.put_volume) >= min_liquidity
        )
    if alerts_only:
        stmt = stmt.join(
            models.AlertsEventLog,
            and_(
                models.AlertsEventLog.trade_date == models.FeaturesUnderlyingDaily.trade_date,
                models.AlertsEventLog.underlying_symbol == models.FeaturesUnderlyingDaily.underlying_symbol,
            ),
        )

    rows = db.execute(stmt).all()

    scores_stmt = select(models.SignalsUnderlyingDaily).where(
        models.SignalsUnderlyingDaily.trade_date == trade_date,
        models.SignalsUnderlyingDaily.signal_name.in_(["BULL_FLOW", "BEAR_FLOW", "VOL_EXPANSION"]),
    )
    scores = db.execute(scores_stmt).scalars().all()
    score_map: dict[tuple[str, str], float] = {
        (row.underlying_symbol, row.signal_name): float(row.score) for row in scores
    }
    output = []
    for feature, score, rank in rows:
        output.append(
            {
                "trade_date": feature.trade_date.isoformat(),
                "underlying_symbol": feature.underlying_symbol,
                "sector": feature.sector,
                "close": float(feature.close) if feature.close is not None else None,
                "ret_1d": float(feature.ret_1d) if feature.ret_1d is not None else None,
                "signal_score": float(score) if score is not None else None,
                "signal_rank": rank,
                "bullish_flow_score": score_map.get((feature.underlying_symbol, "BULL_FLOW")),
                "bearish_flow_score": score_map.get((feature.underlying_symbol, "BEAR_FLOW")),
                "vol_expansion_score": score_map.get((feature.underlying_symbol, "VOL_EXPANSION")),
                "put_call_vol_ratio": float(feature.put_call_vol_ratio) if feature.put_call_vol_ratio is not None else None,
                "net_premium": float(feature.net_premium) if feature.net_premium is not None else None,
                "call_buy_premium": float(feature.call_buy_premium) if feature.call_buy_premium is not None else None,
                "put_buy_premium": float(feature.put_buy_premium) if feature.put_buy_premium is not None else None,
                "iv_atm_proxy": float(feature.iv_atm_proxy) if feature.iv_atm_proxy is not None else None,
                "iv_rank_252": float(feature.iv_rank_252) if feature.iv_rank_252 is not None else None,
                "rv_20": float(feature.rv_20) if feature.rv_20 is not None else None,
                "iv_minus_rv20": float(feature.iv_minus_rv20) if feature.iv_minus_rv20 is not None else None,
                "news_count": feature.news_count,
                "sentiment_mean": float(feature.sentiment_mean) if feature.sentiment_mean is not None else None,
                "uoa_contract_count": feature.uoa_contract_count,
                "uoa_max_volume_z": float(feature.uoa_max_volume_z) if feature.uoa_max_volume_z is not None else None,
            }
        )
    return output


def symbol_timeseries(
    db: Session,
    *,
    symbol: str,
    start_date: date,
    end_date: date,
) -> list[dict[str, Any]]:
    stmt = select(models.FeaturesUnderlyingDaily).where(
        models.FeaturesUnderlyingDaily.underlying_symbol == symbol,
        models.FeaturesUnderlyingDaily.trade_date >= start_date,
        models.FeaturesUnderlyingDaily.trade_date <= end_date,
    )
    rows = db.execute(stmt).scalars().all()

    signals_stmt = select(models.SignalsUnderlyingDaily).where(
        models.SignalsUnderlyingDaily.underlying_symbol == symbol,
        models.SignalsUnderlyingDaily.trade_date >= start_date,
        models.SignalsUnderlyingDaily.trade_date <= end_date,
        models.SignalsUnderlyingDaily.signal_name.in_(["BULL_FLOW", "BEAR_FLOW", "VOL_EXPANSION"]),
    )
    signal_rows = db.execute(signals_stmt).scalars().all()
    signal_map: dict[date, dict[str, float]] = {}
    for row in signal_rows:
        signal_map.setdefault(row.trade_date, {})[row.signal_name] = float(row.score)

    return [
        {
            "trade_date": row.trade_date.isoformat(),
            "close": float(row.close) if row.close is not None else None,
            "ret_1d": float(row.ret_1d) if row.ret_1d is not None else None,
            "iv_atm_proxy": float(row.iv_atm_proxy) if row.iv_atm_proxy is not None else None,
            "rv_20": float(row.rv_20) if row.rv_20 is not None else None,
            "call_premium": float(row.call_premium) if row.call_premium is not None else None,
            "put_premium": float(row.put_premium) if row.put_premium is not None else None,
            "call_volume": float(row.call_volume) if row.call_volume is not None else None,
            "put_volume": float(row.put_volume) if row.put_volume is not None else None,
            "put_call_vol_ratio": float(row.put_call_vol_ratio) if row.put_call_vol_ratio is not None else None,
            "news_count": row.news_count,
            "sentiment_mean": float(row.sentiment_mean) if row.sentiment_mean is not None else None,
            "uoa_contract_count": row.uoa_contract_count,
            "bullish_flow_score": signal_map.get(row.trade_date, {}).get("BULL_FLOW"),
            "bearish_flow_score": signal_map.get(row.trade_date, {}).get("BEAR_FLOW"),
            "vol_expansion_score": signal_map.get(row.trade_date, {}).get("VOL_EXPANSION"),
        }
        for row in rows
    ]


def symbol_uoa(db: Session, *, symbol: str, trade_date: date) -> list[dict[str, Any]]:
    stmt = select(models.OptAggContractDaily).where(
        models.OptAggContractDaily.underlying_symbol == symbol,
        models.OptAggContractDaily.trade_date == trade_date,
        models.OptAggContractDaily.is_uoa.is_(True),
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "option_chain_id": row.option_chain_id,
            "expiry_date": row.expiry_date.isoformat() if row.expiry_date else None,
            "option_type": row.option_type,
            "strike": float(row.strike) if row.strike is not None else None,
            "contract_volume": float(row.contract_volume) if row.contract_volume is not None else None,
            "contract_premium": float(row.contract_premium) if row.contract_premium is not None else None,
            "iv_last": float(row.iv_last) if row.iv_last is not None else None,
            "delta_last": float(row.delta_last) if row.delta_last is not None else None,
            "uoa_volume_z": float(row.uoa_volume_z) if row.uoa_volume_z is not None else None,
            "uoa_vo_i": float(row.uoa_vo_i) if row.uoa_vo_i is not None else None,
        }
        for row in rows
    ]


def symbol_alerts(db: Session, *, symbol: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    stmt = select(models.AlertsEventLog).where(
        models.AlertsEventLog.underlying_symbol == symbol,
        models.AlertsEventLog.trade_date >= start_date,
        models.AlertsEventLog.trade_date <= end_date,
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "event_ts": row.event_ts.isoformat(),
            "trade_date": row.trade_date.isoformat(),
            "event_type": row.event_type,
            "severity": row.severity,
            "payload": row.payload_json,
        }
        for row in rows
    ]


def alerts_range(db: Session, *, start_date: date, end_date: date) -> list[dict[str, Any]]:
    stmt = select(models.AlertsEventLog).where(
        models.AlertsEventLog.trade_date >= start_date,
        models.AlertsEventLog.trade_date <= end_date,
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "event_ts": row.event_ts.isoformat(),
            "trade_date": row.trade_date.isoformat(),
            "underlying_symbol": row.underlying_symbol,
            "event_type": row.event_type,
            "severity": row.severity,
            "payload": row.payload_json,
        }
        for row in rows
    ]


def data_quality_range(db: Session, *, start_date: date, end_date: date) -> list[dict[str, Any]]:
    stmt = select(models.OptionsSignalsDataQualityDaily).where(
        models.OptionsSignalsDataQualityDaily.trade_date >= start_date,
        models.OptionsSignalsDataQualityDaily.trade_date <= end_date,
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "trade_date": row.trade_date.isoformat(),
            "total_trades": row.total_trades,
            "canceled_filtered": row.canceled_filtered,
            "trades_missing_nbbo": row.trades_missing_nbbo,
            "symbols_missing_ohlcv": row.symbols_missing_ohlcv,
            "symbols_missing_news": row.symbols_missing_news,
            "freshness": row.freshness_json,
        }
        for row in rows
    ]
