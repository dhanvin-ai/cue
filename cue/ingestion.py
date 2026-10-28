"""Raw Pub/Sub delivery -> immutable GCS payload and canonical Postgres event."""

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID, NAMESPACE_URL, uuid4, uuid5

import psycopg
from google.api_core.exceptions import PreconditionFailed
from google.cloud import storage
from psycopg.types.json import Jsonb

from cue.connectors.base import AccessControl, CanonicalEvent
from cue.connectors.github import GitHubConnector
from cue.connectors.normalize_v1 import normalize as normalize_v1


def _source_url(raw: dict, source: str) -> str | None:
    if source == "github":
        item = next((raw[key] for key in ("issue", "pull_request", "comment", "review", "commit")
                     if isinstance(raw.get(key), dict)), {})
        if item.get("html_url"):
            return item["html_url"]
        repo = raw.get("repository") or {}
        base = repo.get("html_url")
        if base and item.get("number") and ("issue" in raw or "pull_request" in raw):
            path = "pull" if "pull_request" in raw else "issues"
            return f"{base}/{path}/{item['number']}"
    if source == "gmail":
        thread = (raw.get("message") or {}).get("threadId")
        return f"https://mail.google.com/mail/u/0/#all/{thread}" if thread else None
    if source == "calendar":
        return (raw.get("event") or {}).get("htmlLink")
    if source == "linear":
        return (raw.get("data") or {}).get("url")
    if source == "slack":
        item = raw.get("event") or {}
        channel, stamp = item.get("channel"), item.get("ts")
        return f"https://app.slack.com/archives/{channel}/p{stamp.replace('.', '')}" if channel and stamp else None
    return None


def _routing(database: psycopg.Connection, raw: dict, attributes: dict) -> tuple[UUID, UUID]:
    source = attributes.get("source")
    if source not in {"github", "gmail", "calendar", "slack", "linear", "recall"}:
        raise ValueError("Unsupported raw event source")
    if source != "github":
        if "connection_id" in attributes:
            row = database.execute(
                "SELECT tenant_id, connection_id FROM source_bindings "
                "WHERE provider = %s AND connection_id = %s",
                (source, UUID(attributes["connection_id"])),
            ).fetchone()
            if row is None or str(row[0]) != attributes.get("tenant_id"):
                raise ValueError("Backfill connection does not match tenant")
        else:
            external_id = attributes.get("external_id")
            row = database.execute(
                "SELECT tenant_id, connection_id FROM source_bindings "
                "WHERE provider = %s AND external_id = %s",
                (source, external_id),
            ).fetchone()
            if row is None:
                raise ValueError("Source identity is not linked to a tenant")
        return row[0], row[1]
    if "connection_id" in attributes:
        connection_id = UUID(attributes["connection_id"])
        row = database.execute(
            "SELECT tenant_id, connection_id FROM github_installation_map WHERE connection_id = %s",
            (connection_id,),
        ).fetchone()
        if row is None or str(row[0]) != attributes.get("tenant_id"):
            raise ValueError("Backfill connection does not match tenant")
    else:
        installation_id = raw.get("installation", {}).get("id")
        if not isinstance(installation_id, int) or str(installation_id) != attributes.get("installation_id"):
            raise ValueError("Webhook installation does not match delivery")
        row = database.execute(
            "SELECT tenant_id, connection_id FROM github_installation_map WHERE installation_id = %s",
            (installation_id,),
        ).fetchone()
        if row is None:
            raise ValueError("GitHub installation is not linked to a tenant")
    return row[0], row[1]


def _canonical(raw: dict, attributes: dict, tenant_id: UUID) -> CanonicalEvent:
    source = attributes["source"]
    if source != "github":
        event = normalize_v1(source, raw, tenant_id)
        if "connection_id" in attributes:
            if event.event_id != attributes.get("event_id"):
                raise ValueError("Backfill event ID does not match payload")
            return event
        delivery_id = attributes.get("delivery_id")
        if not delivery_id:
            raise ValueError("Webhook delivery ID is required")
        return replace(event, event_id=f"{source}:delivery:{delivery_id}")
    if "connection_id" in attributes:
        event = GitHubConnector().normalize(raw, tenant_id)
        if event.event_id != attributes.get("event_id"):
            raise ValueError("Backfill event ID does not match payload")
        return event
    delivery_id = attributes.get("delivery_id")
    if not delivery_id:
        raise ValueError("Webhook delivery ID is required")
    if attributes.get("event") == "installation":
        return CanonicalEvent(
            tenant_id=tenant_id,
            event_id=f"gh:delivery:{delivery_id}",
            source="github",
            type=f"installation.{raw.get('action', 'unknown')}",
            occurred_at=datetime.now(timezone.utc),
            actors=(),
            objects=(f"github:installation:{raw['installation']['id']}",),
            text="",
            acl=AccessControl("restricted", ("cue:admins",)),
        )
    if attributes.get("event") not in {
        "issues", "pull_request", "push", "issue_comment",
        "pull_request_review", "pull_request_review_comment",
    }:
        raise ValueError("Unsupported GitHub webhook event")
    return replace(
        GitHubConnector().normalize(raw, tenant_id),
        event_id=f"gh:delivery:{delivery_id}",
    )


