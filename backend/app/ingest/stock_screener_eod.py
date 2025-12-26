from collections import defaultdict
from pathlib import Path

from app.ingest.types import ParsedCSV
from app.utils.csv_read import read_csv
from app.utils.underlying import derive_underlying


def parse_stock_screener(path: Path) -> ParsedCSV:
    headers, rows = read_csv(path)
    return ParsedCSV(headers=headers, rows=rows, errors=[])


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(
        lambda: {
            "implied_move": 0.0,
            "directional_skew": 0.0,
            "iv_percentile": 0.0,
            "iv_rank": 0.0,
            "total_volume": 0.0,
            "avg30_volume": 0.0,
        }
    )
    for row in rows:
        underlying = derive_underlying(row)
        try:
            implied_move = float(row.get("implied_move_pct", 0) or 0)
            skew = float(row.get("directional_skew", 0) or 0)
            iv_percentile = float(row.get("iv_percentile", 0) or 0)
            iv_rank = float(row.get("iv_rank", 0) or 0)
            total_volume = float(row.get("total_volume", 0) or 0)
            avg30_volume = float(row.get("avg30_volume", 0) or 0)
        except (ValueError, TypeError):
            continue
        metrics[underlying]["implied_move"] = max(metrics[underlying]["implied_move"], implied_move)
        metrics[underlying]["directional_skew"] = max(metrics[underlying]["directional_skew"], skew)
        metrics[underlying]["iv_percentile"] = max(metrics[underlying]["iv_percentile"], iv_percentile)
        metrics[underlying]["iv_rank"] = max(metrics[underlying]["iv_rank"], iv_rank)
        metrics[underlying]["total_volume"] = max(metrics[underlying]["total_volume"], total_volume)
        metrics[underlying]["avg30_volume"] = max(metrics[underlying]["avg30_volume"], avg30_volume)
    return metrics
