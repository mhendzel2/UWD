from collections import defaultdict
from pathlib import Path
from typing import Dict, Any

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv


def parse_oi_diff(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Build simple per-underlying aggregates from OI diff rows."""
    metrics: dict[str, dict[str, float]] = defaultdict(lambda: {
        "call_oi": 0.0,
        "put_oi": 0.0,
        "multileg_oi": 0.0,
    })
    for row in rows:
        underlying = row.get("underlying") or row.get("ticker") or "UNKNOWN"
        try:
            metrics[underlying]["call_oi"] += float(row.get("call_oi", 0) or 0)
            metrics[underlying]["put_oi"] += float(row.get("put_oi", 0) or 0)
            metrics[underlying]["multileg_oi"] += float(row.get("multileg_oi", 0) or 0)
        except (ValueError, TypeError):
            continue
    return metrics
