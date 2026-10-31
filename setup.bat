@echo off
REM One-time local setup for Cue on Windows. Safe to rerun.
REM Needs: Python 3.12+, Docker Desktop. See SETUP.md.
setlocal
cd /d "%~dp0"

where py >nul 2>nul && (set PY=py -3.12) || (set PY=python)

echo [1/6] Python virtual environment
if not exist .venv (%PY% -m venv .venv || goto :fail)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
pip install -e ".[test]" || goto :fail

echo [2/6] .env and .secrets
if not exist .env (
  copy .env.example .env >nul
  echo   Created .env from .env.example. Uncomment the "Local stack" block and fill your keys.
)
if not exist .secrets mkdir .secrets

echo [3/6] Docker services: Postgres, Qdrant, Pub/Sub and GCS emulators
docker compose up -d db qdrant pubsub gcs || goto :fail
REM Give Postgres a moment to accept connections.
timeout /t 5 /nobreak >nul

echo [4/6] Database migrations and partitions
python scripts\migrate.py || goto :fail
python scripts\ensure_partitions.py || goto :fail

echo [5/6] Local Pub/Sub topics and raw bucket
python scripts\local_gcp.py || goto :fail

echo [6/6] Demo tenant and admin
python scripts\seed_dev_tenant.py || goto :fail

echo.
echo Setup done. Next: connect your accounts (SETUP.md), then run start.bat
exit /b 0

:fail
echo Setup failed at the step above. See SETUP.md, Troubleshooting.
exit /b 1
