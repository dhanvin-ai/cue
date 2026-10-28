"""Playwright API journey across the Phase 1–5 backend boundaries."""

import base64
import hashlib
import hmac
import json
import os
import socket
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import psycopg
import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from cue.ingestion import process_raw
from cue.main import app
from cue.memory.project import project_event
from cue.memory.summary import run_rollup
from cue.memory.vector import QdrantIndex
from cue.outbox import publish_pending


database_services = pytest.mark.skipif(
    not all(os.getenv(name) for name in (
        "MIGRATION_DATABASE_URL", "DATABASE_URL", "INGEST_DATABASE_URL", "QDRANT_URL"
    )), reason="Playwright E2E needs migrated Postgres and Qdrant",
)


class Publisher:
    def __init__(self):
        self.messages = []

    def publish(self, topic, data, **attributes):
        self.messages.append((topic, data, attributes))
        return self

    def result(self, timeout=None):
        return "test-message-id"


class Storage:
    def __init__(self):
        self.objects = {}
        self.key = None

    def bucket(self, name):
        return self

    def blob(self, key):
        self.key = key
        return self

    def upload_from_string(self, data, **kwargs):
        self.objects[self.key] = data


class ModelHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/v1/embeddings":
            result = {"data": [{"embedding": [1.0] + [0.0] * 1023}]}
        elif self.path == "/v1/chat/completions":
            question = body["messages"][1]["content"]
            if body.get("response_format"):
                route = "count" if question.startswith("How many") else (
                    "period" if question.startswith("Summarize today") else "recall"
                )
                plan = {"route": route}
                if route == "count":
                    plan.update(source="github", event_type="issue.opened")
                if route == "period":
                    today = datetime.now(timezone.utc).date()
                    plan.update(period="day", since=today.isoformat() + "T00:00:00Z",
                                until=(today + timedelta(days=1)).isoformat() + "T00:00:00Z")
                content = json.dumps(plan)
            elif body["messages"][0]["content"].startswith("Summarize these team events"):
                content = "Daily summary: " + json.loads(question)[0]
            else:
                content = json.loads(question)["evidence"][0]["text"] + " [1]"
            result = {"choices": [{"message": {"content": content}}]}
        else:
            self.send_error(404)
            return
        data = json.dumps(result).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass


@contextmanager
def _services():
    model = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
    model_thread = threading.Thread(target=model.serve_forever, daemon=True)
    model_thread.start()
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    api_thread = threading.Thread(target=server.run, daemon=True)
    api_thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not api_thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test API did not start")
            time.sleep(0.02)
        yield f"http://127.0.0.1:{port}", f"http://127.0.0.1:{model.server_port}"
    finally:
        server.should_exit = True
        api_thread.join(timeout=10)
        model.shutdown()
        model.server_close()
        model_thread.join(timeout=10)


def _token(token):
    return {"Authorization": f"Bearer {token}"}


