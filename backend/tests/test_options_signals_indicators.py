import pandas as pd

from app.options_signals.indicators import bollinger, macd, percentile_rank, realized_vol, rsi


def test_rsi_trending_series_high():
    series = pd.Series(range(1, 30))
    rsi_vals = rsi(series, period=14)
    assert rsi_vals.iloc[-1] > 70


def test_macd_outputs_columns():
    series = pd.Series([1, 2, 3, 2, 4, 5, 4, 6, 7, 6, 8, 9, 8, 10, 11])
    out = macd(series)
    assert {"macd", "macd_signal", "macd_hist"} <= set(out.columns)
    assert len(out) == len(series)


def test_bollinger_mid_matches_mean():
    series = pd.Series([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
    bb = bollinger(series, window=5, num_std=2)
    assert abs(bb["bb_mid"].iloc[-1] - series.rolling(5).mean().iloc[-1]) < 1e-6


def test_realized_vol_nonzero():
    series = pd.Series([100, 101, 102, 101, 103, 104, 105, 106, 105, 107, 108, 109])
    rv = realized_vol(series, window=5)
    assert rv.iloc[-1] >= 0


def test_percentile_rank_bounds():
    values = [1, 2, 3, 4, 5]
    assert percentile_rank(3, values) == 0.6
