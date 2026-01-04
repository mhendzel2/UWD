from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv
from app.utils.underlying import derive_underlying


def parse_bot_eod(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(
        lambda: {
            "overpay_count": 0,
            "aggressive_count": 0,
            "gamma_exposure": 0.0,
            "ask_count": 0,
            "bid_count": 0,
        }
    )
    for row in rows:
        underlying = derive_underlying(row)
        try:
            overpay = float(row.get("overpay_score", 0) or 0)
            aggressive = float(row.get("aggressive_score", 0) or 0)
            gamma = float(row.get("gamma_exposure", 0) or 0)
        except (ValueError, TypeError):
            continue

        side = str(row.get("side") or "").strip().lower()
        if side == "ask":
            metrics[underlying]["ask_count"] += 1
        elif side == "bid":
            metrics[underlying]["bid_count"] += 1

        if overpay > 0:
            metrics[underlying]["overpay_count"] += 1
        if aggressive > 0:
            metrics[underlying]["aggressive_count"] += 1
        metrics[underlying]["gamma_exposure"] += gamma
    return metrics


def aggregate_csv(path: Path) -> Tuple[List[str], Dict[str, Dict[str, float]], int]:
    """Stream a BOT_EOD CSV and aggregate without loading all rows in memory.

    Returns: (headers, per_underlying_metrics, row_count)
    """

    metrics: dict[str, dict[str, float]] = defaultdict(
        lambda: {
            "overpay_count": 0,
            "aggressive_count": 0,
            "gamma_exposure": 0.0,
            "ask_count": 0,
            "bid_count": 0,
        }
    )
    row_count = 0

    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        headers = list(reader.fieldnames or [])
        for raw in reader:
            row_count += 1
            # Normalize empty strings
            row = {k: (v if v not in ("", None) else None) for k, v in raw.items()}
            underlying = derive_underlying(row)

            side = str(row.get("side") or "").strip().lower()
            if side == "ask":
                metrics[underlying]["ask_count"] += 1
            elif side == "bid":
                metrics[underlying]["bid_count"] += 1

            try:
                overpay = float(row.get("overpay_score", 0) or 0)
                aggressive = float(row.get("aggressive_score", 0) or 0)
                gamma = float(row.get("gamma_exposure", 0) or 0)
            except (ValueError, TypeError):
                continue

            if overpay > 0:
                metrics[underlying]["overpay_count"] += 1
            if aggressive > 0:
                metrics[underlying]["aggressive_count"] += 1
            metrics[underlying]["gamma_exposure"] += gamma

    return headers, metrics, row_count
