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


def _sql_type_for_series(s: pd.Series):
    # Import lazily so the script can still show a helpful error if SQLAlchemy isn't available.
    from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, Text

    # Pandas extension dtypes
    dt = getattr(s.dtype, "name", str(s.dtype))

    if dt.startswith("datetime"):
        return DateTime(timezone=False)
    if dt.startswith("bool"):
        return Boolean()
    if dt.startswith("int"):
        return Integer()
    if dt.startswith("float"):
        return Float()

    # Mixed/object: try to see if it looks numeric; otherwise Text.
    try:
        non_na = s.dropna()
        if not non_na.empty:
            # If everything can be coerced to numeric, store as Numeric.
            coerced = pd.to_numeric(non_na.astype(str), errors="coerce")
            if coerced.notna().all():
                return Numeric()
    except Exception:
        pass

    return Text()


def _ensure_table_has_df_columns(*, engine, schema: str | None, table: str, df: pd.DataFrame) -> None:
    """When using to_sql(if_exists='append'), ensure the destination table has all df columns.

    This script is used for BI convenience, and the report schema can evolve over time.
    We auto-add missing columns to avoid hard failures like:
      psycopg2.errors.UndefinedColumn: column "dte" does not exist
    """

    from sqlalchemy import inspect, text

    if df.empty:
        return

    insp = inspect(engine)
    if not insp.has_table(table, schema=schema):
        return

    existing_cols = {c["name"] for c in insp.get_columns(table, schema=schema)}
    missing = [c for c in df.columns if c not in existing_cols]
    if not missing:
        return

    # Add columns one by one.
    for col in missing:
        col_type = _sql_type_for_series(df[col])
        # Compile type to a dialect-specific string.
        type_sql = col_type.compile(dialect=engine.dialect)
        if schema:
            full_table = f'"{schema}"."{table}"'
        else:
            full_table = f'"{table}"'
        sql = f"ALTER TABLE {full_table} ADD COLUMN IF NOT EXISTS \"{col}\" {type_sql}"
        with engine.begin() as conn:
            conn.execute(text(sql))


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

    # If we're appending into an existing table, auto-add missing columns.
    # This keeps the workflow resilient when new fields appear in the report output.
    if args.if_exists == "append":
        _ensure_table_has_df_columns(engine=engine, schema=args.schema, table=args.events_table, df=df_ev)
        _ensure_table_has_df_columns(engine=engine, schema=args.schema, table=args.summary_table, df=df_sum)

    df_ev.to_sql(args.events_table, con=engine, schema=args.schema, if_exists=args.if_exists, index=False)
    df_sum.to_sql(args.summary_table, con=engine, schema=args.schema, if_exists=args.if_exists, index=False)

    print(f"Loaded {len(df_ev)} rows -> {args.events_table}")
    print(f"Loaded {len(df_sum)} rows -> {args.summary_table}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
