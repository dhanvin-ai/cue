#!/usr/bin/env bash
# One-time local setup for Cue on macOS or Linux. Safe to rerun.
# Needs: Python 3.12+, Docker. See SETUP.md.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=$(command -v python3.12 || command -v python3)

echo "[1/6] Python virtual environment"
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip >/dev/null
pip install -e '.[test]'

echo "[2/6] .env and .secrets"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created .env from .env.example. Uncomment the \"Local stack\" block and fill your keys."
fi
mkdir -p .secrets && chmod 700 .secrets

echo "[3/6] Docker services: Postgres, Qdrant, Pub/Sub and GCS emulators"
docker compose up -d db qdrant pubsub gcs
# Give Postgres a moment to accept connections.
sleep 5

echo "[4/6] Database migrations and partitions"
python scripts/migrate.py
python scripts/ensure_partitions.py

echo "[5/6] Local Pub/Sub topics and raw bucket"
python scripts/local_gcp.py

echo "[6/6] Demo tenant and admin"
python scripts/seed_dev_tenant.py

echo
echo "Setup done. Next: connect your accounts (SETUP.md), then run ./setup/start.sh"
