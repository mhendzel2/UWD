from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "macd_signal": signal_line, "macd_hist": hist})


def bollinger(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = series.rolling(window=window).mean()
    std = series.rolling(window=window).std(ddof=0)
    upper = mid + num_std * std
    lower = mid - num_std * std
    width = (upper - lower) / mid.replace(0, np.nan)
    pct = (series - lower) / (upper - lower)
    pct = pct.clip(lower=0, upper=1)
    return pd.DataFrame(
        {
            "bb_mid": mid,
            "bb_std": std,
            "bb_upper": upper,
            "bb_lower": lower,
            "bb_width": width,
            "bb_pct": pct,
        }
    )


def realized_vol(series: pd.Series, window: int) -> pd.Series:
    log_ret = np.log(series.astype(float) / series.astype(float).shift(1))
    return log_ret.rolling(window=window).std(ddof=0) * np.sqrt(252)


def rolling_zscore(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    if min_periods is None:
        min_periods = window
    roll = series.rolling(window=window, min_periods=min_periods)
    mean = roll.mean()
    std = roll.std(ddof=0).replace(0, np.nan)
    return (series - mean) / std


def percentile_rank(value: float, sorted_values: list[float]) -> float:
    if not sorted_values:
        return 0.0
    arr = np.array(sorted_values, dtype=float)
    return float(np.sum(arr <= value)) / float(len(arr))


def rolling_percentile_rank(series: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    if min_periods is None:
        min_periods = window
    return series.rolling(window=window, min_periods=min_periods).apply(
        lambda x: percentile_rank(float(x.iloc[-1]), sorted(x.tolist())),
        raw=False,
    )

