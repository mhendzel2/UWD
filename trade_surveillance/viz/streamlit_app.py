from __future__ import annotations

import argparse
from pathlib import Path

from trade_surveillance.viz.app import run


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--scores", required=False)
    # Streamlit may inject its own args; ignore anything unknown.
    args, _unknown = p.parse_known_args()
    return args


def _auto_find_scores_path() -> str | None:
    # repo_root/trade_surveillance/viz/streamlit_app.py -> repo_root
    repo_root = Path(__file__).resolve().parents[2]
    candidates = [
        repo_root / "tmp" / "ts_norm_eval" / "scores_cross.parquet",
        repo_root / "tmp" / "ts_norm_eval" / "scores_base.parquet",
        repo_root / "tmp" / "scores.parquet",
        # Common pitfall: running some generation commands from backend/.
        repo_root / "backend" / "tmp" / "ts_norm_eval" / "scores_cross.parquet",
        repo_root / "backend" / "tmp" / "ts_norm_eval" / "scores_base.parquet",
        repo_root / "backend" / "tmp" / "scores.parquet",
        repo_root / "backend" / "backend" / "tmp" / "ts_norm_eval" / "scores_cross.parquet",
        repo_root / "backend" / "backend" / "tmp" / "ts_norm_eval" / "scores_base.parquet",
        repo_root / "backend" / "backend" / "tmp" / "scores.parquet",
    ]
    for p in candidates:
        try:
            if p.exists() and p.is_file():
                return str(p)
        except Exception:
            continue
    return None


def main() -> None:
    args = _parse_args()
    scores = getattr(args, "scores", None)
    if not scores:
        scores = _auto_find_scores_path()
    if not scores:
        raise SystemExit(
            "Missing --scores and could not auto-detect a scores.parquet. "
            "Provide --scores <path-to-scores.parquet> or generate one under tmp/."
        )
    run(scores_path=str(scores))


if __name__ == "__main__":
    main()
