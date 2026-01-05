from sqlalchemy import text

from app.db.engine import engine


def main() -> None:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                select s.date as session_date,
                       min(p.trade_date) as min_trade_date,
                       max(p.trade_date) as max_trade_date,
                       count(*) as plans
                from sessions s
                join plans p on p.session_id = s.session_id
                group by s.date
                order by s.date desc
                limit 20
                """
            )
        ).all()
        print("plans by session_date:")
        for sd, mn, mx, c in rows:
            print(f"  {sd} plans={c} trade_date_range=[{mn},{mx}]")

        print("\nlatest 20 distinct trade_dates in plans:")
        rows = conn.execute(
            text(
                """
                select trade_date, count(*)
                from plans
                group by trade_date
                order by trade_date desc
                limit 20
                """
            )
        ).all()
        for d, c in rows:
            print(f"  {d} plans={c}")


if __name__ == '__main__':
    main()