def _resolve(database: psycopg.Connection, tenant_id: UUID, alias: str) -> str:
    kind = alias.split(":", 2)[1]
    kind = "person" if kind == "user" else kind
    database.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"{tenant_id}:{alias}",),
    )
    claim = database.execute(
        "SELECT firebase_uid FROM identity_claims WHERE tenant_id = %s AND alias = %s",
        (tenant_id, alias),
    ).fetchone()
    row = database.execute(
        "SELECT entity_id FROM entity_aliases WHERE tenant_id = %s AND alias = %s",
        (tenant_id, alias),
    ).fetchone()
    if claim and kind == "person":
        canonical_id = uuid5(NAMESPACE_URL, f"cue:{tenant_id}:person:{claim[0]}")
        database.execute(
            "INSERT INTO entities (tenant_id, id, kind) VALUES (%s, %s, 'person') ON CONFLICT DO NOTHING",
            (tenant_id, canonical_id),
        )
        if row and row[0] != canonical_id:
            database.execute(
                "INSERT INTO identity_entity_map (tenant_id, from_id, to_id) VALUES (%s, %s, %s) "
                "ON CONFLICT (tenant_id, from_id) DO UPDATE SET to_id = EXCLUDED.to_id",
                (tenant_id, row[0], canonical_id),
            )
            database.execute(
                "UPDATE entity_aliases SET entity_id = %s WHERE tenant_id = %s AND alias = %s",
                (canonical_id, tenant_id, alias),
            )
        elif not row:
            database.execute(
                "INSERT INTO entity_aliases (tenant_id, alias, entity_id) VALUES (%s, %s, %s)",
                (tenant_id, alias, canonical_id),
            )
        return f"person:{canonical_id}"
    if row:
        return f"{kind}:{row[0]}"
    entity_id = uuid4()
    database.execute(
        "INSERT INTO entities (tenant_id, id, kind) VALUES (%s, %s, %s)",
        (tenant_id, entity_id, kind),
    )
    database.execute(
        "INSERT INTO entity_aliases (tenant_id, alias, entity_id) VALUES (%s, %s, %s)",
        (tenant_id, alias, entity_id),
    )
    return f"{kind}:{entity_id}"


def process_raw(data: bytes, attributes: dict, database_url: str, storage_client=None) -> bool:
    """Return True for a new event, False for an already committed delivery."""
    raw = json.loads(data)
    if not isinstance(raw, dict):
        raise ValueError("Raw payload must be a JSON object")
    with psycopg.connect(database_url, autocommit=True) as database:
        tenant_id, _ = _routing(database, raw, attributes)
        event = _canonical(raw, attributes, tenant_id)
        bucket = os.environ["RAW_GCS_BUCKET"]
        key = f"raw/{tenant_id}/{attributes['source']}/{hashlib.sha256(data).hexdigest()}.json"
        client = storage_client or storage.Client()
        try:
            client.bucket(bucket).blob(key).upload_from_string(
                data, content_type="application/json", if_generation_match=0
            )
        except PreconditionFailed:
            pass  # A retry already stored these exact bytes at the content-addressed key.
        raw_ref = f"gs://{bucket}/{key}"
        with database.transaction():
            database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            inserted = database.execute(
                "INSERT INTO event_dedupe (tenant_id, event_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                (tenant_id, event.event_id),
            ).rowcount
            if not inserted:
                return False
            actors = [_resolve(database, tenant_id, alias) for alias in event.actors]
            objects = [_resolve(database, tenant_id, alias) for alias in event.objects]
            facts = dict(event.facts)
            if "owner_alias" in facts:
                owner_alias = facts.pop("owner_alias")
                facts["owner_id"] = _resolve(database, tenant_id, owner_alias) if owner_alias else None
            payload = {
                "tenant_id": str(tenant_id),
                "event_id": event.event_id,
                "source": event.source,
                "type": event.type,
                "occurred_at": event.occurred_at.isoformat(),
                "actors": actors,
                "objects": objects,
                "facts": facts,
                "text": event.text,
                "acl": {
                    "visibility": event.acl.visibility,
                    "principals": list(event.acl.principals),
                },
                "raw_ref": raw_ref,
                "source_url": _source_url(raw, attributes["source"]),
            }
            database.execute(
                "INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (tenant_id, event.event_id, event.occurred_at, event.source, event.type, Jsonb(payload)),
            )
            database.execute(
                "INSERT INTO event_outbox (tenant_id, event_id, payload) VALUES (%s, %s, %s)",
                (tenant_id, event.event_id, Jsonb(payload)),
            )
            return True
