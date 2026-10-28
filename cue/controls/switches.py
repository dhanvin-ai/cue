"""Tenant and connector kill switches, including the paused-ingest buffer."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from cue.runtime import store

TENANT = "tenant"
CONNECTOR = "connector"


class Paused(RuntimeError):
    def __init__(self, scope: str, subject: str, mode: str):
        self.scope = scope
        self.subject = subject
        self.mode = mode
        super().__init__(f"{scope} {subject} is paused ({mode})")


def _tenant(database: psycopg.Connection, tenant_id: UUID) -> None:
    database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


def set_switch(database: psycopg.Connection, tenant_id: UUID, *, scope: str, subject: str,
               paused: bool, actor: str, mode: str = "queue", reason: str | None = None) -> dict:
    if scope not in {TENANT, CONNECTOR} or mode not in {"queue", "drop"}:
        raise ValueError("Unsupported kill switch")
    _tenant(database, tenant_id)
    database.execute(
        "INSERT INTO kill_switches (tenant_id, scope, subject, paused, mode, reason, changed_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, scope, subject) DO UPDATE SET paused = EXCLUDED.paused, "
        "mode = EXCLUDED.mode, reason = EXCLUDED.reason, changed_by = EXCLUDED.changed_by, "
        "changed_at = now()",
        (tenant_id, scope, subject, paused, mode, reason, actor),
    )
    store.audit(database, tenant_id, actor=actor, action="control",
                decision="resumed" if not paused else "paused",
                detail={"scope": scope, "subject": subject, "mode": mode, "reason": reason})
    return switch(database, tenant_id, scope, subject)


def switch(database: psycopg.Connection, tenant_id: UUID, scope: str,
           subject: str) -> dict | None:
    _tenant(database, tenant_id)
    row = database.execute(
        "SELECT scope, subject, paused, mode, reason, changed_by, changed_at "
        "FROM kill_switches WHERE tenant_id = %s AND scope = %s AND subject = %s",
        (tenant_id, scope, subject),
    ).fetchone()
    if row is None:
        return None
    return dict(zip(("scope", "subject", "paused", "mode", "reason", "changed_by",
                     "changed_at"), row))


def tenant_paused(database: psycopg.Connection, tenant_id: UUID) -> dict | None:
    row = switch(database, tenant_id, TENANT, "*")
    return row if row and row["paused"] else None


def connector_switch(database: psycopg.Connection, tenant_id: UUID,
                     connection_id: UUID) -> dict | None:
    return switch(database, tenant_id, CONNECTOR, str(connection_id))


def paused_provider(database: psycopg.Connection, tenant_id: UUID, provider: str) -> dict | None:
    _tenant(database, tenant_id)
    row = database.execute(
        "SELECT c.id, c.status, k.paused, k.mode FROM connector_connections AS c "
        "LEFT JOIN kill_switches AS k ON k.tenant_id = c.tenant_id "
        "AND k.scope = 'connector' AND k.subject = c.id::text "
        "WHERE c.tenant_id = %s AND c.provider = %s "
        "AND (c.status <> 'active' OR k.paused) LIMIT 1",
        (tenant_id, provider),
    ).fetchone()
    if row is None:
        return None
    return {"subject": str(row[0]), "mode": row[3] if row[2] else row[1]}


def pause_reason(database: psycopg.Connection, tenant_id: UUID,
                 provider: str | None = None) -> Paused | None:
    tenant = tenant_paused(database, tenant_id)
    if tenant:
        return Paused(TENANT, "*", tenant["mode"])
    if provider:
        connector = paused_provider(database, tenant_id, provider)
        if connector:
            return Paused(CONNECTOR, connector["subject"], connector["mode"])
    return None


def assert_active(database: psycopg.Connection, tenant_id: UUID,
                  provider: str | None = None) -> None:
    paused = pause_reason(database, tenant_id, provider)
    if paused:
        raise paused


def ingestion_gate(database: psycopg.Connection, tenant_id: UUID, connection_id: UUID,
                   source: str, attributes: dict, payload: bytes) -> str:
    """Return active, queued, dropped, or blocked before an event reaches the log."""
    _tenant(database, tenant_id)
    status = database.execute(
        "SELECT status FROM connector_connections WHERE tenant_id = %s AND id = %s",
        (tenant_id, connection_id),
    ).fetchone()
    if status is None or status[0] != "active":
        return "blocked"
    for scope, subject in ((TENANT, "*"), (CONNECTOR, str(connection_id))):
        row = database.execute(
            "SELECT paused, mode FROM kill_switches WHERE tenant_id = %s AND scope = %s "
            "AND subject = %s", (tenant_id, scope, subject),
        ).fetchone()
        if row is None or not row[0]:
            continue
        if row[1] == "drop":
            return "dropped"
        database.execute(
            "INSERT INTO paused_events (tenant_id, source, delivery_id, attributes, payload) "
            "VALUES (%s, %s, %s, %s, %s)",
            (tenant_id, source, attributes.get("delivery_id"), Jsonb(attributes), payload),
        )
        return "queued"
    return "active"


def pending_paused(database: psycopg.Connection, tenant_id: UUID, limit: int = 100) -> list[dict]:
    _tenant(database, tenant_id)
    rows = database.execute(
        "SELECT id, source, attributes, payload, received_at FROM paused_events "
        "WHERE tenant_id = %s AND replayed_at IS NULL ORDER BY id LIMIT %s",
        (tenant_id, limit),
    ).fetchall()
    return [{"id": row[0], "source": row[1], "attributes": row[2],
             "payload": bytes(row[3]), "received_at": row[4]} for row in rows]


def replay_paused(database: psycopg.Connection, tenant_id: UUID, ingest, *,
                  limit: int = 100) -> int:
    """Replay buffered deliveries after a resume. Idempotent through event dedupe."""
    _tenant(database, tenant_id)
    replayed = 0
    for item in pending_paused(database, tenant_id, limit):
        try:
            ingest(item["payload"], item["attributes"])
        except Exception:
            continue
        database.execute(
            "UPDATE paused_events SET replayed_at = now() WHERE tenant_id = %s AND id = %s",
            (tenant_id, item["id"]),
        )
        replayed += 1
    return replayed


def resume(database: psycopg.Connection, tenant_id: UUID, *, scope: str, subject: str,
           actor: str, ingest=None) -> dict:
    set_switch(database, tenant_id, scope=scope, subject=subject, paused=False, actor=actor)
    # The replay connection must see the un-paused switch.
    database.commit()
    return {"paused": False, "replayed": replay_paused(database, tenant_id, ingest)
            if ingest else 0}


def drop_paused(database: psycopg.Connection, tenant_id: UUID, *, actor: str,
                reason: str = "dropped while paused") -> int:
    _tenant(database, tenant_id)
    deleted = database.execute(
        "DELETE FROM paused_events WHERE tenant_id = %s AND replayed_at IS NULL", (tenant_id,)
    ).rowcount
    store.audit(database, tenant_id, actor=actor, action="control", decision="dropped",
                detail={"count": deleted, "reason": reason})
    return deleted


def status(database: psycopg.Connection, tenant_id: UUID) -> dict:
    _tenant(database, tenant_id)
    rows = database.execute(
        "SELECT scope, subject, paused, mode, reason, changed_by, changed_at "
        "FROM kill_switches WHERE tenant_id = %s ORDER BY scope, subject", (tenant_id,),
    ).fetchall()
    queued = database.execute(
        "SELECT count(*) FROM paused_events WHERE tenant_id = %s AND replayed_at IS NULL",
        (tenant_id,),
    ).fetchone()[0]
    keys = ("scope", "subject", "paused", "mode", "reason", "changed_by", "changed_at")
    return {"switches": [dict(zip(keys, row)) for row in rows], "paused_events": queued}
