import json
import os
from datetime import datetime, time, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from cue.audit import report as audit_report
from cue.controls import switches
from cue.ingestion import process_raw
from cue.lifecycle import propagation
from cue.memory.model import QueryPlan
from cue.memory.query import query_memory
from cue.ops import status as ops_status
from cue.proactive import quiet, rules
from cue.reconcile import jobs as reconcile_jobs
from cue.runtime import scheduler, service, store
from cue.runtime.executor import ToolRegistry, ToolSpec
from cue.runtime.gateway import Completion
from cue.runtime.ingress import RuntimeRequest, submit

MIGRATION = "MIGRATION_DATABASE_URL"
NOW = datetime(2026, 10, 28, 9, 30, tzinfo=timezone.utc)


def migration_url() -> str:
    if MIGRATION not in os.environ:
        pytest.skip("Postgres integration database not configured")
    return os.environ[MIGRATION]


@pytest.fixture
def tenants():
    url = migration_url()
    a, b = uuid4(), uuid4()
    slack, github = uuid4(), uuid4()
    team = f"T-{uuid4()}"
    with psycopg.connect(url) as database:
        database.execute("INSERT INTO tenants (id, name) VALUES (%s, 'pilot-a'), (%s, 'pilot-b')",
                         (a, b))
        database.execute(
            "INSERT INTO users (tenant_id, firebase_uid, role) VALUES "
            "(%s, 'admin-a', 'admin'), (%s, 'member-a', 'member'), (%s, 'member-b', 'member'), "
            "(%s, 'admin-b', 'admin')",
            (a, a, a, b),
        )
        database.execute(
            "INSERT INTO user_principals (tenant_id, firebase_uid, principal) VALUES "
            "(%s, 'member-a', 'github:repo:1'), (%s, 'member-a', 'email:owner:alice@example.com'), "
            "(%s, 'member-b', 'github:repo:2')", (a, a, a),
        )
        database.execute(
            "INSERT INTO connector_connections (id, tenant_id, provider, external_id) VALUES "
            "(%s, %s, 'slack', %s), (%s, %s, 'github', %s)",
            (slack, a, team, github, a, f"gh-{uuid4()}"),
        )
        database.execute(
            "INSERT INTO source_bindings (provider, external_id, tenant_id, connection_id) "
            "VALUES ('slack', %s, %s, %s)", (team, a, slack),
        )
    yield SimpleNamespace(a=a, b=b, team=team, slack=slack, github=github, url=url)
    with psycopg.connect(url) as database:
        for table in (
            "paused_events", "kill_switches", "quiet_hours", "proactive_runs",
            "proactive_mutes", "proactive_rules", "deletion_tombstones",
            "access_revocations", "reconciliation_runs",
            "meeting_note_deliveries", "meeting_note_sources", "meeting_replies",
            "meeting_notes", "meeting_transcript_segments", "meeting_speaker_map",
            "meeting_participants", "meeting_sessions",
            "memory_summary_sources", "memory_summaries", "memory_edges", "memory_documents",
            "agent_approvals", "agent_tool_runs", "agent_tasks", "agent_policies",
            "agent_audit", "event_outbox", "event_dedupe", "event_log",
            "identity_entity_map", "entity_aliases", "entities",
        ):
            database.execute(f"DELETE FROM {table} WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM source_bindings WHERE external_id = %s", (team,))
        database.execute("DELETE FROM connector_connections WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM identity_claims WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM user_principals WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM users WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (a, b))


class FakeGateway:
    def __init__(self, plan: dict | None = None):
        self.plan = plan or {"tool_calls": [], "reply": "Digest [1]"}
        self.calls = 0

    def complete(self, messages, *, model_class="planner"):
        self.calls += 1
        return Completion(json.dumps(self.plan), "fake")


class Queue:
    def __init__(self):
        self.items = []

    def enqueue(self, tenant_id, task_id, delay=None):
        self.items.append((tenant_id, task_id))


class Outbound:
    def __init__(self):
        self.sent = []

    def send(self, task, text):
        self.sent.append((task["id"], text))


class EvalModel:
    def route(self, question):
        return QueryPlan("recall")

    def answer(self, question, evidence):
        return (evidence[0]["text"] + " [1]") if evidence else "No accessible evidence found."

    def summarize(self, texts, *, period):
        return " | ".join(texts)


class EvalIndex:
    def __init__(self, ids):
        self.ids = ids

    def search(self, tenant, vector, principals, limit):
        return list(reversed(self.ids))


class EvalEmbedder:
    def embed(self, value, *, query=False):
        return [0.0] * 1024


def doc(tenant, event_id, text, *, source="github", kind="pr.opened",
        visibility="restricted", principals=("github:repo:1",), when=None, facts=None):
    return {
        "tenant_id": str(tenant), "event_id": event_id, "source": source, "type": kind,
        "occurred_at": (when or NOW).isoformat(), "actors": [], "objects": [f"pr:{event_id}"],
        "facts": facts or {}, "text": text,
        "acl": {"visibility": visibility, "principals": list(principals)},
        "raw_ref": f"gs://test/{event_id}",
    }


def insert_doc(database, tenant, event_id, text, *, source="github", kind="pr.opened",
               visibility="restricted", principals=("github:repo:1",), when=None, facts=None):
    when = when or NOW
    database.execute(
        "INSERT INTO memory_documents (tenant_id, event_id, source, type, occurred_at, actors, "
        "objects, facts, text, visibility, principals, raw_ref) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (tenant, event_id, source, kind, when, [], [f"pr:{event_id}"], Jsonb(facts or {}),
         text, visibility, list(principals), f"gs://test/{event_id}"),
    )


