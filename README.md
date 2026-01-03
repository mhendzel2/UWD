# UWD Regime-First EOD Market Analysis (v1)

This repository provides a PostgreSQL-backed, regime-first EOD analysis stack. It ingests Unusual Whales CSV exports, builds boolean features, classifies next-day regimes, and emits conditional trade plans. v1 adds discovery (Daily Briefs), interpretability (Ecology), and a conservative v1 ensemble while keeping v0 intact and stored separately.

## Prerequisites
- Python 3.11+
- Node 20+ (for the frontend)
- Docker (for PostgreSQL)

## Quickstart
1. `docker-compose up -d` to start PostgreSQL 16 (port 5433, user `uw_app`, password `uw_password`, db `uw_eod`).
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
- `POST /compute/v0` – build features, classify regimes, and stage plans for the session/date (v0 only).
- `POST /compute/ecology_v0` – compute ecology state overlays (dominant horizon, tail-risk flags, plan modifiers).
- `POST /briefs/generate_v1` – build the three Daily Briefs (flow short-term, high IV sell premium, low IV buy premium).
- `POST /compute/v1` – build v1 feature persistence metrics and conservative ensemble classification.
- `GET /sessions/{id}/summary` – lightweight summary.
- `GET /sessions/{id}/briefs` – Daily Brief artifacts for the session.
- `GET /sessions/{id}/ensemble` – v1 ensemble decisions.
- `GET /sessions/{id}/regimes` – regime decisions (v0) with ecology overlays when computed.
- `POST /outcomes` – record manual outcomes.
- WebSockets: `/ws/logs`, `/ws/decisions` (broadcasts for briefs/ecology/ensemble events).

Frontend UI actions on Session Dashboard:
- Compute v0
- Compute Ecology State (v0-compatible overlays)
- Generate Daily Briefs
- Compute v1 Ensemble

## Testing
From `backend`: `pytest`.

## Design notes
- Regime-first logic with conservative boolean rules (see `app/features/constants_v0.py` and `app/regime/classify_v0.py`); v1 adds persistence metrics and ensemble voting without ML or threshold tuning.
- Daily Briefs are discovery-only and marked as “candidates” requiring regime permission; no execution commands are emitted.
- Ecology panel is interpretability-focused (dominant horizon, disagreement, timing profile, strike-level walls/pockets, sector/market overlays, tail-risk flags) and feeds plan modifiers, not alpha.
- Ensemble horizon weights update slowly (weekly) and only after at least 12 labeled Fridays; weights are floored and change-limited.
- Orthogonal datasets are preserved as JSONB on import; per-underlying aggregates feed the feature builders. All structured fields use UUID primary keys and JSONB payloads where appropriate.
