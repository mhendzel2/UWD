from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.db import models
from app.options_signals.constants import DEFAULT_CONFIG, OptionsSignalsConfig
from app.options_signals.indicators import (
    bollinger,
    ema,
    macd,
    realized_vol,
    rolling_percentile_rank,
    rolling_zscore,
    rsi,
)
from app.options_signals.normalization import normalize_trades_frame


def _read_sql_df(db: Session, stmt) -> pd.DataFrame:
    return pd.read_sql(stmt, db.connection())


def ingest_opt_trades(
    db: Session,
    *,
    trade_date: date,
    trades_path: str,
    config: OptionsSignalsConfig = DEFAULT_CONFIG,
    trusted_report_flags: set[str] | None = None,
) -> dict[str, int]:
    df = pd.read_csv(trades_path)
    normalized = normalize_trades_frame(
        df,
        market_tz=config.market_tz,
        trusted_report_flags=trusted_report_flags,
    )
    normalized = normalized[normalized["trade_date"] == trade_date].copy()

    normalized["executed_at_utc"] = normalized["executed_at_utc"].dt.tz_convert("UTC").dt.tz_localize(None)
    normalized["executed_at_market"] = normalized["executed_at_market"].dt.tz_localize(None)

    db.execute(delete(models.OptTradeRaw).where(models.OptTradeRaw.trade_date == trade_date))
    db.flush()

    records = normalized[
        [
            "trade_id",
            "executed_at_utc",
            "executed_at_market",
            "trade_date",
            "underlying_symbol",
            "option_chain_id",
            "side",
            "strike",
            "option_type",
            "expiry_date",
            "underlying_price",
            "nbbo_bid",
            "nbbo_ask",
            "ewma_nbbo_bid",
            "ewma_nbbo_ask",
            "price",
            "size",
            "premium",
            "volume",
            "open_interest",
            "implied_volatility",
            "delta",
            "theta",
            "gamma",
            "vega",
            "rho",
            "theo",
            "sector",
            "exchange",
            "report_flags",
            "canceled",
            "upstream_condition_detail",
            "equity_type",
            "trade_direction",
            "nbbo_valid",
            "excluded_reason",
            "is_excluded",
        ]
    ].to_dict(orient="records")

    if records:
        db.bulk_insert_mappings(models.OptTradeRaw, records)

    return {
        "rows_ingested": len(records),
        "rows_excluded": int(normalized["is_excluded"].sum()),
    }


def upsert_ohlcv_daily(db: Session, df: pd.DataFrame) -> int:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    db.execute(delete(models.EqOhlcvDaily).where(models.EqOhlcvDaily.trade_date.in_(df["trade_date"].unique())))
    records = df.to_dict(orient="records")
    if records:
        db.bulk_insert_mappings(models.EqOhlcvDaily, records)
    return len(records)


def upsert_market_context(db: Session, df: pd.DataFrame) -> int:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    db.execute(delete(models.MktContextDaily).where(models.MktContextDaily.trade_date.in_(df["trade_date"].unique())))
    records = df.to_dict(orient="records")
    if records:
        db.bulk_insert_mappings(models.MktContextDaily, records)
    return len(records)


def upsert_sector_context(db: Session, df: pd.DataFrame) -> int:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    db.execute(delete(models.SectorContextDaily).where(models.SectorContextDaily.trade_date.in_(df["trade_date"].unique())))
    records = df.to_dict(orient="records")
    if records:
        db.bulk_insert_mappings(models.SectorContextDaily, records)
    return len(records)


def upsert_news_sentiment(db: Session, df: pd.DataFrame) -> int:
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    df["news_missing"] = df.get("news_missing", False)
    if "sentiment_abs_mean" not in df.columns:
        if "sentiment_mean" in df.columns:
            df["sentiment_abs_mean"] = df["sentiment_mean"].abs()
        else:
            df["sentiment_abs_mean"] = 0.0
    db.execute(delete(models.NewsSentimentDaily).where(models.NewsSentimentDaily.trade_date.in_(df["trade_date"].unique())))
    records = df.to_dict(orient="records")
    if records:
        db.bulk_insert_mappings(models.NewsSentimentDaily, records)
    return len(records)


def _weighted_avg(values: pd.Series, weights: pd.Series) -> float | None:
    v = pd.to_numeric(values, errors="coerce")
    w = pd.to_numeric(weights, errors="coerce")
    mask = v.notna() & w.notna()
    if mask.sum() == 0:
        return None
    return float((v[mask] * w[mask]).sum() / w[mask].sum())


