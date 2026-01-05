"""Backfill v0 compute (features/regimes/plans) for a range of existing sessions.

Use this when raw_files have been imported but v0 compute (and therefore plans) were
not run for all dates.

Example:
  set "UW_DATABASE_URL=postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
  C:/Users/mjhen/Github/UWD/.venv/Scripts/python.exe -u scripts/backfill_compute_v0.py --start-date 2025-12-01 --end-date 2026-01-02

Notes:
- This operates on existing `sessions` in the DB.
- By default it only runs compute for sessions missing plans for that session date.
"""

from __future__ import annotations

import argparse
from datetime import date

from app.api import routes
from app.db import models
from app.db.engine import session_scope
from app.utils.time import parse_date


def _has_plans_for_session_date(db, session: models.Session) -> bool:
    return (
        db.query(models.Plan)
        .filter(models.Plan.session_id == session.session_id, models.Plan.trade_date == session.date)
        .first()
        is not None
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default=None, help="Optional YYYY-MM-DD")
    ap.add_argument("--end-date", default=None, help="Optional YYYY-MM-DD")
    ap.add_argument(
        "--include-already-planned",
        action="store_true",
        help="Also run compute_v0 even if plans already exist for that session date.",
    )
    ap.add_argument("--limit", type=int, default=0, help="Optional max sessions to process (0=all)")
    args = ap.parse_args()

    start: date | None = parse_date(args.start_date) if args.start_date else None
    end: date | None = parse_date(args.end_date) if args.end_date else None

    processed = 0
    skipped = 0
    errors = 0

    with session_scope() as db:
        q = db.query(models.Session).order_by(models.Session.date.asc())
        if start:
            q = q.filter(models.Session.date >= start)
        if end:
            q = q.filter(models.Session.date <= end)
        sessions = q.all()

    # Process each session in its own transaction.
    for sess in sessions:
        if args.limit and processed >= args.limit:
            break

        try:
            with session_scope() as db:
                session = db.get(models.Session, sess.session_id)
                if not session:
                    continue

                if not args.include_already_planned and _has_plans_for_session_date(db, session):
                    skipped += 1
                    continue

                # Compute v0 for the session date (also builds plans).
                routes.compute_v0(session_id=str(session.session_id), asof_date=str(session.date), db=db)
                processed += 1
                print(f"OK {session.date} session_id={session.session_id}")
        except Exception as e:
            errors += 1
            print(f"ERR {sess.date} session_id={sess.session_id}: {e}")

    print(f"done processed={processed} skipped={skipped} errors={errors}")
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
