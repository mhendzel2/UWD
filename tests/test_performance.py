from __future__ import annotations

from pathlib import Path

import pandas as pd

from trade_surveillance.performance import analyze_top_signals_vs_price


def test_analyze_performance_builds_outputs(tmp_path: Path) -> None:
    # Create a minimal scores.parquet spanning 2 session dates.
    scores = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T20:00:00Z",
                    "2026-01-02T20:01:00Z",
                    "2026-01-03T20:00:00Z",
                    "2026-01-03T20:01:00Z",
                    "2026-01-03T20:02:00Z",
                ],
                utc=True,
            ),
            "symbol": ["AAPL", "AAPL", "AAPL", "AAPL", "AAPL"],
            "ensemble_pct": [0.90, 0.99, 0.95, 0.97, 0.80],
            "reason": ["r1", "r2", "r3", "r4", "r5"],
        }
    )
    scores_path = tmp_path / "scores.parquet"
    scores.to_parquet(scores_path, index=False)

    # Create daily prices for AAPL under a local prices-dir.
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pd.DataFrame(
        {
            "date": ["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-02", "2026-01-03", "2026-01-06"],
            "open": [100, 101, 102, 103, 104, 105],
            "high": [101, 102, 103, 104, 105, 106],
            "low": [99, 100, 101, 102, 103, 104],
            "close": [100, 101, 102, 103, 104, 105],
            "volume": [1, 1, 1, 1, 1, 1],
        }
    )
    prices.to_csv(prices_dir / "aapl.us.csv", index=False)

    out_dir = tmp_path / "out"
    analyze_top_signals_vs_price(
        scores_path=str(scores_path),
        prices_dir=str(prices_dir),
        out_dir=str(out_dir),
        top_k=2,
        lookback_days=3,
        forward_days=3,
        tz="America/New_York",
    )

    assert (out_dir / "signals.parquet").exists()
    assert (out_dir / "signal_price_windows.parquet").exists()
    assert (out_dir / "signal_return_summary.parquet").exists()

    sig = pd.read_parquet(out_dir / "signals.parquet")
    summ = pd.read_parquet(out_dir / "signal_return_summary.parquet")

    assert len(sig) > 0
    assert "signal_id" in sig.columns
    assert "session_date" in sig.columns
    assert "entry_close" in summ.columns


def test_analyze_performance_threshold_selects_all_above_cutoff(tmp_path: Path) -> None:
    scores = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T20:00:00Z",
                    "2026-01-02T20:01:00Z",
                    "2026-01-02T20:02:00Z",
                    "2026-01-03T20:00:00Z",
                    "2026-01-03T20:01:00Z",
                    "2026-01-03T20:02:00Z",
                ],
                utc=True,
            ),
            "symbol": ["AAPL"] * 6,
            "ensemble_pct": [0.90, 0.96, 0.99, 0.20, 0.95, 0.97],
            "reason": ["r1", "r2", "r3", "r4", "r5", "r6"],
        }
    )
    scores_path = tmp_path / "scores.parquet"
    scores.to_parquet(scores_path, index=False)

    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pd.DataFrame(
        {
            "date": ["2025-12-31", "2026-01-02", "2026-01-03", "2026-01-06"],
            "open": [102, 103, 104, 105],
            "high": [103, 104, 105, 106],
            "low": [101, 102, 103, 104],
            "close": [102, 103, 104, 105],
            "volume": [1, 1, 1, 1],
        }
    )
    prices.to_csv(prices_dir / "aapl.us.csv", index=False)

    out_dir = tmp_path / "out"
    analyze_top_signals_vs_price(
        scores_path=str(scores_path),
        prices_dir=str(prices_dir),
        out_dir=str(out_dir),
        top_k=1,
        min_percentile=0.95,
        percentile_col="ensemble_pct",
        lookback_days=1,
        forward_days=1,
        tz="America/New_York",
    )

    sig = pd.read_parquet(out_dir / "signals.parquet")
    # Rows with ensemble_pct >= 0.95: 0.96, 0.99, 0.95, 0.97 => 4
    assert len(sig) == 4
    assert "daily_rank" in sig.columns


def test_analyze_performance_per_symbol_cap_balances_symbols(tmp_path: Path) -> None:
    scores = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-01-02T20:00:00Z",
                    "2026-01-02T20:01:00Z",
                    "2026-01-02T20:02:00Z",
                    "2026-01-03T20:00:00Z",
                    "2026-01-03T20:01:00Z",
                    "2026-01-03T20:02:00Z",
                    "2026-01-02T20:00:30Z",
                    "2026-01-02T20:01:30Z",
                    "2026-01-03T20:00:30Z",
                    "2026-01-03T20:01:30Z",
                ],
                utc=True,
            ),
            "symbol": [
                "AAPL",
                "AAPL",
                "AAPL",
                "AAPL",
                "AAPL",
                "AAPL",
                "SPY",
                "SPY",
                "SPY",
                "SPY",
            ],
            "ensemble_pct": [0.90, 0.96, 0.99, 0.20, 0.95, 0.97, 0.50, 0.99, 0.10, 0.98],
            "reason": [f"r{i}" for i in range(10)],
        }
    )
    scores_path = tmp_path / "scores.parquet"
    scores.to_parquet(scores_path, index=False)

    prices_dir = tmp_path / "prices"
    prices_dir.mkdir(parents=True, exist_ok=True)
    prices = pd.DataFrame(
        {
            "date": ["2026-01-02", "2026-01-03", "2026-01-06"],
            "open": [100, 101, 102],
            "high": [101, 102, 103],
            "low": [99, 100, 101],
            "close": [100, 101, 102],
            "volume": [1, 1, 1],
        }
    )
    prices.to_csv(prices_dir / "aapl.us.csv", index=False)
    prices.to_csv(prices_dir / "spy.us.csv", index=False)

    out_dir = tmp_path / "out"
    analyze_top_signals_vs_price(
        scores_path=str(scores_path),
        prices_dir=str(prices_dir),
        out_dir=str(out_dir),
        min_percentile=0.0,
        percentile_col="ensemble_pct",
        per_symbol_top_n=1,
        lookback_days=1,
        forward_days=1,
        tz="America/New_York",
    )

    sig = pd.read_parquet(out_dir / "signals.parquet")
    # With per_symbol_top_n=1 and 2 days, expect 2 symbols * 2 days * 1 = 4 signals.
    assert len(sig) == 4
    assert set(sig["symbol"]) == {"AAPL", "SPY"}
