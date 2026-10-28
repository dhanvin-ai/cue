import hashlib
import hmac
import json
import os
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from cue.main import app
from cue.runtime import context as context_builder
from cue.runtime import cron, policy, service, store
from cue.runtime.executor import ToolRegistry, ToolSpec
from cue.runtime.gateway import Completion, LiteLLMGateway, ModelUnavailable
from cue.runtime.ingress import RuntimeRequest, from_email, from_slack, from_web, submit

MIGRATION = "MIGRATION_DATABASE_URL"


def migration_url() -> str:
    if MIGRATION not in os.environ:
        pytest.skip("Postgres integration database not configured")
    return os.environ[MIGRATION]


@pytest.fixture
def tenants():
    url = migration_url()
    first, second = uuid4(), uuid4()
    team = f"T-{uuid4()}"
    connection_id = uuid4()
    with psycopg.connect(url) as database:
        database.execute("INSERT INTO tenants (id, name) VALUES (%s, 'first'), (%s, 'second')",
                         (first, second))
        database.execute(
            "INSERT INTO users (tenant_id, firebase_uid, role) VALUES "
            "(%s, 'member-a', 'member'), (%s, 'admin-a', 'admin'), (%s, 'member-b', 'member')",
            (first, first, second),
        )
        database.execute(
            "INSERT INTO user_principals (tenant_id, firebase_uid, principal) VALUES (%s, 'member-a', 'slack:channel:C1')",
            (first,),
        )
        database.execute(
            "INSERT INTO connector_connections (id, tenant_id, provider, external_id) VALUES (%s, %s, 'slack', %s)",
            (connection_id, first, team),
        )
        database.execute(
            "INSERT INTO source_bindings (provider, external_id, tenant_id, connection_id) VALUES ('slack', %s, %s, %s)",
            (team, first, connection_id),
        )
    yield SimpleNamespace(a=first, b=second, team=team, connection=connection_id)
    with psycopg.connect(url) as database:
        database.execute("DELETE FROM agent_audit WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM agent_tasks WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM agent_policies WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM memory_summary_sources WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM memory_documents WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM source_bindings WHERE external_id = %s", (team,))
        database.execute("DELETE FROM connector_connections WHERE id = %s", (connection_id,))
        database.execute("DELETE FROM user_principals WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM users WHERE tenant_id IN (%s, %s)", (first, second))
        database.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (first, second))


class FakeGateway:
    def __init__(self, plan: dict | None = None, answer: str = "Answer with citation [1]"):
        self.plan = plan or {"tool_calls": [], "reply": "Answered from context"}
        self.answer = answer
        self.calls: list[str] = []

    def complete(self, messages, *, model_class="planner"):
        self.calls.append(model_class)
        if model_class == "planner":
            return Completion(json.dumps(self.plan), "fake-primary")
        return Completion(self.answer, "fake-primary")


def make_task(tenant, uid="member-a", text="What shipped?", key=None, source="web"):
    request = RuntimeRequest(tenant_id=tenant, source=source, requester_uid=uid, text=text,
                             idempotency_key=key or f"k-{uuid4()}")
    return submit(request)[0]


def registry_with(tool: str, tier: int, handler):
    return ToolRegistry([ToolSpec(tool, tier, handler, "test tool")])


def run(tenant, task_id, gateway, registry, outbound=None):
    return service.run_task(tenant, task_id, gateway=gateway, registry=registry,
                            outbound=outbound,
                            memory=lambda *args: {"summary": "context", "citations": []})


def test_policy_uses_pdf_tiers_and_tenant_overrides(tenants):
    with store.tenant_connection(tenants.a) as database:
        assert policy.decide(database, tenants.a, "github.read_issue", 0, "member-a").mode == "auto"
        assert policy.decide(database, tenants.a, "slack.post_message", 1, "member-a").mode == "auto"
        assert policy.decide(database, tenants.a, "linear.create_issue", 2, "member-a").mode == "approve"
        assert policy.decide(database, tenants.a, "gmail.send", 3, "member-a").mode == "approve"
        assert policy.decide(database, tenants.a, "github.delete_repo", 4, "member-a").forbidden

    with psycopg.connect(migration_url()) as admin:
        admin.execute(
            "INSERT INTO agent_policies (tenant_id, scope, subject, mode) VALUES "
            "(%s, 'tool', 'linear.create_issue', 'auto'), (%s, 'person', 'member-a', 'deny')",
            (tenants.a, tenants.a),
        )
    with store.tenant_connection(tenants.a) as database:
        assert policy.decide(database, tenants.a, "linear.create_issue", 2, "member-a").mode == "deny"
        assert policy.decide(database, tenants.a, "linear.create_issue", 2, "admin-a").mode == "auto"
        # Admin overrides cannot widen external or prohibited tiers.
        assert policy.decide(database, tenants.a, "gmail.send", 3, "member-a").mode == "approve"


