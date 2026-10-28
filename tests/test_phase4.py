import base64
import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from cue.connectors import signatures
from cue.connectors.calendar import CalendarConnector
from cue.connectors.credentials import Credential as StoredCredential
from cue.connectors.gmail import GmailConnector
from cue.connectors.github import GitHubConnector
from cue.connectors.linear import LinearConnector
from cue.connectors.normalize_v1 import normalize
from cue.connectors.recall import RecallConnector
from cue.connectors.slack import SlackConnector
from cue.ingestion import process_raw
from cue.main import app


class Credential:
    def token(self):
        return "test-token"


def test_provider_normalization_preserves_acl():
    tenant = uuid4()
    gmail = normalize("gmail", {
        "mailbox": "owner@example.com",
        "message": {"id": "m1", "threadId": "t1", "internalDate": "1793181600000",
                    "historyId": "10", "snippet": "Hello", "payload": {"headers": [
                        {"name": "From", "value": "Alice <alice@example.com>"},
                        {"name": "Subject", "value": "Status"},
                    ]}},
    }, tenant)
    assert gmail.acl.principals == ("email:owner:owner@example.com",)
    assert gmail.actors == ("gmail:person:alice@example.com",)
    calendar = normalize("calendar", {
        "owner": "owner@example.com", "calendar_id": "owner@example.com",
        "event": {"id": "e1", "etag": "etag1", "updated": "2026-10-28T10:00:00Z",
                  "summary": "Planning", "attendees": [{"email": "alice@example.com"}]},
    }, tenant)
    assert set(calendar.acl.principals) == {"email:owner:owner@example.com", "email:owner:alice@example.com"}
    slack = normalize("slack", {"team_id": "T1", "event": {
        "type": "message", "channel": "C1", "ts": "1793181600.000001", "user": "U1", "text": "Hi",
    }}, tenant)
    assert slack.acl.principals == ("slack:channel:C1",)
    linear = normalize("linear", {"organizationId": "O1", "type": "Issue", "action": "update",
        "data": {"id": "I1", "title": "Bug", "team": {"id": "TEAM1"}, "updatedAt": "2026-10-28T10:00:00Z"}}, tenant)
    assert linear.acl.principals == ("linear:team:TEAM1",)
    recall = normalize("recall", {"event": "transcript.data", "data": {
        "bot": {"id": "B1", "metadata": {"attendees": ["owner@example.com"]}},
        "transcript": {"original_transcript_id": 1, "speaker_id": 2, "words": [{"text": "Hello"}]},
    }}, tenant)
    assert recall.acl.principals == ("email:owner:owner@example.com",)
    assert recall.text == "Hello"


def test_webhook_signatures_reject_tampering_and_stale_requests():
    body = b'{"event":"test"}'
    now = str(int(time.time()))
    slack_headers = {"x-slack-request-timestamp": now,
        "x-slack-signature": "v0=" + hmac.new(b"key", b"v0:" + now.encode() + b":" + body, hashlib.sha256).hexdigest()}
    assert signatures.slack(body, slack_headers, b"key")
    assert not signatures.slack(body + b"x", slack_headers, b"key")
    assert not signatures.slack(body, {**slack_headers, "x-slack-request-timestamp": "1"}, b"key")
    linear_body = json.dumps({"webhookTimestamp": int(time.time() * 1000)}).encode()
    linear_headers = {"linear-timestamp": str(int(time.time() * 1000)),
        "linear-signature": hmac.new(b"key", linear_body, hashlib.sha256).hexdigest()}
    assert signatures.linear(linear_body, linear_headers, b"key")
    assert not signatures.linear(linear_body + b"x", linear_headers, b"key")
    stale_body = json.dumps({"webhookTimestamp": 1}).encode()
    stale_headers = {"linear-timestamp": str(int(time.time() * 1000)),
        "linear-signature": hmac.new(b"key", stale_body, hashlib.sha256).hexdigest()}
    assert not signatures.linear(stale_body, stale_headers, b"key")
    key = b"whsec_" + base64.b64encode(b"recall-key")
    signed = b"msg_1." + now.encode() + b"." + body
    recall_headers = {"webhook-id": "msg_1", "webhook-timestamp": now,
        "webhook-signature": "v1," + base64.b64encode(hmac.new(b"recall-key", signed, hashlib.sha256).digest()).decode()}
    assert signatures.recall(body, recall_headers, key)
    assert not signatures.recall(body + b"x", recall_headers, key)


