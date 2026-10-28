"""Idempotent Postgres graph projection and Qdrant fan-out from canonical events."""

import json
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from cue.memory.vector import QdrantIndex, QwenEmbedder


def _relations(event: dict) -> list[tuple[str, str, str, str | None]]:
    objects = event.get("objects") or []
    if not objects:
        return []
    primary = objects[0]
    relations = [(actor, "worked_on", primary, None) for actor in event.get("actors") or []]
    relations.extend((primary, "part_of", context, None) for context in objects[1:])
    facts = event.get("facts") or {}
    state = facts.get("state") or event["type"].rsplit(".", 1)[-1]
    if state in {"open", "opened", "reopened", "closed", "merged", "deleted", "cancelled", "confirmed"}:
        relations.append((primary, "state", f"state:{state}", state))
    if "owner_id" in facts:
        relations.append((primary, "owned_by", facts["owner_id"] or "person:unassigned",
                          facts.get("owner_label")))
    return relations


def _canonical_person(database: psycopg.Connection, tenant_id: UUID, value: str) -> str:
    if not value.startswith("person:"):
        return value
    mapped = database.execute(
        "SELECT to_id FROM identity_entity_map WHERE tenant_id = %s AND from_id = %s",
        (tenant_id, UUID(value.removeprefix("person:"))),
    ).fetchone()
    return f"person:{mapped[0]}" if mapped else value


def project_event(data: bytes, attributes: dict, database_url: str,
                  index: QdrantIndex | None = None, embedder: QwenEmbedder | None = None) -> bool:
    event = json.loads(data)
    tenant_id = UUID(attributes["tenant_id"])
    if event["tenant_id"] != str(tenant_id) or event["event_id"] != attributes["event_id"]:
        raise ValueError("Canonical message identity does not match its attributes")
    acl = event["acl"]
    if acl["visibility"] not in {"public", "restricted"}:
        raise ValueError("Unsupported ACL visibility")
    occurred_at = datetime.fromisoformat(event["occurred_at"])
    principals = sorted(set(acl["principals"]))
    with psycopg.connect(database_url, autocommit=True) as database:
        with database.transaction():
            database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            tombstone = database.execute(
                "SELECT 1 FROM deletion_tombstones WHERE tenant_id = %s "
                "AND (event_id = %s OR source = %s) LIMIT 1",
                (tenant_id, event["event_id"], event["source"]),
            ).fetchone()
            if tombstone is not None:
                return False
            original = database.execute(
                "SELECT payload FROM event_log WHERE tenant_id = %s AND event_id = %s",
                (tenant_id, event["event_id"]),
            ).fetchone()
            if original is None or original[0] != event:
                raise ValueError("Canonical message is absent from the event log")
            projected = {**event,
                         "actors": [_canonical_person(database, tenant_id, actor) for actor in event["actors"]],
                         "objects": [_canonical_person(database, tenant_id, item) for item in event["objects"]],
                         "facts": dict(event.get("facts") or {})}
            if projected["facts"].get("owner_id"):
                projected["facts"]["owner_id"] = _canonical_person(
                    database, tenant_id, projected["facts"]["owner_id"]
                )
            database.execute(
                "INSERT INTO memory_documents (tenant_id, event_id, source, type, occurred_at, actors, objects, "
                "facts, text, visibility, principals, raw_ref, source_url) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (tenant_id, event["event_id"], event["source"], event["type"], occurred_at,
                 projected["actors"], projected["objects"],
                 Jsonb(projected["facts"]), event["text"], acl["visibility"], principals,
                 event["raw_ref"], event.get("source_url")),
            )
            for source, predicate, target, label in _relations(projected):
                database.execute(
                    "INSERT INTO memory_edges (tenant_id, event_id, source_entity, predicate, target, "
                    "target_label, valid_from, visibility, principals) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT DO NOTHING",
                    (tenant_id, event["event_id"], source, predicate, target, label, occurred_at,
                     acl["visibility"], principals),
                )
                if predicate in {"state", "owned_by"}:
                    database.execute(
                        "WITH ordered AS (SELECT event_id, source_entity, predicate, target, "
                        "lead(valid_from) OVER (ORDER BY valid_from, event_id) AS next_time "
                        "FROM memory_edges WHERE tenant_id = %s AND source_entity = %s AND predicate = %s) "
                        "UPDATE memory_edges AS edge SET valid_to = ordered.next_time FROM ordered "
                        "WHERE edge.tenant_id = %s AND edge.event_id = ordered.event_id "
                        "AND edge.source_entity = ordered.source_entity AND edge.predicate = ordered.predicate "
                        "AND edge.target = ordered.target AND edge.valid_to IS DISTINCT FROM ordered.next_time",
                        (tenant_id, source, predicate, tenant_id),
                    )
            row = database.execute(
                "SELECT vector_indexed_at FROM memory_documents WHERE tenant_id = %s AND event_id = %s",
                (tenant_id, event["event_id"]),
            ).fetchone()
    if not event["text"].strip() or row[0] is not None:
        return False
    vector = (embedder or QwenEmbedder()).embed(event["text"])
    (index or QdrantIndex()).upsert(tenant_id, event, vector)
    with psycopg.connect(database_url) as database:
        database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        database.execute(
            "UPDATE memory_documents SET vector_indexed_at = now() "
            "WHERE tenant_id = %s AND event_id = %s AND vector_indexed_at IS NULL",
            (tenant_id, event["event_id"]),
        )
    return True
