@echo off
REM Start Cue on Windows: Docker services, then the API and all workers in this window.
REM Optional: setup\start.bat --voice   also starts the GPU Whisper/Kokoro container.
REM Optional: setup\start.bat --tunnel  also opens a Cloudflare quick tunnel to the API.
setlocal
cd /d "%~dp0.."
call .venv\Scripts\activate.bat || (echo Run setup\setup.bat first & exit /b 1)

docker compose up -d db qdrant pubsub gcs || exit /b 1
for %%A in (%*) do (
  if "%%A"=="--voice" docker compose --profile stt up -d whisper
  if "%%A"=="--tunnel" start "cue tunnel" cloudflared tunnel --url http://localhost:8080
)

python scripts\ensure_partitions.py
python scripts\run_stack.py