def compute_contract_aggregates(db: Session, *, trade_date: date) -> int:
    trades = _read_sql_df(
        db,
        select(models.OptTradeRaw).where(models.OptTradeRaw.trade_date == trade_date),
    )
    if trades.empty:
        return 0
    trades = trades[~trades["is_excluded"]].copy()
    trades["trade_qty"] = trades["size"].fillna(trades["volume"]).fillna(0)
    trades = trades.sort_values("executed_at_market")

    grouped = trades.groupby("option_chain_id", dropna=False)
    agg = grouped.agg(
        underlying_symbol=("underlying_symbol", "first"),
        expiry_date=("expiry_date", "first"),
        option_type=("option_type", "first"),
        strike=("strike", "first"),
        contract_volume=("trade_qty", "sum"),
        contract_premium=("premium", "sum"),
        contract_trade_count=("trade_id", "count"),
    )
    last = grouped.tail(1).set_index("option_chain_id")
    agg["iv_last"] = last["implied_volatility"]
    agg["delta_last"] = last["delta"]
    agg["gamma_last"] = last["gamma"]
    agg["vega_last"] = last["vega"]
    agg["oi_eod"] = last["open_interest"]

    iv_vwap = grouped.apply(lambda g: _weighted_avg(g["implied_volatility"], g["trade_qty"]))
    agg["iv_vwap"] = iv_vwap
    agg = agg.reset_index()
    agg["trade_date"] = trade_date

    db.execute(delete(models.OptAggContractDaily).where(models.OptAggContractDaily.trade_date == trade_date))
    db.flush()
    records = agg.to_dict(orient="records")
    if records:
        db.bulk_insert_mappings(models.OptAggContractDaily, records)
    return len(records)


def compute_underlying_aggregates(db: Session, *, trade_date: date, config: OptionsSignalsConfig = DEFAULT_CONFIG) -> int:
    trades = _read_sql_df(
        db,
        select(models.OptTradeRaw).where(models.OptTradeRaw.trade_date == trade_date),
    )
    if trades.empty:
        return 0
    trades = trades[~trades["is_excluded"]].copy()
    trades["trade_qty"] = trades["size"].fillna(trades["volume"]).fillna(0)

    trades["is_call"] = trades["option_type"].str.lower().eq("call")
    trades["is_put"] = trades["option_type"].str.lower().eq("put")
    trades["direction_sign"] = trades["trade_direction"].map(
        {"buyer_initiated": 1.0, "seller_initiated": -1.0}
    ).fillna(0.0)

    trades["premium_dir"] = trades["premium"] * trades["direction_sign"]
    trades["delta_exposure"] = trades["delta"] * trades["trade_qty"] * config.contract_multiplier * trades["direction_sign"]
    trades["gamma_exposure"] = trades["gamma"] * trades["trade_qty"] * config.contract_multiplier * trades["direction_sign"]
    trades["vega_exposure"] = trades["vega"] * trades["trade_qty"] * config.contract_multiplier * trades["direction_sign"]

    trades["log_moneyness"] = np.log(trades["strike"] / trades["underlying_price"])
    trades["abs_log_moneyness"] = trades["log_moneyness"].abs()
    trades["is_atm"] = trades["abs_log_moneyness"] < 0.02
    trades["is_deep_otm"] = trades["abs_log_moneyness"] > 0.10
    trades["is_otm"] = (
        (trades["is_call"] & (trades["strike"] > trades["underlying_price"]))
        | (trades["is_put"] & (trades["strike"] < trades["underlying_price"]))
    )

    grouped = trades.groupby("underlying_symbol", dropna=False)
    agg = grouped.agg(
        sector=("sector", "first"),
        call_volume=("trade_qty", lambda x: float(x[trades.loc[x.index, "is_call"]].sum())),
        put_volume=("trade_qty", lambda x: float(x[trades.loc[x.index, "is_put"]].sum())),
        call_premium=("premium", lambda x: float(x[trades.loc[x.index, "is_call"]].sum())),
        put_premium=("premium", lambda x: float(x[trades.loc[x.index, "is_put"]].sum())),
        call_trade_count=("trade_id", lambda x: int(trades.loc[x.index, "is_call"].sum())),
        put_trade_count=("trade_id", lambda x: int(trades.loc[x.index, "is_put"].sum())),
    )

    agg["avg_iv_call"] = grouped.apply(lambda g: _weighted_avg(g.loc[g["is_call"], "implied_volatility"], g.loc[g["is_call"], "trade_qty"]))
    agg["avg_iv_put"] = grouped.apply(lambda g: _weighted_avg(g.loc[g["is_put"], "implied_volatility"], g.loc[g["is_put"], "trade_qty"]))
    agg["avg_iv_all"] = grouped.apply(lambda g: _weighted_avg(g["implied_volatility"], g["trade_qty"]))

    agg["call_buy_premium"] = grouped.apply(lambda g: float(g.loc[g["is_call"] & (g["direction_sign"] > 0), "premium"].sum()))
    agg["call_sell_premium"] = grouped.apply(lambda g: float(g.loc[g["is_call"] & (g["direction_sign"] < 0), "premium"].sum()))
    agg["put_buy_premium"] = grouped.apply(lambda g: float(g.loc[g["is_put"] & (g["direction_sign"] > 0), "premium"].sum()))
    agg["put_sell_premium"] = grouped.apply(lambda g: float(g.loc[g["is_put"] & (g["direction_sign"] < 0), "premium"].sum()))
    agg["net_call_premium"] = agg["call_buy_premium"] - agg["call_sell_premium"]
    agg["net_put_premium"] = agg["put_buy_premium"] - agg["put_sell_premium"]
    agg["net_premium"] = agg["net_call_premium"] - agg["net_put_premium"]
    agg["net_delta"] = grouped["delta_exposure"].sum()
    agg["net_gamma"] = grouped["gamma_exposure"].sum()
    agg["net_vega"] = grouped["vega_exposure"].sum()

    def _bucket_net_premium(g: pd.DataFrame, bucket_col: str, is_call: bool) -> float:
        subset = g[g[bucket_col] & (g["is_call"] if is_call else g["is_put"])]
        return float(subset["premium_dir"].sum())

    agg["net_premium_atm_calls"] = grouped.apply(lambda g: _bucket_net_premium(g, "is_atm", True))
    agg["net_premium_atm_puts"] = grouped.apply(lambda g: _bucket_net_premium(g, "is_atm", False))
    agg["net_premium_otm_calls"] = grouped.apply(lambda g: _bucket_net_premium(g, "is_otm", True))
    agg["net_premium_otm_puts"] = grouped.apply(lambda g: _bucket_net_premium(g, "is_otm", False))
    agg["net_premium_deep_otm_calls"] = grouped.apply(lambda g: _bucket_net_premium(g, "is_deep_otm", True))
    agg["net_premium_deep_otm_puts"] = grouped.apply(lambda g: _bucket_net_premium(g, "is_deep_otm", False))

    agg["put_call_vol_ratio"] = agg["put_volume"] / agg["call_volume"].clip(lower=1)
    agg["put_call_prem_ratio"] = agg["put_premium"] / agg["call_premium"].clip(lower=1)

    total_trades = grouped.size()
    missing_nbbo = grouped.apply(lambda g: int((~g["nbbo_valid"]).sum()))
    agg["pct_trades_missing_nbbo"] = (missing_nbbo / total_trades).replace([np.inf, -np.inf], np.nan)

    contract_agg = _read_sql_df(
        db,
        select(models.OptAggContractDaily).where(models.OptAggContractDaily.trade_date == trade_date),
    )
    if not contract_agg.empty:
        by_underlying = contract_agg.groupby(["underlying_symbol", "option_type"])
        oi = by_underlying["oi_eod"].sum().unstack().rename(columns={"call": "oi_call_eod", "put": "oi_put_eod"})
        agg = agg.join(oi, how="left")

    prev_date = trade_date - timedelta(days=1)
    prev = _read_sql_df(
        db,
        select(models.OptAggUnderlyingDaily).where(models.OptAggUnderlyingDaily.trade_date == prev_date),
    )
    if not prev.empty:
        prev = prev.set_index("underlying_symbol")
        agg["oi_change_call"] = agg.get("oi_call_eod") - prev.get("oi_call_eod")
        agg["oi_change_put"] = agg.get("oi_put_eod") - prev.get("oi_put_eod")

    agg = agg.reset_index().rename(columns={"underlying_symbol": "underlying_symbol"})
    agg["trade_date"] = trade_date

    db.execute(delete(models.OptAggUnderlyingDaily).where(models.OptAggUnderlyingDaily.trade_date == trade_date))
    db.flush()
    records = agg.to_dict(orient="records")
    if records:
        db.bulk_insert_mappings(models.OptAggUnderlyingDaily, records)
    return len(records)


