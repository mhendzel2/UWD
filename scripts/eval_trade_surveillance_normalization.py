from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

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


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--work", default="tmp/ts_norm_eval", help="Working directory under repo root")
    p.add_argument("--n-trades", type=int, default=20000)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()

    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

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
