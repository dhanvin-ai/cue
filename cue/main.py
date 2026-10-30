import os
import json
import hashlib
import hmac
from datetime import datetime, time
from pathlib import Path
from urllib.parse import parse_qs
from uuid import UUID

import firebase_admin
import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
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
from cue.audit import report as audit_report
from cue.controls import switches
from cue.lifecycle import propagation
from cue.meetings import bolna
from cue.meetings import notes as meeting_notes
from cue.meetings import service as meeting_service
from cue.memory.query import query_memory
from cue.ops import status as ops_status
from cue.proactive import quiet, rules as proactive_rules
from cue.runtime import ingress as agent_ingress
from cue.runtime import service as agent_service
from cue.runtime import store as agent_store
from cue.runtime import tools as agent_tools
from cue.runtime.gateway import LiteLLMGateway

app = FastAPI(title="Cue API")
bearer = HTTPBearer(auto_error=False)

if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    provider = TracerProvider(resource=Resource.create({"service.name": "cue-api"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)


DEV_TENANT_ENV = "CUE_DEV_TENANT_ID"


def firebase_uid(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str:
    # Local development only: CUE_DEV_AUTH_UID skips Firebase verification so the
    # dev console and curl work without a Firebase project. Never set it in a
    # deployed environment.
    if dev_uid := os.getenv("CUE_DEV_AUTH_UID"):
        return dev_uid
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


@app.get("/readyz")
def readyz() -> dict:
    checks = {}
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as database:
            database.execute("SELECT 1")
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - readiness reports the check, not a stack trace
        checks["postgres"] = type(exc).__name__
    status = "ok" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


CONSOLE_HTML = Path(__file__).parent / "static" / "console.html"
CONSOLE_JS = Path(__file__).parent / "static" / "console.js"


def console_enabled() -> bool:
    # Local development only: the console relies on the dev auth bypass, so it is
    # never served when that bypass is off.
    return bool(os.getenv("CUE_DEV_AUTH_UID"))


@app.get("/ui", include_in_schema=False)
def dev_console() -> HTMLResponse:
    """The teammate console. Available only while the dev auth bypass is on."""
    if not console_enabled():
        raise HTTPException(status_code=404)
    html = CONSOLE_HTML.read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/ui/console.js", include_in_schema=False)
def dev_console_script() -> Response:
    if not console_enabled():
        raise HTTPException(status_code=404)
    # The page and this script are same-origin, so no CORS is needed for either.
    body = (
        f"window.__CUE_TENANT__={json.dumps(os.getenv(DEV_TENANT_ENV, ''))};\n"
        f"window.__CUE_UID__={json.dumps(os.getenv('CUE_DEV_AUTH_UID', ''))};\n"
        f"window.__CUE_GATEWAY_URL__={json.dumps(os.getenv('MODEL_GATEWAY_BASE_URL', ''))};\n"
        # Only whether a key exists is exposed; the key itself never leaves the server.
        f"window.__CUE_GATEWAY_KEY__={json.dumps(bool(os.getenv('MODEL_GATEWAY_API_KEY')))};\n"
        + CONSOLE_JS.read_text(encoding="utf-8")
    )
    return Response(body, media_type="application/javascript")


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
                "SELECT role FROM users WHERE tenant_id = %s AND firebase_uid = %s "
                "AND revoked_at IS NULL",
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


@app.get("/v1/tenants/{tenant_id}/agent/tasks")
def agent_tasks(tenant_id: UUID, uid: str = Depends(firebase_uid),
                status_filter: str | None = Query(default=None, alias="status", max_length=30),
                limit: int = Query(default=25, ge=1, le=100)) -> dict:
    """Recent tasks with their approvals, newest first."""
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) is None:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        tasks = agent_store.list_tasks(database, tenant_id, limit=limit,
                                       status=status_filter)
        snapshots = []
        for task in tasks:
            approvals = agent_store.task_approvals(
                database, tenant_id, task["id"])
            snapshots.append(agent_service.snapshot(task, approvals))
    return {"tasks": snapshots}


@app.get("/v1/tenants/{tenant_id}/agent/approvals")
def agent_approvals(tenant_id: UUID, uid: str = Depends(firebase_uid),
                    limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Pending approvals across every task, so one person can clear the queue."""
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) is None:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        rows = agent_store.pending_approvals(database, tenant_id, limit=limit)
    return {"approvals": [
        {"id": str(row[0]), "tool": row[1], "tier": row[2], "status": row[3],
         "arguments": row[4] or {}, "task_id": str(row[5]), "request_text": row[6],
         "source": row[7], "task_status": row[8],
         "created_at": row[9].isoformat() if row[9] else None}
        for row in rows
    ]}


@app.post("/v1/tenants/{tenant_id}/agent/tasks/{task_id}/requeue", status_code=202)
async def agent_task_requeue(tenant_id: UUID, task_id: UUID,
                             uid: str = Depends(firebase_uid)) -> dict:
    """Retry a queued task whose dispatch was lost before any worker ran it."""
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) is None:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        task = agent_store.get_task(database, tenant_id, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        if task["status"] != "queued":
            raise HTTPException(status_code=409,
                                detail=f"Task is {task['status']}, not queued")
        released = agent_store.requeue_task(database, tenant_id, task_id)
        agent_store.audit(database, tenant_id, actor=uid, action="retry", task_id=task_id,
                          decision="requeued", detail={"attempts": task["attempts"]})
    return {"task_id": str(task_id), "requeued": released}


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
        with agent_store.tenant_connection(tenant_id) as database:
            task = agent_store.get_task(database, tenant_id, task_id)
        if task is None:
            raise agent_service.TaskNotFound(str(task_id))
        registry = await run_in_threadpool(
            agent_tools.build_registry, tenant_id, task["requester_uid"])
        return await run_in_threadpool(
            agent_service.run_task, tenant_id, task_id,
            gateway=LiteLLMGateway(), registry=registry,
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
    # "bolna": the meeting phones Cue's Bolna number instead of a Recall bot joining.
    voice: str = Field(default="recall", pattern="^(recall|bolna)$")


@app.post("/v1/tenants/{tenant_id}/meetings", status_code=202)
async def meeting_join(tenant_id: UUID, body: MeetingJoinBody,
                       uid: str = Depends(firebase_uid)) -> dict:
    bot = bolna.BolnaMeetingBot() if body.voice == "bolna" else None
    try:
        result = await run_in_threadpool(
            meeting_service.join_meeting, tenant_id, uid, body.meeting_url,
            [item.model_dump() for item in body.attendees], title=body.title, bot=bot,
        )
        if bot is not None:
            result["dial"] = os.getenv("BOLNA_PHONE_NUMBER")
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _bolna_tenant(request: Request) -> UUID:
    scheme, _, key = request.headers.get("Authorization", "").partition(" ")
    tenant_id = bolna.tenant_for_key(key) if scheme.lower() == "bearer" and key else None
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Invalid Bolna model key")
    return tenant_id


@app.get("/bolna/v1/models")
def bolna_models(request: Request) -> dict:
    _bolna_tenant(request)
    return {"object": "list", "data": [{"id": "cue", "object": "model", "owned_by": "cue"}]}


@app.post("/bolna/v1/chat/completions")
async def bolna_chat(request: Request):
    """OpenAI-compatible endpoint Bolna calls for each caller turn on the meeting line."""
    tenant_id = _bolna_tenant(request)
    body = await request.json()
    model = str(body.get("model") or "cue")
    pieces = bolna.respond(tenant_id, list(body.get("messages") or []),
                           gateway=LiteLLMGateway(),
                           registry=lambda uid: agent_tools.build_registry(tenant_id, uid))
    if body.get("stream"):
        return StreamingResponse(bolna.sse(pieces, model), media_type="text/event-stream")
    return await run_in_threadpool(lambda: bolna.completion(list(pieces), model))


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
            registry=agent_tools.build_registry(tenant_id, uid),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def require_admin(tenant_id: UUID, uid: str) -> None:
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) != "admin":
            raise HTTPException(status_code=403, detail="Admin role required")


def replay_ingest(data: bytes, attributes: dict) -> bool:
    from cue.ingestion import process_raw
    return process_raw(data, attributes, os.environ["INGEST_DATABASE_URL"])


class KillSwitchBody(BaseModel):
    paused: bool = True
    mode: str = Field(default="queue", pattern="^(queue|drop)$")
    reason: str | None = None


class RevocationBody(BaseModel):
    kind: str = Field(pattern="^(user|connector)$")
    subject: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)


class QuietHoursBody(BaseModel):
    scope: str = Field(pattern="^(tenant|user)$")
    subject: str = "*"
    timezone: str = Field(min_length=1, max_length=80)
    start: time
    end: time


class ProactiveRuleBody(BaseModel):
    rule_key: str = Field(min_length=1, max_length=80)
    kind: str = Field(pattern="^(daily_digest|weekly_digest|reminder|stale_pr|overdue_action)$")
    owner_uid: str | None = None
    schedule: str | None = None
    timezone: str = "UTC"
    config: dict = Field(default_factory=dict)
    next_run_at: datetime | None = None


class MuteBody(BaseModel):
    rule_key: str = Field(default="*", max_length=80)
    uid: str | None = None


@app.get("/v1/tenants/{tenant_id}/status")
def tenant_status(tenant_id: UUID, uid: str = Depends(firebase_uid)) -> dict:
    try:
        return ops_status.tenant_status(tenant_id, uid)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/v1/tenants/{tenant_id}/admin/access-report")
def admin_access_report(tenant_id: UUID, uid: str = Depends(firebase_uid)) -> dict:
    try:
        return audit_report.access_report(
            tenant_id, uid, tools=list(audit_report.AGENT_TOOLS),
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@app.get("/v1/tenants/{tenant_id}/admin/audit/export")
def admin_audit_export(tenant_id: UUID, since: datetime, until: datetime,
                       format: str = "json", uid: str = Depends(firebase_uid)):
    try:
        result = audit_report.export_audit(tenant_id, uid, since, until, fmt=format)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if isinstance(result, str):
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(result, media_type="text/csv")
    return result


@app.put("/v1/tenants/{tenant_id}/admin/kill-switches/{scope}/{subject}")
def admin_kill_switch(tenant_id: UUID, scope: str, subject: str, body: KillSwitchBody,
                      uid: str = Depends(firebase_uid)) -> dict:
    require_admin(tenant_id, uid)
    try:
        with agent_store.tenant_connection(tenant_id) as database:
            if not body.paused:
                return switches.resume(
                    database, tenant_id, scope=scope, subject=subject, actor=uid,
                    ingest=replay_ingest,
                )
            return switches.set_switch(
                database, tenant_id, scope=scope, subject=subject, paused=body.paused,
                actor=uid, mode=body.mode, reason=body.reason,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/tenants/{tenant_id}/admin/kill-switches")
def admin_kill_switches(tenant_id: UUID, uid: str = Depends(firebase_uid)) -> dict:
    require_admin(tenant_id, uid)
    with agent_store.tenant_connection(tenant_id) as database:
        return switches.status(database, tenant_id)


@app.post("/v1/tenants/{tenant_id}/admin/revocations")
def admin_revocation(tenant_id: UUID, body: RevocationBody,
                     uid: str = Depends(firebase_uid)) -> dict:
    require_admin(tenant_id, uid)
    try:
        with agent_store.tenant_connection(tenant_id) as database:
            if body.kind == "user":
                return propagation.revoke_user(
                    database, tenant_id, body.subject, requested_by=uid, reason=body.reason,
                )
            return propagation.revoke_connector(
                database, tenant_id, UUID(body.subject), requested_by=uid, reason=body.reason,
            )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/v1/tenants/{tenant_id}/admin/events/{event_id:path}")
def admin_delete_event(tenant_id: UUID, event_id: str, uid: str = Depends(firebase_uid)) -> dict:
    require_admin(tenant_id, uid)
    with agent_store.tenant_connection(tenant_id) as database:
        return propagation.delete_event(
            database, tenant_id, event_id, requested_by=uid,
            reason="admin deletion request",
        )


@app.put("/v1/tenants/{tenant_id}/admin/quiet-hours")
def admin_quiet_hours(tenant_id: UUID, body: QuietHoursBody,
                      uid: str = Depends(firebase_uid)) -> dict:
    if body.scope == "tenant":
        require_admin(tenant_id, uid)
    elif body.subject != uid:
        require_admin(tenant_id, uid)
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) is None:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        try:
            window = quiet.set_window(
                database, tenant_id, scope=body.scope, subject=body.subject,
                timezone_name=body.timezone, start=body.start, end=body.end,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"scope": body.scope, "subject": body.subject, "timezone": window.timezone,
            "start": window.start.isoformat(), "end": window.end.isoformat()}


@app.get("/v1/tenants/{tenant_id}/proactive")
def proactive_view(tenant_id: UUID, uid: str = Depends(firebase_uid),
                   limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """Rules, recent runs and mutes for this tenant."""
    with agent_store.tenant_connection(tenant_id) as database:
        if agent_store.membership(database, tenant_id, uid) is None:
            raise HTTPException(status_code=403, detail="Not a member of this tenant")
        rules = proactive_rules.all_rules(database, tenant_id)
        recent_runs = proactive_rules.runs(database, tenant_id, limit=limit)
        muted = proactive_rules.mutes(database, tenant_id)
        windows = quiet.list_windows(database, tenant_id)

    def _moment(value):
        return value.isoformat() if value is not None else None

    return {
        "rules": [{**rule, "id": str(rule["id"]), "next_run_at": _moment(rule["next_run_at"]),
                   "last_run_at": _moment(rule["last_run_at"])} for rule in rules],
        "runs": [{**run, "id": str(run["id"]),
                  "task_id": str(run["task_id"]) if run["task_id"] else None,
                  "deliver_after": _moment(run["deliver_after"]),
                  "created_at": _moment(run["created_at"])} for run in recent_runs],
        "mutes": [{**item, "created_at": _moment(item["created_at"])} for item in muted],
        "quiet_hours": [{**item, "start_time": item["start_time"].isoformat(),
                         "end_time": item["end_time"].isoformat()} for item in windows],
    }


@app.post("/v1/tenants/{tenant_id}/proactive/rules")
def create_proactive_rule(tenant_id: UUID, body: ProactiveRuleBody,
                          uid: str = Depends(firebase_uid)) -> dict:
    owner = body.owner_uid or uid
    if owner != uid:
        require_admin(tenant_id, uid)
    try:
        with agent_store.tenant_connection(tenant_id) as database:
            rule_id = proactive_rules.create_rule(
                database, tenant_id, rule_key=body.rule_key, kind=body.kind,
                owner_uid=owner, schedule=body.schedule, timezone_name=body.timezone,
                config=body.config, next_run_at=body.next_run_at,
            )
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rule_id": str(rule_id), "rule_key": body.rule_key}


@app.post("/v1/tenants/{tenant_id}/proactive/mutes")
def mute_proactive_rule(tenant_id: UUID, body: MuteBody,
                        uid: str = Depends(firebase_uid)) -> dict:
    target = body.uid or uid
    if target != uid:
        require_admin(tenant_id, uid)
    try:
        with agent_store.tenant_connection(tenant_id) as database:
            proactive_rules.mute(database, tenant_id, target, body.rule_key)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return {"uid": target, "rule_key": body.rule_key, "muted": True}


@app.delete("/v1/tenants/{tenant_id}/proactive/mutes/{rule_key}")
def unmute_proactive_rule(tenant_id: UUID, rule_key: str, uid_query: str | None = None,
                          uid: str = Depends(firebase_uid)) -> dict:
    target = uid_query or uid
    if target != uid:
        require_admin(tenant_id, uid)
    with agent_store.tenant_connection(tenant_id) as database:
        proactive_rules.unmute(database, tenant_id, target, rule_key)
    return {"uid": target, "rule_key": rule_key, "muted": False}
