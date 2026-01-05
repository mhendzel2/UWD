from __future__ import annotations

from pathlib import Path

import pandas as pd

from trade_surveillance.pipeline import featurize
from trade_surveillance.synth import generate_demo_data


def test_featurize_writes_parquet(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo"
    generate_demo_data(out_dir=str(out_dir), n_trades=2000, with_quotes=True, seed=7)

    trades_path = out_dir / "trades.csv"
    quotes_path = out_dir / "quotes.csv"
    features_path = tmp_path / "features.parquet"

    featurize(trades_path=str(trades_path), quotes_path=str(quotes_path), out_path=str(features_path))

    assert features_path.exists()

    df = pd.read_parquet(features_path)
    # Minimal shape expectations
    assert len(df) > 0
    for col in [
        "timestamp",
        "symbol",
        "venue",
        "trader_id",
        "side",
        "price",
        "qty",
        "notional",
        "price_vs_mid_bps",
        "spread_bps",
    ]:
        assert col in df.columns

    # Normalized columns exist and are numeric
    assert "qty_z_s" in df.columns
    assert df["qty_z_s"].dtype.kind in {"f", "i"}
    
        # Liquidity/volume normalization features (from trade stream)
        for col in [
            "notional_participation",
            "qty_participation",
            "log_notional_over_roll_median",
            "log_qty_over_roll_median",
            "z_log_notional_over_roll_median",
            "z_log_qty_over_roll_median",
        ]:
            assert col in df.columns
