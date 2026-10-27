import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from cue.main import app


def test_health_and_missing_token():
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get(f"/v1/tenants/{uuid4()}/me").status_code == 401


@pytest.fixture
def tenants():
    if "MIGRATION_DATABASE_URL" not in os.environ:
        pytest.skip("Postgres integration database not configured")
    first, second = uuid4(), uuid4()
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("INSERT INTO tenants (id, name) VALUES (%s, 'first'), (%s, 'second')", (first, second))
            cursor.execute(
                "INSERT INTO users (tenant_id, firebase_uid, role) VALUES (%s, 'firebase-user', 'member')",
                (first,),
            )
    yield first, second
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM users WHERE tenant_id = %s", (first,))
            cursor.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (first, second))


def test_tenant_rows_are_isolated(tenants):
    first, second = tenants
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM tenants")
            assert cursor.fetchone()[0] == 0
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(first),))
            cursor.execute("SELECT id FROM tenants")
            assert cursor.fetchall() == [(first,)]
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(second),))
            cursor.execute("SELECT id FROM tenants")
            assert cursor.fetchall() == [(second,)]


def test_firebase_identity_cannot_access_another_tenant(tenants, monkeypatch):
    first, second = tenants
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "cue-test")
    monkeypatch.setattr("cue.main.auth.verify_id_token", lambda token: {"uid": "firebase-user"})
    headers = {"Authorization": "Bearer test-token"}
    client = TestClient(app)
    assert client.get(f"/v1/tenants/{first}/me", headers=headers).json()["role"] == "member"
    assert client.get(f"/v1/tenants/{second}/me", headers=headers).status_code == 403
    assert client.get(f"/v1/tenants/{first}/me").status_code == 401
