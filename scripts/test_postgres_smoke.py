import sys
from pathlib import Path
from datetime import date

# Add backend to path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.append(str(BACKEND_ROOT))

from sqlalchemy import text

from app.db.engine import engine, SessionLocal
from app.db import models
from app.settings import get_settings


TABLES_TO_CHECK = [
    "sessions",
    "raw_files",
    "features_underlying_day",
    "regime_decisions",
    "plans",
]


def main() -> int:
    settings = get_settings()
    db_url = settings.database_url
    print(f"database_url={db_url}")

    try:
        with engine.connect() as conn:
            one = conn.execute(text("select 1"))
            print("select 1 =>", one.scalar_one())
            version = conn.execute(text("select version()"))
            print("version =>", version.scalar_one())

            # Check expected tables
            for table in TABLES_TO_CHECK:
                exists = conn.execute(
                    text(
                        """
                        select exists(
                          select 1
                          from information_schema.tables
                          where table_schema='public'
                            and table_name=:t
                        )
                        """
                    ),
                    {"t": table},
                ).scalar_one()
                print(f"table public.{table} exists => {bool(exists)}")

            # Lightweight read-only checks via ORM
            db = SessionLocal()
            try:
                sessions_count = db.query(models.Session).count()
                raw_files_count = db.query(models.RawFile).count()
                print("sessions count =>", sessions_count)
                print("raw_files count =>", raw_files_count)

                latest = db.query(models.Session).order_by(models.Session.date.desc()).first()
                if latest:
                    print("latest session =>", str(latest.session_id), str(latest.date))
                else:
                    print("latest session => <none>")

                # Non-destructive write test: start a transaction, insert, rollback
                # This verifies INSERT permissions + constraints without polluting data.
                tx = db.begin_nested()
                try:
                    test_sess = models.Session(
                        date=date.today(),
                        strategy_mode=models.StrategyMode.INDEX_EOD,
                        notes="smoke-test (will rollback)",
                    )
                    db.add(test_sess)
                    db.flush()  # forces INSERT
                    print("insert+flush session => OK (rolling back)")
                finally:
                    tx.rollback()
            finally:
                db.close()

        print("SMOKE TEST: OK")
        return 0

    except Exception as exc:
        print("SMOKE TEST: FAILED")
        print(type(exc).__name__ + ":", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
