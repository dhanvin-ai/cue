# Cue

Cue is an AI teammate for software teams, being developed for the Bolna AI Buildathon.

The product concept is an agent with its own team identity that can answer questions about work, participate in meetings when addressed, track decisions and action items, and carry out approved actions across tools. The first planned integrations are Google Workspace, Slack, GitHub, meetings, and a project tracker.

This repository is private. It contains the Phase 1 FastAPI foundation, the [Phase 2 connector setup](docs/phase2-connectors.md), the [Phase 3 event pipeline](docs/phase3-ingestion.md), the [Phase 4 v1 connectors](docs/phase4-connectors.md), the [Phase 5 memory layer](docs/phase5-memory.md), the [Phase 6 agent runtime](docs/phase6.md), and a [license decision guide](docs/licensing.md).

Before Phase 6, [Playwright API end-to-end tests](docs/e2e-testing.md) exercise the backend over HTTP with real Postgres and Qdrant services in CI.

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
docker compose up -d db qdrant
python3.12 -m venv .venv
.venv/bin/pip install -e '.[test]'
cp .env.example .env
set -a; . ./.env; set +a
.venv/bin/python scripts/migrate.py
.venv/bin/python scripts/ensure_partitions.py
.venv/bin/pytest -q
.venv/bin/uvicorn cue.main:app --reload
```

Set `FIREBASE_PROJECT_ID` to a Firebase project you control before sending a real ID token. `GET /healthz` is public. `GET /v1/tenants/{tenant_id}/me` requires a Firebase bearer token and a matching row in `users`. Create tenants and users through the migration/admin connection while provisioning a team; onboarding is a later phase.

For Cloud Run, put database credentials in Secret Manager and connect to Cloud SQL using the service's configured socket or connector. Keep the migration role separate from `cue_app`; the API must use the restricted role. Do not put production credentials in `.env` or the repository. Connector credentials are read from Secret Manager beginning in Phase 2; per-tenant encryption key work remains part of the security rollout.

## Phase 2 connectors

The connector contract defines authorization, backfill, subscription checks, normalization, ACL mapping, and tools. The first implementation is a GitHub App connector. It sends signed webhook deliveries and resumable issue/PR snapshots to the Pub/Sub raw-events topic. See [setup and current limits](docs/phase2-connectors.md).

## Phase 3 event pipeline

The ingest worker stores raw GitHub events in GCS, resolves source identities, and writes canonical events to a tenant-isolated, monthly Postgres log. The outbox worker publishes committed events for later memory-store fan-out. See [pipeline setup and replay](docs/phase3-ingestion.md).

## Phase 4 v1 connectors

Gmail, Google Calendar, Slack, GitHub, Linear, and Recall meeting bots now have read/sync, source ACL mapping, and typed write methods. GitHub, Slack, Linear, and Recall have signed webhook ingress; Gmail and Calendar notifications trigger cursor-based backfill. See [vendor setup and remaining production work](docs/phase4-connectors.md).

## Phase 5 memory and query routing

Canonical events project into tenant-isolated Postgres documents and temporal graph edges, and into Qdrant collections using Qwen3 embeddings. The query API routes exact counts, ownership, current status, recall, and period questions through the appropriate store after resolving each requester's source principals. Daily, weekly, monthly, and yearly summaries retain citations to source events. See [memory setup and query examples](docs/phase5-memory.md).

## Phase 6 agent runtime

Slack, email, and web requests enter one runtime that builds ACL-filtered context, plans tool calls, checks each against the PDF risk tiers, and records every decision in an append-only audit log. Tasks retry with idempotent tool calls; tier 2 and 3 actions wait for approval. See [runtime setup and tool registration](docs/phase6.md).