def make_task(tenant, uid="admin-a", text="Work", key=None, source="schedule"):
    return submit(RuntimeRequest(tenant_id=tenant, source=source, requester_uid=uid,
                                 text=text, idempotency_key=key or f"p8-{uuid4()}"))[0]


def run_task(tenant, task_id, gateway, registry, outbound=None):
    return service.run_task(tenant, task_id, gateway=gateway, registry=registry,
                            outbound=outbound,
                            memory=lambda *args: {"summary": "context", "citations": []})


def test_each_proactive_rule_fires_once_and_scheduler_runs_it(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        prefs = "30 9 * * *"
        for key, kind in (("daily", "daily_digest"), ("weekly", "weekly_digest"),
                          ("stale", "stale_pr"), ("overdue", "overdue_action")):
            rules.create_rule(database, tenants.a, rule_key=key, kind=kind,
                              owner_uid="admin-a", schedule=prefs)
        insert_doc(database, tenants.a, "pr-stale", "Old PR waiting for review",
                   when=NOW - timedelta(days=3), facts={"state": "open"})
        meeting_id, note_id = uuid4(), uuid4()
        database.execute(
            "INSERT INTO meeting_sessions (tenant_id, id, meeting_url, owner_uid, status, "
            "visibility, principals, disclosure) VALUES (%s, %s, 'https://meet/x', "
            "'admin-a', 'ended', 'restricted', '{}', 'AI teammate')", (tenants.a, meeting_id),
        )
        database.execute(
            "INSERT INTO meeting_notes (tenant_id, id, meeting_id, summary, decisions, "
            "action_items, visibility, principals) VALUES (%s, %s, %s, 'notes', '[]', %s, "
            "'restricted', '{}')",
            (tenants.a, note_id, meeting_id,
             Jsonb([{"text": "File the bug", "due": "2026-10-27"}])),
        )
    queue = Queue()
    first = scheduler.tick(tenants.a, queue, now=NOW, proactive=True)
    second = scheduler.tick(tenants.a, queue, now=NOW, proactive=True)
    assert len(first) == 4 and second == []
    assert len(queue.items) == 4
    with store.tenant_connection(tenants.a, tenants.url) as database:
        tasks = database.execute(
            "SELECT count(*) FROM agent_tasks WHERE tenant_id = %s "
            "AND idempotency_key LIKE 'proactive:%%'", (tenants.a,)).fetchone()[0]
        assert tasks == 4
        assert database.execute(
            "SELECT count(*) FROM proactive_runs WHERE tenant_id = %s AND status = 'dispatched'",
            (tenants.a,)).fetchone()[0] == 4


def test_quiet_hours_defer_and_release_proactive_message(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        quiet.set_window(database, tenants.a, scope="tenant", subject="*",
                         timezone_name="UTC", start=time(22), end=time(7))
        rules.create_rule(database, tenants.a, rule_key="nightly", kind="daily_digest",
                          owner_uid="admin-a", schedule="0 23 * * *")
    night = datetime(2026, 10, 28, 23, 0, tzinfo=timezone.utc)
    assert rules.tick(tenants.a, now=night) == []
    with store.tenant_connection(tenants.a, tenants.url) as database:
        row = database.execute(
            "SELECT status, deliver_after FROM proactive_runs WHERE tenant_id = %s",
            (tenants.a,)).fetchone()
        assert row[0] == "deferred"
        assert row[1] == datetime(2026, 10, 29, 7, 0, tzinfo=timezone.utc)
        assert database.execute("SELECT count(*) FROM agent_tasks WHERE tenant_id = %s",
                                (tenants.a,)).fetchone()[0] == 0
    assert rules.tick(tenants.a, now=datetime(2026, 10, 29, 6, 30, tzinfo=timezone.utc)) == []
    released = rules.tick(tenants.a, now=datetime(2026, 10, 29, 7, 0, tzinfo=timezone.utc))
    assert len(released) == 1
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute(
            "SELECT status FROM proactive_runs WHERE tenant_id = %s", (tenants.a,)
        ).fetchone()[0] == "dispatched"


def test_user_quiet_hours_override_tenant_and_mute_skips(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        quiet.set_window(database, tenants.a, scope="tenant", subject="*",
                         timezone_name="UTC", start=time(22), end=time(7))
        quiet.set_window(database, tenants.a, scope="user", subject="admin-a",
                         timezone_name="America/Los_Angeles", start=time(23), end=time(6))
        rules.create_rule(database, tenants.a, rule_key="evening", kind="daily_digest",
                          owner_uid="admin-a", schedule="30 23 * * *")
    # 23:30 UTC is 16:30 in Los Angeles: the user window overrides the tenant window.
    evening = datetime(2026, 10, 28, 23, 30, tzinfo=timezone.utc)
    assert len(rules.tick(tenants.a, now=evening)) == 1
    with store.tenant_connection(tenants.a, tenants.url) as database:
        rules.create_rule(database, tenants.a, rule_key="morning", kind="daily_digest",
                          owner_uid="admin-a", schedule="0 8 * * *")
        rules.create_rule(database, tenants.a, rule_key="muted", kind="daily_digest",
                          owner_uid="admin-a", schedule="0 8 * * *")
        rules.mute(database, tenants.a, "admin-a", "muted")
    # 08:00 UTC is 01:00 in Los Angeles, inside the user's quiet window.
    assert rules.tick(tenants.a, now=datetime(2026, 10, 29, 8, 0, tzinfo=timezone.utc)) == []
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute(
            "SELECT count(*) FROM proactive_runs WHERE tenant_id = %s AND status = 'deferred'",
            (tenants.a,)).fetchone()[0] == 1
        assert database.execute(
            "SELECT count(*) FROM proactive_runs AS run JOIN proactive_rules AS rule "
            "ON rule.tenant_id = run.tenant_id AND rule.id = run.rule_id "
            "WHERE run.tenant_id = %s AND rule.rule_key = 'muted'", (tenants.a,)
        ).fetchone()[0] == 0
    released = rules.tick(tenants.a, now=datetime(2026, 10, 29, 13, 0, tzinfo=timezone.utc))
    assert len(released) == 1


def test_controls_and_reconciliation_are_tenant_isolated(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        switches.set_switch(database, tenants.a, scope="tenant", subject="*", paused=True,
                            actor="admin-a")
        rules.create_rule(database, tenants.a, rule_key="a-daily", kind="daily_digest",
                          owner_uid="admin-a", schedule="30 9 * * *")
        assert {item["provider"] for item in reconcile_jobs.due_connections(
            database, tenants.a, NOW)} == {"github", "slack"}
    with store.tenant_connection(tenants.b, tenants.url) as database:
        assert switches.tenant_paused(database, tenants.b) is None
        assert reconcile_jobs.due_connections(database, tenants.b, NOW) == []
        rules.create_rule(database, tenants.b, rule_key="b-daily", kind="daily_digest",
                          owner_uid="admin-b", schedule="30 9 * * *")
    assert len(rules.tick(tenants.b, now=NOW)) == 1
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute(
            "SELECT count(*) FROM agent_tasks WHERE tenant_id = %s", (tenants.a,)
        ).fetchone()[0] == 0
    reconcile_jobs.reconcile(tenants.a, tenants.github, "github", [], lambda *args: None,
                             now=NOW)
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert [item["provider"] for item in reconcile_jobs.due_connections(
            database, tenants.a, NOW)] == ["slack"]
    reconcile_jobs.reconcile(tenants.a, tenants.slack, "slack", [], lambda *args: None, now=NOW)
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert reconcile_jobs.due_connections(database, tenants.a, NOW) == []


def test_reminder_fires_once_at_its_scheduled_time(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        rules.create_rule(database, tenants.a, rule_key="remind", kind="reminder",
                          owner_uid="admin-a", next_run_at=NOW,
                          config={"message": "Ask Alice for the release date."})
    assert len(rules.tick(tenants.a, now=NOW)) == 1
    assert rules.tick(tenants.a, now=NOW) == []
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute(
            "SELECT count(*) FROM agent_tasks WHERE tenant_id = %s AND thread_ref = 'remind'",
            (tenants.a,)).fetchone()[0] == 1
        assert database.execute(
            "SELECT next_run_at FROM proactive_rules WHERE tenant_id = %s AND rule_key = 'remind'",
            (tenants.a,)).fetchone()[0] is None


def test_proactive_actions_still_need_policy_approval(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        rules.create_rule(database, tenants.a, rule_key="ticket", kind="daily_digest",
                          owner_uid="admin-a", schedule="30 9 * * *")
    task_id = rules.tick(tenants.a, now=NOW)[0]
    calls = []
    gateway = FakeGateway({"tool_calls": [{"name": "linear.create_issue",
                                           "arguments": {"title": "Digest follow-up"}}],
                           "reply": None})
    registry = ToolRegistry([ToolSpec("linear.create_issue", 2,
                                      lambda args: calls.append(args) or {"id": "L1"},
                                      "create an issue")])
    result = run_task(tenants.a, task_id, gateway, registry)
    assert result["status"] == "awaiting_approval"
    assert calls == []
    approval_id = result["approvals"][0]["id"]
    assert service.decide(tenants.a, approval_id, "admin-a", True)["status"] == "queued"
    assert run_task(tenants.a, task_id, gateway, registry)["status"] == "completed"
    assert calls == [{"title": "Digest follow-up"}]


class Blob:
    def upload_from_string(self, *args, **kwargs):
        return None


class Bucket:
    def blob(self, key):
        return Blob()


class Storage:
    def bucket(self, name):
        return Bucket()


def slack_raw(team):
    return json.dumps({"team_id": team, "event": {
        "type": "message", "text": "hello", "user": "U1", "channel": "C1",
        "ts": "1761648000.000100", "client_msg_id": "m1",
    }}).encode()


def test_kill_switch_pauses_ingestion_and_outbound_then_resumes(tenants, monkeypatch):
    monkeypatch.setenv("RAW_GCS_BUCKET", "test")
    ingest_url = os.environ.get("INGEST_DATABASE_URL", tenants.url)
    attributes = {"source": "slack", "external_id": tenants.team, "delivery_id": "d1"}
    with store.tenant_connection(tenants.a, tenants.url) as database:
        switches.set_switch(database, tenants.a, scope="connector", subject=str(tenants.slack),
                            paused=True, actor="admin-a", mode="queue")
    assert process_raw(slack_raw(tenants.team), attributes, ingest_url,
                       storage_client=Storage()) is False
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute("SELECT count(*) FROM event_log WHERE tenant_id = %s",
                                (tenants.a,)).fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM paused_events WHERE tenant_id = %s "
                                "AND replayed_at IS NULL", (tenants.a,)).fetchone()[0] == 1
        result = switches.resume(
            database, tenants.a, scope="connector", subject=str(tenants.slack), actor="admin-a",
            ingest=lambda data, attrs: process_raw(data, attrs, ingest_url,
                                                   storage_client=Storage()),
        )
        assert result["replayed"] == 1
        assert database.execute("SELECT count(*) FROM event_log WHERE tenant_id = %s",
                                (tenants.a,)).fetchone()[0] == 1
        event_id = database.execute(
            "SELECT event_id FROM event_log WHERE tenant_id = %s", (tenants.a,)
        ).fetchone()[0]
        propagation.delete_event(
            database, tenants.a, event_id, requested_by="admin-a", reason="redelivery test",
            index=SimpleNamespace(deleted=[], delete_event=lambda *args: None,
                                  delete_source=lambda *args: None),
        )
    assert process_raw(slack_raw(tenants.team), attributes, ingest_url,
                       storage_client=Storage()) is False
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute("SELECT count(*) FROM event_log WHERE tenant_id = %s",
                                (tenants.a,)).fetchone()[0] == 0

    calls = []
    gateway = FakeGateway({"tool_calls": [{"name": "slack.post_message",
                                           "arguments": {"text": "hi"}}], "reply": None})
    registry = ToolRegistry([ToolSpec("slack.post_message", 1,
                                      lambda args: calls.append(args) or {"ok": True},
                                      "post")])
    with store.tenant_connection(tenants.a, tenants.url) as database:
        switches.set_switch(database, tenants.a, scope="connector", subject=str(tenants.slack),
                            paused=True, actor="admin-a")
    task_id = make_task(tenants.a)
    blocked = run_task(tenants.a, task_id, gateway, registry)
    assert blocked["status"] == "cancelled" and calls == []
    with store.tenant_connection(tenants.a, tenants.url) as database:
        switches.resume(database, tenants.a, scope="connector", subject=str(tenants.slack),
                        actor="admin-a")
    resumed = make_task(tenants.a)
    assert run_task(tenants.a, resumed, gateway, registry)["status"] == "completed"
    assert calls == [{"text": "hi"}]


def test_tenant_kill_switch_blocks_actions_and_ingestion_drop(tenants, monkeypatch):
    monkeypatch.setenv("RAW_GCS_BUCKET", "test")
    with store.tenant_connection(tenants.a, tenants.url) as database:
        switches.set_switch(database, tenants.a, scope="tenant", subject="*",
                            paused=True, actor="admin-a", mode="drop")
        assert switches.ingestion_gate(
            database, tenants.a, tenants.slack, "slack",
            {"source": "slack"}, b"{}",
        ) == "dropped"
    task_id = make_task(tenants.a)
    result = run_task(tenants.a, task_id, FakeGateway(), ToolRegistry())
    assert result["status"] == "cancelled"


def test_deletion_removes_event_from_every_derived_store(tenants):
    event_id = "gh:delivery:delete-me"
    meeting_id, note_id = uuid4(), uuid4()
    index = SimpleNamespace(deleted=[], delete_event=lambda tenant, value: index.deleted.append(value),
                            delete_source=lambda tenant, value: None)
    with store.tenant_connection(tenants.a, tenants.url) as database:
        database.execute(
            "INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
            "VALUES (%s, %s, %s, 'github', 'pr.opened', %s)",
            (tenants.a, event_id, NOW, Jsonb({})),
        )
        database.execute("INSERT INTO event_dedupe (tenant_id, event_id) VALUES (%s, %s)",
                         (tenants.a, event_id))
        database.execute("INSERT INTO event_outbox (tenant_id, event_id, payload) VALUES (%s, %s, %s)",
                         (tenants.a, event_id, Jsonb({})))
        insert_doc(database, tenants.a, event_id, "SECRET billing incident details")
        database.execute(
            "INSERT INTO memory_edges (tenant_id, event_id, source_entity, predicate, target, "
            "valid_from, visibility, principals) VALUES (%s, %s, 'a', 'worked_on', 'b', %s, "
            "'restricted', ARRAY['github:repo:1'])",
            (tenants.a, event_id, NOW),
        )
        summary_id = uuid4()
        database.execute(
            "INSERT INTO memory_summaries (tenant_id, id, period, period_start, scope, visibility, "
            "principals, text, event_count) VALUES (%s, %s, 'day', '2026-10-28', 'all', "
            "'restricted', ARRAY['github:repo:1'], 'secret summary', 1)",
            (tenants.a, summary_id),
        )
        database.execute(
            "INSERT INTO memory_summary_sources (tenant_id, summary_id, event_id) "
            "VALUES (%s, %s, %s)", (tenants.a, summary_id, event_id),
        )
        database.execute(
            "INSERT INTO meeting_sessions (tenant_id, id, meeting_url, owner_uid, status, "
            "visibility, principals, disclosure) VALUES (%s, %s, 'https://meet/x', 'admin-a', "
            "'ended', 'restricted', '{}', 'AI teammate')", (tenants.a, meeting_id),
        )
        database.execute(
            "INSERT INTO meeting_transcript_segments (tenant_id, meeting_id, position, "
            "segment_index, speaker_id, text, started_at, ended_at) VALUES (%s, %s, 0, 's0', "
            "'spk', 'secret transcript', %s, %s)", (tenants.a, meeting_id, NOW, NOW),
        )
        database.execute(
            "INSERT INTO meeting_notes (tenant_id, id, meeting_id, summary, visibility, principals) "
            "VALUES (%s, %s, %s, 'secret notes', 'restricted', '{}')",
            (tenants.a, note_id, meeting_id),
        )
        database.execute(
            "INSERT INTO meeting_note_sources (tenant_id, note_id, meeting_id, position, quote) "
            "VALUES (%s, %s, %s, 0, 'secret transcript')",
            (tenants.a, note_id, meeting_id),
        )
        result = propagation.delete_event(
            database, tenants.a, event_id, requested_by="admin-a", reason="subject request",
            index=index,
        )
        assert result["documents"] == 1 and result["event_log"] == 1 and result["summaries"] == 1
        assert database.execute("SELECT count(*) FROM memory_documents WHERE event_id = %s",
                                (event_id,)).fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM memory_edges WHERE event_id = %s",
                                (event_id,)).fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM memory_summaries WHERE id = %s",
                                (summary_id,)).fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM event_log WHERE event_id = %s",
                                (event_id,)).fetchone()[0] == 0
        assert database.execute("SELECT count(*) FROM deletion_tombstones WHERE event_id = %s",
                                (event_id,)).fetchone()[0] == 1
    assert index.deleted == [event_id]
    with store.tenant_connection(tenants.a, tenants.url) as database:
        propagation.delete_event(
            database, tenants.a, f"meeting:{meeting_id}:segment:0", requested_by="admin-a",
            reason="transcript deletion", index=index,
        )
        assert database.execute(
            "SELECT count(*) FROM meeting_transcript_segments WHERE tenant_id = %s",
            (tenants.a,)).fetchone()[0] == 0
        assert database.execute(
            "SELECT count(*) FROM meeting_note_sources WHERE tenant_id = %s",
            (tenants.a,)).fetchone()[0] == 0
        propagation.delete_event(
            database, tenants.a, f"meeting:{meeting_id}:notes", requested_by="admin-a",
            reason="notes deletion", index=index,
        )
        assert database.execute(
            "SELECT count(*) FROM meeting_notes WHERE tenant_id = %s", (tenants.a,)
        ).fetchone()[0] == 0
    result = query_memory(
        tenants.a, "member-a", "SECRET billing incident", [], os.environ["DATABASE_URL"],
        model=EvalModel(), index=EvalIndex([event_id]), embedder=EvalEmbedder(),
    )
    assert result["citations"] == []
    assert "SECRET billing" not in result["answer"]


def test_revocation_removes_user_and_connector_access_everywhere(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        insert_doc(database, tenants.a, "gh-secret", "private github plan")
        insert_doc(database, tenants.a, "slack-secret", "private slack plan", source="slack",
                   principals=("slack:channel:C1",))
        rules.create_rule(database, tenants.a, rule_key="member-a-daily", kind="daily_digest",
                          owner_uid="member-a", schedule="30 9 * * *")
    pending = make_task(tenants.a, uid="member-a", key="revoked-member-task")
    query = lambda text: query_memory(
        tenants.a, "member-a", text, [], os.environ["DATABASE_URL"],
        model=EvalModel(), index=EvalIndex(["gh-secret", "slack-secret"]),
        embedder=EvalEmbedder(),
    )
    assert "private github plan" in query("github plan")["answer"]
    with store.tenant_connection(tenants.a, tenants.url) as database:
        propagation.revoke_user(database, tenants.a, "member-a", requested_by="admin-a",
                                reason="offboarding")
        assert database.execute(
            "SELECT count(*) FROM user_principals WHERE tenant_id = %s AND firebase_uid = 'member-a'",
            (tenants.a,)).fetchone()[0] == 0
        assert database.execute(
            "SELECT status FROM agent_tasks WHERE tenant_id = %s AND id = %s",
            (tenants.a, pending)).fetchone()[0] == "cancelled"
    assert rules.tick(tenants.a, now=NOW) == []
    with pytest.raises(PermissionError):
        query("github plan")
    with store.tenant_connection(tenants.a, tenants.url) as database:
        result = propagation.revoke_connector(database, tenants.a, tenants.github,
                                              requested_by="admin-a", reason="disconnect")
        assert result["revoked"] and result["documents"] == 1
        assert database.execute(
            "SELECT status FROM connector_connections WHERE id = %s", (tenants.github,)
        ).fetchone()[0] == "revoked"
        assert database.execute(
            "SELECT count(*) FROM memory_documents WHERE tenant_id = %s AND source = 'github'",
            (tenants.a,)).fetchone()[0] == 0
        assert database.execute(
            "SELECT count(*) FROM access_revocations WHERE tenant_id = %s", (tenants.a,)
        ).fetchone()[0] == 2
    calls = []
    registry = ToolRegistry([ToolSpec("github.read_issue", 0,
                                      lambda args: calls.append(args) or {"title": "x"},
                                      "read an issue")])
    gateway = FakeGateway({"tool_calls": [{"name": "github.read_issue", "arguments": {}}],
                           "reply": None})
    blocked = run_task(tenants.a, make_task(tenants.a), gateway, registry)
    assert blocked["status"] == "cancelled" and calls == []


def test_reconciliation_backfills_missing_and_is_idempotent(tenants):
    def backfill(tenant, event):
        with store.tenant_connection(tenant, tenants.url) as database:
            database.execute(
                "INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
                "VALUES (%s, %s, %s, 'github', 'pr.opened', %s)",
                (tenant, event["event_id"], event["occurred_at"], Jsonb({})),
            )
    with store.tenant_connection(tenants.a, tenants.url) as database:
        database.execute(
            "INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
            "VALUES (%s, 'e1', %s, 'github', 'pr.opened', %s)",
            (tenants.a, NOW, Jsonb({})),
        )
    events = [
        {"event_id": "e0", "occurred_at": (NOW - timedelta(hours=1)).isoformat()},
        {"event_id": "e1", "occurred_at": NOW.isoformat()},
    ]
    first = reconcile_jobs.reconcile(tenants.a, tenants.github, "github", events, backfill,
                                     now=NOW)
    assert first["missing"] == 1 and first["backfilled"] == 1
    assert first["out_of_order"] == ["e0"]
    second = reconcile_jobs.reconcile(tenants.a, tenants.github, "github", events, backfill,
                                      now=NOW)
    assert second["missing"] == 0 and second["backfilled"] == 0
    with store.tenant_connection(tenants.a, tenants.url) as database:
        assert database.execute("SELECT count(*) FROM event_log WHERE tenant_id = %s",
                                (tenants.a,)).fetchone()[0] == 2
        runs = database.execute(
            "SELECT status, missing_count, backfilled_count FROM reconciliation_runs "
            "WHERE tenant_id = %s ORDER BY started_at", (tenants.a,)).fetchall()
    assert runs == [("completed", 1, 1), ("completed", 0, 0)]


def test_audit_export_is_tenant_scoped_and_permissioned(tenants):
    with psycopg.connect(tenants.url) as database:
        database.execute(
            "INSERT INTO agent_audit (tenant_id, actor, action, decision, detail, created_at) "
            "VALUES (%s, 'admin-a', 'ingress', 'created', '{}', %s), "
            "(%s, 'admin-a', 'policy', 'auto', '{}', %s), "
            "(%s, 'outside', 'ingress', 'created', '{}', %s), "
            "(%s, 'admin-a', 'ingress', 'created', '{}', %s)",
            (tenants.a, NOW, tenants.a, NOW + timedelta(hours=1),
             tenants.b, NOW, tenants.a, NOW + timedelta(days=2)),
        )
    exported = audit_report.export_audit(
        tenants.a, "admin-a", NOW - timedelta(minutes=1), NOW + timedelta(hours=2),
    )
    assert [item["action"] for item in exported["records"]] == ["ingress", "policy"]
    assert all(item["actor"] != "outside" for item in exported["records"])
    csv_text = audit_report.export_audit(
        tenants.a, "admin-a", NOW - timedelta(minutes=1), NOW + timedelta(hours=2), fmt="csv",
    )
    assert csv_text.startswith("id,task_id,actor,action")
    assert "outside" not in csv_text
    with psycopg.connect(tenants.url) as database:
        assert database.execute(
            "SELECT count(*) FROM agent_audit WHERE tenant_id = %s AND action = 'export'",
            (tenants.a,)).fetchone()[0] == 2
    with pytest.raises(PermissionError):
        audit_report.export_audit(tenants.a, "member-a", NOW - timedelta(minutes=1),
                                  NOW + timedelta(hours=2))


def test_health_access_report_and_pilot_status(tenants):
    from fastapi.testclient import TestClient
    from cue.main import app

    client = TestClient(app)
    assert client.get("/healthz").json()["status"] == "ok"
    assert client.get("/readyz").json()["checks"]["postgres"] == "ok"
    with store.tenant_connection(tenants.a, tenants.url) as database:
        insert_doc(database, tenants.a, "visible", "visible work")
        switches.set_switch(database, tenants.a, scope="tenant", subject="*", paused=False,
                            actor="admin-a")
    report = audit_report.access_report(
        tenants.a, "admin-a", tools=[{"name": "memory.query", "tier": 0}],
    )
    assert report["users"][0]["role"] == "admin"
    assert report["connectors"][0]["provider"] in {"github", "slack"}
    assert report["can_read"]["totals"]["documents"] == 1
    assert report["can_do"] == [{"name": "memory.query", "tier": 0}]
    with pytest.raises(PermissionError):
        audit_report.access_report(tenants.a, "member-a")
    status = ops_status.tenant_status(tenants.a, "admin-a")
    assert status["tenant_id"] == str(tenants.a)
    assert status["paused"] == []


def test_eval_set_is_grounded_and_has_zero_permission_leaks(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        insert_doc(database, tenants.a, "billing", "Billing fix shipped on Friday",
                   visibility="public", principals=())
        insert_doc(database, tenants.a, "secret", "SECRET acquisition plan for Project X")
        insert_doc(database, tenants.a, "alice", "Alice owns the billing service")
    cases = [
        ("what shipped on friday", "billing"),
        ("what is the acquisition plan", "secret"),
        ("who owns billing", "alice"),
    ]
    for question, expected in cases:
        result = query_memory(
            tenants.a, "member-a", question, [], os.environ["DATABASE_URL"],
            model=EvalModel(), index=EvalIndex(["billing", "secret", "alice"]),
            embedder=EvalEmbedder(),
        )
        assert result["citations"], question
        assert any(item["event_id"] == expected for item in result["citations"])
        assert "[" in result["answer"]
    leaks = 0
    for question, _ in cases:
        result = query_memory(
            tenants.a, "member-b", question, [], os.environ["DATABASE_URL"],
            model=EvalModel(), index=EvalIndex(["billing", "secret", "alice"]),
            embedder=EvalEmbedder(),
        )
        leaks += sum(1 for item in result["citations"] if item["event_id"] in {"secret", "alice"})
    assert leaks == 0


def test_end_to_end_pilot_proactive_reconcile_delete_and_revoke(tenants):
    with store.tenant_connection(tenants.a, tenants.url) as database:
        rules.create_rule(database, tenants.a, rule_key="daily", kind="daily_digest",
                          owner_uid="admin-a", schedule="30 9 * * *")
    task_id = rules.tick(tenants.a, now=NOW)[0]
    outbound = Outbound()
    result = run_task(tenants.a, task_id, FakeGateway({"tool_calls": [], "reply": "Digest [1]"}),
                      ToolRegistry(), outbound)
    assert result["status"] == "completed" and outbound.sent
    assert rules.tick(tenants.a, now=NOW) == []

    def backfill(tenant, event):
        with store.tenant_connection(tenant, tenants.url) as database:
            database.execute(
                "INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
                "VALUES (%s, %s, %s, 'github', 'pr.opened', %s)",
                (tenant, event["event_id"], event["occurred_at"], Jsonb({})),
            )
    missing = reconcile_jobs.reconcile(
        tenants.a, tenants.github, "github",
        [{"event_id": "pilot-1", "occurred_at": NOW.isoformat()}], backfill, now=NOW,
    )
    assert missing["backfilled"] == 1
    with store.tenant_connection(tenants.a, tenants.url) as database:
        insert_doc(database, tenants.a, "pilot-1", "pilot secret")
        propagation.delete_event(database, tenants.a, "pilot-1", requested_by="admin-a",
                                 reason="pilot cleanup")
        propagation.revoke_user(database, tenants.a, "member-b", requested_by="admin-a",
                                reason="pilot offboarding")
    report = audit_report.access_report(tenants.a, "admin-a")
    assert report["revocations"][0]["kind"] == "user"
    assert report["can_read"]["totals"]["documents"] == 0
