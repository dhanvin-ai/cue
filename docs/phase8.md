# Phase 8: proactive work and pilot readiness

Adds proactive rules, quiet hours, kill switches, deletion/revocation propagation, reconciliation, audit export, and pilot status on top of Phases 1-7.

## Pilot runbook
1. `docker compose up -d db qdrant`, copy `.env.example` to `.env`, then run `python scripts/migrate.py`.
2. Provision tenants, users, principals, and connectors with the migration role.
3. Create rules via `POST /v1/tenants/{tenant_id}/proactive/rules` (`daily_digest`, `weekly_digest`, `reminder`, `stale_pr`, `overdue_action`).
4. Run `python scripts/run_tasks.py --tenant <uuid>` every minute. It ticks the Phase 6 scheduler, dispatches proactive rules, and runs tasks through policy and approvals.
5. Check `/healthz`, `/readyz`, `GET /v1/tenants/{tenant_id}/status` (member), and `GET /v1/tenants/{tenant_id}/admin/access-report` (admin).
6. Export audit rows with `GET /v1/tenants/{tenant_id}/admin/audit/export?since=&until=&format=json|csv`.

Proactive tasks use the same runtime, tiers, and approval tables as user requests. Daily digests default to 09:30, weekly digests to Friday 16:00, stale-PR/overdue checks to hourly. Each rule has a time zone and a per-person mute.

## Quiet hours
`PUT /v1/tenants/{tenant_id}/admin/quiet-hours` sets a tenant or user window with an IANA time zone; windows may cross midnight and a user window overrides the tenant window. Runs inside the window are stored as `deferred` with `deliver_after` and released by a later tick. The PDF defines no urgent exception, so urgent items wait too.

## Kill switches
`PUT /v1/tenants/{tenant_id}/admin/kill-switches/{scope}/{subject}` uses `scope=tenant` (subject `*`) or `scope=connector` (connection UUID). `mode=queue` buffers raw deliveries in `paused_events`; `mode=drop` discards them. Pausing blocks ingestion, outbound publication, meeting-note delivery, and tool actions immediately. Resume with `paused=false`; buffered deliveries replay idempotently through event dedupe. `GET` the same path lists switches and queued counts; tenant status summarizes them.

## Revocation and deletion
`POST /v1/tenants/{tenant_id}/admin/revocations` accepts `kind=user` or `kind=connector`. A revoked user gets `revoked_at`, loses principals and claims, and is denied `/me`, queries, and task submission. A revoked connector becomes `revoked`; its documents, edges, summaries, event log/outbox/dedupe rows, meeting data, and Qdrant points are purged. `DELETE /v1/tenants/{tenant_id}/admin/events/{event_id}` tombstones one event, purges the same stores, and prevents re-projection. Both paths are audited.

## Reconciliation
`cue.reconcile.jobs.due_connections` selects active connectors with no completed run in six hours. `run_due`/`reconcile` compare provider event IDs with the log, report missing, out-of-order, and extra events, and call the connector backfill callback for gaps. Normal event dedupe makes retries idempotent. Runs and drift land in `reconciliation_runs` and tenant status.

## Evals
`pytest -q tests/test_phase8.py` runs the fixed fake-model suite: grounded and cited answers, zero ACL leaks, proactive idempotency, quiet-hour deferral, kill-switch queue and replay, revocation/deletion, reconciliation idempotency, audit scoping, tenant isolation, and an end-to-end pilot path. Full suite: `pytest -q`.

## Unverified live items
Live vendor backfill, Pub/Sub/GCS delivery, Cloud Tasks scheduling, Firebase token exchange, Recall webhooks/audio, real embeddings, and the web UI were not exercised; local fakes and Postgres/Qdrant cover the backend paths. Audit retention, Cloud Armor, and production alerting remain rollout work.
