from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from trade_surveillance.pipeline import featurize, score
from trade_surveillance.synth import generate_demo_data


def _top_share_by_symbol(scores: pd.DataFrame, *, threshold: float = 0.99) -> pd.DataFrame:
    s = scores.copy()
    if "symbol" not in s.columns or "ensemble_pct" not in s.columns:
        return pd.DataFrame()
    s["is_top"] = pd.to_numeric(s["ensemble_pct"], errors="coerce") >= float(threshold)
    out = (
        s.groupby("symbol", dropna=False)["is_top"]
        .mean()
        .reset_index()
        .rename(columns={"is_top": f"share_pct_ge_{threshold}"})
    )
    return out.sort_values(f"share_pct_ge_{threshold}", ascending=False).reset_index(drop=True)


def _make_labeled_synthetic_trades(
    *,
    n_rows: int,
    seed: int,
    symbols: list[str] | None = None,
    anomaly_rate: float = 0.01,
    include_regime_shift: bool = True,
) -> tuple[pd.DataFrame, pd.Series]:
    """Create a labeled dataset to objectively measure anomaly-ranking quality.

    We inject anomalies as *relative* spikes per symbol (not just absolute size),
    and optionally include a regime shift where "normal" sizes increase later.
    """
    rng = np.random.default_rng(int(seed))
    symbols = symbols or ["SPY", "AAPL", "NVDA", "TSLA", "MSFT"]

    # Make unique timestamps (avoid join ambiguity).
    start = pd.Timestamp("2026-01-02T14:30:00Z")
    ts = pd.date_range(start=start, periods=int(n_rows), freq="1s")

    sym = rng.choice(symbols, size=int(n_rows), replace=True)
    venue = rng.choice(["NYSE", "NASDAQ", "ARCA"], size=int(n_rows), replace=True)
    trader = rng.choice(["T1", "T2", "T3"], size=int(n_rows), replace=True)
    side = rng.choice(["BUY", "SELL"], size=int(n_rows), replace=True)

    # Symbol-specific baseline sizes (to simulate market-cap/liquidity differences).
    base_qty_by_sym = {
        "SPY": 400.0,
        "AAPL": 300.0,
        "MSFT": 280.0,
        "NVDA": 220.0,
        "TSLA": 180.0,
    }

    # Regime shift: later in time, normal sizes drift up across all symbols.
    t = np.linspace(0.0, 1.0, int(n_rows), dtype=float)
    regime_mult = 1.0 + (0.8 * (t > 0.65)) if include_regime_shift else 1.0

    qty = np.empty(int(n_rows), dtype=float)
    for i in range(int(n_rows)):
        b = float(base_qty_by_sym.get(str(sym[i]), 200.0))
        # Mild noise around the baseline.
        qty[i] = max(1.0, b * float(regime_mult if np.isscalar(regime_mult) else regime_mult[i]) * rng.lognormal(0.0, 0.25))

    # Mid price varies per symbol; bid/ask with realistic spreads.
    base_px_by_sym = {
        "SPY": 470.0,
        "AAPL": 190.0,
        "MSFT": 410.0,
        "NVDA": 490.0,
        "TSLA": 240.0,
    }
    mid = np.array([float(base_px_by_sym.get(str(s), 100.0)) for s in sym], dtype=float)
    mid = mid * np.exp(rng.normal(0.0, 0.0002, size=int(n_rows)).cumsum())
    spread_bps = rng.choice([2.0, 4.0, 8.0, 15.0], size=int(n_rows), p=[0.70, 0.20, 0.08, 0.02])
    spread = mid * (spread_bps / 10000.0)
    bid = mid - 0.5 * spread
    ask = mid + 0.5 * spread

    # Trade price near mid.
    price = mid + rng.normal(0.0, 0.10, size=int(n_rows)) * (spread / 2.0)

    # Inject labeled anomalies: big size + aggressive price vs mid.
    y = pd.Series(np.zeros(int(n_rows), dtype=int), name="is_anomaly")
    n_anom = max(1, int(round(float(anomaly_rate) * int(n_rows))))
    pick = rng.choice(np.arange(int(n_rows)), size=int(n_anom), replace=False)
    y.iloc[pick] = 1
    qty[pick] = qty[pick] * rng.uniform(15.0, 35.0, size=int(n_anom))
    # Force price to be 50-150 bps away from mid.
    bps = rng.uniform(50.0, 150.0, size=int(n_anom)) * rng.choice([-1.0, 1.0], size=int(n_anom))
    price[pick] = mid[pick] * (1.0 + bps / 10000.0)

    trades = pd.DataFrame(
        {
            "timestamp": ts,
            "symbol": sym,
            "venue": venue,
            "trader_id": trader,
            "side": side,
            "price": price,
            "qty": qty,
            "bid": bid,
            "ask": ask,
            "mid_price": mid,
        }
    )
    return trades, y


