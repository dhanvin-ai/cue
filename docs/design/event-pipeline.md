# Event pipeline: canonical ingestion and replay

This implements the PDF's Pub/Sub → GCS raw archive → normalized event → entity resolution → fan-out path. Phase 4 adds Gmail, Calendar, Slack, Linear, and Recall to the original GitHub path. The fan-out topic is the handoff to graph, vector, structured and summarizer consumers in the next memory phase; those stores are not yet populated.

## Deploy

1. Apply migrations using `MIGRATION_DATABASE_URL`, `CUE_APP_DB_PASSWORD`, and `CUE_INGEST_DB_PASSWORD`: `python scripts/migrate.py`. Run `python scripts/ensure_partitions.py` on deploy and at least monthly. It creates monthly partitions 12 months back and two months ahead, each hash-partitioned by tenant. For a 36-month import, run `python scripts/ensure_partitions.py --months-back 36` **before** importing. The default partition catches dates outside the prepared range; create new monthly partitions before events land there.
2. Create the Pub/Sub raw-events topic and pull subscription `RAW_EVENTS_SUBSCRIPTION`, a canonical-events topic, and a raw GCS bucket. Configure a dead-letter topic and finite delivery attempts on the raw subscription so malformed or unlinked events can be inspected instead of retried forever. Restrict raw topic publishers to the webhook API and trusted backfill job. Restrict canonical topic publishers to the outbox worker.
3. Run `scripts/process_raw.py` and `scripts/publish_outbox.py` as separate continuously running GCP workers with CPU allocated while idle, for example GKE deployments. Both use `INGEST_DATABASE_URL` (`cue_ingest` role). The ingest worker needs Pub/Sub Subscriber on the raw subscription and GCS object creation on the raw bucket. The outbox worker needs Pub/Sub Publisher on the canonical topic. Give neither worker the migration credential. Supply `RAW_EVENTS_SUBSCRIPTION`, `RAW_GCS_BUCKET`, and `CANONICAL_EVENTS_TOPIC` through service configuration; store production DB credentials in Secret Manager.
4. Bind the installation with `scripts/connect_github.py` after verifying its tenant. The binding also writes a narrow installation-to-tenant map for the ingest role. Existing bindings are copied into that map by migration 003.

The raw worker acknowledges a message only after the GCS write and Postgres transaction commit. It rejects a backfill tenant/connection mismatch and resolves webhooks from their verified installation binding. A stable event ID deduplicates retries. Event and pending outbox rows commit together. The outbox publisher marks a row sent only after Pub/Sub confirms publication. A crash between publication and marking can publish a duplicate; consumers must deduplicate on `(tenant_id, event_id)`.

Entity aliases map vendor identities and objects to canonical UUIDs. Cross-vendor person/project merging still needs verified identity evidence; this phase does not guess that two accounts are the same person. Source ACLs are retained in each canonical payload for permission-aware consumers.

## Replay and operations

Use the admin credential to requeue a bounded period without changing the immutable event log:

```sh
python scripts/replay_events.py TENANT_UUID 2026-10-01T00:00:00+00:00 2026-11-01T00:00:00+00:00
```

The outbox worker will republish those events. Keep GCS raw objects for the same retention period as the event log, and protect the bucket with tenant-appropriate access controls and encryption. Monitor raw dead-letter backlog, outbox age, partition creation, and worker failures. The default partition is a fallback, not a substitute for monthly partition maintenance. Backfill remains a 365-day default; six-hour reconciliation, oversized webhook handling, deletion/retention automation, and downstream memory-store consumers remain follow-up work.
