from __future__ import annotations

import argparse


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

    a = sub.add_parser("run-app", help="Launch dashboard pointing to scores.parquet")
    a.add_argument("--scores", required=True)

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

        score(features_path=args.features, out_path=args.out)
        return 0

    if args.cmd == "run-app":
        from trade_surveillance.viz.app import run

        run(scores_path=args.scores)
        return 0

    raise AssertionError(f"Unhandled cmd: {args.cmd}")