def _ranking_metrics(y_true: pd.Series, score_series: pd.Series) -> dict[str, float]:
    y = pd.to_numeric(y_true, errors="coerce").fillna(0).astype(int).to_numpy()
    s = pd.to_numeric(score_series, errors="coerce").fillna(0.0).to_numpy(dtype=float)

    out: dict[str, float] = {}
    # Some degenerate cases can happen if y has one class; guard.
    if len(np.unique(y)) >= 2:
        out["auroc"] = float(roc_auc_score(y, s))
        out["avg_precision"] = float(average_precision_score(y, s))
    else:
        out["auroc"] = float("nan")
        out["avg_precision"] = float("nan")

    n_pos = int(y.sum())
    k = max(1, n_pos)
    order = np.argsort(-s)
    topk = y[order[:k]]
    out["precision_at_k"] = float(topk.mean())
    out["recall_at_k"] = float(topk.sum() / max(1, n_pos))

    top1 = y[order[: max(1, int(round(0.01 * len(y))))]]
    out["precision_top_1pct"] = float(top1.mean())
    out["recall_top_1pct"] = float(top1.sum() / max(1, n_pos))

    # Lift: how much better top-1% precision is vs base rate.
    base_rate = float(y.mean()) if len(y) else 0.0
    out["lift_top_1pct"] = float(out["precision_top_1pct"] / base_rate) if base_rate > 0 else float("nan")
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--work", default="tmp/ts_norm_eval", help="Working directory under repo root")
    p.add_argument("--n-trades", type=int, default=20000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--labeled", action="store_true", help="Run labeled evaluation metrics (AUROC/AP/precision@k)")
    p.add_argument("--anomaly-rate", type=float, default=0.01)
    args = p.parse_args()

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    # Either use existing demo generator (unlabeled) or a labeled synthetic dataset.
    y = None
    if bool(args.labeled):
        trades, y = _make_labeled_synthetic_trades(
            n_rows=int(args.n_trades),
            seed=int(args.seed),
            anomaly_rate=float(args.anomaly_rate),
            include_regime_shift=True,
        )
        trades_path = work / "trades_labeled.csv"
        trades.to_csv(trades_path, index=False)
        features_path = work / "features.parquet"
        featurize(trades_path=str(trades_path), quotes_path=None, out_path=str(features_path))
    else:
        demo_dir = work / "demo"
        demo_dir.mkdir(parents=True, exist_ok=True)
        generate_demo_data(out_dir=str(demo_dir), n_trades=int(args.n_trades), with_quotes=True, seed=int(args.seed))
        features_path = work / "features.parquet"
        featurize(trades_path=str(demo_dir / "trades.csv"), quotes_path=str(demo_dir / "quotes.csv"), out_path=str(features_path))

    base_path = work / "scores_base.parquet"
    cross_path = work / "scores_cross.parquet"

    score(features_path=str(features_path), out_path=str(base_path), use_cross_norm=False)
    score(features_path=str(features_path), out_path=str(cross_path), use_cross_norm=True)

    base = pd.read_parquet(base_path)
    cross = pd.read_parquet(cross_path)

    if y is not None and "ensemble_score" in base.columns and "ensemble_score" in cross.columns:
        m_base = _ranking_metrics(y, base["ensemble_score"])
        m_cross = _ranking_metrics(y, cross["ensemble_score"])
        print("=== Labeled metrics (higher is better) ===")
        keys = [
            "auroc",
            "avg_precision",
            "precision_at_k",
            "recall_at_k",
            "precision_top_1pct",
            "recall_top_1pct",
            "lift_top_1pct",
        ]
        for k in keys:
            print(f"{k:>18s}  baseline={m_base.get(k, float('nan')):8.4f}   cross_norm={m_cross.get(k, float('nan')):8.4f}")
        print("")

    # Proxy metrics
    base_top = _top_share_by_symbol(base)
    cross_top = _top_share_by_symbol(cross)

    print("=== Baseline (no cross/rolling norm) ===")
    print(f"rows={len(base)}")
    print("top-share by symbol (ensemble_pct>=0.99):")
    print(base_top.to_string(index=False) if not base_top.empty else "(missing cols)")

    print("\n=== With cross/rolling norm features ===")
    print(f"rows={len(cross)}")
    print("top-share by symbol (ensemble_pct>=0.99):")
    print(cross_top.to_string(index=False) if not cross_top.empty else "(missing cols)")

    # Correlation sanity (should not be purely driven by raw notional)
    for label, df in [("baseline", base), ("cross_norm", cross)]:
        if "ensemble_pct" in df.columns and "notional" in df.columns:
            corr = df[["ensemble_pct", "notional"]].corr(method="spearman").iloc[0, 1]
            print(f"\nSpearman corr(ensemble_pct, notional) [{label}]: {corr:.4f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
