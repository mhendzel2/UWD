from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from trade_surveillance.pipeline import featurize, score
from trade_surveillance.synth import generate_demo_data


def _ensure_ensemble_pct_by_symbol(scores: pd.DataFrame) -> pd.DataFrame:
    s = scores
    if "ensemble_pct_by_symbol" in s.columns:
        return s
    if "symbol" not in s.columns or "ensemble_score" not in s.columns:
        return s
    s = s.copy()
    s["ensemble_pct_by_symbol"] = (
        s.groupby("symbol", dropna=False)["ensemble_score"].rank(pct=True, method="average")
    )
    return s


def _top_share_by_symbol(
    scores: pd.DataFrame,
    *,
    pct_col: str = "ensemble_pct",
    threshold: float = 0.99,
) -> pd.DataFrame:
    s = scores.copy()
    if "symbol" not in s.columns or pct_col not in s.columns:
        return pd.DataFrame()
    s["is_top"] = pd.to_numeric(s[pct_col], errors="coerce") >= float(threshold)
    out = (
        s.groupby("symbol", dropna=False)["is_top"]
        .mean()
        .reset_index()
        .rename(columns={"is_top": f"share_{pct_col}_ge_{threshold}"})
    )
    return out.sort_values(f"share_{pct_col}_ge_{threshold}", ascending=False).reset_index(drop=True)


