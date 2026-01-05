from __future__ import annotations

import argparse

from trade_surveillance.viz.app import run


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--scores", required=True)
    # Streamlit may inject its own args; ignore anything unknown.
    args, _unknown = p.parse_known_args()
    return args


def main() -> None:
    args = _parse_args()
    run(scores_path=args.scores)


if __name__ == "__main__":
    main()
