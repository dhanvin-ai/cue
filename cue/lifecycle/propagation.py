"""Deletion and access revocation propagated to every derived store."""

import os
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from cue.runtime import store


def _tenant(database: psycopg.Connection, tenant_id: UUID) -> None:
    database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))


def _index(index):
    if index is not None:
        return index
    if os.getenv("QDRANT_URL"):
        from cue.memory.vector import QdrantIndex
        return QdrantIndex()
    return None


def _meeting_ref(event_id: str) -> tuple[UUID, str, int | None] | None:
    parts = event_id.split(":")
    if len(parts) < 3 or parts[0] != "meeting":
        return None
    try:
        meeting_id = UUID(parts[1])
    except ValueError:
        return None
    if len(parts) >= 4 and parts[2] == "segment":
        try:
            return meeting_id, "segment", int(parts[3])
        except ValueError:
            return meeting_id, "segment", None
    if parts[2] == "notes":
        return meeting_id, "notes", None
    return None


def delete_event(database: psycopg.Connection, tenant_id: UUID, event_id: str, *,
                 requested_by: str, reason: str, index=None) -> dict:
    """Tombstone an event and remove it from the log, graph, summaries, notes, and vectors."""
    _tenant(database, tenant_id)
    original = database.execute(
        "SELECT source FROM event_log WHERE tenant_id = %s AND event_id = %s",
        (tenant_id, event_id),
    ).fetchone()
    source = original[0] if original else None
    database.execute(
        "INSERT INTO deletion_tombstones (tenant_id, id, event_id, source, reason, requested_by) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (tenant_id, uuid4(), event_id, source, reason, requested_by),
    )
    summary_ids = [row[0] for row in database.execute(
        "SELECT DISTINCT summary_id FROM memory_summary_sources "
        "WHERE tenant_id = %s AND event_id = %s", (tenant_id, event_id),
    ).fetchall()]
    if summary_ids:
        database.execute(
            "DELETE FROM memory_summaries WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, summary_ids),
        )
    database.execute(
        "DELETE FROM memory_summary_sources WHERE tenant_id = %s AND event_id = %s",
        (tenant_id, event_id),
    )
    database.execute("DELETE FROM memory_edges WHERE tenant_id = %s AND event_id = %s",
                     (tenant_id, event_id))
    deleted_docs = database.execute(
        "DELETE FROM memory_documents WHERE tenant_id = %s AND event_id = %s",
        (tenant_id, event_id),
    ).rowcount
    meeting = _meeting_ref(event_id)
    if meeting:
        meeting_id, kind, position = meeting
        if kind == "segment":
            if position is not None:
                database.execute(
                    "DELETE FROM meeting_note_sources WHERE tenant_id = %s AND meeting_id = %s "
                    "AND position = %s", (tenant_id, meeting_id, position),
                )
                database.execute(
                    "DELETE FROM meeting_transcript_segments WHERE tenant_id = %s "
                    "AND meeting_id = %s AND position = %s",
                    (tenant_id, meeting_id, position),
                )
        else:
            database.execute(
                "DELETE FROM meeting_notes WHERE tenant_id = %s AND meeting_id = %s",
                (tenant_id, meeting_id),
            )
    database.execute("DELETE FROM event_outbox WHERE tenant_id = %s AND event_id = %s",
                     (tenant_id, event_id))
    database.execute("DELETE FROM event_dedupe WHERE tenant_id = %s AND event_id = %s",
                     (tenant_id, event_id))
    deleted_log = database.execute(
        "DELETE FROM event_log WHERE tenant_id = %s AND event_id = %s", (tenant_id, event_id)
    ).rowcount
    store.audit(database, tenant_id, actor=requested_by, action="deletion",
                decision="deleted", detail={"event_id": event_id, "source": source,
                                            "reason": reason})
    result = {"event_id": event_id, "source": source, "documents": deleted_docs,
              "event_log": deleted_log, "summaries": len(summary_ids)}
    vector_index = _index(index)
    if vector_index is not None:
        vector_index.delete_event(tenant_id, event_id)
        result["vector"] = True
    return result


def revoke_user(database: psycopg.Connection, tenant_id: UUID, uid: str, *,
                requested_by: str, reason: str) -> dict:
    _tenant(database, tenant_id)
    if store.membership(database, tenant_id, uid) is None:
        raise LookupError("User is not an active tenant member")
    database.execute("UPDATE users SET revoked_at = now() WHERE tenant_id = %s AND firebase_uid = %s",
                     (tenant_id, uid))
    database.execute("DELETE FROM user_principals WHERE tenant_id = %s AND firebase_uid = %s",
                     (tenant_id, uid))
    database.execute("DELETE FROM identity_claims WHERE tenant_id = %s AND firebase_uid = %s",
                     (tenant_id, uid))
    database.execute(
        "UPDATE meeting_speaker_map SET firebase_uid = NULL, label = 'unknown' "
        "WHERE tenant_id = %s AND firebase_uid = %s", (tenant_id, uid),
    )
    database.execute(
        "UPDATE agent_tasks SET status = 'cancelled', answer = 'Requester access revoked', "
        "updated_at = now() WHERE tenant_id = %s AND requester_uid = %s "
        "AND status IN ('queued', 'running', 'awaiting_approval')", (tenant_id, uid),
    )
    database.execute(
        "INSERT INTO access_revocations (tenant_id, id, kind, subject, reason, revoked_by) "
        "VALUES (%s, %s, 'user', %s, %s, %s)",
        (tenant_id, uuid4(), uid, reason, requested_by),
    )
    store.audit(database, tenant_id, actor=requested_by, action="revocation",
                decision="revoked", detail={"kind": "user", "subject": uid, "reason": reason})
    return {"kind": "user", "subject": uid, "revoked": True}