def test_tier_two_needs_approval_while_tier_one_runs_automatically(tenants):
    calls = []
    gateway = FakeGateway({"tool_calls": [{"name": "linear.create_issue",
                                           "arguments": {"title": "Bug"}}], "reply": None})
    registry = registry_with("linear.create_issue", 2, lambda args: calls.append(args) or {"id": "L1"})

    task_id = make_task(tenants.a, text="File a bug")
    result = run(tenants.a, task_id, gateway, registry)
    assert result["status"] == "awaiting_approval"
    assert calls == []
    assert result["approvals"][0]["status"] == "pending"

    approval_id = result["approvals"][0]["id"]
    assert service.decide(tenants.a, approval_id, "member-a", True)["status"] == "queued"
    assert run(tenants.a, task_id, gateway, registry)["status"] == "completed"
    assert len(calls) == 1

    auto_gateway = FakeGateway({"tool_calls": [{"name": "slack.post_message",
                                                "arguments": {"channel": "C1", "text": "hi"}}], "reply": None})
    auto_registry = registry_with("slack.post_message", 1, lambda args: {"ok": True})
    auto_task = make_task(tenants.a, text="Post it")
    assert run(tenants.a, auto_task, auto_gateway, auto_registry)["status"] == "completed"


def test_prohibited_tier_never_executes(tenants):
    calls = []
    gateway = FakeGateway({"tool_calls": [{"name": "github.delete_repo", "arguments": {}}], "reply": None})
    registry = registry_with("github.delete_repo", 4, lambda args: calls.append(args))
    result = run(tenants.a, make_task(tenants.a), gateway, registry)
    assert result["status"] == "completed"
    assert calls == []
    with store.tenant_connection(tenants.a) as database:
        decisions = [row[0] for row in database.execute(
            "SELECT decision FROM agent_audit WHERE tenant_id = %s AND action = 'policy'", (tenants.a,))]
    assert decisions == ["deny"]


def test_tenant_isolation_for_tasks_approvals_and_audit(tenants):
    task_id = make_task(tenants.a, key="shared-key")
    with store.tenant_connection(tenants.b) as database:
        assert store.get_task(database, tenants.b, task_id) is None
        assert database.execute("SELECT count(*) FROM agent_tasks").fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM agent_audit").fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM agent_approvals").fetchone()[0] == 0
    with store.tenant_connection(tenants.a) as database:
        assert store.get_task(database, tenants.a, task_id) is not None


def test_task_retries_then_reuses_completed_tool_run(tenants):
    attempts = {"count": 0}

    def flaky(arguments):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("transient")
        return {"ok": True}

    gateway = FakeGateway({"tool_calls": [{"name": "slack.post_message", "arguments": {"text": "x"}}],
                           "reply": None})
    registry = registry_with("slack.post_message", 1, flaky)
    task_id = make_task(tenants.a, text="Retry me")
    moment = datetime.now(timezone.utc)

    first = run(tenants.a, task_id, gateway, registry)
    assert first["status"] == "queued" and first["attempts"] == 1
    second = run(tenants.a, task_id, gateway, registry)
    assert second["status"] == "queued" and second["attempts"] == 2
    third = service.run_task(
        tenants.a, task_id, gateway=gateway, registry=registry, now=moment + timedelta(seconds=60),
        memory=lambda *args: {"summary": "context", "citations": []})
    assert third["status"] == "completed"
    assert attempts["count"] == 3

    again = run(tenants.a, task_id, gateway, registry)
    assert again["status"] == "completed"
    assert attempts["count"] == 3
    with store.tenant_connection(tenants.a) as database:
        rows = database.execute(
            "SELECT status FROM agent_tool_runs WHERE tenant_id = %s AND task_id = %s",
            (tenants.a, task_id)).fetchall()
        assert rows == [("completed",)]


def test_duplicate_ingress_is_one_task(tenants):
    request = from_web(tenants.a, "member-a", {"text": "status?", "request_id": "req-1"})
    first, created_first = submit(request)
    second, created_second = submit(request)
    assert first == second
    assert created_first and not created_second


