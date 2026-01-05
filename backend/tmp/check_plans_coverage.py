from sqlalchemy import text

from app.db.engine import engine


def main() -> None:
    print("check_plans_coverage: start")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                select
                    s.date,
                    (select count(*) from regime_decisions r where r.session_id=s.session_id and r.asof_date=s.date) as regimes,
                    (select count(*) from plans p where p.session_id=s.session_id and p.trade_date=s.date) as plans
                from sessions s
                where s.date >= '2025-12-01'
                order by s.date desc
                limit 25
                """
            )
        ).all()
        print(f"rows_returned: {len(rows)}")
        for d, regimes, plans in rows:
            print(f"{d} regimes={regimes} plans={plans}")

        missing = conn.execute(
            text(
                """
                select count(*)
                from sessions s
                where exists (
                    select 1 from regime_decisions r where r.session_id=s.session_id and r.asof_date=s.date
                )
                and not exists (
                    select 1 from plans p where p.session_id=s.session_id and p.trade_date=s.date
                )
                """
            )
        ).scalar()
        print(f"\nsessions missing plans (but have regimes): {missing}")
    print("check_plans_coverage: done")


if __name__ == '__main__':
    main()
