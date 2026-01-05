from __future__ import annotations

from pathlib import Path

import pandas as pd

from trade_surveillance.pipeline import featurize, score


def test_cross_norm_improves_spike_separation(tmp_path: Path) -> None:
    # Build a synthetic single-symbol dataset with a regime shift + one extreme spike.
    # Baseline (global/context z-features) tends to flag the whole shift.
    # With cross/rolling norm features enabled, we expect fewer false positives in the new regime
    # and a clearer separation for the single extreme spike.

    n1 = 400  # early regime
    n2 = 120  # later regime

    ts = pd.date_range("2026-01-02T14:30:00Z", periods=n1 + n2, freq="1s")

    # Early regime: small sizes
    qty1 = pd.Series([100.0] * n1)
    # Late regime: bigger sizes (new normal)
    qty2 = pd.Series([1000.0] * (n2 - 1))
    # Extreme spike at the very end
    spike_qty = 100000.0

    qty = pd.concat([qty1, qty2, pd.Series([spike_qty])], ignore_index=True)

    trades = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": ["SPY"] * len(ts),
            "venue": ["NYSE"] * len(ts),
            "trader_id": ["T1"] * len(ts),
            "side": ["BUY"] * len(ts),
            "price": [100.0] * len(ts),
            "qty": qty,
        }
    )

    trades_path = tmp_path / "trades.csv"
    trades.to_csv(trades_path, index=False)

    features_path = tmp_path / "features.parquet"
    featurize(trades_path=str(trades_path), quotes_path=None, out_path=str(features_path))

    scores_base = tmp_path / "scores_base.parquet"
    scores_cross = tmp_path / "scores_cross.parquet"

    score(features_path=str(features_path), out_path=str(scores_base), use_cross_norm=False)
    score(features_path=str(features_path), out_path=str(scores_cross), use_cross_norm=True)

    base = pd.read_parquet(scores_base)
    cross = pd.read_parquet(scores_cross)

    # Identify spike row in each output via max qty.
    spike_base = base.loc[base["qty"].idxmax()]
    spike_cross = cross.loc[cross["qty"].idxmax()]

    assert float(spike_base["qty"]) == spike_qty
    assert float(spike_cross["qty"]) == spike_qty

    # Measure "quality" proxy: fewer high-stringency false positives in the late regime,
    # while keeping the spike extremely high percentile.
    #
    # We compare the number of rows with ensemble_pct >= 0.99 among the final 100 rows,
    # excluding the spike row itself.
    tail_n = 100

    base_tail = base.tail(tail_n).copy()
    cross_tail = cross.tail(tail_n).copy()

    base_tail_no_spike = base_tail[base_tail["qty"] != spike_qty]
    cross_tail_no_spike = cross_tail[cross_tail["qty"] != spike_qty]

    base_fp = int((base_tail_no_spike["ensemble_pct"] >= 0.99).sum())
    cross_fp = int((cross_tail_no_spike["ensemble_pct"] >= 0.99).sum())

    # Spike should remain an extreme outlier.
    assert float(spike_cross["ensemble_pct"]) >= 0.99

    # Cross/rolling normalization should reduce false positives in the new regime.
    assert cross_fp <= base_fp
