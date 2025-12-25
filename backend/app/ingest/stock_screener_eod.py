from collections import defaultdict
from pathlib import Path

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv


def parse_stock_screener(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(lambda: {"implied_move": 0.0, "directional_skew": 0.0, "iv_percentile": 0.0})
    for row in rows:
        underlying = row.get("underlying") or row.get("ticker") or "UNKNOWN"
        try:
            implied_move = float(row.get("implied_move_pct", 0) or 0)
            skew = float(row.get("directional_skew", 0) or 0)
            iv_percentile = float(row.get("iv_percentile", 0) or 0)
        except (ValueError, TypeError):
            continue
        metrics[underlying]["implied_move"] = max(metrics[underlying]["implied_move"], implied_move)
        metrics[underlying]["directional_skew"] = max(metrics[underlying]["directional_skew"], skew)
        metrics[underlying]["iv_percentile"] = max(metrics[underlying]["iv_percentile"], iv_percentile)
    return metrics
