import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Iterable

import tempfile

# Add backend to path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.append(str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.engine import engine, SessionLocal
from app.db import models
from app.api.routes import _dispatch_parser
from app.utils.hashing import sha256_file


DATE_RE = re.compile(r".*-(\d{4}-\d{2}-\d{2})\.csv$")


def _extract_date_from_filename(filename: str) -> date | None:
    m = DATE_RE.match(filename)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d").date()


def _guess_source(filename: str) -> models.RawSource | None:
    name = filename.lower()
    if "chain-oi-changes" in name:
        return models.RawSource.OI_DIFF
    if "hot-chains" in name:
        return models.RawSource.HOT_CHAINS
    if "dp-eod-report" in name:
        return models.RawSource.DARKPOOL_EOD
    if "bot-eod-report" in name:
        return models.RawSource.BOT_EOD
    if "stock-screener" in name:
        return models.RawSource.STOCK_SCREENER
    return None


def _ensure_session(db, session_date: date) -> models.Session:
    existing = db.query(models.Session).filter(models.Session.date == session_date).first()
    if existing:
        return existing
    session = models.Session(date=session_date, strategy_mode=models.StrategyMode.INDEX_EOD)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _parse_yyyy_mm_dd(value: str) -> date:
    return datetime.strptime(value.strip(), "%Y-%m-%d").date()


def _truncate_csv_to_n_rows(src: Path, max_rows: int) -> Path:
    """Create a temporary CSV containing header + first N data rows."""
    if max_rows <= 0:
        return src

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=src.suffix)
    tmp_path = Path(tmp.name)
    tmp.close()

    with src.open("r", encoding="utf-8", errors="replace", newline="") as r, tmp_path.open(
        "w", encoding="utf-8", newline=""
    ) as w:
        header = r.readline()
        if not header:
            return src
        w.write(header)
        for _ in range(max_rows):
            line = r.readline()
            if not line:
                break
            w.write(line)

    return tmp_path


def import_all_sample_data(
    sample_dir: Path,
    date_start: date | None,
    date_end: date | None,
    max_oi_rows: int | None,
) -> None:
    if not sample_dir.exists():
        raise FileNotFoundError(sample_dir)

    # For local SQLite testing, we need tables. This is a no-op if they already exist.
    print("Creating tables (if needed)...", flush=True)
    models.Base.metadata.create_all(bind=engine)
    print("Tables ready.", flush=True)

    files = sorted([p for p in sample_dir.glob("*.csv")])
    if not files:
        print("No CSVs found in sample_data")
        return

    db = SessionLocal()
    try:
        imported = 0
        skipped = 0

        for idx, f in enumerate(files, start=1):
            d = _extract_date_from_filename(f.name)
            source = _guess_source(f.name)
            if d is None or source is None:
                continue

            if date_start and d < date_start:
                continue
            if date_end and d > date_end:
                continue

            if idx % 10 == 0:
                print(f"Progress: scanned {idx}/{len(files)} files...", flush=True)

            session = _ensure_session(db, d)

            # Skip if already ingested
            existing = (
                db.query(models.RawFile)
                .filter(models.RawFile.session_id == str(session.session_id), models.RawFile.filename == f.name)
                .first()
            )
            if existing:
                skipped += 1
                continue

            path_for_parse = f
            tmp_path: Path | None = None
            if source == models.RawSource.OI_DIFF and max_oi_rows:
                tmp_path = _truncate_csv_to_n_rows(f, max_oi_rows)
                path_for_parse = tmp_path

            print(f"Importing {f.name} ({source.value}) for {d}...", flush=True)
            parsed = _dispatch_parser(source, path_for_parse)
            checksum = sha256_file(path_for_parse)

            extras = {"headers": parsed.headers, "rows": parsed.rows}
            if tmp_path is not None:
                extras["truncated"] = True
                extras["truncated_rows"] = len(parsed.rows)
                extras["truncated_from"] = f.name

            raw_file = models.RawFile(
                session_id=str(session.session_id),
                source=source,
                filename=f.name,
                sha256=checksum,
                rows=len(parsed.rows),
                extras=extras,
                parse_status=models.ParseStatus.OK if not parsed.errors else models.ParseStatus.ERROR,
                error_message=";".join(parsed.errors) if parsed.errors else None,
            )
            db.add(raw_file)
            db.commit()

            print(f"  -> stored rows={len(parsed.rows)} status={raw_file.parse_status.value}", flush=True)

            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

            imported += 1

        print(f"Imported files: {imported}")
        print(f"Skipped files (already ingested): {skipped}")

    finally:
        db.close()


def verify_db(sample_dir: Path) -> None:
    db = SessionLocal()
    try:
        sessions_count = db.query(models.Session).count()
        raw_files_count = db.query(models.RawFile).count()
        print(f"DB sessions: {sessions_count}")
        print(f"DB raw_files: {raw_files_count}")

        # Verify a couple of known sample dates exist (if present in sample_dir)
        dates_in_files: set[date] = set()
        for f in sample_dir.glob("*.csv"):
            d = _extract_date_from_filename(f.name)
            if d:
                dates_in_files.add(d)

        for d in sorted(list(dates_in_files))[:3]:
            sess = db.query(models.Session).filter(models.Session.date == d).first()
            if not sess:
                print(f"Missing session for {d}")
                continue
            cnt = db.query(models.RawFile).filter(models.RawFile.session_id == str(sess.session_id)).count()
            print(f"Session {d} ({sess.session_id}) raw_files={cnt}")

        # Sample one OI_DIFF file and confirm we can read extras.rows
        oi_file = (
            db.query(models.RawFile)
            .filter(models.RawFile.source == models.RawSource.OI_DIFF)
            .order_by(models.RawFile.imported_at.desc())
            .first()
        )
        if not oi_file:
            print("No OI_DIFF raw files found to verify")
            return

        rows = (oi_file.extras or {}).get("rows") or []
        print(f"Sample OI_DIFF file: {oi_file.filename} rows={oi_file.rows} extras.rows={len(rows)}")
        if rows:
            first = rows[0]
            keys_preview = sorted(list(first.keys()))[:10]
            print(f"First row keys (first 10): {keys_preview}")

        # Basic SQL connectivity smoke test
        db.execute(text("select 1"))
        print("SQL smoke test: OK")

    finally:
        db.close()


def main() -> None:
    sample_dir = REPO_ROOT / "sample_data"

    date_start = None
    date_end = None
    max_oi_rows = None

    if os.environ.get("UW_IMPORT_DATE_START"):
        date_start = _parse_yyyy_mm_dd(os.environ["UW_IMPORT_DATE_START"])
    if os.environ.get("UW_IMPORT_DATE_END"):
        date_end = _parse_yyyy_mm_dd(os.environ["UW_IMPORT_DATE_END"])
    if os.environ.get("UW_IMPORT_MAX_OI_ROWS"):
        max_oi_rows = int(os.environ["UW_IMPORT_MAX_OI_ROWS"])

    print("Database URL:", os.environ.get("UW_DATABASE_URL", "<default from settings>"))
    if date_start or date_end or max_oi_rows:
        print(
            f"Import filters: date_start={date_start} date_end={date_end} max_oi_rows={max_oi_rows}",
            flush=True,
        )

    import_all_sample_data(sample_dir, date_start=date_start, date_end=date_end, max_oi_rows=max_oi_rows)
    verify_db(sample_dir)


if __name__ == "__main__":
    main()