def _fairness_by_symbol(
    scores: pd.DataFrame,
    *,
    label_col: str = "is_anomaly",
    symbol_col: str = "symbol",
    pct_col: str,
    top_frac: float,
) -> tuple[pd.DataFrame, dict[str, float]]:
    s = scores.copy()
    if symbol_col not in s.columns or pct_col not in s.columns or label_col not in s.columns:
        return pd.DataFrame(), {}

    y = pd.to_numeric(s[label_col], errors="coerce").fillna(0).astype(int)
    picked = pd.to_numeric(s[pct_col], errors="coerce").fillna(0.0) >= (1.0 - float(top_frac))
    s = s.assign(_y=y, _picked=picked)

    g = s.groupby(symbol_col, dropna=False)
    out = g.apply(
        lambda df: pd.Series(
            {
                "n": int(len(df)),
                "n_norm": int((df["_y"] == 0).sum()),
                "n_pos": int((df["_y"] == 1).sum()),
                "normal_pick_rate": float(((df["_picked"]) & (df["_y"] == 0)).sum() / max(1, int((df["_y"] == 0).sum()))),
                "pos_pick_rate": float(((df["_picked"]) & (df["_y"] == 1)).sum() / max(1, int((df["_y"] == 1).sum()))),
                "pick_rate_all": float(df["_picked"].mean()),
            }
        )
    ).reset_index()

    # Summary disparity metrics for normals (i.e., false-positive exposure per symbol).
    rates = pd.to_numeric(out["normal_pick_rate"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    if len(rates) == 0:
        summary: dict[str, float] = {}
    else:
        p05 = float(np.quantile(rates, 0.05))
        p50 = float(np.quantile(rates, 0.50))
        p95 = float(np.quantile(rates, 0.95))
        summary = {
            "normal_pick_rate_mean": float(np.mean(rates)),
            "normal_pick_rate_std": float(np.std(rates)),
            "normal_pick_rate_p05": p05,
            "normal_pick_rate_p50": p50,
            "normal_pick_rate_p95": p95,
            "normal_pick_rate_p95_over_p05": float(p95 / max(1e-12, p05)),
            "normal_pick_rate_p95_over_p50": float(p95 / max(1e-12, p50)),
        }

    out = out.sort_values("normal_pick_rate", ascending=False).reset_index(drop=True)
    return out, summary


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

    # Regime shift: later in time, normal sizes jump up across all symbols.
    t = np.linspace(0.0, 1.0, int(n_rows), dtype=float)
    regime_gate = (t > 0.65)
    # Stronger jump makes this a more discriminative stress test.
    regime_mult = (1.0 + 2.0 * regime_gate) if include_regime_shift else 1.0

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
            "phase": np.where(regime_gate, "post_shift", "pre_shift"),
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


def _regime_metrics(
    *,
    y_true: pd.Series,
    score_series: pd.Series,
    phase: pd.Series,
    top_frac: float = 0.01,
) -> dict[str, float]:
    y = pd.to_numeric(y_true, errors="coerce").fillna(0).astype(int).to_numpy()
    s = pd.to_numeric(score_series, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    ph = phase.astype(str).to_numpy()

    k = max(1, int(round(float(top_frac) * len(y))))
    order = np.argsort(-s)
    picked = np.zeros(len(y), dtype=bool)
    picked[order[:k]] = True

    out: dict[str, float] = {}
    for label in ["pre_shift", "post_shift"]:
        mask = ph == label
        denom_normals = max(1, int(((y == 0) & mask).sum()))
        denom_all = max(1, int(mask.sum()))

        fp = int((picked & mask & (y == 0)).sum())
        tp = int((picked & mask & (y == 1)).sum())

        out[f"fpr_{label}"] = float(fp / denom_normals)
        out[f"pick_rate_{label}"] = float(int((picked & mask).sum()) / denom_all)
        out[f"tp_{label}"] = float(tp)

    # Stability ratio: how much more we pick in post vs pre (lower is better here).
    out["pick_rate_ratio_post_over_pre"] = float(
        out["pick_rate_post_shift"] / max(1e-12, out["pick_rate_pre_shift"])
    )
    out["fpr_ratio_post_over_pre"] = float(out["fpr_post_shift"] / max(1e-12, out["fpr_pre_shift"]))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--work", default="tmp/ts_norm_eval", help="Working directory under repo root")
    p.add_argument("--n-trades", type=int, default=20000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--labeled", action="store_true", help="Run labeled evaluation metrics (AUROC/AP/precision@k)")
    p.add_argument("--anomaly-rate", type=float, default=0.01)
    p.add_argument("--top-frac", type=float, default=0.01, help="Alert rate used for stability/fairness metrics")
    args = p.parse_args()

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    # Either use existing demo generator (unlabeled) or a labeled synthetic dataset.
    y = None
    labeled_trades: pd.DataFrame | None = None
    if bool(args.labeled):
        trades, y = _make_labeled_synthetic_trades(
            n_rows=int(args.n_trades),
            seed=int(args.seed),
            anomaly_rate=float(args.anomaly_rate),
            include_regime_shift=True,
        )
        trades = trades.copy()
        trades["is_anomaly"] = pd.to_numeric(y, errors="coerce").fillna(0).astype(int).to_numpy()
        labeled_trades = trades
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

    if labeled_trades is not None:
        join_cols = ["timestamp", "symbol", "phase", "is_anomaly"]
        key_cols = ["timestamp", "symbol"]
        base = base.merge(labeled_trades[join_cols], on=key_cols, how="left")
        cross = cross.merge(labeled_trades[join_cols], on=key_cols, how="left")

    base = _ensure_ensemble_pct_by_symbol(base)
    cross = _ensure_ensemble_pct_by_symbol(cross)

    if "is_anomaly" in base.columns and "is_anomaly" in cross.columns and "ensemble_score" in base.columns and "ensemble_score" in cross.columns:
        m_base = _ranking_metrics(base["is_anomaly"], base["ensemble_score"])
        m_cross = _ranking_metrics(cross["is_anomaly"], cross["ensemble_score"])
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

        if "phase" in base.columns and "phase" in cross.columns:
            r_base = _regime_metrics(
                y_true=base["is_anomaly"],
                score_series=base["ensemble_score"],
                phase=base["phase"],
                top_frac=float(args.top_frac),
            )
            r_cross = _regime_metrics(
                y_true=cross["is_anomaly"],
                score_series=cross["ensemble_score"],
                phase=cross["phase"],
                top_frac=float(args.top_frac),
            )
            print("=== Regime-aware stability (top 1% picks) ===")
            keys2 = [
                "fpr_pre_shift",
                "fpr_post_shift",
                "fpr_ratio_post_over_pre",
                "pick_rate_pre_shift",
                "pick_rate_post_shift",
                "pick_rate_ratio_post_over_pre",
            ]
            for k in keys2:
                print(f"{k:>28s}  baseline={r_base.get(k, float('nan')):10.4f}   cross_norm={r_cross.get(k, float('nan')):10.4f}")
            print("")

        # Per-symbol false-positive / fairness metrics.
        print(f"=== Per-symbol fairness (top {float(args.top_frac)*100:.2f}% alerts) ===")
        for pct_col in ["ensemble_pct", "ensemble_pct_by_symbol"]:
            for label, df in [("baseline", base), ("cross_norm", cross)]:
                tab, summary = _fairness_by_symbol(
                    df,
                    label_col="is_anomaly",
                    symbol_col="symbol",
                    pct_col=pct_col,
                    top_frac=float(args.top_frac),
                )
                print(f"\n[{label}] pct_col={pct_col}")
                if tab.empty:
                    print("(missing columns)")
                    continue
                # Show the worst 10 symbols by normal pick rate.
                show = tab.head(10).copy()
                print(show.to_string(index=False))
                if summary:
                    print(
                        "summary_normals: "
                        + " ".join(
                            [
                                f"mean={summary.get('normal_pick_rate_mean', float('nan')):.4f}",
                                f"std={summary.get('normal_pick_rate_std', float('nan')):.4f}",
                                f"p05={summary.get('normal_pick_rate_p05', float('nan')):.4f}",
                                f"p50={summary.get('normal_pick_rate_p50', float('nan')):.4f}",
                                f"p95={summary.get('normal_pick_rate_p95', float('nan')):.4f}",
                                f"p95/p05={summary.get('normal_pick_rate_p95_over_p05', float('nan')):.2f}",
                            ]
                        )
                    )
        print("")

    # Proxy metrics
    base_top = _top_share_by_symbol(base, pct_col="ensemble_pct", threshold=0.99)
    cross_top = _top_share_by_symbol(cross, pct_col="ensemble_pct", threshold=0.99)

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