def _compute_skew_term_structure(trades: pd.DataFrame, trade_date: date, config: OptionsSignalsConfig) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame()
    trades = trades.copy()
    trades["dte"] = (pd.to_datetime(trades["expiry_date"]) - pd.to_datetime(trade_date)).dt.days

    skew_rows = []
    for underlying, g in trades.groupby("underlying_symbol", dropna=False):
        calls_25 = g[(g["is_call"]) & (g["delta"].between(0.2, 0.3))]
        puts_25 = g[(g["is_put"]) & (g["delta"].between(-0.3, -0.2))]
        iv_25d_call = calls_25["implied_volatility"].median()
        iv_25d_put = puts_25["implied_volatility"].median()
        skew_25d = iv_25d_put - iv_25d_call if pd.notna(iv_25d_call) and pd.notna(iv_25d_put) else np.nan

        front = g[g["dte"] >= config.term_front_min_days]
        back = g[g["dte"].between(config.term_back_min_days, config.term_back_max_days)]
        iv_front = front.loc[front["abs_log_moneyness"] < 0.02, "implied_volatility"].median()
        iv_back = back.loc[back["abs_log_moneyness"] < 0.02, "implied_volatility"].median()
        term_structure = iv_front - iv_back if pd.notna(iv_front) and pd.notna(iv_back) else np.nan

        skew_rows.append(
            {
                "underlying_symbol": underlying,
                "iv_25d_call": iv_25d_call,
                "iv_25d_put": iv_25d_put,
                "skew_25d": skew_25d,
                "iv_front": iv_front,
                "iv_back": iv_back,
                "term_structure": term_structure,
            }
        )
    return pd.DataFrame(skew_rows)


