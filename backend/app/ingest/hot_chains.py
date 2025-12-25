from collections import defaultdict
from pathlib import Path

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv


def parse_hot_chains(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(lambda: {
        "turnover_notional": 0.0,
        "sweep_count": 0,
        "multileg_count": 0,
        "buy_volume": 0.0,
        "sell_volume": 0.0,
    })
    for row in rows:
        underlying = row.get("underlying") or row.get("ticker") or "UNKNOWN"
        try:
            turnover = float(row.get("notional", 0) or 0)
            sweep = int(row.get("sweep", 0) or 0)
            multileg = int(row.get("multi_leg", 0) or 0)
            buy_side = float(row.get("buy_volume", 0) or 0)
            sell_side = float(row.get("sell_volume", 0) or 0)
        except (ValueError, TypeError):
            continue
        metrics[underlying]["turnover_notional"] += turnover
        metrics[underlying]["sweep_count"] += sweep
        metrics[underlying]["multileg_count"] += multileg
        metrics[underlying]["buy_volume"] += buy_side
        metrics[underlying]["sell_volume"] += sell_side
    return metrics
