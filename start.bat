@echo off
echo Starting UWD System...

echo Activating virtual environment...
call venv\Scripts\activate

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

echo System started.
