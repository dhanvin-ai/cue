import os
import json
import hashlib
import hmac
from urllib.parse import parse_qs
from uuid import UUID

import firebase_admin
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from google.cloud import pubsub_v1
from pydantic import BaseModel, Field

from cue.connectors.github import REQUIRED_EVENTS, secret, verify_webhook
from cue.connectors import signatures
from cue.meetings import notes as meeting_notes
from cue.meetings import service as meeting_service
from cue.memory.query import query_memory
from cue.runtime import ingress as agent_ingress
from cue.runtime import service as agent_service
from cue.runtime import store as agent_store
from cue.runtime.executor import ToolRegistry
from cue.runtime.gateway import LiteLLMGateway

app = FastAPI(title="Cue API")
bearer = HTTPBearer(auto_error=False)

if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    provider = TracerProvider(resource=Resource.create({"service.name": "cue-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)


def firebase_uid(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(options={"projectId": os.environ["FIREBASE_PROJECT_ID"]})
    try:
        return auth.verify_id_token(credentials.credentials)["uid"]
    except (FirebaseError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=401, detail="Invalid Firebase token") from exc


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/github", status_code=202)
async def github_webhook(request: Request) -> dict[str, bool]:
    body = await request.body()
    # Keep below Pub/Sub's message limit; raw payloads are archived by the ingest worker.
    if len(body) > 9_000_000:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    key = await run_in_threadpool(secret, os.environ["GITHUB_WEBHOOK_SECRET_VERSION"])
    if not verify_webhook(
        body,
        request.headers.get("X-Hub-Signature-256"),
        key,
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    event = request.headers.get("X-GitHub-Event")
    if event not in REQUIRED_EVENTS:
        return {"accepted": False}
    delivery_id = request.headers.get("X-GitHub-Delivery")
    if not delivery_id:
        raise HTTPException(status_code=400, detail="Missing GitHub delivery ID")
    try:
        payload = json.loads(body)
        installation_id = int(payload["installation"]["id"])
        if installation_id <= 0:
            raise ValueError("Invalid installation ID")
    except (ValueError, TypeError, KeyError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid GitHub payload") from exc
    def publish() -> None:
        pubsub_v1.PublisherClient().publish(
            os.environ["RAW_EVENTS_TOPIC"],
            body,
            source="github",
            event=event,
            delivery_id=delivery_id,
            installation_id=str(installation_id),
        ).result(timeout=5)

    await run_in_threadpool(publish)
    return {"accepted": True}


def publish_raw(body: bytes, source: str, external_id: str, delivery_id: str) -> None:
    pubsub_v1.PublisherClient().publish(
        os.environ["RAW_EVENTS_TOPIC"], body,
        source=source, external_id=external_id, delivery_id=delivery_id,
    ).result(timeout=5)


@app.post("/webhooks/slack")
async def slack_webhook(request: Request) -> dict:
    body = await request.body()
    if len(body) > 9_000_000:
        raise HTTPException(status_code=413)
    key = await run_in_threadpool(secret, os.environ["SLACK_SIGNING_SECRET_VERSION"])
    if not signatures.slack(body, request.headers, key):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}
    event = payload.get("event", {})
    if payload.get("type") != "event_callback" or event.get("type") != "message" or event.get("subtype") not in (None, "message_changed"):
        return {"accepted": False}
    await run_in_threadpool(publish_raw, body, "slack", payload["team_id"], payload["event_id"])
    return {"accepted": True}


@app.post("/webhooks/linear", status_code=202)
async def linear_webhook(request: Request) -> dict[str, bool]:
    body = await request.body()
    if len(body) > 9_000_000:
        raise HTTPException(status_code=413)
    key = await run_in_threadpool(secret, os.environ["LINEAR_WEBHOOK_SECRET_VERSION"])
    if not signatures.linear(body, request.headers, key):
        raise HTTPException(status_code=401, detail="Invalid Linear signature")
    payload = json.loads(body)
    if payload.get("type") != "Issue":
        return {"accepted": False}
    await run_in_threadpool(
        publish_raw, body, "linear", payload["organizationId"], hashlib.sha256(body).hexdigest()
    )
    return {"accepted": True}


@app.post("/webhooks/recall", status_code=202)
async def recall_webhook(request: Request) -> dict[str, bool]:
    body = await request.body()
    if len(body) > 9_000_000:
        raise HTTPException(status_code=413)
    key = await run_in_threadpool(secret, os.environ["RECALL_VERIFICATION_SECRET_VERSION"])
    if not signatures.recall(body, request.headers, key):
        raise HTTPException(status_code=401, detail="Invalid Recall signature")
    payload = json.loads(body)
    data = payload.get("data", {})
    bot_id = (data.get("bot") or {}).get("id") or data.get("bot_id")
    if not bot_id:
        raise HTTPException(status_code=400, detail="Missing bot ID")
    delivery_id = request.headers.get("webhook-id") or request.headers.get("svix-id")
    await run_in_threadpool(publish_raw, body, "recall", bot_id, delivery_id)
    return {"accepted": True}


@app.post("/webhooks/calendar", status_code=202)
async def calendar_webhook(request: Request) -> dict[str, bool]:
    params = parse_qs(request.headers.get("X-Goog-Channel-Token", ""))
    owner = params.get("owner", [""])[0]
    signature = params.get("signature", [""])[0]
    if not owner or not signature:
        raise HTTPException(status_code=401)
    key = await run_in_threadpool(secret, os.environ["CALENDAR_CHANNEL_SECRET_VERSION"])
    expected = hmac.new(key, owner.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401)
    if request.headers.get("X-Goog-Resource-State") == "sync":
        return {"accepted": False}
    external_id = owner
    def publish_trigger() -> None:
        pubsub_v1.PublisherClient().publish(
            os.environ["SYNC_TRIGGERS_TOPIC"], b"", provider="calendar", external_id=external_id
        ).result(timeout=5)
    await run_in_threadpool(publish_trigger)
    return {"accepted": True}


@app.get("/v1/tenants/{tenant_id}/me")
def me(tenant_id: UUID, uid: str = Depends(firebase_uid)) -> dict[str, str]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            cursor.execute(
                "SELECT role FROM users WHERE tenant_id = %s AND firebase_uid = %s",
                (tenant_id, uid),
            )
            row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")
    return {"tenant_id": str(tenant_id), "firebase_uid": uid, "role": row[0]}


class MemoryQuestion(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    participants: list[str] = Field(default_factory=list, max_length=20)
    target: dict | None = None


@app.post("/v1/tenants/{tenant_id}/memory/query")
async def memory_query(tenant_id: UUID, request: MemoryQuestion,
                       uid: str = Depends(firebase_uid)) -> dict:
    try:
        return await run_in_threadpool(
            query_memory, tenant_id, uid, request.question, request.participants,
            os.environ["DATABASE_URL"], request.target,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class AgentRequestBody(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    request_id: str | None = None
    participants: list[str] = Field(default_factory=list, max_length=20)


class ApprovalBody(BaseModel):
    approve: bool


@app.post("/v1/tenants/{tenant_id}/agent/requests", status_code=202)
async def agent_request(tenant_id: UUID, body: AgentRequestBody,
                        uid: str = Depends(firebase_uid)) -> dict:
    try:
        runtime_request = agent_ingress.from_web(tenant_id, uid, body.model_dump())
        task_id, created = await run_in_threadpool(agent_ingress.submit, runtime_request)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except agent_ingress.IngressRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"task_id": str(task_id), "created": created, "status": "queued"}


@app.get("/v1/tenants/{tenant_id}/agent/tasks/{task_id}")
def agent_task(tenant_id: UUID, task_id: UUID, uid: str = Depends(firebase_uid)) -> dict:
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) is None:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        task = agent_store.get_task(database, tenant_id, task_id)
        approvals = agent_store.task_approvals(database, tenant_id, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return agent_service.snapshot(task, approvals)


@app.post("/v1/tenants/{tenant_id}/agent/approvals/{approval_id}")
async def agent_approval(tenant_id: UUID, approval_id: UUID, body: ApprovalBody,
                         uid: str = Depends(firebase_uid)) -> dict:
    try:
        return await run_in_threadpool(
            agent_service.decide, tenant_id, approval_id, uid, body.approve,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except agent_service.TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/webhooks/slack/agent")
async def slack_agent_webhook(request: Request) -> dict:
    body = await request.body()
    if len(body) > 9_000_000:
        raise HTTPException(status_code=413)
    key = await run_in_threadpool(secret, os.environ["SLACK_SIGNING_SECRET_VERSION"])
    if not signatures.slack(body, request.headers, key):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")
    payload = json.loads(body)
    if payload.get("type") == "url_verification":
        return {"challenge": payload["challenge"]}
    event = payload.get("event") or {}
    if (payload.get("type") != "event_callback"
            or event.get("type") not in {"app_mention", "message"}
            or event.get("bot_id") or event.get("subtype")):
        return {"accepted": False}
    tenant_id = await run_in_threadpool(
        agent_ingress.tenant_for_source, "slack", payload.get("team_id"))
    if tenant_id is None:
        raise HTTPException(status_code=404, detail="Slack team is not linked to a tenant")
    try:
        runtime_request = agent_ingress.from_slack(tenant_id, payload)
        task_id, created = await run_in_threadpool(agent_ingress.submit, runtime_request)
    except agent_ingress.IngressRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"accepted": True, "task_id": str(task_id), "created": created}


@app.post("/webhooks/email/agent")
async def email_agent_webhook(request: Request) -> dict:
    body = await request.body()
    key = await run_in_threadpool(secret, os.environ["EMAIL_INGRESS_SECRET_VERSION"])
    signature = request.headers.get("X-Cue-Signature", "")
    expected = "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid email signature")
    payload = json.loads(body)
    try:
        runtime_request = agent_ingress.from_email(
            UUID(payload["tenant_id"]), payload["firebase_uid"], payload)
        task_id, created = await run_in_threadpool(agent_ingress.submit, runtime_request)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except agent_ingress.IngressRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid email payload") from exc
    return {"accepted": True, "task_id": str(task_id), "created": created}


@app.post("/internal/tasks/{tenant_id}/{task_id}", status_code=202)
async def internal_task(tenant_id: UUID, task_id: UUID, request: Request) -> dict:
    key = await run_in_threadpool(secret, os.environ["INTERNAL_TASK_TOKEN_SECRET_VERSION"])
    token = request.headers.get("X-Cue-Task-Token", "")
    if not token or not hmac.compare_digest(token, key.decode()):
        raise HTTPException(status_code=401, detail="Invalid task token")
    try:
        return await run_in_threadpool(
            agent_service.run_task, tenant_id, task_id,
            gateway=LiteLLMGateway(), registry=ToolRegistry(),
        )
    except agent_service.TaskNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


class MeetingAttendee(BaseModel):
    id: str | None = None
    email: str | None = None
    display_name: str | None = None


class MeetingJoinBody(BaseModel):
    meeting_url: str = Field(min_length=1, max_length=2000)
    title: str | None = None
    attendees: list[MeetingAttendee] = Field(default_factory=list, max_length=100)


@app.post("/v1/tenants/{tenant_id}/meetings", status_code=202)
async def meeting_join(tenant_id: UUID, body: MeetingJoinBody,
                       uid: str = Depends(firebase_uid)) -> dict:
    try:
        return await run_in_threadpool(
            meeting_service.join_meeting, tenant_id, uid, body.meeting_url,
            [item.model_dump() for item in body.attendees], title=body.title,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/tenants/{tenant_id}/meetings/{meeting_id}/notes")
def meeting_notes_view(tenant_id: UUID, meeting_id: UUID,
                       uid: str = Depends(firebase_uid)) -> dict:
    try:
        note = meeting_service.get_notes(tenant_id, meeting_id, uid)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if note is None:
        raise HTTPException(status_code=404, detail="Notes not found or not accessible")
    return note


@app.post("/v1/tenants/{tenant_id}/meetings/{meeting_id}/end")
async def meeting_end(tenant_id: UUID, meeting_id: UUID,
                      uid: str = Depends(firebase_uid)) -> dict:
    try:
        with agent_store.tenant_connection(tenant_id) as database:
            if agent_store.membership(database, tenant_id, uid) is None:
                raise PermissionError("Not a member of this tenant")
        return await run_in_threadpool(
            meeting_service.end_meeting, tenant_id, meeting_id,
            notes_model=meeting_notes.GatewayNotesModel(LiteLLMGateway()),
            registry=ToolRegistry(),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
