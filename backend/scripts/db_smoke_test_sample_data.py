"""Load one day of sample_data into the UWD Postgres database and run verification queries.

This script is intentionally small and only intended as a DB connectivity + ingest sanity check.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import text

from app.api import routes
from app.db import models
from app.db.engine import session_scope
from app.utils.hashing import sha256_file
from app.utils.time import parse_date


def _import_file(
    *,
    db,
    session_id: str,
    source: models.RawSource,
    path: Path,
) -> None:
    print(f"Parsing {source.value}: {path.name}", flush=True)
    parsed = routes._dispatch_parser(source, path)
    checksum = sha256_file(path)

    existing = (
        db.query(models.RawFile)
        .filter(
            models.RawFile.session_id == session_id,
            models.RawFile.source == source,
            models.RawFile.sha256 == checksum,
        )
        .first()
    )
    if existing:
        print(f"Already imported {source.value}: {path.name}", flush=True)
        return

    raw_file = models.RawFile(
        session_id=session_id,
        source=source,
        filename=path.name,
        sha256=checksum,
        rows=len(parsed.rows),
        extras={"headers": parsed.headers, "rows": parsed.rows},
        parse_status=models.ParseStatus.OK if not parsed.errors else models.ParseStatus.ERROR,
        error_message=";".join(parsed.errors) if parsed.errors else None,
    )
    db.add(raw_file)
    db.add(
        models.LogMessage(
            session_id=session_id,
            level=models.LogLevel.INFO,
            message=f"Imported {path.name}",
            context={"source": source.value, "rows": len(parsed.rows)},
        )
    )
    print(f"Staged import {source.value}: {path.name} rows={len(parsed.rows)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2025-12-24", help="YYYY-MM-DD present in sample_data")
    parser.add_argument(
        "--compute-v0",
        action="store_true",
        help="Also run compute_v0 (can take a while on full sample_data JSONB payloads)",
    )
    parser.add_argument(
        "--sample-data-dir",
        default=str(Path(__file__).resolve().parents[2] / "sample_data"),
        help="Path to sample_data directory",
    )
    args = parser.parse_args()

    asof_date = args.date
    parsed_date = parse_date(asof_date)
    sample_dir = Path(args.sample_data_dir)
    if not sample_dir.exists():
        raise SystemExit(f"sample_data dir not found: {sample_dir}")

    # Map sample_data filenames to RawSource.
    files = [
        (models.RawSource.OI_DIFF, sample_dir / f"chain-oi-changes-{asof_date}.csv"),
        (models.RawSource.DARKPOOL_EOD, sample_dir / f"dp-eod-report-{asof_date}.csv"),
        (models.RawSource.HOT_CHAINS, sample_dir / f"hot-chains-{asof_date}.csv"),
        (models.RawSource.STOCK_SCREENER, sample_dir / f"stock-screener-{asof_date}.csv"),
    ]

    missing = [str(p) for _, p in files if not p.exists()]
    if missing:
        raise SystemExit(
            "Missing one or more sample CSVs for the chosen date. Try a different --date.\n"
            + "\n".join(missing)
        )

    with session_scope() as db:
        # Create/ensure session for date.
        resp = routes.ensure_session(session_date=asof_date, strategy_mode=models.StrategyMode.INDEX_EOD, db=db)
        session_id = resp["session_id"]

        print(f"Using session_id={session_id} date={asof_date}", flush=True)

        if args.compute_v0:
            # Keep reruns deterministic: remove previously derived rows for this session/date.
            print("Clearing derived rows for rerun...", flush=True)
            db.query(models.Plan).filter(
                models.Plan.session_id == session_id,
                models.Plan.trade_date == parsed_date,
            ).delete(synchronize_session=False)
            db.query(models.RegimeDecision).filter(
                models.RegimeDecision.session_id == session_id,
                models.RegimeDecision.asof_date == parsed_date,
            ).delete(synchronize_session=False)
            db.query(models.FeaturesUnderlyingDay).filter(
                models.FeaturesUnderlyingDay.session_id == session_id,
                models.FeaturesUnderlyingDay.asof_date == parsed_date,
            ).delete(synchronize_session=False)

        for source, path in files:
            _import_file(db=db, session_id=session_id, source=source, path=path)

        if args.compute_v0:
            # Run v0 compute to populate derived tables.
            print("Running compute_v0...", flush=True)
            routes.compute_v0(session_id=session_id, asof_date=asof_date, db=db)

        # Verification queries (always validate raw load; derived validation only if computed).
        print("Running verification queries...", flush=True)
        counts = {
            "sessions": db.execute(text("select count(*) from sessions")).scalar_one(),
            "raw_files": db.execute(text("select count(*) from raw_files")).scalar_one(),
            "logs": db.execute(text("select count(*) from logs")).scalar_one(),
        }
        by_source = db.execute(
            text(
                """
                select source, count(*) as files, sum(rows) as total_rows
                from raw_files
                where session_id = :sid
                group by source
                order by source
                """
            ),
            {"sid": session_id},
        ).all()
        json_lengths = db.execute(
            text(
                """
                select source, filename, rows, jsonb_array_length(extras->'rows') as json_rows
                from raw_files
                where session_id = :sid
                order by source
                """
            ),
            {"sid": session_id},
        ).all()

        derived_counts = None
        if args.compute_v0:
            derived_counts = {
                "features": db.execute(text("select count(*) from features_underlying_day")).scalar_one(),
                "regimes": db.execute(text("select count(*) from regime_decisions")).scalar_one(),
                "plans": db.execute(text("select count(*) from plans")).scalar_one(),
            }

    print("DB smoke test OK")
    print(f"session_id={session_id} asof_date={asof_date}")
    print("Counts:")
    for k, v in counts.items():
        print(f"  {k}: {v}")

    print("\nRaw files by source:")
    for source, files, total_rows in by_source:
        print(f"  {source}: files={files} total_rows={total_rows}")

    print("\nRaw files JSONB length check (rows vs json_rows):")
    for source, filename, rows, json_rows in json_lengths:
        print(f"  {source} {filename}: rows={rows} json_rows={json_rows}")

    if derived_counts:
        print("\nDerived table counts (after compute_v0):")
        for k, v in derived_counts.items():
            print(f"  {k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
