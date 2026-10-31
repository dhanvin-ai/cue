#!/usr/bin/env bash
# Start Cue on macOS or Linux: Docker services, then the API and all workers in this terminal.
# Optional: ./start.sh --voice   also starts the GPU Whisper/Kokoro container (NVIDIA only).
# Optional: ./start.sh --tunnel  also opens a Cloudflare quick tunnel to the API.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { echo "Run ./setup.sh first"; exit 1; }
. .venv/bin/activate

docker compose up -d db qdrant pubsub gcs
for arg in "$@"; do
  case "$arg" in
    --voice) docker compose --profile stt up -d whisper ;;
    --tunnel) cloudflared tunnel --url http://localhost:8080 > .tunnel.log 2>&1 &
              echo "Tunnel starting; its https URL is in .tunnel.log" ;;
  esac
done

python scripts/ensure_partitions.py
exec python scripts/run_stack.py
