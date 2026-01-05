from __future__ import annotations

from pathlib import Path

import pandas as pd


def read_trades(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
    elif p.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(p)
    else:
        raise ValueError(f"Unsupported trades format: {p.suffix}")

    if "timestamp" not in df.columns:
        raise ValueError("trades must include 'timestamp'")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def read_quotes(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(p)

    if p.suffix.lower() == ".csv":
        df = pd.read_csv(p)
    elif p.suffix.lower() in {".parquet", ".pq"}:
        df = pd.read_parquet(p)
    else:
        raise ValueError(f"Unsupported quotes format: {p.suffix}")

    if "timestamp" not in df.columns:
        raise ValueError("quotes must include 'timestamp'")

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return df


def write_csv(df: pd.DataFrame, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_parquet(df: pd.DataFrame, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)