def _compute_iv_atm_proxy(trades: pd.DataFrame) -> pd.Series:
    if trades.empty:
        return pd.Series(dtype=float)
    atm = trades[trades["delta"].abs().between(0.45, 0.55)]
    if atm.empty:
        return trades.groupby("underlying_symbol")["implied_volatility"].median()
    return atm.groupby("underlying_symbol")["implied_volatility"].median()


def compute_underlying_features(db: Session, *, trade_date: date, config: OptionsSignalsConfig = DEFAULT_CONFIG) -> int:
    agg = _read_sql_df(
        db,
        select(models.OptAggUnderlyingDaily).where(models.OptAggUnderlyingDaily.trade_date == trade_date),
    )
    if agg.empty:
        return 0
    agg = agg.set_index("underlying_symbol")
    agg = agg.rename(
        columns={
            "avg_iv_call": "iv_vwap_call",
            "avg_iv_put": "iv_vwap_put",
            "avg_iv_all": "iv_vwap_all",
        }
    )

    trades = _read_sql_df(
        db,
        select(models.OptTradeRaw).where(models.OptTradeRaw.trade_date == trade_date),
    )
    trades = trades[~trades["is_excluded"]].copy()
    trades["is_call"] = trades["option_type"].str.lower().eq("call")
    trades["is_put"] = trades["option_type"].str.lower().eq("put")
    trades["log_moneyness"] = np.log(trades["strike"] / trades["underlying_price"])
    trades["abs_log_moneyness"] = trades["log_moneyness"].abs()

    iv_atm_proxy = _compute_iv_atm_proxy(trades)
    skew = _compute_skew_term_structure(trades, trade_date, config)
    skew = skew.set_index("underlying_symbol")

    contract_agg = _read_sql_df(
        db,
        select(models.OptAggContractDaily).where(models.OptAggContractDaily.trade_date == trade_date),
    )
    if not contract_agg.empty:
        uoa_rollup = (
            contract_agg.assign(is_uoa=contract_agg["is_uoa"].fillna(False))
            .groupby("underlying_symbol")
            .agg(
                uoa_contract_count=("is_uoa", "sum"),
                uoa_max_volume_z=("uoa_volume_z", "max"),
                uoa_max_vo_i=("uoa_vo_i", "max"),
                uoa_total_premium=("contract_premium", lambda x: float(x[contract_agg.loc[x.index, "is_uoa"]].sum())),
            )
        )
    else:
        uoa_rollup = pd.DataFrame()

    ohlcv = _read_sql_df(
        db,
        select(models.EqOhlcvDaily).where(
            models.EqOhlcvDaily.underlying_symbol.in_(agg.index.tolist()),
            models.EqOhlcvDaily.trade_date <= trade_date,
        ),
    )
    tech_rows = []
    for underlying, g in ohlcv.groupby("underlying_symbol", dropna=False):
        g = g.sort_values("trade_date")
        close = g["close"].astype(float)
        if close.empty:
            continue
        macd_df = macd(close)
        boll = bollinger(close)
        tech = pd.DataFrame(
            {
                "trade_date": g["trade_date"],
                "underlying_symbol": underlying,
                "close": close,
                "ret_1d": close.pct_change(1),
                "ret_5d": close.pct_change(5),
                "ret_10d": close.pct_change(10),
                "ret_20d": close.pct_change(20),
                "sma_20": close.rolling(20).mean(),
                "sma_50": close.rolling(50).mean(),
                "ema_12": ema(close, 12),
                "ema_26": ema(close, 26),
                "rsi_14": rsi(close, 14),
                "rv_10": realized_vol(close, 10),
                "rv_20": realized_vol(close, 20),
            }
        )
        tech = pd.concat([tech, macd_df, boll], axis=1)
        rolling_high = close.rolling(20).max().shift(1)
        rolling_low = close.rolling(20).min().shift(1)
        tech["is_new_20d_high"] = close >= rolling_high
        tech["is_new_20d_low"] = close <= rolling_low
        tech_rows.append(tech)

    tech_df = pd.concat(tech_rows, ignore_index=True) if tech_rows else pd.DataFrame()
    tech_df = tech_df[tech_df["trade_date"] == trade_date].set_index("underlying_symbol")

    news = _read_sql_df(
        db,
        select(models.NewsSentimentDaily).where(models.NewsSentimentDaily.trade_date <= trade_date),
    )
    news_cur = pd.DataFrame()
    if not news.empty:
        news = news.sort_values("trade_date")
        news["news_count"] = news["article_count_24h"].fillna(0)
        news["sentiment_abs"] = news["sentiment_mean"].abs().fillna(0)
        news["sentiment_change_1d"] = news.groupby("underlying_symbol")["sentiment_mean"].diff()
    news["news_count_z_60"] = news.groupby("underlying_symbol")["news_count"].transform(
        lambda s: rolling_zscore(s, config.zscore_window, min_periods=5)
    )
        news_cur = news[news["trade_date"] == trade_date].set_index("underlying_symbol")

    mkt = _read_sql_df(db, select(models.MktContextDaily).where(models.MktContextDaily.trade_date == trade_date))
    sector = _read_sql_df(db, select(models.SectorContextDaily).where(models.SectorContextDaily.trade_date == trade_date))

    features = agg.join(tech_df, how="left").join(skew, how="left")
    features = features.join(uoa_rollup, how="left")
    features["iv_atm_proxy"] = iv_atm_proxy
    for col in ["rv_20", "rv_10", "bb_width", "close"]:
        if col not in features.columns:
            features[col] = np.nan
    features["iv_minus_rv20"] = features["iv_atm_proxy"] - features["rv_20"]
    features["iv_to_rv20_ratio"] = features["iv_atm_proxy"] / features["rv_20"].replace(0, np.nan)

    if not mkt.empty:
        mkt_row = mkt.iloc[0]
        features["spx_ret_1d"] = mkt_row["spx_return_1d"]
        features["spx_ret_5d"] = mkt_row["spx_return_5d"]
        features["vix_level"] = mkt_row["vix_close"]
        features["vix_change_1d"] = mkt_row["vix_change_1d"]
        features["vix_change_5d"] = mkt_row["vix_change_5d"]
        features["t10y_change_1d"] = mkt_row["t10y_change_1d"]
        features["t10y_change_5d"] = mkt_row["t10y_change_5d"]
        features["wti_ret_1d"] = mkt_row["wti_ret_1d"]

    if not sector.empty:
        sector_map = sector.set_index("sector_or_etf")
        features["sector_ret_1d"] = features["sector"].map(sector_map["return_1d"]) if "sector" in features.columns else np.nan
        features["sector_ret_5d"] = features["sector"].map(sector_map["return_5d"]) if "sector" in features.columns else np.nan
        features["sector_rv_20"] = features["sector"].map(sector_map["realized_vol_20d"]) if "sector" in features.columns else np.nan

    if not news_cur.empty:
        features = features.join(
            news_cur[
                [
                    "news_count",
                    "sentiment_mean",
                    "sentiment_abs",
                    "sentiment_change_1d",
                    "news_count_z_60",
                    "news_missing",
                ]
            ],
            how="left",
        )
    if "news_count" not in features.columns:
        features["news_count"] = 0
    features["news_count"] = features["news_count"].fillna(0)
    if "sentiment_mean" not in features.columns:
        features["sentiment_mean"] = 0
    else:
        features["sentiment_mean"] = features["sentiment_mean"].fillna(0)
    if "sentiment_abs" not in features.columns:
        features["sentiment_abs"] = 0
    else:
        features["sentiment_abs"] = features["sentiment_abs"].fillna(0)
    if "sentiment_change_1d" not in features.columns:
        features["sentiment_change_1d"] = np.nan
    if "news_count_z_60" not in features.columns:
        features["news_count_z_60"] = np.nan
    if "news_missing" not in features.columns:
        features["news_missing"] = True
    features["news_missing"] = features["news_missing"].fillna(True)

    history = _read_sql_df(
        db,
        select(models.FeaturesUnderlyingDaily).where(models.FeaturesUnderlyingDaily.underlying_symbol.in_(features.index.tolist())),
    )
    if not history.empty:
        history = history.sort_values("trade_date")
        combined = pd.concat([history, features.reset_index()], ignore_index=True, sort=False)
    else:
        combined = features.reset_index()

    combined = combined.sort_values(["underlying_symbol", "trade_date"])
    combined["iv_rank_252"] = combined.groupby("underlying_symbol")["iv_atm_proxy"].transform(
        lambda s: rolling_percentile_rank(s, config.iv_rank_window, min_periods=10)
    )
    combined["rv20_z"] = combined.groupby("underlying_symbol")["rv_20"].transform(
        lambda s: rolling_zscore(s, config.iv_rank_window, min_periods=10)
    )
    combined["iv_atm_proxy_change_1d"] = combined.groupby("underlying_symbol")["iv_atm_proxy"].diff()
    combined["iv_atm_proxy_change_5d"] = combined.groupby("underlying_symbol")["iv_atm_proxy"].diff(5)
    combined["rv_10_change_5d"] = combined.groupby("underlying_symbol")["rv_10"].diff(5)

    current = combined[combined["trade_date"] == trade_date].copy()
    current["trade_date"] = trade_date
    current = current.replace({np.nan: None})
    current_records = current.to_dict(orient="records")

    db.execute(delete(models.FeaturesUnderlyingDaily).where(models.FeaturesUnderlyingDaily.trade_date == trade_date))
    db.flush()
    if current_records:
        db.bulk_insert_mappings(models.FeaturesUnderlyingDaily, current_records)
    return len(current_records)