def test_github_deeper_events_and_writes(monkeypatch):
    calls = []
    def responder(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/installation/repositories":
            data = {"repositories": [{"id": 9, "private": True, "name": "cue", "owner": {"login": "acme"}}]}
        elif path == "/graphql":
            query = json.loads(request.content)["query"]
            is_pull = "CuePullBackfill" in query
            nodes = ([{"databaseId": 12, "number": 2, "title": "Fix", "body": "",
                       "updatedAt": "2026-10-28T10:00:00Z", "mergedAt": None,
                       "author": {"databaseId": 7}}] if is_pull else [])
            data = {"data": {"repository": {"pullRequests" if is_pull else "issues": {
                "nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}}}
        elif path == "/repos/acme/cue/commits":
            data = [{"sha": "abc", "commit": {"message": "Fix", "author": {"date": "2026-10-28T10:00:00Z"}}, "author": {"id": 7}}]
        elif path == "/repos/acme/cue/issues/comments":
            data = [{"id": 10, "updated_at": "2026-10-28T10:00:00Z", "body": "Review", "user": {"id": 7}}]
        elif path == "/repos/acme/cue/pulls/2/reviews":
            data = [{"id": 11, "submitted_at": "2026-10-28T10:00:00Z", "body": "LGTM", "user": {"id": 7}}]
        else:
            data = {"id": 1}
        return httpx.Response(200, json=data)
    connector = GitHubConnector(httpx.Client(transport=httpx.MockTransport(responder)))
    monkeypatch.setattr(connector, "_installation_token", lambda external_id: "token")
    raw = list(connector.backfill("42", datetime(2026, 10, 1, tzinfo=timezone.utc)))
    assert [connector.normalize(item, uuid4()).type for item in raw] == ["commit.pushed", "comment.snapshot", "pr.snapshot", "review.snapshot"]
    connector.create_issue("42", "acme", "cue", "Title", "Body")
    assert ("POST", "/repos/acme/cue/issues") in calls


def test_provider_clients_call_expected_apis(monkeypatch):
    def gmail_response(request):
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "owner@example.com"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(200, json={"messages": [{"id": "m1"}]})
        return httpx.Response(200, json={"id": "m1", "threadId": "t1", "internalDate": "1793181600000"})
    gmail = GmailConnector(Credential(), httpx.Client(transport=httpx.MockTransport(gmail_response)))
    gmail.authorize("owner@example.com")
    assert len(list(gmail.backfill("owner@example.com", datetime(2026, 10, 1, tzinfo=timezone.utc)))) == 1

    def calendar_response(request):
        if request.url.path.endswith("/events") and request.method == "GET":
            return httpx.Response(200, json={"items": [{"id": "e1", "updated": "2026-10-28T10:00:00Z"}]})
        return httpx.Response(200, json={"id": "e1"})
    calendar = CalendarConnector(Credential(), "owner@example.com", httpx.Client(transport=httpx.MockTransport(calendar_response)))
    calendar.authorize("owner@example.com")
    assert len(list(calendar.backfill("owner@example.com", datetime(2026, 10, 1, tzinfo=timezone.utc)))) == 1

    def slack_response(request):
        path = request.url.path
        if path.endswith("/auth.test"):
            data = {"ok": True, "team_id": "T1"}
        elif path.endswith("/conversations.list"):
            data = {"ok": True, "channels": [{"id": "C1", "is_member": True}]}
        else:
            data = {"ok": True, "messages": [{"type": "message", "ts": "1793181600.000001", "text": "Hi"}]}
        return httpx.Response(200, json=data)
    slack = SlackConnector(Credential(), httpx.Client(transport=httpx.MockTransport(slack_response)))
    slack.authorize("T1")
    assert len(list(slack.backfill("T1", datetime(2026, 10, 1, tzinfo=timezone.utc)))) == 1

    def linear_response(request):
        query = json.loads(request.content)["query"]
        if "organization" in query:
            data = {"organization": {"id": "O1"}}
        else:
            data = {"issues": {"nodes": [{"id": "I1", "updatedAt": "2026-10-28T10:00:00Z", "title": "Bug", "team": {"id": "TEAM1"}}],
                               "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        return httpx.Response(200, json={"data": data})
    linear = LinearConnector(Credential(), httpx.Client(transport=httpx.MockTransport(linear_response)))
    linear.authorize("O1")
    assert len(list(linear.backfill("O1", datetime(2026, 10, 1, tzinfo=timezone.utc)))) == 1

    bot_id = str(uuid4())
    def recall_response(request):
        if request.url.host == "files.example.com":
            return httpx.Response(200, json=[{"participant": {"id": 2}, "words": [
                {"text": "Hello", "start_timestamp": {"absolute": "2026-10-28T10:00:00Z"}}]}])
        if request.method == "GET":
            return httpx.Response(200, json={"id": bot_id, "metadata": {"attendees": ["owner@example.com"]},
                "recordings": [{"id": "R1", "media_shortcuts": {"transcript": {"data": {
                    "download_url": "https://files.example.com/transcript.json"}}}}]})
        return httpx.Response(200, json={"id": bot_id})
    recall = RecallConnector("key", "us-east-1", httpx.Client(transport=httpx.MockTransport(recall_response)))
    assert recall.create_bot("https://meet.google.com/abc-defg-hij", ["owner@example.com"])["id"]
    events = list(recall.backfill(bot_id, datetime(2026, 10, 1, tzinfo=timezone.utc)))
    assert [event["event"] for event in events] == ["bot.snapshot", "transcript.segment"]
    assert recall.normalize(events[1], uuid4()).text == "Hello"


def test_signed_webhooks_publish_only_supported_events(monkeypatch):
    published = []
    class Publisher:
        def publish(self, topic, data, **attributes):
            published.append((topic, data, attributes))
            return type("Future", (), {"result": lambda self, timeout: "ok"})()
    monkeypatch.setenv("RAW_EVENTS_TOPIC", "raw")
    monkeypatch.setenv("SLACK_SIGNING_SECRET_VERSION", "slack-secret")
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET_VERSION", "linear-secret")
    monkeypatch.setenv("RECALL_VERIFICATION_SECRET_VERSION", "recall-secret")
    monkeypatch.setenv("CALENDAR_CHANNEL_SECRET_VERSION", "calendar-secret")
    monkeypatch.setenv("SYNC_TRIGGERS_TOPIC", "sync-triggers")
    monkeypatch.setattr("cue.main.secret", lambda ref: b"key" if ref != "recall-secret" else b"whsec_" + base64.b64encode(b"recall-key"))
    monkeypatch.setattr("cue.main.pubsub_v1.PublisherClient", Publisher)
    client = TestClient(app)
    now = str(int(time.time()))
    slack_body = json.dumps({"type": "event_callback", "team_id": "T1", "event_id": "Ev1",
        "event": {"type": "message", "channel": "C1", "ts": "1793181600.000001", "text": "Hi"}}).encode()
    slack_sig = "v0=" + hmac.new(b"key", b"v0:" + now.encode() + b":" + slack_body, hashlib.sha256).hexdigest()
    assert client.post("/webhooks/slack", content=slack_body, headers={
        "X-Slack-Request-Timestamp": now, "X-Slack-Signature": slack_sig}).status_code == 200
    assert published[-1][2]["external_id"] == "T1"
    assert client.post("/webhooks/slack", content=slack_body + b"x", headers={
        "X-Slack-Request-Timestamp": now, "X-Slack-Signature": slack_sig}).status_code == 401
    linear_body = json.dumps({"type": "Issue", "organizationId": "O1", "data": {"id": "I1"},
        "webhookTimestamp": int(time.time() * 1000)}).encode()
    linear_sig = hmac.new(b"key", linear_body, hashlib.sha256).hexdigest()
    assert client.post("/webhooks/linear", content=linear_body, headers={
        "Linear-Timestamp": str(int(time.time() * 1000)), "Linear-Signature": linear_sig,
        "Linear-Delivery": "L1"}).status_code == 202
    assert published[-1][2]["source"] == "linear"
    recall_body = json.dumps({"event": "transcript.done", "data": {"bot": {"id": "B1"}}}).encode()
    recall_sig = base64.b64encode(hmac.new(b"recall-key", b"msg_1." + now.encode() + b"." + recall_body, hashlib.sha256).digest()).decode()
    assert client.post("/webhooks/recall", content=recall_body, headers={
        "Webhook-Id": "msg_1", "Webhook-Timestamp": now, "Webhook-Signature": f"v1,{recall_sig}"}).status_code == 202
    assert published[-1][2]["external_id"] == "B1"
    owner = "owner@example.com"
    calendar_sig = hmac.new(b"key", owner.encode(), hashlib.sha256).hexdigest()
    assert client.post("/webhooks/calendar", headers={
        "X-Goog-Channel-Token": f"owner=owner%40example.com&signature={calendar_sig}",
        "X-Goog-Resource-State": "exists"}).status_code == 202
    assert published[-1][2] == {"provider": "calendar", "external_id": owner}
    assert client.post("/webhooks/calendar", headers={
        "X-Goog-Channel-Token": "owner=owner%40example.com&signature=bad",
        "X-Goog-Resource-State": "exists"}).status_code == 401


def test_oauth_refresh_rotates_secret_without_logging_token(monkeypatch):
    old = {"access_token": "old", "refresh_token": "refresh", "client_id": "client",
           "client_secret": "secret", "expires_at": 1}
    versions = []
    class Store:
        def access_secret_version(self, name):
            return type("Version", (), {"payload": type("Payload", (), {"data": json.dumps(old).encode()})()})()
        def add_secret_version(self, parent, payload):
            versions.append((parent, json.loads(payload["data"])))
    def responder(request):
        assert request.url.host == "oauth2.googleapis.com"
        return httpx.Response(200, json={"access_token": "new", "refresh_token": "new-refresh", "expires_in": 3600})
    credential = StoredCredential(
        "projects/p/secrets/s/versions/latest", "gmail",
        httpx.Client(transport=httpx.MockTransport(responder)), Store(),
    )
    assert credential.token() == "new"
    assert versions[0][0] == "projects/p/secrets/s"
    assert versions[0][1]["refresh_token"] == "new-refresh"


@pytest.mark.skipif("INGEST_DATABASE_URL" not in os.environ, reason="Postgres not configured")
def test_slack_binding_prevents_cross_tenant_ingestion(monkeypatch):
    tenant, other, connection_id = uuid4(), uuid4(), uuid4()
    external_id = f"T{uuid4().hex[:10]}"
    monkeypatch.setenv("RAW_GCS_BUCKET", "test-raw")
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as db:
        db.execute("INSERT INTO tenants (id, name) VALUES (%s, 'one'), (%s, 'two')", (tenant, other))
        db.execute("INSERT INTO connector_connections (id, tenant_id, provider, external_id) VALUES (%s, %s, 'slack', %s)", (connection_id, tenant, external_id))
        db.execute("INSERT INTO source_bindings (provider, external_id, tenant_id, connection_id) VALUES ('slack', %s, %s, %s)", (external_id, tenant, connection_id))
    class Storage:
        def bucket(self, name): return self
        def blob(self, name): return self
        def upload_from_string(self, data, **kwargs): pass
    raw = {"team_id": external_id, "event": {"type": "message", "channel": "C1", "ts": "1793181600.000001", "text": "Hi"}}
    body = json.dumps(raw).encode()
    attrs = {"source": "slack", "external_id": external_id, "delivery_id": str(uuid4())}
    try:
        assert process_raw(body, attrs, os.environ["INGEST_DATABASE_URL"], Storage())
        assert not process_raw(body, attrs, os.environ["INGEST_DATABASE_URL"], Storage())
        with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as db:
            db.execute("SELECT set_config('app.tenant_id', %s, true)", (str(other),))
            assert db.execute("SELECT count(*) FROM event_log").fetchone()[0] == 0
        with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as db:
            payload = db.execute("SELECT payload FROM event_log WHERE tenant_id = %s", (tenant,)).fetchone()[0]
            assert payload["acl"]["principals"] == ["slack:channel:C1"]
    finally:
        with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as db:
            for table in ("event_outbox", "event_log", "event_dedupe", "entity_aliases", "entities"):
                db.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant,))
            db.execute("DELETE FROM source_bindings WHERE connection_id = %s", (connection_id,))
            db.execute("DELETE FROM connector_connections WHERE id = %s", (connection_id,))
            db.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (tenant, other))
