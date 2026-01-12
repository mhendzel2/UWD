@echo off
setlocal

REM Ensure we are running from the repo root (this script's directory)
cd /d "%~dp0"

echo Starting UWD: backend API, frontend, dashboards...

REM Verify venv exists
if not exist ".venv\Scripts\python.exe" (
  echo.
  echo ERROR: .venv not found at %cd%\.venv
  echo Run install.bat first.
  echo.
  pause
  exit /b 1
)

REM Default ports (can be overridden by env vars)
if "%UWD_API_PORT%"=="" set "UWD_API_PORT=8000"
if "%UWD_FRONTEND_PORT%"=="" set "UWD_FRONTEND_PORT=5173"

REM Default DB connection (only set if not already set)
if "%UW_DATABASE_URL%"=="" (
  set "UW_DATABASE_URL=postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
)

echo UW_DATABASE_URL=%UW_DATABASE_URL%
echo UWD_API_PORT=%UWD_API_PORT%
echo UWD_FRONTEND_PORT=%UWD_FRONTEND_PORT%

REM Ensure DB schema is up to date (idempotent). Set UWD_SKIP_MIGRATIONS=true to skip.
if "%UWD_SKIP_MIGRATIONS%"=="" set "UWD_SKIP_MIGRATIONS=false"
if /I not "%UWD_SKIP_MIGRATIONS%"=="true" (
  echo.
  echo Running alembic upgrade head...
  pushd "%~dp0backend"
  ..\.venv\Scripts\alembic.exe upgrade head
  popd
)

REM Optionally start Postgres via docker-compose if docker is available
docker --version >nul 2>&1
if errorlevel 1 goto :skip_docker

echo.
echo Starting docker-compose services (if defined)...
docker compose up -d
goto :after_docker

:skip_docker
echo.
echo NOTE: docker not found; skipping docker compose.

:after_docker

REM Start backend API (FastAPI)
start "UWD API" cmd /k "cd /d \"%~dp0backend\" & ..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port %UWD_API_PORT%"

REM Start frontend (Vite)
start "UWD Frontend" cmd /k "cd /d \"%~dp0frontend\" & npm run dev -- --port %UWD_FRONTEND_PORT%"

REM Start outlier dashboard (Streamlit)
start "UWD Outlier Dashboard" cmd /k "cd /d \"%~dp0\" & call start_dashboard.bat"

REM Pick a separate port for the trade_surveillance Streamlit app (8601..8699)
if "%TS_DASHBOARD_PORT%"=="" (
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$ports=8601..8699; $used=@(); try { $used=(Get-NetTCPConnection -State Listen | Select-Object -ExpandProperty LocalPort) } catch {} ; $free=($ports | Where-Object { $_ -notin $used } | Select-Object -First 1); if (-not $free) { $free=8601 }; Write-Output $free"`) do (
    set "TS_DASHBOARD_PORT=%%P"
  )
)

echo TS_DASHBOARD_PORT=%TS_DASHBOARD_PORT%

REM Find a scores parquet for trade_surveillance, unless explicitly provided
if "%TS_SCORES_PATH%"=="" (
  if exist "tmp\ts_norm_eval\scores_cross.parquet" (
    set "TS_SCORES_PATH=tmp\ts_norm_eval\scores_cross.parquet"
  ) else if exist "tmp\ts_norm_eval\scores_base.parquet" (
    set "TS_SCORES_PATH=tmp\ts_norm_eval\scores_base.parquet"
  ) else if exist "tmp\scores.parquet" (
    set "TS_SCORES_PATH=tmp\scores.parquet"
  )
)

if not "%TS_SCORES_PATH%"=="" (
  echo Launching trade_surveillance app with scores: %TS_SCORES_PATH%
  REM NOTE: Do not use backslash-escaped quotes (\") in cmd.exe; it becomes a literal quote in the argument.
  REM TS_SCORES_PATH is expected to be a simple relative path without spaces.
  start "Trade Surveillance" cmd /k "cd /d \"%~dp0\" & .\.venv\Scripts\python.exe -m streamlit run trade_surveillance\viz\streamlit_app.py --server.port %TS_DASHBOARD_PORT% -- --scores %TS_SCORES_PATH%"
) else (
  echo.
  echo NOTE: No trade_surveillance scores found.
  echo To start it, set TS_SCORES_PATH to a scores.parquet and re-run startall.bat.
  echo Example:
  echo   set TS_SCORES_PATH=tmp\ts_norm_eval\scores_cross.parquet
)

REM Open key URLs
start "Frontend" http://localhost:%UWD_FRONTEND_PORT%
start "API Docs" http://localhost:%UWD_API_PORT%/docs
if not "%TS_SCORES_PATH%"=="" start "Trade Surveillance" http://localhost:%TS_DASHBOARD_PORT%

echo.
echo All components launched.
echo Close each spawned window to stop that component.

endlocal
