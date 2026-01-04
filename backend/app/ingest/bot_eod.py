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


def _default_metrics() -> Dict[str, float]:
    """Return a fresh default metrics dict for per-underlying aggregation."""
    return {
        "overpay_count": 0,
        "aggressive_count": 0,
        "gamma_exposure": 0.0,
        "ask_count": 0,
        "bid_count": 0,
        # Flow sentiment metrics
        "total_premium": 0.0,
        "bullish_premium": 0.0,
        "bearish_premium": 0.0,
        "call_premium": 0.0,
        "put_premium": 0.0,
        "call_count": 0,
        "put_count": 0,
    }


def _classify_sentiment(side: str, option_type: str) -> str:
    """Classify trade sentiment based on side and option type.
    
    Sentiment logic:
    - Call @ ASK = Bullish (buyer paying up to buy calls)
    - Put @ ASK = Bearish (buyer paying up to buy puts)
    - Call @ BID = Bearish (seller hitting the bid to sell calls)
    - Put @ BID = Bullish (seller hitting the bid to sell puts)
    
    Returns: 'bullish', 'bearish', or 'neutral'
    """
    side = side.lower().strip()
    option_type = option_type.lower().strip()
    
    if side == "ask":
        return "bullish" if option_type == "call" else "bearish"
    elif side == "bid":
        return "bearish" if option_type == "call" else "bullish"
    return "neutral"


def _calculate_sentiment_score(metrics: Dict[str, float]) -> float:
    """Calculate sentiment score from -1 (bearish) to +1 (bullish).
    
    Formula: (bullish_premium - bearish_premium) / total_premium
    Returns 0.0 if no premium data available.
    """
    total = metrics.get("total_premium", 0)
    if total <= 0:
        return 0.0
    bullish = metrics.get("bullish_premium", 0)
    bearish = metrics.get("bearish_premium", 0)
    return (bullish - bearish) / total


def aggregate(rows: list[dict]) -> dict[str, dict[str, float]]:
    metrics = defaultdict(_default_metrics)
    
    for row in rows:
        underlying = derive_underlying(row)
        try:
            overpay = float(row.get("overpay_score", 0) or 0)
            aggressive = float(row.get("aggressive_score", 0) or 0)
            gamma = float(row.get("gamma_exposure", 0) or 0)
            premium = float(row.get("premium", 0) or 0)
        except (ValueError, TypeError):
            continue

        side = str(row.get("side") or "").strip().lower()
        option_type = str(row.get("option_type") or "").strip().lower()
        
        if side == "ask":
            metrics[underlying]["ask_count"] += 1
        elif side == "bid":
            metrics[underlying]["bid_count"] += 1

        if option_type == "call":
            metrics[underlying]["call_count"] += 1
            metrics[underlying]["call_premium"] += premium
        elif option_type == "put":
            metrics[underlying]["put_count"] += 1
            metrics[underlying]["put_premium"] += premium

        # Classify and accumulate sentiment
        sentiment = _classify_sentiment(side, option_type)
        metrics[underlying]["total_premium"] += premium
        if sentiment == "bullish":
            metrics[underlying]["bullish_premium"] += premium
        elif sentiment == "bearish":
            metrics[underlying]["bearish_premium"] += premium

        if overpay > 0:
            metrics[underlying]["overpay_count"] += 1
        if aggressive > 0:
            metrics[underlying]["aggressive_count"] += 1
        metrics[underlying]["gamma_exposure"] += gamma

    # Calculate final sentiment scores
    for underlying in metrics:
        metrics[underlying]["sentiment_score"] = _calculate_sentiment_score(metrics[underlying])
        total = metrics[underlying]["total_premium"]
        if total > 0:
            metrics[underlying]["net_bullish_premium"] = (
                metrics[underlying]["bullish_premium"] - metrics[underlying]["bearish_premium"]
            )

    return dict(metrics)


def aggregate_csv(path: Path) -> Tuple[List[str], Dict[str, Dict[str, float]], int]:
    """Stream a BOT_EOD CSV and aggregate without loading all rows in memory.

    Returns: (headers, per_underlying_metrics, row_count)
    
    Aggregates per-underlying metrics including:
    - overpay_count, aggressive_count, gamma_exposure
    - ask_count, bid_count
    - Flow sentiment: total_premium, bullish_premium, bearish_premium, sentiment_score
    """

    metrics: dict[str, dict[str, float]] = defaultdict(_default_metrics)
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
            option_type = str(row.get("option_type") or "").strip().lower()
            
            if side == "ask":
                metrics[underlying]["ask_count"] += 1
            elif side == "bid":
                metrics[underlying]["bid_count"] += 1

            if option_type == "call":
                metrics[underlying]["call_count"] += 1
            elif option_type == "put":
                metrics[underlying]["put_count"] += 1

            try:
                overpay = float(row.get("overpay_score", 0) or 0)
                aggressive = float(row.get("aggressive_score", 0) or 0)
                gamma = float(row.get("gamma_exposure", 0) or 0)
                premium = float(row.get("premium", 0) or 0)
            except (ValueError, TypeError):
                continue

            # Accumulate premium by type
            if option_type == "call":
                metrics[underlying]["call_premium"] += premium
            elif option_type == "put":
                metrics[underlying]["put_premium"] += premium

            # Classify and accumulate sentiment
            sentiment = _classify_sentiment(side, option_type)
            metrics[underlying]["total_premium"] += premium
            if sentiment == "bullish":
                metrics[underlying]["bullish_premium"] += premium
            elif sentiment == "bearish":
                metrics[underlying]["bearish_premium"] += premium

            if overpay > 0:
                metrics[underlying]["overpay_count"] += 1
            if aggressive > 0:
                metrics[underlying]["aggressive_count"] += 1
            metrics[underlying]["gamma_exposure"] += gamma

    # Calculate final sentiment scores
    for underlying in metrics:
        metrics[underlying]["sentiment_score"] = _calculate_sentiment_score(metrics[underlying])
        total = metrics[underlying]["total_premium"]
        if total > 0:
            metrics[underlying]["net_bullish_premium"] = (
                metrics[underlying]["bullish_premium"] - metrics[underlying]["bearish_premium"]
            )
        else:
            metrics[underlying]["net_bullish_premium"] = 0.0

    return headers, dict(metrics), row_count
