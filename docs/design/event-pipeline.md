# Event pipeline

Every vendor record follows one path:

```
webhook / backfill → raw Pub/Sub topic → process_raw → GCS raw archive
                                                     → canonical event log + outbox (one transaction)
outbox → publish_outbox → canonical Pub/Sub topic → memory worker
```

## Guarantees

- **At-least-once delivery, exactly-once effect.** The raw worker acknowledges a message only after
  the GCS write and the Postgres transaction both commit. A stable event ID deduplicates retries.
- **Transactional outbox.** The event row and its pending outbox row commit together. The publisher
  marks a row sent only after Pub/Sub confirms it. A crash between those two steps can publish a
  duplicate, so consumers deduplicate on `(tenant_id, event_id)`.
- **Tenant resolution.** Webhooks resolve their tenant from the verified installation binding.
  Backfill messages must match their stated tenant and connection, or they are rejected.
- **Immutable log.** Events land in a monthly partitioned table, hash-partitioned by tenant. Entity
  aliases map vendor identities to canonical UUIDs. Two accounts are merged into one person only
  with verified identity evidence.
- **ACLs travel with the event.** Each canonical payload keeps its source ACL for the stores
  downstream.

## Deploying

1. Run the migrations: `python scripts/migrate.py`. This needs `MIGRATION_DATABASE_URL`,
   `CUE_APP_DB_PASSWORD` and `CUE_INGEST_DB_PASSWORD`.
2. Run `python scripts/ensure_partitions.py` on deploy and at least monthly. It prepares 12 months
   back and 2 ahead. Before a longer import, run it with `--months-back 36`.
3. Create the raw and canonical topics, the raw pull subscription, and the raw GCS bucket. Give the
   raw subscription a dead-letter topic and a finite number of delivery attempts.
4. Restrict publishers: only the API and the backfill job may publish raw events, and only the
   outbox worker may publish canonical events.
5. Run `scripts/process_raw.py` and `scripts/publish_outbox.py` as always-on workers using the
   `cue_ingest` role (`INGEST_DATABASE_URL`). Neither worker gets the migration credential.

## Replay

Requeue a time range without touching the immutable log:

```sh
python scripts/replay_events.py TENANT 2026-10-01T00:00:00+00:00 2026-11-01T00:00:00+00:00
```

The outbox worker republishes those events, and memory projection is idempotent.

Keep GCS raw objects for as long as the event log. The default partition is a safety net, not a
substitute for creating each month's partition.
