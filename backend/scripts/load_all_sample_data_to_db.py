"""Bulk-load all CSVs in repo sample_data/ into the UWD Postgres database.

This uses the same import mechanism as the API: data is stored in raw_files.extras (JSONB)
with sha256 de-duplication.

Example:
  $env:UW_DATABASE_URL="postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
  C:/Users/mjhen/Github/UWD/.venv/Scripts/python.exe -u scripts/load_all_sample_data_to_db.py

Notes:
- This can take a while and will make the DB large (OI_DIFF files are big).
"""

from __future__ import annotations

import argparse
import hashlib
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from app.api import routes
from app.db import models
from app.db.engine import session_scope
from app.ingest import bot_eod
from app.utils.hashing import sha256_file
from app.utils.time import parse_date


def _extract_date_anywhere(name: str) -> date | None:
    m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
    if not m:
        return None
    try:
        return parse_date(m.group(1))
    except Exception:
        return None


_PREFIX_TO_SOURCE: dict[str, models.RawSource] = {
    "chain-oi-changes": models.RawSource.OI_DIFF,
    "bot-eod-report": models.RawSource.BOT_EOD,
    "dp-eod-report": models.RawSource.DARKPOOL_EOD,
    "hot-chains": models.RawSource.HOT_CHAINS,
    "stock-screener": models.RawSource.STOCK_SCREENER,
}

_FILE_RE = re.compile(r"^(?P<prefix>chain-oi-changes|bot-eod-report|dp-eod-report|hot-chains|stock-screener)-(?P<date>\d{4}-\d{2}-\d{2})\.csv$")


def _import_csv_for_session(*, db, session_id: str, source: models.RawSource, path: Path) -> bool:
    # BOT_EOD files can be extremely large; avoid full-file hashing where possible.
    file_size = int(path.stat().st_size)
    if source == models.RawSource.BOT_EOD and file_size > 50 * 1024 * 1024:
        fingerprint = f"{path.name}:{file_size}:{int(path.stat().st_mtime_ns)}"
        checksum = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
    else:
        checksum = sha256_file(path)
    # IMPORTANT: don't select the full RawFile row here.
    # RawFile includes a large JSONB payload (extras). Selecting it forces psycopg2
    # to decode JSON just to determine existence, which is very slow.
    existing_id = (
        db.query(models.RawFile.file_id)
        .filter(
            models.RawFile.session_id == session_id,
            models.RawFile.source == source,
            models.RawFile.sha256 == checksum,
        )
        .first()
    )
    if existing_id:
        return False

    rows_count = 0

    # BOT_EOD large-file import: store only per-underlying aggregates (no full row payload).
    if source == models.RawSource.BOT_EOD and file_size > 50 * 1024 * 1024:
        headers, agg, row_count = bot_eod.aggregate_csv(path)
        rows_count = row_count
        raw_file = models.RawFile(
            session_id=session_id,
            source=source,
            filename=path.name,
            sha256=checksum,
            rows=row_count,
            extras={"headers": headers, "agg": agg},
            parse_status=models.ParseStatus.OK,
        )
    else:
        parsed = routes._dispatch_parser(source, path)
        rows_count = len(parsed.rows)
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
            context={"source": source.value, "rows": rows_count},
        )
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sample-data-dir",
        default=str(Path(__file__).resolve().parents[2] / "sample_data"),
        help="Path to sample_data directory",
    )
    parser.add_argument("--start-date", default=None, help="Optional YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="Optional YYYY-MM-DD")
    parser.add_argument(
        "--sources",
        default="ALL",
        help="Comma-separated sources: OI_DIFF,BOT_EOD,HOT_CHAINS,DARKPOOL_EOD,STOCK_SCREENER,OPTIONS_FLOW or ALL",
    )
    args = parser.parse_args()

    sample_dir = Path(args.sample_data_dir)
    if not sample_dir.exists():
        raise SystemExit(f"sample_data dir not found: {sample_dir}")

    selected_sources: set[models.RawSource]
    if args.sources.strip().upper() == "ALL":
        selected_sources = set(_PREFIX_TO_SOURCE.values()) | {models.RawSource.OPTIONS_FLOW}
    else:
        selected_sources = set()
        for part in args.sources.split(","):
            part = part.strip().upper()
            selected_sources.add(models.RawSource(part))

    start = parse_date(args.start_date) if args.start_date else None
    end = parse_date(args.end_date) if args.end_date else None

    # Discover files by date
    by_date: dict[str, list[tuple[models.RawSource, Path]]] = defaultdict(list)
    for p in sample_dir.iterdir():
        if not p.is_file():
            continue
        m = _FILE_RE.match(p.name)
        if not m:
            continue
        prefix = m.group("prefix")
        date_str = m.group("date")
        source = _PREFIX_TO_SOURCE[prefix]
        if source not in selected_sources:
            continue

        d = parse_date(date_str)
        if start and d < start:
            continue
        if end and d > end:
            continue

        by_date[date_str].append((source, p))

    # Discover local options_flow files under sample_data/options_flow
    multi_day_options_flow: list[Path] = []
    options_dir = sample_dir / "options_flow"
    if models.RawSource.OPTIONS_FLOW in selected_sources and options_dir.exists() and options_dir.is_dir():
        for p in options_dir.iterdir():
            if not p.is_file() or p.suffix.lower() != ".csv":
                continue
            d = _extract_date_anywhere(p.name)
            if d:
                if start and d < start:
                    continue
                if end and d > end:
                    continue
                by_date[d.isoformat()].append((models.RawSource.OPTIONS_FLOW, p))
            else:
                # Multi-day file; imported after the per-date loop (grouping by timestamp/date).
                multi_day_options_flow.append(p)

    dates = sorted(by_date.keys())
    if not dates:
        print("No matching sample_data CSVs found.")
        return 0

    total_imported = 0
    total_skipped = 0

    print(f"Found {len(dates)} dates to load.")

    for date_str in dates:
        files = sorted(by_date[date_str], key=lambda t: t[0].value)
        with session_scope() as db:
            resp = routes.ensure_session(session_date=date_str, strategy_mode=models.StrategyMode.INDEX_EOD, db=db)
            session_id = resp["session_id"]

            imported_here = 0
            skipped_here = 0
            print(f"\n{date_str} session_id={session_id} files={len(files)}")

            for source, path in files:
                print(f"  importing {source.value}: {path.name} ...", flush=True)
                try:
                    did = _import_csv_for_session(db=db, session_id=session_id, source=source, path=path)
                    if did:
                        db.commit()
                        imported_here += 1
                    else:
                        skipped_here += 1
                except KeyboardInterrupt:
                    db.rollback()
                    raise
                except Exception:
                    db.rollback()
                    raise

            total_imported += imported_here
            total_skipped += skipped_here
            print(f"  done: imported={imported_here} skipped={skipped_here}")

    # Import multi-day options_flow CSVs (no date in filename) by grouping to sessions.
    if multi_day_options_flow:
        from app.ingest.local_files import import_local_options_flow_file

        with session_scope() as db:
            for p in sorted(multi_day_options_flow):
                try:
                    import_local_options_flow_file(db=db, filename=p.name, start_date=start, end_date=end)
                except Exception as e:
                    print(f"WARN: failed to import multi-day options flow file {p.name}: {e}")

    print(f"\nAll done. imported_files={total_imported} skipped_files={total_skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