def _compute_contract_uoa(db: Session, trade_date: date, config: OptionsSignalsConfig) -> pd.DataFrame:
    start_date = trade_date - timedelta(days=config.uoa_window * 2)
    history = _read_sql_df(
        db,
        select(models.OptAggContractDaily).where(
            models.OptAggContractDaily.trade_date >= start_date,
            models.OptAggContractDaily.trade_date <= trade_date,
        ),
    )
    if history.empty:
        return pd.DataFrame()
    history = history.sort_values(["option_chain_id", "trade_date"])
    history["volume_z"] = history.groupby("option_chain_id")["contract_volume"].transform(
        lambda s: rolling_zscore(s, config.uoa_window, min_periods=5)
    )
    history["premium_z"] = history.groupby("option_chain_id")["contract_premium"].transform(
        lambda s: rolling_zscore(s, config.uoa_window, min_periods=5)
    )
    history["vol_oi_ratio"] = history["contract_volume"] / history["oi_eod"].replace(0, np.nan)
    current = history[history["trade_date"] == trade_date].copy()
    current["is_uoa"] = (current["volume_z"] >= 3) | (
        (current["vol_oi_ratio"] >= 1.0) & (current["contract_volume"] >= 10)
    )
    return current[
        [
            "option_chain_id",
            "volume_z",
            "premium_z",
            "vol_oi_ratio",
            "is_uoa",
        ]
    ].rename(
        columns={
            "volume_z": "uoa_volume_z",
            "premium_z": "uoa_premium_z",
            "vol_oi_ratio": "uoa_vo_i",
        }
    )