def purge_source(database: psycopg.Connection, tenant_id: UUID, source: str, *,
                 requested_by: str, reason: str, index=None) -> dict:
    _tenant(database, tenant_id)
    summary_ids = [row[0] for row in database.execute(
        "SELECT DISTINCT source.summary_id FROM memory_summary_sources AS source "
        "JOIN memory_documents AS doc ON doc.tenant_id = source.tenant_id "
        "AND doc.event_id = source.event_id WHERE doc.tenant_id = %s AND doc.source = %s",
        (tenant_id, source),
    ).fetchall()]
    if summary_ids:
        database.execute(
            "DELETE FROM memory_summaries WHERE tenant_id = %s AND id = ANY(%s)",
            (tenant_id, summary_ids),
        )
    database.execute(
        "DELETE FROM memory_summary_sources WHERE tenant_id = %s AND event_id IN "
        "(SELECT event_id FROM memory_documents WHERE tenant_id = %s AND source = %s)",
        (tenant_id, tenant_id, source),
    )
    database.execute(
        "DELETE FROM memory_edges WHERE tenant_id = %s AND event_id IN "
        "(SELECT event_id FROM memory_documents WHERE tenant_id = %s AND source = %s)",
        (tenant_id, tenant_id, source),
    )
    documents = database.execute(
        "DELETE FROM memory_documents WHERE tenant_id = %s AND source = %s",
        (tenant_id, source),
    ).rowcount
    if source == "recall":
        database.execute("DELETE FROM meeting_notes WHERE tenant_id = %s", (tenant_id,))
        database.execute("DELETE FROM meeting_sessions WHERE tenant_id = %s", (tenant_id,))
    log_rows = database.execute(
        "DELETE FROM event_log WHERE tenant_id = %s AND source = %s RETURNING event_id",
        (tenant_id, source),
    ).fetchall()
    event_ids = [row[0] for row in log_rows]
    if event_ids:
        database.execute(
            "DELETE FROM event_outbox WHERE tenant_id = %s AND event_id = ANY(%s)",
            (tenant_id, event_ids),
        )
        database.execute(
            "DELETE FROM event_dedupe WHERE tenant_id = %s AND event_id = ANY(%s)",
            (tenant_id, event_ids),
        )
    database.execute(
        "INSERT INTO deletion_tombstones (tenant_id, id, source, reason, requested_by) "
        "VALUES (%s, %s, %s, %s, %s)",
        (tenant_id, uuid4(), source, reason, requested_by),
    )
    store.audit(database, tenant_id, actor=requested_by, action="deletion",
                decision="revoked", detail={"source": source, "documents": documents,
                                            "reason": reason})
    vector_index = _index(index)
    if vector_index is not None:
        vector_index.delete_source(tenant_id, source)
    return {"source": source, "documents": documents, "events": len(event_ids),
            "summaries": len(summary_ids)}


def revoke_connector(database: psycopg.Connection, tenant_id: UUID, connection_id: UUID, *,
                     requested_by: str, reason: str, index=None) -> dict:
    _tenant(database, tenant_id)
    row = database.execute(
        "SELECT provider FROM connector_connections WHERE tenant_id = %s AND id = %s",
        (tenant_id, connection_id),
    ).fetchone()
    if row is None:
        raise LookupError("Connector not found")
    provider = row[0]
    database.execute(
        "UPDATE connector_connections SET status = 'revoked' WHERE tenant_id = %s AND id = %s",
        (tenant_id, connection_id),
    )
    database.execute(
        "INSERT INTO access_revocations (tenant_id, id, kind, subject, reason, revoked_by) "
        "VALUES (%s, %s, 'connector', %s, %s, %s)",
        (tenant_id, uuid4(), str(connection_id), reason, requested_by),
    )
    purged = purge_source(database, tenant_id, provider, requested_by=requested_by,
                          reason=reason, index=index)
    store.audit(database, tenant_id, actor=requested_by, action="revocation",
                decision="revoked", detail={"kind": "connector", "subject": str(connection_id),
                                            "provider": provider, "reason": reason})
    return {"kind": "connector", "subject": str(connection_id), "provider": provider,
            "revoked": True, **purged}
