from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from app.db.engine import SessionLocal
from app.options_signals.pipeline import run_daily_pipeline
from app.utils.time import parse_date


def _resolve_trade_path(trades_dir: Path, pattern: str, trade_date: date) -> str | None:
    filename = pattern.format(date=trade_date.isoformat())
    candidate = trades_dir / filename
    if candidate.exists():
        return str(candidate)
    matches = list(trades_dir.glob(f"*{trade_date.isoformat()}*.csv"))
    return str(matches[0]) if matches else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Options Signals daily ETL.")
    parser.add_argument("--trade-date", required=True, help="Trade date (YYYY-MM-DD)")
    parser.add_argument("--trades-path", help="Path to daily options trades CSV")
    parser.add_argument("--trades-dir", help="Directory containing daily trades CSVs")
    parser.add_argument("--trades-pattern", default="options-trades-{date}.csv", help="Filename pattern with {date}")
    parser.add_argument("--ohlcv-path", help="Path to OHLCV daily CSV")
    parser.add_argument("--market-path", help="Path to market context CSV")
    parser.add_argument("--news-path", help="Path to news sentiment CSV")
    parser.add_argument("--sector-path", help="Path to sector context CSV")
    parser.add_argument("--backfill-end", help="Optional backfill end date (YYYY-MM-DD)")

    args = parser.parse_args()
    start_date = parse_date(args.trade_date)
    end_date = parse_date(args.backfill_end) if args.backfill_end else start_date

    trades_dir = Path(args.trades_dir) if args.trades_dir else None
    trade_date = start_date

    with SessionLocal() as db:
        while trade_date <= end_date:
            trades_path = args.trades_path
            if not trades_path and trades_dir:
                trades_path = _resolve_trade_path(trades_dir, args.trades_pattern, trade_date)
            if not trades_path:
                raise FileNotFoundError(f"No trades CSV found for {trade_date}")

            counts = run_daily_pipeline(
                db,
                trade_date=trade_date,
                trades_path=trades_path,
                ohlcv_path=args.ohlcv_path,
                market_path=args.market_path,
                news_path=args.news_path,
                sector_path=args.sector_path,
            )
            print(f"{trade_date}: {counts}")
            trade_date += timedelta(days=1)


if __name__ == "__main__":
    main()