def compute_uoa_metrics(db: Session, *, trade_date: date, config: OptionsSignalsConfig = DEFAULT_CONFIG) -> int:
    uoa = _compute_contract_uoa(db, trade_date, config)
    if uoa.empty:
        return 0
    for _, row in uoa.iterrows():
        db.execute(
            models.OptAggContractDaily.__table__.update()
            .where(models.OptAggContractDaily.trade_date == trade_date)
            .where(models.OptAggContractDaily.option_chain_id == row["option_chain_id"])
            .values(
                uoa_volume_z=row.get("uoa_volume_z"),
                uoa_premium_z=row.get("uoa_premium_z"),
                uoa_vo_i=row.get("uoa_vo_i"),
                is_uoa=bool(row.get("is_uoa")),
            )
        )
    return int(len(uoa))


def _compute_feature_zscores(features: pd.DataFrame, config: OptionsSignalsConfig) -> pd.DataFrame:
    features = features.sort_values(["underlying_symbol", "trade_date"])
    zcols = {
        "call_buy_premium": "z_call_buy_premium_60",
        "put_buy_premium": "z_put_buy_premium_60",
        "net_delta": "z_net_delta_60",
        "put_call_vol_ratio": "z_put_call_vol_ratio_60",
        "uoa_contract_count": "z_uoa_contract_count_60",
        "skew_25d": "z_skew_60",
        "bb_width": "z_bb_width_60",
        "iv_atm_proxy_change_5d": "z_iv_atm_proxy_change_5d",
        "rv_10_change_5d": "z_rv_10_change_5d",
        "news_count": "z_news_count_60",
    }
    for col, zcol in zcols.items():
        if col not in features.columns:
            features[zcol] = np.nan
            continue
        features[zcol] = features.groupby("underlying_symbol")[col].transform(
            lambda s: rolling_zscore(s, config.zscore_window, min_periods=5)
        )
    return features