def test_web_slack_and_email_reach_the_same_runtime(tenants, monkeypatch):
    monkeypatch.setenv("SLACK_SIGNING_SECRET_VERSION", "slack-secret")
    monkeypatch.setenv("EMAIL_INGRESS_SECRET_VERSION", "email-secret")
    monkeypatch.setattr("cue.main.secret", lambda ref: b"secret")
    monkeypatch.setattr("cue.main.auth.verify_id_token", lambda token: {"uid": token})
    client = TestClient(app)

    headers = {"Authorization": "Bearer member-a"}
    web = client.post(f"/v1/tenants/{tenants.a}/agent/requests",
                      json={"text": "What merged?", "request_id": "web-1"}, headers=headers)
    assert web.status_code == 202

    slack_body = json.dumps({
        "type": "event_callback", "team_id": tenants.team,
        "event": {"type": "app_mention", "user": "member-a", "text": "<@U9> what merged?",
                  "channel": "C1", "ts": "1700000000.0001", "client_msg_id": "slack-1"},
    }).encode()
    timestamp = str(int(time.time()))
    slack_signature = "v0=" + hmac.new(b"secret", b"v0:" + timestamp.encode() + b":" + slack_body,
                                       hashlib.sha256).hexdigest()
    slack = client.post("/webhooks/slack/agent", content=slack_body, headers={
        "x-slack-request-timestamp": timestamp, "x-slack-signature": slack_signature,
        "content-type": "application/json"})
    assert slack.status_code == 200 and slack.json()["accepted"] is True

    email_body = json.dumps({"tenant_id": str(tenants.a), "firebase_uid": "member-a",
                             "message_id": "email-1", "subject": "Status", "body": "what merged?"}).encode()
    email_signature = "sha256=" + hmac.new(b"secret", email_body, hashlib.sha256).hexdigest()
    email = client.post("/webhooks/email/agent", content=email_body,
                        headers={"X-Cue-Signature": email_signature, "content-type": "application/json"})
    assert email.status_code == 200 and email.json()["accepted"] is True

    task_ids = {"web": web.json()["task_id"], "slack": slack.json()["task_id"],
                "email": email.json()["task_id"]}
    from uuid import UUID

    gateway = FakeGateway()
    for source, raw_id in task_ids.items():
        result = service.run_task(
            tenants.a, UUID(raw_id), gateway=gateway, registry=ToolRegistry(),
            memory=lambda *args: {"summary": "context " + source, "citations": []})
        assert result["status"] == "completed"
        assert result["source"] == source

    with store.tenant_connection(tenants.a) as database:
        assert database.execute("SELECT count(*) FROM agent_tasks").fetchone()[0] == 3


def test_model_gateway_falls_back_to_second_provider(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "https://gateway.example")
    seen = []

    def responder(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "primary":
            return httpx.Response(503, json={"error": "down"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "second"}}]})

    gateway = LiteLLMGateway(models=["primary", "fallback"],
                             client=httpx.Client(transport=httpx.MockTransport(responder)))
    assert gateway.complete([{"role": "user", "content": "hi"}]) == Completion("second", "fallback")
    assert seen == ["primary", "fallback"]

    broken = LiteLLMGateway(models=["primary", "fallback"], client=httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500))))
    with pytest.raises(ModelUnavailable):
        broken.complete([{"role": "user", "content": "hi"}])


def test_scheduler_dispatches_due_tasks_and_recurring_tasks(tenants):
    from cue.runtime.queue import LocalQueue
    from cue.runtime.scheduler import tick

    task_id = make_task(tenants.a, key="due-1")
    queue = LocalQueue()
    assert tick(tenants.a, queue) == [task_id]
    assert queue.drain() == [(tenants.a, task_id, 0)]
    assert tick(tenants.a, queue) == []

    next_run = cron.next_after("0 9 * * 1-5", datetime(2026, 10, 28, 10, 0, tzinfo=timezone.utc))
    assert next_run == datetime(2026, 10, 29, 9, 0, tzinfo=timezone.utc)


def test_context_builder_passes_requester_and_participants(tenants, monkeypatch):
    captured = {}

    def fake_query(tenant_id, requester, question, participants, database_url, **kwargs):
        captured.update(tenant=tenant_id, requester=requester, participants=participants)
        return {"route": "recall", "answer": "evidence", "citations": [{"event_id": "e1"}]}

    monkeypatch.setattr(context_builder, "query_memory", fake_query)
    result = context_builder.build_context(tenants.a, "member-a", "what merged?", ["member-b"])
    assert result["summary"] == "evidence"
    assert captured == {"tenant": tenants.a, "requester": "member-a", "participants": ["member-b"]}
