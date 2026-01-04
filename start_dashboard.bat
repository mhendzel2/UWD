@echo off
setlocal

echo Starting UWD Outlier Dashboard...

REM Ensure we are running from the repo root (this script's directory)
cd /d "%~dp0"

REM Verify venv exists
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo ERROR: .venv not found at %cd%\.venv
  echo Run install.bat first.
  echo.
  pause
  exit /b 1
)

REM Default DB connection (only set if not already set)
if "%UW_DATABASE_URL%"=="" (
  set "UW_DATABASE_URL=postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
)

echo UW_DATABASE_URL=%UW_DATABASE_URL%

REM Streamlit should run from backend/ so relative paths and imports behave
cd /d "%~dp0backend"

REM Launch Streamlit (opens at http://localhost:8501)
..\.venv\Scripts\python.exe -m streamlit run scripts\outlier_dashboard.py

endlocal