def compute_signals(db: Session, *, trade_date: date, config: OptionsSignalsConfig = DEFAULT_CONFIG) -> int:
    history = _read_sql_df(
        db,
        select(models.FeaturesUnderlyingDaily).where(models.FeaturesUnderlyingDaily.trade_date <= trade_date),
    )
    if history.empty:
        return 0
    history = _compute_feature_zscores(history, config)
    current = history[history["trade_date"] == trade_date].copy()
    if current.empty:
        return 0

    z_cols = [
        "z_call_buy_premium_60",
        "z_put_buy_premium_60",
        "z_net_delta_60",
        "z_iv_atm_proxy_change_5d",
        "z_rv_10_change_5d",
        "z_news_count_60",
        "z_bb_width_60",
    ]
    for col in z_cols:
        if col in current.columns:
            current[col] = current[col].fillna(0.0)

    current["bull_flow"] = (
        current["z_call_buy_premium_60"] - current["z_put_buy_premium_60"] + 0.5 * current["z_net_delta_60"]
    )
    current["bear_flow"] = (
        current["z_put_buy_premium_60"] - current["z_call_buy_premium_60"] - 0.5 * current["z_net_delta_60"]
    )
    current["vol_expansion"] = (
        current["z_iv_atm_proxy_change_5d"] + current["z_rv_10_change_5d"] + current["z_news_count_60"]
    )
    current["tech_breakout"] = (
        current["is_new_20d_high"].fillna(False).astype(int)
        - current["is_new_20d_low"].fillna(False).astype(int)
        + 0.5 * current["z_bb_width_60"]
    )

    signal_rows = []
    for signal_name, score_col, components in [
        ("BULL_FLOW", "bull_flow", ["z_call_buy_premium_60", "z_put_buy_premium_60", "z_net_delta_60"]),
        ("BEAR_FLOW", "bear_flow", ["z_put_buy_premium_60", "z_call_buy_premium_60", "z_net_delta_60"]),
        ("VOL_EXPANSION", "vol_expansion", ["z_iv_atm_proxy_change_5d", "z_rv_10_change_5d", "z_news_count_60"]),
        ("TECH_BREAKOUT", "tech_breakout", ["z_bb_width_60", "is_new_20d_high", "is_new_20d_low"]),
    ]:
        ranked = current[["underlying_symbol", score_col] + components].copy()
        ranked = ranked.sort_values(score_col, ascending=False)
        ranked["rank"] = range(1, len(ranked) + 1)
        for _, row in ranked.iterrows():
            explanation = {c: float(row.get(c)) if pd.notna(row.get(c)) else None for c in components}
            signal_rows.append(
                {
                    "trade_date": trade_date,
                    "underlying_symbol": row["underlying_symbol"],
                    "signal_name": signal_name,
                    "score": float(row[score_col]) if pd.notna(row[score_col]) else 0.0,
                    "rank": int(row["rank"]),
                    "explanation_json": {"components": explanation},
                }
            )

    db.execute(delete(models.SignalsUnderlyingDaily).where(models.SignalsUnderlyingDaily.trade_date == trade_date))
    db.flush()
    if signal_rows:
        db.bulk_insert_mappings(models.SignalsUnderlyingDaily, signal_rows)
    return len(signal_rows)


def generate_alerts(db: Session, *, trade_date: date, config: OptionsSignalsConfig = DEFAULT_CONFIG) -> int:
    features = _read_sql_df(
        db,
        select(models.FeaturesUnderlyingDaily).where(models.FeaturesUnderlyingDaily.trade_date <= trade_date),
    )
    if features.empty:
        return 0
    features = _compute_feature_zscores(features, config)
    current = features[features["trade_date"] == trade_date].copy()
    if current.empty:
        return 0

    alerts = []
    for _, row in current.iterrows():
        sym = row["underlying_symbol"]
        thresholds = {}
        if row.get("uoa_max_volume_z", 0) >= 3 or row.get("uoa_max_vo_i", 0) >= 1.0:
            thresholds["UOA_SPIKE"] = True
        if row.get("z_call_buy_premium_60", 0) >= 2.5 and row.get("put_call_vol_ratio", 1) <= 0.7:
            thresholds["FLOW_EXTREME_BULL"] = True
        if row.get("z_put_buy_premium_60", 0) >= 2.5 and row.get("put_call_vol_ratio", 1) >= 1.3:
            thresholds["FLOW_EXTREME_BEAR"] = True
        if row.get("iv_atm_proxy_change_1d", 0) >= 0.05:
            thresholds["IV_SPIKE"] = True
        if row.get("news_count_z_60", 0) >= 3:
            thresholds["NEWS_SURGE"] = True

        if not thresholds:
            continue

        contracts = _read_sql_df(
            db,
            select(models.OptAggContractDaily).where(
                models.OptAggContractDaily.trade_date == trade_date,
                models.OptAggContractDaily.underlying_symbol == sym,
            ),
        )
        top_contracts = []
        if not contracts.empty:
            contracts = contracts.sort_values("contract_premium", ascending=False).head(5)
            for _, c in contracts.iterrows():
                top_contracts.append(
                    {
                        "option_chain_id": c["option_chain_id"],
                        "strike": float(c["strike"]) if pd.notna(c["strike"]) else None,
                        "expiry_date": c["expiry_date"],
                        "option_type": c["option_type"],
                        "contract_volume": float(c["contract_volume"]) if pd.notna(c["contract_volume"]) else None,
                        "contract_premium": float(c["contract_premium"]) if pd.notna(c["contract_premium"]) else None,
                        "uoa_volume_z": float(c["uoa_volume_z"]) if pd.notna(c["uoa_volume_z"]) else None,
                    }
                )

        alerts.append(
            {
                "event_ts": datetime.utcnow(),
                "trade_date": trade_date,
                "underlying_symbol": sym,
                "event_type": ",".join(sorted(thresholds.keys())),
                "severity": "high" if len(thresholds) > 1 else "medium",
                "payload_json": {
                    "thresholds": thresholds,
                    "values": {
                        "z_call_buy_premium_60": row.get("z_call_buy_premium_60"),
                        "z_put_buy_premium_60": row.get("z_put_buy_premium_60"),
                        "put_call_vol_ratio": row.get("put_call_vol_ratio"),
                        "uoa_max_volume_z": row.get("uoa_max_volume_z"),
                        "uoa_max_vo_i": row.get("uoa_max_vo_i"),
                        "news_count_z_60": row.get("news_count_z_60"),
                    },
                    "top_contracts": top_contracts,
                },
            }
        )

    db.execute(delete(models.AlertsEventLog).where(models.AlertsEventLog.trade_date == trade_date))
    db.flush()
    if alerts:
        db.bulk_insert_mappings(models.AlertsEventLog, alerts)
    return len(alerts)


