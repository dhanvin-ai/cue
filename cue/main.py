import os
import json
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
