@echo off
setlocal

REM Ensure we are running from the repo root (this script's directory)
cd /d "%~dp0"

echo Starting UWD: Ticker Batch dashboard only (backend + frontend)

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
if "%UWD_FRONTEND_PORT%"=="" (
  for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$ports=5173..5199; $used=@(); try { $used=(Get-NetTCPConnection -State Listen | Select-Object -ExpandProperty LocalPort) } catch {} ; $free=($ports | Where-Object { $_ -notin $used } | Select-Object -First 1); if (-not $free) { $free=5173 }; Write-Output $free"`) do (
    set "UWD_FRONTEND_PORT=%%P"
  )
)

REM If the API port is already in use, pick a free one from 8000..8099
for /f "usebackq delims=" %%A in (`powershell -NoProfile -Command "$p=%UWD_API_PORT%; $inUse=$false; try { $inUse=(@(Get-NetTCPConnection -State Listen | Where-Object { $_.LocalPort -eq $p }).Count -gt 0) } catch {} ; if ($inUse) { $ports=8000..8099; $used=@(); try { $used=(Get-NetTCPConnection -State Listen | Select-Object -ExpandProperty LocalPort) } catch {} ; $free=($ports | Where-Object { $_ -notin $used } | Select-Object -First 1); if (-not $free) { $free=$p }; Write-Output $free } else { Write-Output $p }"`) do (
  set "UWD_API_PORT=%%A"
)

REM Default DB connection (only set if not already set)
if "%UW_DATABASE_URL%"=="" (
  set "UW_DATABASE_URL=postgresql+psycopg2://uw_app:uw_password@127.0.0.1:5433/uw_eod"
)

REM Optional: open all frontend views (regime/options/tickers) automatically
if "%UWD_OPEN_ALL_VIEWS%"=="" set "UWD_OPEN_ALL_VIEWS=false"

REM Enable dev-only helper for loading a local CSV by absolute path (localhost-only)
REM This is required for the dashboard's "Load from path" button.
if "%UW_DEV_LOCAL_FILE_READ_ENABLED%"=="" set "UW_DEV_LOCAL_FILE_READ_ENABLED=true"

echo UW_DATABASE_URL=%UW_DATABASE_URL%
echo UWD_API_PORT=%UWD_API_PORT%
echo UWD_FRONTEND_PORT=%UWD_FRONTEND_PORT%
echo UW_DEV_LOCAL_FILE_READ_ENABLED=%UW_DEV_LOCAL_FILE_READ_ENABLED%

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
start "UWD API" cmd /k "cd /d \"%~dp0backend\" ^& ..\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port %UWD_API_PORT%"

REM Start frontend (Vite)
start "UWD Frontend" cmd /k "cd /d \"%~dp0frontend\" ^& npm run dev -- --port %UWD_FRONTEND_PORT% --strictPort"

REM Wait briefly for Vite to bind, then open the ticker batch view directly
for /L %%I in (1,1,30) do (
  powershell -NoProfile -Command "try { $c=Get-NetTCPConnection -State Listen -LocalPort %UWD_FRONTEND_PORT% -ErrorAction Stop; if ($c) { exit 0 } } catch { } ; exit 1" >nul 2>&1
  if not errorlevel 1 goto :open_browser
  timeout /t 1 /nobreak >nul
)

:open_browser
start "Ticker Batch" http://localhost:%UWD_FRONTEND_PORT%/?view=tickers
if /I "%UWD_OPEN_ALL_VIEWS%"=="true" (
  start "Frontend" http://localhost:%UWD_FRONTEND_PORT%/
  start "Frontend - Options" http://localhost:%UWD_FRONTEND_PORT%/?view=options
)

echo.
echo Ticker Batch launched.
echo Close each spawned window to stop that component.

endlocal