@database_services
def test_signed_github_delivery_to_acl_filtered_memory(monkeypatch):
    import cue.main as main

    admin = os.environ["MIGRATION_DATABASE_URL"]
    ingest = os.environ["INGEST_DATABASE_URL"]
    tenant, other, connection_id = uuid4(), uuid4(), uuid4()
    installation_id = int.from_bytes(os.urandom(4), "big") + 1
    repo_id = int.from_bytes(os.urandom(4), "big") + 1
    principal = f"github:repo:{repo_id}"
    publisher, storage = Publisher(), Storage()
    monkeypatch.setattr(main, "secret", lambda reference: b"test-signing-key")
    monkeypatch.setattr(main.pubsub_v1, "PublisherClient", lambda: publisher)
    monkeypatch.setattr(main.firebase_admin, "get_app", lambda: object())

    def verify(token):
        if token not in {"alice-token", "bob-token"}:
            raise ValueError("Invalid test token")
        return {"uid": token.removesuffix("-token")}

    monkeypatch.setattr(main.auth, "verify_id_token", verify)
    for name in ("GITHUB_WEBHOOK_SECRET_VERSION", "SLACK_SIGNING_SECRET_VERSION",
                 "LINEAR_WEBHOOK_SECRET_VERSION", "RECALL_VERIFICATION_SECRET_VERSION",
                 "CALENDAR_CHANNEL_SECRET_VERSION"):
        monkeypatch.setenv(name, "test-secret-ref")
    monkeypatch.setenv("RAW_EVENTS_TOPIC", "raw-test")
    monkeypatch.setenv("SYNC_TRIGGERS_TOPIC", "sync-test")
    monkeypatch.setenv("RAW_GCS_BUCKET", "cue-e2e")
    monkeypatch.setenv("MEMORY_SMALL_MODEL", "test-small")
    with psycopg.connect(admin) as db:
        db.execute("INSERT INTO tenants (id, name) VALUES (%s, 'e2e'), (%s, 'other')", (tenant, other))
        db.execute("INSERT INTO users (tenant_id, firebase_uid, role) VALUES "
                   "(%s, 'alice', 'member'), (%s, 'bob', 'member')", (tenant, tenant))
        db.execute("INSERT INTO user_principals (tenant_id, firebase_uid, principal) "
                   "VALUES (%s, 'alice', %s)", (tenant, principal))
        db.execute("INSERT INTO connector_connections (id, tenant_id, provider, external_id) "
                   "VALUES (%s, %s, 'github', %s)", (connection_id, tenant, str(installation_id)))
        db.execute("INSERT INTO github_installation_map (installation_id, tenant_id, connection_id) "
                   "VALUES (%s, %s, %s)", (installation_id, tenant, connection_id))
    try:
        with _services() as (base_url, model_url):
            monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", model_url)
            monkeypatch.setenv("EMBEDDING_BASE_URL", model_url)
            with sync_playwright() as playwright:
                request = playwright.request.new_context(base_url=base_url)
                try:
                    assert request.get("/healthz").json() == {"status": "ok"}
                    me = f"/v1/tenants/{tenant}/me"
                    assert request.get(me).status == 401
                    assert request.get(me, headers=_token("wrong")).status == 401
                    assert request.get(me, headers=_token("alice-token")).json()["role"] == "member"
                    assert request.get(f"/v1/tenants/{other}/me", headers=_token("alice-token")).status == 403

                    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                    delivery = str(uuid4())
                    source_url = "https://github.com/example/cue/issues/7"
                    raw = {"action": "opened", "installation": {"id": installation_id},
                           "repository": {"id": repo_id, "private": True},
                           "issue": {"id": 7, "number": 7, "title": "Auth decision",
                                     "body": "Use tenant scoped memory", "state": "open",
                                     "updated_at": now, "html_url": source_url,
                                     "user": {"id": 9}}}
                    body = json.dumps(raw).encode()
                    headers = {"Content-Type": "application/json", "X-GitHub-Event": "issues",
                               "X-GitHub-Delivery": delivery,
                               "X-Hub-Signature-256": "sha256=" + hmac.new(
                                   b"test-signing-key", body, hashlib.sha256).hexdigest()}
                    assert request.post("/webhooks/github", data=body,
                                        headers={**headers, "X-Hub-Signature-256": "sha256=bad"}).status == 401
                    assert publisher.messages == []
                    accepted = request.post("/webhooks/github", data=body, headers=headers)
                    assert accepted.status == 202 and accepted.json() == {"accepted": True}
                    topic, raw_body, raw_attrs = publisher.messages.pop()
                    assert topic == "raw-test" and raw_body == body
                    assert process_raw(raw_body, raw_attrs, ingest, storage)
                    assert not process_raw(raw_body, raw_attrs, ingest, storage)
                    assert len(storage.objects) == 1
                    assert publish_pending(ingest, publisher, "canonical-test") == 1
                    assert publish_pending(ingest, publisher, "canonical-test") == 0
                    topic, canonical_body, canonical_attrs = publisher.messages.pop()
                    assert topic == "canonical-test"
                    event = json.loads(canonical_body)
                    assert event["raw_ref"].startswith("gs://cue-e2e/")
                    assert event["acl"] == {"visibility": "restricted", "principals": [principal]}
                    assert project_event(canonical_body, canonical_attrs, ingest)
                    assert not project_event(canonical_body, canonical_attrs, ingest)

                    query = f"/v1/tenants/{tenant}/memory/query"
                    count = {"question": "How many issues opened?"}
                    assert request.post(query, data=count, headers=_token("alice-token")).json()["answer"] == "1"
                    assert request.post(query, data=count, headers=_token("bob-token")).json() == {
                        "route": "count", "answer": "0", "citations": []}
                    assert request.post(query, data={**count, "participants": ["bob"]},
                                        headers=_token("alice-token")).json()["answer"] == "0"
                    assert request.post(query, data=count, headers=_token("wrong")).status == 401
                    assert request.post(f"/v1/tenants/{other}/memory/query", data=count,
                                        headers=_token("alice-token")).status == 403

                    recall = {"question": "What was the auth decision?"}
                    found = request.post(query, data=recall, headers=_token("alice-token")).json()
                    assert found["route"] == "recall"
                    assert found["citations"][0]["url"] == source_url
                    assert found["citations"][0]["event_id"] == f"gh:delivery:{delivery}"
                    assert "[1]" in found["answer"]
                    hidden = request.post(query, data=recall, headers=_token("bob-token")).json()
                    assert hidden == {"route": "recall", "answer": "No accessible evidence found.",
                                      "citations": []}
                    assert run_rollup(tenant, "day", datetime.now(timezone.utc).date(), ingest) == 1
                    summary = request.post(query, data={"question": "Summarize today"},
                                           headers=_token("alice-token")).json()
                    assert summary["route"] == "period"
                    assert summary["citations"][0]["sources"][0]["event_id"] == f"gh:delivery:{delivery}"
                    assert request.post(query, data={"question": "Summarize today"},
                                        headers=_token("bob-token")).json()["citations"] == []
                finally:
                    request.dispose()
    finally:
        with psycopg.connect(admin) as db:
            for table in ("memory_summaries", "memory_edges", "memory_documents", "event_outbox",
                          "event_log", "event_dedupe", "entity_aliases", "entities",
                          "user_principals", "github_installation_map", "connector_connections", "users"):
                db.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant,))
            db.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (tenant, other))
        index = QdrantIndex()
        index._request("DELETE", f"/collections/{index.collection(tenant)}")


