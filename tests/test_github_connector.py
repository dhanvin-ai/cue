import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from cue.connectors.backfill import run
from cue.connectors.github import GitHubConnector, verify_webhook
from cue.main import app


def issue_snapshot(private=True):
    return {
        "event": "snapshot",
        "repository": {"id": 9, "private": private, "name": "cue", "owner": {"login": "acme"}},
        "issue": {
            "id": 123,
            "number": None,
            "state": "",
            "assignee": None,
            "title": "Fix login",
            "body": "Session expires early",
            "updated_at": "2026-10-28T10:00:00Z",
            "user": {"id": 7},
        },
    }


def test_github_connector_contract(monkeypatch):
    calls = []

    def responder(request):
        calls.append((str(request.url), request.content))
        path = request.url.path
        if path == "/app/installations/42":
            data = {"id": 42}
        elif path == "/app":
            data = {"events": ["installation", "issues", "pull_request", "push", "issue_comment", "pull_request_review", "pull_request_review_comment"]}
        elif path == "/app/installations/42/access_tokens":
            data = {"token": "installation-token", "expires_at": "2099-01-01T00:00:00Z"}
        elif path == "/installation/repositories":
            data = {"repositories": [issue_snapshot()["repository"]]}
        elif path == "/graphql":
            query = json.loads(request.content)["query"]
            data = {"data": {"repository": {
                "issues" if "CueBackfill" in query else "pullRequests": {
                    "nodes": [{"databaseId": 123, "title": "Fix login", "body": "Session expires early",
                               "updatedAt": "2026-10-28T10:00:00Z", "author": {"databaseId": 7}}]
                    if "CueBackfill" in query else [],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                },
            }}}
        elif path in {"/repos/acme/cue/commits", "/repos/acme/cue/issues/comments"}:
            data = []
        else:
            raise AssertionError(path)
        return httpx.Response(200, json=data)

    connector = GitHubConnector(httpx.Client(transport=httpx.MockTransport(responder)))
    monkeypatch.setattr(connector, "_app_jwt", lambda: "app-jwt")
    connector.authorize("42")
    connector.subscribe()
    raw = list(connector.backfill("42", datetime(2026, 1, 1, tzinfo=timezone.utc)))
    assert raw == [issue_snapshot()]
    assert any(b'"since":"2026-01-01' in body for _, body in calls)
    event = connector.normalize(raw[0], uuid4())
    assert event.type == "issue.snapshot"
    assert event.acl.principals == ("github:repo:9",)
    assert connector.acl(issue_snapshot(False)).visibility == "public"
    assert connector.tools()[0].risk_tier == 0


def test_webhook_signature_and_publish(monkeypatch):
    body = json.dumps({"installation": {"id": 42}}).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, signature, b"secret")
    assert not verify_webhook(body + b" ", signature, b"secret")

    published = []

    class Publisher:
        def publish(self, topic, data, **attributes):
            published.append((topic, data, attributes))
            return type("Future", (), {"result": lambda self, timeout: "id"})()

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET_VERSION", "test-secret-ref")
    monkeypatch.setenv("RAW_EVENTS_TOPIC", "projects/test/topics/raw")
    monkeypatch.setattr("cue.main.secret", lambda ref: b"secret")
    monkeypatch.setattr("cue.main.pubsub_v1.PublisherClient", Publisher)
    client = TestClient(app)
    headers = {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": "issues",
        "X-GitHub-Delivery": "delivery-1",
    }
    assert client.post("/webhooks/github", content=body, headers=headers).status_code == 202
    assert published[0][2]["installation_id"] == "42"
    assert published[0][2]["delivery_id"] == "delivery-1"
    assert client.post("/webhooks/github", content=body + b" ", headers=headers).status_code == 401
    assert len(published) == 1


@pytest.fixture
def connection():
    if "MIGRATION_DATABASE_URL" not in os.environ:
        pytest.skip("Postgres integration database not configured")
    tenant_id, other_tenant, connection_id = uuid4(), uuid4(), uuid4()
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        with database.cursor() as cursor:
            cursor.execute("INSERT INTO tenants (id, name) VALUES (%s, 'first'), (%s, 'second')", (tenant_id, other_tenant))
            cursor.execute(
                "INSERT INTO connector_connections (id, tenant_id, provider, external_id) "
                "VALUES (%s, %s, 'github', '42')",
                (connection_id, tenant_id),
            )
    yield tenant_id, other_tenant, connection_id
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        with database.cursor() as cursor:
            cursor.execute("DELETE FROM connector_connections WHERE id = %s", (connection_id,))
            cursor.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (tenant_id, other_tenant))


def test_backfill_resumes_after_publish_failure(connection, monkeypatch):
    tenant_id, other_tenant, connection_id = connection
    monkeypatch.setenv("RAW_EVENTS_TOPIC", "projects/test/topics/raw")

    class Connector:
        provider = "github"

        def authorize(self, external_id):
            assert external_id == "42"

        def subscribe(self):
            pass

        def backfill(self, external_id, since):
            yield issue_snapshot()

        def normalize(self, raw, tenant_id):
            return GitHubConnector().normalize(raw, tenant_id)

    class Publisher:
        fail = True
        count = 0

        def publish(self, topic, data, **attributes):
            self.count += 1
            assert attributes["tenant_id"] == str(tenant_id)
            assert json.loads(data)["issue"]["id"] == 123

            class Future:
                def result(inner, timeout):
                    if self.fail:
                        raise RuntimeError("publish failed")

            return Future()

    publisher = Publisher()
    with pytest.raises(ValueError):
        run(other_tenant, connection_id, publisher, Connector())
    with pytest.raises(RuntimeError, match="publish failed"):
        run(tenant_id, connection_id, publisher, Connector())
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        row = database.execute(
            "SELECT cursor, status FROM connector_connections WHERE id = %s", (connection_id,)
        ).fetchone()
        assert row == (None, "error")
    publisher.fail = False
    assert run(tenant_id, connection_id, publisher, Connector()) == 1
    assert publisher.count == 2
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        row = database.execute(
            "SELECT cursor, status FROM connector_connections WHERE id = %s", (connection_id,)
        ).fetchone()
        assert datetime.fromisoformat(row[0]).tzinfo is not None
        assert row[1] == "active"
