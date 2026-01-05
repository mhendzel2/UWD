from __future__ import annotations

from pathlib import Path

import pandas as pd

from trade_surveillance.pipeline import featurize, score
from trade_surveillance.synth import generate_demo_data


def test_score_writes_parquet(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo"
    generate_demo_data(out_dir=str(out_dir), n_trades=3000, with_quotes=True, seed=7)

    trades_path = out_dir / "trades.csv"
    quotes_path = out_dir / "quotes.csv"
    features_path = tmp_path / "features.parquet"
    scores_path = tmp_path / "scores.parquet"

    featurize(trades_path=str(trades_path), quotes_path=str(quotes_path), out_path=str(features_path))
    score(features_path=str(features_path), out_path=str(scores_path))

    assert scores_path.exists()

    df = pd.read_parquet(scores_path)
    assert len(df) > 0

    for col in [
        "timestamp",
        "symbol",
        "score_mcd_mahal",
        "score_isoforest",
        "score_pca_spe",
        "score_pca_t2",
        "score_changepoint",
        "ensemble_score",
        "ensemble_pct",
        "reason",
    ]:
        assert col in df.columns

    assert df["ensemble_pct"].between(0.0, 1.0).all()
