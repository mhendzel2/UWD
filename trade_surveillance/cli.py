from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m trade_surveillance")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate-data", help="Write demo trades.csv (+ optional quotes.csv)")
    g.add_argument("--out", required=True, help="Output directory")
    g.add_argument("--n-trades", type=int, default=20000)
    g.add_argument("--with-quotes", action="store_true")
    g.add_argument("--seed", type=int, default=7)

    f = sub.add_parser("featurize", help="Read trades (+ quotes), write features.parquet")
    f.add_argument("--trades", required=True)
    f.add_argument("--quotes", default=None)
    f.add_argument("--out", required=True)

    s = sub.add_parser("score", help="Fit detectors on features, write scores.parquet")
    s.add_argument("--features", required=True)
    s.add_argument("--out", required=True)
    s.add_argument(
        "--use-cross-norm",
        action="store_true",
        help="Include rolling/percentile normalization features (z_log_*, pct_*_in_symbol) in scoring when available",
    )

    a = sub.add_parser("run-app", help="Launch dashboard pointing to scores.parquet")
    a.add_argument("--scores", required=True)

    perf = sub.add_parser("analyze-performance", help="Top-K per day + price action windows + forward returns")
    perf.add_argument("--scores", required=True, help="Path to scores.parquet")
    perf.add_argument(
        "--prices-dir",
        default=None,
        help="Directory containing daily OHLCV CSVs like aapl.us.csv (defaults to backend/.cache/prices)",
    )
    perf.add_argument("--out-dir", required=True, help="Output directory")
    perf.add_argument("--top-k", type=int, default=5)
    perf.add_argument(
        "--min-pct",
        type=float,
        default=0.995,
        help="If set, score all signals with percentile >= min-pct (overrides --top-k)",
    )
    perf.add_argument(
        "--use-top-k",
        action="store_true",
        help="Use legacy top-K per day selection (ignores --min-pct)",
    )
    perf.add_argument(
        "--pct-col",
        default="ensemble_pct",
        choices=["ensemble_pct", "ensemble_pct_by_symbol"],
        help="Percentile column to threshold on when using --min-pct",
    )
    perf.add_argument(
        "--per-symbol-top-n",
        type=int,
        default=None,
        help="If set, score up to N signals per symbol per day (overrides --min-pct and --top-k)",
    )
    perf.add_argument("--lookback-days", type=int, default=5)
    perf.add_argument("--forward-days", type=int, default=10)
    perf.add_argument("--tz", default="America/New_York", help="Timezone for session_date bucketing")
    perf.add_argument("--option-type", default="CALL", choices=["CALL", "PUT"])
    perf.add_argument("--option-dte", type=int, default=30, help="Days-to-expiration at entry (trading-day approx)")
    perf.add_argument("--option-iv", type=float, default=0.50, help="Assumed IV (sigma) for fair value")
    perf.add_argument("--option-rate", type=float, default=0.04, help="Risk-free rate (continuous comp)")
    perf.add_argument("--option-div-yield", type=float, default=0.0, help="Dividend yield (continuous comp)")
    perf.add_argument("--option-strike-round", type=float, default=1.0, help="Round ATM strike to nearest increment")

    return p


def main(argv: list[str] | None = None) -> int:
    p = _build_parser()
    args = p.parse_args(argv)

    if args.cmd == "generate-data":
        from trade_surveillance.synth import generate_demo_data

        generate_demo_data(
            out_dir=args.out,
            n_trades=int(args.n_trades),
            with_quotes=bool(args.with_quotes),
            seed=int(args.seed),
        )
        return 0

    if args.cmd == "featurize":
        from trade_surveillance.pipeline import featurize

        featurize(trades_path=args.trades, quotes_path=args.quotes, out_path=args.out)
        return 0

    if args.cmd == "score":
        from trade_surveillance.pipeline import score

        score(features_path=args.features, out_path=args.out, use_cross_norm=bool(args.use_cross_norm))
        return 0

    if args.cmd == "run-app":
        script = Path(__file__).resolve().parent / "viz" / "streamlit_app.py"
        cmd = [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(script),
            "--",
            "--scores",
            str(args.scores),
        ]
        return int(subprocess.call(cmd))

    if args.cmd == "analyze-performance":
        from trade_surveillance.performance import analyze_top_signals_vs_price

        analyze_top_signals_vs_price(
            scores_path=str(args.scores),
            prices_dir=None if args.prices_dir in {None, ""} else str(args.prices_dir),
            out_dir=str(args.out_dir),
            top_k=int(args.top_k),
            min_percentile=None if bool(args.use_top_k) else float(args.min_pct),
            percentile_col=str(args.pct_col),
            per_symbol_top_n=None if args.per_symbol_top_n in {None, ""} else int(args.per_symbol_top_n),
            lookback_days=int(args.lookback_days),
            forward_days=int(args.forward_days),
            tz=str(args.tz),
            option_type=str(args.option_type),
            option_dte=int(args.option_dte),
            option_iv=float(args.option_iv),
            option_rate=float(args.option_rate),
            option_dividend_yield=float(args.option_div_yield),
            option_strike_round=float(args.option_strike_round),
        )
        return 0

    raise AssertionError(f"Unhandled cmd: {args.cmd}")
