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

from cue.connectors.github import REQUIRED_EVENTS, secret, verify_webhook
from cue.connectors import signatures

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
