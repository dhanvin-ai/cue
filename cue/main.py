import os
from uuid import UUID

import firebase_admin
import psycopg
from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

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