def update_data_quality(db: Session, *, trade_date: date) -> int:
    trades = _read_sql_df(
        db,
        select(models.OptTradeRaw).where(models.OptTradeRaw.trade_date == trade_date),
    )
    total_trades = len(trades)
    canceled_filtered = int(trades["excluded_reason"].eq("canceled").sum()) if not trades.empty else 0
    trades_missing_nbbo = int((~trades["nbbo_valid"]).sum()) if not trades.empty else 0

    underlyings = trades["underlying_symbol"].unique().tolist() if not trades.empty else []
    ohlcv = _read_sql_df(
        db,
        select(models.EqOhlcvDaily).where(
            models.EqOhlcvDaily.trade_date == trade_date,
            models.EqOhlcvDaily.underlying_symbol.in_(underlyings),
        ),
    )
    news = _read_sql_df(
        db,
        select(models.NewsSentimentDaily).where(
            models.NewsSentimentDaily.trade_date == trade_date,
            models.NewsSentimentDaily.underlying_symbol.in_(underlyings),
        ),
    )

    symbols_missing_ohlcv = len(set(underlyings) - set(ohlcv["underlying_symbol"].unique())) if underlyings else 0
    symbols_missing_news = len(set(underlyings) - set(news["underlying_symbol"].unique())) if underlyings else 0

    freshness = {
        "opt_trades_raw": trade_date.isoformat() if total_trades else None,
        "eq_ohlcv_daily": ohlcv["trade_date"].max().isoformat() if not ohlcv.empty else None,
        "news_sentiment_daily": news["trade_date"].max().isoformat() if not news.empty else None,
    }

    db.execute(delete(models.OptionsSignalsDataQualityDaily).where(models.OptionsSignalsDataQualityDaily.trade_date == trade_date))
    db.flush()
    db.add(
        models.OptionsSignalsDataQualityDaily(
            trade_date=trade_date,
            total_trades=total_trades,
            canceled_filtered=canceled_filtered,
            trades_missing_nbbo=trades_missing_nbbo,
            symbols_missing_ohlcv=symbols_missing_ohlcv,
            symbols_missing_news=symbols_missing_news,
            freshness_json=freshness,
        )
    )
    return 1


def run_daily_pipeline(
    db: Session,
    *,
    trade_date: date,
    trades_path: str | None = None,
    ohlcv_path: str | None = None,
    market_path: str | None = None,
    news_path: str | None = None,
    sector_path: str | None = None,
    config: OptionsSignalsConfig = DEFAULT_CONFIG,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    if trades_path:
        counts["trades_ingested"] = ingest_opt_trades(
            db,
            trade_date=trade_date,
            trades_path=trades_path,
            config=config,
        )["rows_ingested"]

    if ohlcv_path:
        counts["ohlcv_upserted"] = upsert_ohlcv_daily(db, pd.read_csv(ohlcv_path))
    if market_path:
        counts["market_upserted"] = upsert_market_context(db, pd.read_csv(market_path))
    if news_path:
        counts["news_upserted"] = upsert_news_sentiment(db, pd.read_csv(news_path))
    if sector_path:
        counts["sector_upserted"] = upsert_sector_context(db, pd.read_csv(sector_path))

    counts["contract_agg"] = compute_contract_aggregates(db, trade_date=trade_date)
    counts["uoa_updates"] = compute_uoa_metrics(db, trade_date=trade_date, config=config)
    counts["underlying_agg"] = compute_underlying_aggregates(db, trade_date=trade_date, config=config)
    counts["features"] = compute_underlying_features(db, trade_date=trade_date, config=config)
    counts["signals"] = compute_signals(db, trade_date=trade_date, config=config)
    counts["alerts"] = generate_alerts(db, trade_date=trade_date, config=config)
    counts["data_quality"] = update_data_quality(db, trade_date=trade_date)
    return counts


def run_backfill(
    db: Session,
    *,
    start_date: date,
    end_date: date,
    trades_paths: dict[date, str],
    config: OptionsSignalsConfig = DEFAULT_CONFIG,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    current = start_date
    while current <= end_date:
        counts[current.isoformat()] = run_daily_pipeline(
            db,
            trade_date=current,
            trades_path=trades_paths.get(current),
            config=config,
        )
        current += timedelta(days=1)
    return counts
