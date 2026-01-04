@echo off
echo Starting UWD System...

echo Activating virtual environment...
call .venv\Scripts\activate

REM Default DB connection (only set if not already set)
if "%UW_DATABASE_URL%"=="" (
	set "UW_DATABASE_URL=postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
)

echo Running Database Migrations...
cd backend
alembic upgrade head
cd ..

echo Processing Daily Data...
python scripts/process_daily.py

echo Starting Backend Server...
start "UWD Backend" cmd /k "cd backend && uvicorn app.main:app --reload"

echo Starting Frontend Client...
start "UWD Frontend" cmd /k "cd frontend && npm run dev"

echo Starting Outlier Dashboard...
start "UWD Dashboard" cmd /k "cd backend && ..\.venv\Scripts\python.exe -m streamlit run scripts\outlier_dashboard.py"

echo System started.
