import sys
from pathlib import Path
from datetime import date
import os
from urllib.parse import urlparse

# Add backend to path
REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.append(str(BACKEND_ROOT))

from sqlalchemy import text
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

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


def _redact_database_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme.startswith("postgres") and (parsed.username or parsed.password):
            user = parsed.username or ""
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port else ""
            auth = f"{user}:***" if user else "***"
            netloc = f"{auth}@{host}{port}" if host else auth
            return parsed._replace(netloc=netloc).geturl()
    except Exception:
        return "<unprintable database url>"
    return url


def main() -> int:
    settings = get_settings()
    db_url = settings.database_url
    print(f"database_url={_redact_database_url(db_url)}")

    # If the target DB does not exist yet, optionally create it using a maintenance connection.
    # Enable with: UW_CREATE_DB=1
    if db_url.startswith("postgresql"):
        parsed = urlparse(db_url)
        target_db = (parsed.path or "").lstrip("/")
        if target_db:
            maintenance_db = os.environ.get("UW_MAINTENANCE_DB", "postgres")
            maintenance_url = parsed._replace(path=f"/{maintenance_db}").geturl()

            def _ensure_database_exists() -> None:
                create_db = os.environ.get("UW_CREATE_DB", "0") in ("1", "true", "True")
                try:
                    maint_engine = create_engine(maintenance_url, future=True, echo=False)
                    with maint_engine.connect() as conn:
                        # List databases
                        dbs = conn.execute(
                            text(
                                """
                                select datname
                                from pg_database
                                where datistemplate = false
                                order by datname
                                """
                            )
                        ).scalars().all()
                        print("existing databases =>", ", ".join(dbs) if dbs else "<none>")

                        if target_db in dbs:
                            return

                        if not create_db:
                            print(
                                f"database '{target_db}' does not exist. Set UW_CREATE_DB=1 to create it.",
                                flush=True,
                            )
                            return

                        # CREATE DATABASE must run outside an explicit transaction.
                        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
                        conn.execute(text(f'create database "{target_db}"'))
                        print(f"created database => {target_db}")
                except Exception as e:
                    print("maintenance connection / create-db failed:", repr(e))

            # Only attempt ensure/create if the main connection fails with "does not exist".
            try:
                with engine.connect() as conn:
                    conn.execute(text("select 1")).scalar_one()
            except OperationalError as e:
                msg = str(e).lower()
                if "does not exist" in msg and target_db.lower() in msg:
                    _ensure_database_exists()
                else:
                    raise

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
        if isinstance(exc, OperationalError):
            msg = str(exc).lower()
            if "password authentication failed" in msg or "authentication failed" in msg:
                print(
                    "Hint: authentication failed. Verify UW_DATABASE_URL user/password (and pg_hba.conf auth settings)."
                )
            elif "does not exist" in msg and "database" in msg:
                print(
                    "Hint: database missing. Try rerunning with UW_CREATE_DB=1 (if your role has CREATEDB) or create the DB in pgAdmin/psql."
                )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
