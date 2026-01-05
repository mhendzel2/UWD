from __future__ import annotations

import argparse

from app.api import routes
from app.db import models
from app.db.engine import session_scope


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD")
    args = ap.parse_args()

    with session_scope() as db:
        session = db.query(models.Session).filter(models.Session.date == args.date).first()
        if not session:
            raise SystemExit(f"No session found for date={args.date}")

        print(f"session_id={session.session_id} date={session.date}")
        before = db.query(models.Plan).filter(models.Plan.session_id == session.session_id, models.Plan.trade_date == session.date).count()
        print(f"plans_before={before}")

        routes.compute_v0(session_id=str(session.session_id), asof_date=str(session.date), db=db)

        after = db.query(models.Plan).filter(models.Plan.session_id == session.session_id, models.Plan.trade_date == session.date).count()
        print(f"plans_after={after}")


if __name__ == '__main__':
    main()
