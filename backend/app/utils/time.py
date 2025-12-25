from datetime import datetime, date


def parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def utcnow() -> datetime:
    return datetime.utcnow()
