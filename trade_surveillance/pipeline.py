from __future__ import annotations


def featurize(*, trades_path: str, quotes_path: str | None, out_path: str) -> None:
    raise NotImplementedError("Phase 3: feature engineering")


def score(*, features_path: str, out_path: str) -> None:
    raise NotImplementedError("Phase 4: detectors + ensemble")
