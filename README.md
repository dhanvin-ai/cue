# Cue

Cue is an AI teammate for software teams, being developed for the Bolna AI Buildathon.

The product concept is an agent with its own team identity that can answer questions about work, participate in meetings when addressed, track decisions and action items, and carry out approved actions across tools. The first planned integrations are Google Workspace, Slack, GitHub, meetings, and a project tracker.

This repository is private. It contains the Phase 1 FastAPI foundation and a [license decision guide](docs/licensing.md).

## Planned system areas

- Connectors and an event pipeline for team tools
- Permission aware memory and retrieval
- A shared agent runtime with approval controls
- Meeting voice and follow up workflows
- A web interface for chat, tasks, approvals, and audit history

## Licensing status

No open source license has been applied yet. The repository is private while the team decides what to release and confirms who owns the rights to each component. See [licensing options](docs/licensing.md).

## Phase 1 backend

The API uses Firebase ID tokens and Cloud SQL PostgreSQL. Every tenant table has row level security; the API connects as the restricted `cue_app` role and sets the tenant ID for each transaction. OpenTelemetry exports traces when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. The container runs on Cloud Run.

Local setup requires Python 3.12 and a running Docker daemon:

```sh
docker compose up -d db
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
set -a; . ./.env; set +a
.venv/bin/python scripts/migrate.py
.venv/bin/pytest -q
.venv/bin/uvicorn cue.main:app --reload
```

Set `FIREBASE_PROJECT_ID` to a Firebase project you control before sending a real ID token. `GET /healthz` is public. `GET /v1/tenants/{tenant_id}/me` requires a Firebase bearer token and a matching row in `users`. Create tenants and users through the migration/admin connection while provisioning a team; onboarding is a later phase.

For Cloud Run, put database credentials in Secret Manager and connect to Cloud SQL using the service's configured socket or connector. Keep the migration role separate from `cue_app`; the API must use the restricted role. Do not put production credentials in `.env` or the repository. Phase 1 does not yet store OAuth tokens, so Secret Manager and Cloud KMS integration for connector credentials belongs to Phase 2.
