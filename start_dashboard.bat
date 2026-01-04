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

REM Pick a port (honor UWD_DASHBOARD_PORT if set; otherwise pick first free from 8501..8599)
if "%UWD_DASHBOARD_PORT%"=="" (
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$ports=8501..8599; $used=@(); try { $used=(Get-NetTCPConnection -State Listen | Select-Object -ExpandProperty LocalPort) } catch {} ; $free=($ports | Where-Object { $_ -notin $used } | Select-Object -First 1); if (-not $free) { $free=8501 }; Write-Output $free"`) do (
    set "UWD_DASHBOARD_PORT=%%P"
  )
)

echo UWD_DASHBOARD_PORT=%UWD_DASHBOARD_PORT%

REM Streamlit should run from backend/ so relative paths and imports behave
cd /d "%~dp0backend"

REM Open browser and launch Streamlit
start "UWD Dashboard" http://localhost:%UWD_DASHBOARD_PORT%
..\.venv\Scripts\python.exe -m streamlit run scripts\outlier_dashboard.py --server.port %UWD_DASHBOARD_PORT%

endlocal
