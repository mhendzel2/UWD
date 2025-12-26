from collections import defaultdict
from pathlib import Path

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv
from app.utils.underlying import derive_underlying


def parse_darkpool(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(lambda: {"notional": 0.0, "buy_notional": 0.0, "sell_notional": 0.0})
    for row in rows:
        underlying = derive_underlying(row)
        try:
            notion = float(row.get("notional", 0) or 0)
            side = row.get("side", "").lower()
        except (ValueError, TypeError):
            continue
        metrics[underlying]["notional"] += notion
        if side == "buy":
            metrics[underlying]["buy_notional"] += notion
        elif side == "sell":
            metrics[underlying]["sell_notional"] += notion
    return metrics