def test_playwright_rejects_bad_vendor_signatures(monkeypatch):
    import cue.main as main

    publisher = Publisher()
    monkeypatch.setattr(main, "secret", lambda reference: b"test-signing-key")
    monkeypatch.setattr(main.pubsub_v1, "PublisherClient", lambda: publisher)
    for name in ("SLACK_SIGNING_SECRET_VERSION", "LINEAR_WEBHOOK_SECRET_VERSION",
                 "RECALL_VERIFICATION_SECRET_VERSION", "CALENDAR_CHANNEL_SECRET_VERSION"):
        monkeypatch.setenv(name, "test-secret-ref")
    monkeypatch.setenv("RAW_EVENTS_TOPIC", "raw-test")
    monkeypatch.setenv("SYNC_TRIGGERS_TOPIC", "sync-test")
    now = str(int(time.time()))
    with _services() as (base_url, _):
        with sync_playwright() as playwright:
            request = playwright.request.new_context(base_url=base_url)
            try:
                slack = json.dumps({"type": "event_callback", "team_id": "T1", "event_id": "E1",
                                    "event": {"type": "message", "channel": "C1",
                                              "ts": now + ".000001", "text": "Decision"}}).encode()
                slack_headers = {"X-Slack-Request-Timestamp": now,
                                 "X-Slack-Signature": "v0=" + hmac.new(
                                     b"test-signing-key", b"v0:" + now.encode() + b":" + slack,
                                     hashlib.sha256).hexdigest()}
                assert request.post("/webhooks/slack", data=slack, headers=slack_headers).json() == {"accepted": True}
                assert request.post("/webhooks/slack", data=slack + b" ", headers=slack_headers).status == 401
                linear = json.dumps({"type": "Issue", "organizationId": "O1",
                                     "webhookTimestamp": int(time.time() * 1000),
                                     "data": {"id": "I1"}}).encode()
                linear_headers = {"Linear-Signature": hmac.new(
                    b"test-signing-key", linear, hashlib.sha256).hexdigest()}
                assert request.post("/webhooks/linear", data=linear, headers=linear_headers).status == 202
                assert request.post("/webhooks/linear", data=linear + b" ", headers=linear_headers).status == 401
                recall_key = b"whsec_" + base64.b64encode(b"recall-test-key")
                monkeypatch.setattr(main, "secret", lambda reference: recall_key)
                recall = b'{"event":"transcript.done","data":{"bot":{"id":"B1"}}}'
                recall_sig = base64.b64encode(hmac.new(
                    b"recall-test-key", b"msg_1." + now.encode() + b"." + recall,
                    hashlib.sha256).digest()).decode()
                recall_headers = {"Webhook-Id": "msg_1", "Webhook-Timestamp": now,
                                  "Webhook-Signature": "v1," + recall_sig}
                assert request.post("/webhooks/recall", data=recall, headers=recall_headers).status == 202
                assert request.post("/webhooks/recall", data=recall + b" ", headers=recall_headers).status == 401
                monkeypatch.setattr(main, "secret", lambda reference: b"test-signing-key")
                owner = "owner@example.com"
                channel_token = "owner=" + owner + "&signature=" + hmac.new(
                    b"test-signing-key", owner.encode(), hashlib.sha256).hexdigest()
                calendar_headers = {"X-Goog-Channel-Token": channel_token,
                                    "X-Goog-Resource-State": "exists"}
                assert request.post("/webhooks/calendar", headers=calendar_headers).status == 202
                assert request.post("/webhooks/calendar", headers={
                    **calendar_headers, "X-Goog-Channel-Token": "owner=" + owner + "&signature=bad"
                }).status == 401
                assert [attributes["source"] for _, _, attributes in publisher.messages[:3]] == [
                    "slack", "linear", "recall"]
                assert publisher.messages[3][0] == "sync-test"
            finally:
                request.dispose()
