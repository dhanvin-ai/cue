# Operations: proactive work and admin controls

Proactive rules, quiet hours, kill switches, revocation, reconciliation and audit export. They all
run through the same runtime, risk tiers and approval tables as user requests.

## Running the scheduler

```sh
python scripts/run_tasks.py --tenant TENANT   # run every minute
```

Each tick advances scheduled tasks, dispatches proactive rules, and runs work through policy and
approvals.

Health endpoints:

| Endpoint | Who can call it |
|---|---|
| `/healthz` | anyone |
| `/readyz` | anyone |
| `GET /v1/tenants/{t}/status` | members |
| `GET /v1/tenants/{t}/admin/access-report` | admins |

## Proactive rules

Create rules with `POST /v1/tenants/{t}/proactive/rules`:

| Kind | Default schedule |
|---|---|
| `daily_digest` | 09:30 |
| `weekly_digest` | Friday 16:00 |
| `reminder` | per rule |
| `stale_pr` | hourly |
| `overdue_action` | hourly |

Each rule has a time zone and per-person mutes.

## Quiet hours

`PUT /v1/tenants/{t}/admin/quiet-hours` sets a tenant-wide or per-user window in an IANA time
zone. Windows may cross midnight, and a user's window overrides the tenant's. A run that falls
inside the window is stored as `deferred` with a `deliver_after` time and released by a later
tick. Urgent items wait too.

## Kill switches

`PUT /v1/tenants/{t}/admin/kill-switches/{scope}/{subject}` pauses a whole tenant (`scope=tenant`,
subject `*`) or one connection (`scope=connector`, subject is the connection UUID).

- `mode=queue` buffers raw deliveries in `paused_events`. `mode=drop` discards them.
- Pausing immediately stops ingestion, outbound publishing, meeting-note delivery and tool actions.
- Resume with `paused=false`. Buffered deliveries replay idempotently through event deduplication.
- `GET` on the same path lists switches and how many deliveries each has queued.

## Revocation and deletion

`POST /v1/tenants/{t}/admin/revocations` takes `kind=user` or `kind=connector`.

- **Revoked user:** loses principals and claims, and is refused `/me`, queries and task submission.
- **Revoked connector:** its documents, graph edges, summaries, event-log rows, meeting data and
  Qdrant points are purged.

`DELETE /v1/tenants/{t}/admin/events/{event_id}` tombstones one event, purges it from the same
stores, and blocks it from being projected again. Every one of these actions is audited.

## Reconciliation

`cue.reconcile.jobs.due_connections` selects active connectors that have no completed run in the
last six hours. For each one, `reconcile` compares the provider's event IDs with the event log. It
reports missing, out-of-order and extra events, and backfills the gaps. Runs and drift are recorded
in `reconciliation_runs` and shown in tenant status.

## Audit export

`GET /v1/tenants/{t}/admin/audit/export?since=&until=&format=json|csv` exports every ingress,
policy decision, tool run, approval, retry and response from `agent_audit`.

## Production checklist

- Configure Cloud Scheduler jobs for `run_tasks.py`, `renew_watches.py`, reconciliation and
  `build_summaries.py`.
- Add dead-letter topics on the raw, Gmail push and sync-trigger subscriptions.
- Set audit retention, Cloud Armor and alerting. The useful signals are dead-letter backlog,
  outbox age, partition creation and worker failures.
