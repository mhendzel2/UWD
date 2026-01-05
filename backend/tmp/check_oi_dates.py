from sqlalchemy import text

from app.db.engine import engine


def main() -> None:
    with engine.connect() as conn:
        max_session = conn.execute(text("select max(date) from sessions")).scalar()
        max_oi = conn.execute(
            text(
                """
                select max(s.date)
                from sessions s
                join raw_files rf on rf.session_id = s.session_id
                where rf.source = 'OI_DIFF'
                """
            )
        ).scalar()

        print(f"max_session_date: {max_session}")
        print(f"max_oi_diff_date: {max_oi}")

        rows = conn.execute(
            text(
                """
                select s.date, count(*) as oi_files
                from sessions s
                join raw_files rf on rf.session_id = s.session_id
                where rf.source = 'OI_DIFF'
                group by s.date
                order by s.date desc
                limit 15
                """
            )
        ).all()

        print("latest OI_DIFF dates:")
        for d, c in rows:
            print(f"  {d} oi_files={c}")


if __name__ == "__main__":
    main()
