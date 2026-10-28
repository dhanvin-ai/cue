"""Per-connector reconciliation: compare provider state, backfill gaps, report drift."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import psycopg

from cue.runtime import store

INTERVAL = timedelta(hours=6)


def _tenant(database: psycopg.Connection, tenant_id: UUID) -> None:
    database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


def _when(event: dict) -> datetime | None:
    value = event.get("occurred_at")
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def reconcile(tenant_id: UUID, connection_id: UUID, provider: str,
              provider_events: list[dict], backfill, *, database_url: str | None = None,
              now: datetime | None = None) -> dict:
    """Backfill events missing from the log. Re-running with the same provider state is a no-op."""
    moment = now or datetime.now(timezone.utc)
    with store.tenant_connection(tenant_id, database_url) as database:
        row = database.execute(
            "SELECT provider FROM connector_connections WHERE tenant_id = %s AND id = %s "
            "AND status = 'active'", (tenant_id, connection_id),
        ).fetchone()
        if row is None or row[0] != provider:
            raise PermissionError("Connector is not active for this tenant")
        run_id = uuid4()
        database.execute(
            "INSERT INTO reconciliation_runs (tenant_id, id, connection_id, provider, status, "
            "provider_count) VALUES (%s, %s, %s, %s, 'running', %s)",
            (tenant_id, run_id, connection_id, provider, len(provider_events)),
        )
    try:
        with store.tenant_connection(tenant_id, database_url) as database:
            rows = database.execute(
                "SELECT event_id, occurred_at FROM event_log WHERE tenant_id = %s AND source = %s",
                (tenant_id, provider),
            ).fetchall()
        log = {event_id: occurred_at for event_id, occurred_at in rows}
        provider_ids = {event.get("event_id") for event in provider_events if event.get("event_id")}
        missing = [event for event in provider_events
                   if event.get("event_id") and event["event_id"] not in log]
        latest = max(log.values(), default=None)
        out_of_order = [event["event_id"] for event in missing
                        if latest is not None and _when(event) is not None
                        and _when(event) < latest]
        backfilled = 0
        for event in missing:
            backfill(tenant_id, event)
            backfilled += 1
        drift = {"missing": [event["event_id"] for event in missing],
                 "out_of_order": out_of_order,
                 "extra_in_log": sorted(set(log) - provider_ids),
                 "provider_count": len(provider_events),
                 "log_count": len(log) + backfilled}
        with store.tenant_connection(tenant_id, database_url) as database:
            database.execute(
                "UPDATE reconciliation_runs SET status = 'completed', event_count = %s, "
                "missing_count = %s, backfilled_count = %s, drift = %s, finished_at = %s "
                "WHERE tenant_id = %s AND id = %s",
                (len(log) + backfilled, len(missing), backfilled, json.dumps(drift), moment,
                 tenant_id, run_id),
            )
            store.audit(database, tenant_id, actor="cue", action="reconciliation",
                        decision="completed", detail={"provider": provider,
                                                      "backfilled": backfilled, "drift": drift})
        return {"run_id": str(run_id), "provider": provider, "missing": len(missing),
                "backfilled": backfilled, "out_of_order": out_of_order, "drift": drift}
    except Exception as exc:
        with store.tenant_connection(tenant_id, database_url) as database:
            database.execute(
                "UPDATE reconciliation_runs SET status = 'failed', error = %s, finished_at = %s "
                "WHERE tenant_id = %s AND id = %s", (str(exc), moment, tenant_id, run_id),
            )
        raise


def due_connections(database: psycopg.Connection, tenant_id: UUID,
                    now: datetime | None = None) -> list[dict]:
    moment = now or datetime.now(timezone.utc)
    _tenant(database, tenant_id)
    rows = database.execute(
        "SELECT c.id, c.provider FROM connector_connections AS c "
        "WHERE c.tenant_id = %s AND c.status = 'active' AND NOT EXISTS ("
        "SELECT 1 FROM reconciliation_runs AS r WHERE r.tenant_id = c.tenant_id "
        "AND r.connection_id = c.id AND r.status = 'completed' AND r.finished_at > %s) "
        "ORDER BY c.provider", (tenant_id, moment - INTERVAL),
    ).fetchall()
    return [{"connection_id": row[0], "provider": row[1]} for row in rows]


def run_due(tenant_id: UUID, provider_events: dict[UUID, list[dict]], backfill, *,
            database_url: str | None = None, now: datetime | None = None) -> list[dict]:
    """Run every connector that has not completed in the last six hours."""
    moment = now or datetime.now(timezone.utc)
    results = []
    with store.tenant_connection(tenant_id, database_url) as database:
        due = due_connections(database, tenant_id, moment)
    for item in due:
        events = provider_events.get(item["connection_id"], [])
        results.append(reconcile(tenant_id, item["connection_id"], item["provider"], events,
                                 backfill, database_url=database_url, now=moment))
    return results
