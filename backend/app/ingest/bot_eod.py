from collections import defaultdict
from pathlib import Path

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv
from app.utils.underlying import derive_underlying


def parse_bot_eod(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(lambda: {"overpay_count": 0, "aggressive_count": 0, "gamma_exposure": 0.0})
    for row in rows:
        underlying = derive_underlying(row)
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
    return metrics
