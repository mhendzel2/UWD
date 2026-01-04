"""Load outlier report CSV outputs into Postgres tables for DB-native dashboards.

This is helpful if you want to visualize results in Metabase/Superset/Grafana/PowerBI
via SQL rather than reading CSVs.

Default behavior is to REPLACE the destination tables.

Run:
  $env:UW_DATABASE_URL="postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
  C:/Users/mjhen/Github/UWD/.venv/Scripts/python.exe -u scripts/load_outlier_reports_to_db.py

Then point your BI tool at:
- report_outlier_events
- report_outlier_summary
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser()
    root = Path(__file__).resolve().parents[1]

    parser.add_argument("--events-csv", default=str(root / "tmp" / "outlier_events.csv"))
    parser.add_argument("--summary-csv", default=str(root / "tmp" / "outlier_summary.csv"))
    parser.add_argument("--schema", default=None, help="Optional schema (default: public)")
    parser.add_argument("--events-table", default="report_outlier_events")
    parser.add_argument("--summary-table", default="report_outlier_summary")
    parser.add_argument(
        "--if-exists",
        default="replace",
        choices=["replace", "append"],
        help="replace (default) or append",
    )

    args = parser.parse_args()

    from app.db.engine import engine

    events_path = Path(args.events_csv)
    summary_path = Path(args.summary_csv)

    if not events_path.exists():
        raise SystemExit(f"Events CSV not found: {events_path}")
    if not summary_path.exists():
        raise SystemExit(f"Summary CSV not found: {summary_path}")

    df_ev = pd.read_csv(events_path)
    df_sum = pd.read_csv(summary_path)

    # Normalize types a bit (helps BI tools)
    for c in ["event_date", "anchor_date", "date_1", "date_5", "date_20"]:
        if c in df_ev.columns:
            df_ev[c] = pd.to_datetime(df_ev[c], errors="coerce")

    df_ev.to_sql(args.events_table, con=engine, schema=args.schema, if_exists=args.if_exists, index=False)
    df_sum.to_sql(args.summary_table, con=engine, schema=args.schema, if_exists=args.if_exists, index=False)

    print(f"Loaded {len(df_ev)} rows -> {args.events_table}")
    print(f"Loaded {len(df_sum)} rows -> {args.summary_table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
