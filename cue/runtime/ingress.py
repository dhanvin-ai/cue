"""Shared ingress: Slack, email, schedule, and web become one runtime request."""

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Mapping
from uuid import UUID, uuid4

import psycopg

from cue.runtime import store


class IngressRejected(ValueError):
    """The payload cannot be turned into a valid request."""


@dataclass(frozen=True)
class RuntimeRequest:
    tenant_id: UUID
    source: str
    requester_uid: str
    text: str
    idempotency_key: str
    channel_ref: str | None = None
    thread_ref: str | None = None
    participants: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)


def _clean(text: str) -> str:
    value = " ".join((text or "").split())
    if not value:
        raise IngressRejected("Request text is empty")
    return value[:8000]


def _digest(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode()).hexdigest()


def from_web(tenant_id: UUID, uid: str, payload: Mapping[str, Any]) -> RuntimeRequest:
    request_id = payload.get("request_id") or f"web-{uuid4()}"
    return RuntimeRequest(
        tenant_id=tenant_id,
        source="web",
        requester_uid=uid,
        text=_clean(str(payload.get("text") or payload.get("question") or "")),
        idempotency_key=f"web:{request_id}",
        channel_ref=payload.get("channel_ref"),
        participants=tuple(payload.get("participants") or ()),
    )


def from_slack(tenant_id: UUID, payload: Mapping[str, Any]) -> RuntimeRequest:
    event = payload.get("event") or {}
    if not event.get("user") or not event.get("text"):
        raise IngressRejected("Slack event is missing a user or text")
    text = event["text"]
    for token in (event.get("text") or "").split():
        if token.startswith("<@") and token.endswith(">"):
            text = text.replace(token, " ")
    stable_id = event.get("client_msg_id") or event.get("ts") or _digest(text, event["user"])
    return RuntimeRequest(
        tenant_id=tenant_id,
        source="slack",
        requester_uid=event["user"],
        text=_clean(text),
        idempotency_key=f"slack:{payload.get('team_id', '')}:{stable_id}",
        channel_ref=event.get("channel"),
        thread_ref=event.get("thread_ts") or event.get("ts"),
        metadata={"team_id": payload.get("team_id")},
    )


def from_email(tenant_id: UUID, uid: str, payload: Mapping[str, Any]) -> RuntimeRequest:
    subject = str(payload.get("subject") or "").strip()
    body = str(payload.get("body") or payload.get("text") or "").strip()
    message_id = payload.get("message_id") or _digest(uid, subject, body)
    return RuntimeRequest(
        tenant_id=tenant_id,
        source="email",
        requester_uid=uid,
        text=_clean(f"{subject}\n{body}"),
        idempotency_key=f"email:{message_id}",
        channel_ref=payload.get("thread_id"),
        thread_ref=payload.get("thread_id"),
        metadata={"subject": subject},
    )


def submit(request: RuntimeRequest, *, database_url: str | None = None, queue=None) -> tuple[UUID, bool]:
    """Persist the request once, audit the ingress, and queue the task."""
    with store.tenant_connection(request.tenant_id, database_url) as database:
        if store.membership(database, request.tenant_id, request.requester_uid) is None:
            raise PermissionError("Requester is not a member of this tenant")
        task_id, created = store.create_task(
            database, request.tenant_id,
            source=request.source,
            requester_uid=request.requester_uid,
            request_text=request.text,
            idempotency_key=request.idempotency_key,
            channel_ref=request.channel_ref,
            thread_ref=request.thread_ref,
        )
        if created:
            store.audit(
                database, request.tenant_id, actor=request.requester_uid, action="ingress",
                task_id=task_id, decision="created",
                detail={"source": request.source, "channel": request.channel_ref},
            )
    if created and queue is not None:
        queue.enqueue(request.tenant_id, task_id)
    return task_id, created


def tenant_for_source(provider: str, external_id: str, database_url: str | None = None):
    """Resolve a vendor identity to a tenant before a request can enter the runtime."""
    with psycopg.connect(database_url or os.environ["INGEST_DATABASE_URL"]) as database:
        row = database.execute(
            "SELECT tenant_id FROM source_bindings WHERE provider = %s AND external_id = %s",
            (provider, external_id),
        ).fetchone()
    return row[0] if row else None
