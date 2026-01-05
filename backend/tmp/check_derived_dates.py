from sqlalchemy import text

from app.db.engine import engine


QUERIES = {
    "sessions_max": "select max(date) from sessions",
    "raw_oi_max": """
        select max(s.date)
        from sessions s
        join raw_files rf on rf.session_id=s.session_id
        where rf.source='OI_DIFF'
    """,
    "raw_bot_max": """
        select max(s.date)
        from sessions s
        join raw_files rf on rf.session_id=s.session_id
        where rf.source='BOT_EOD'
    """,
    "features_max": "select max(asof_date) from features_underlying_day",
    "regimes_max": "select max(asof_date) from regime_decisions",
    "plans_max": "select max(trade_date) from plans",
    "ensemble_max": "select max(asof_date) from ensemble_decisions",
}


def main() -> None:
    with engine.connect() as conn:
        for name, q in QUERIES.items():
            try:
                v = conn.execute(text(q)).scalar()
            except Exception as e:
                v = f"ERROR: {e}"
            print(f"{name}: {v}")

        # Show any sessions after 2025-12-26 that are missing BOT_EOD or OI_DIFF
        rows = conn.execute(
            text(
                """
                select s.date,
                       sum(case when rf.source='BOT_EOD' then 1 else 0 end) as bot_files,
                       sum(case when rf.source='OI_DIFF' then 1 else 0 end) as oi_files
                from sessions s
                left join raw_files rf on rf.session_id = s.session_id
                where s.date > '2025-12-26'
                group by s.date
                order by s.date asc
                """
            )
        ).all()
        print("\npost-2025-12-26 sessions (BOT_EOD vs OI_DIFF counts):")
        for d, bot, oi in rows:
            print(f"  {d} bot={bot} oi={oi}")


if __name__ == "__main__":
    main()
