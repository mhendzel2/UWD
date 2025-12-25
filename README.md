# UWD Regime-First EOD Market Analysis (v0)

This repository provides a PostgreSQL-backed, regime-first EOD analysis stack. It ingests Unusual Whales CSV exports, builds boolean features, classifies next-day regimes, and emits conditional trade plans. v0 is analysis-only (no execution).

## Prerequisites
- Python 3.11+
- Node 20+ (for the frontend)
- Docker (for PostgreSQL)

## Quickstart
1. `docker-compose up -d` to start PostgreSQL 16 (port 5432, user `uw_app`, password `uw_password`, db `uw_eod`).
2. Backend:
   - `cd backend`
   - `python -m venv .venv && . .venv/Scripts/activate` (PowerShell: `.\.venv\Scripts\activate`)
   - `pip install -e .[dev]`
   - `alembic upgrade head` to create tables.
   - `uvicorn app.main:app --reload` to run the API.
3. Frontend:
   - `cd frontend`
   - `npm install`
   - `npm run dev`

## API surface (FastAPI)
- `POST /sessions` – create an EOD session (`session_date`, `strategy_mode`).
- `POST /import/{source}` – upload CSV for a source (`OI_DIFF|BOT_EOD|HOT_CHAINS|DARKPOOL_EOD|STOCK_SCREENER`, multipart `file`, `session_id`).
- `POST /compute/v0` – build features, classify regimes, and stage plans for the session/date.
- `GET /sessions/{id}/summary` – lightweight summary.
- `POST /outcomes` – record manual outcomes.
- WebSockets: `/ws/logs`, `/ws/decisions` (stubbed keep-alives for v0).

## Testing
From `backend`: `pytest`.

## Design notes
- Regime-first logic with conservative boolean rules (see `app/features/constants_v0.py` and `app/regime/classify_v0.py`).
- Orthogonal datasets are preserved as JSONB on import; per-underlying aggregates feed the feature builder.
- All structured fields use UUID primary keys and JSONB payloads where appropriate.
