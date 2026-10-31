import json
import os
from datetime import date, datetime, timezone
from uuid import uuid4

import httpx
import psycopg
import pytest
from psycopg.types.json import Jsonb

from cue.memory.model import QueryPlan, SmallModel
from cue.memory.project import project_event
from cue.memory.query import query_memory
from cue.memory.summary import run_rollup
from cue.memory.vector import QdrantIndex
from cue.connectors.github import GitHubConnector


class Model:
    def route(self, question):
        if question == "count":
            return QueryPlan("count", event_type="pr.merged")
        if question == "period":
            return QueryPlan("period", period="day", since=datetime(2026, 10, 28, tzinfo=timezone.utc),
                             until=datetime(2026, 10, 29, tzinfo=timezone.utc))
        return QueryPlan("recall")

    def answer(self, question, evidence):
        return evidence[0]["text"] + " [1]"

    def summarize(self, texts, *, period):
        return " | ".join(texts)


class Embedder:
    def __init__(self):
        self.calls = []

    def embed(self, value, *, query=False):
        self.calls.append((value, query))
        return [0.0] * 1024


class Index:
    def __init__(self):
        self.ids = []

    def upsert(self, tenant, event, vector):
        self.ids.append(event["event_id"])

    def search(self, tenant, vector, principals, limit):
        # The second-stage Postgres ACL check must reject a stale or malicious point.
        return list(reversed(self.ids))


def event(tenant, event_id, kind, visibility, principals, text, when, owner=None):
    return {
        "tenant_id": str(tenant), "event_id": event_id, "source": "github" if kind == "pr.merged" else "gmail",
        "type": kind, "occurred_at": when, "actors": [f"person:{uuid4()}"],
        "objects": [f"pr:{uuid4()}", f"repo:{uuid4()}"], "text": text,
        "facts": {"owner_id": owner, "owner_label": "Alex"} if owner else {},
        "acl": {"visibility": visibility, "principals": principals},
        "raw_ref": f"gs://test/{event_id}", "source_url": f"https://example.test/{event_id}",
    }


def test_qdrant_filter_is_applied_before_ranking(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example")
    requests = []

    def respond(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404)
        if request.method == "POST":
            return httpx.Response(200, json={"result": {"points": [{"payload": {"event_id": "e1"}}]}})
        return httpx.Response(200, json={"result": {}})

    index = QdrantIndex(httpx.Client(transport=httpx.MockTransport(respond)))
    tenant = uuid4()
    index.upsert(tenant, {"event_id": "e1", "source": "gmail",
                          "acl": {"visibility": "restricted", "principals": ["email:owner:a@example.com"]}},
                 [0.0] * 1024)
    assert index.search(tenant, [0.0] * 1024, {"email:owner:a@example.com"}, 10) == ["e1"]
    search = json.loads(requests[-1].content)
    assert search["filter"]["should"] == [
        {"key": "visibility", "match": {"value": "public"}},
        {"key": "principals", "match": {"any": ["email:owner:a@example.com"]}},
    ]
    assert index.collection(tenant) == f"cue_{tenant.hex}"


def test_small_model_route_validates_allowed_values(monkeypatch):
    monkeypatch.setenv("MODEL_GATEWAY_BASE_URL", "https://gateway.example")
    monkeypatch.setenv("MEMORY_SMALL_MODEL", "small-model")
    def respond(request):
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "route": "count", "event_type": "pr.merged", "since": "2026-10-01T00:00:00Z"})}}]})
    model = SmallModel(httpx.Client(transport=httpx.MockTransport(respond)))
    assert model.route("How many PRs merged?").event_type == "pr.merged"


def test_merged_pr_snapshot_keeps_merge_time_for_exact_counts():
    raw = {"event": "snapshot", "repository": {"id": 9, "private": True},
           "pull_request": {"id": 123, "title": "Billing", "body": "", "user": {"id": 7},
                            "updated_at": "2026-10-28T12:00:00Z", "merged_at": "2026-10-28T10:00:00Z"}}
    canonical = GitHubConnector().normalize(raw, uuid4())
    assert canonical.type == "pr.merged"
    assert canonical.occurred_at == datetime(2026, 10, 28, 10, tzinfo=timezone.utc)


@pytest.mark.skipif("QDRANT_URL" not in os.environ, reason="Qdrant service not configured")
def test_qdrant_live_acl_roundtrip():
    tenant = uuid4()
    index = QdrantIndex()
    vector = [1.0] + [0.0] * 1023
    event = {"event_id": "private-event", "source": "gmail",
             "acl": {"visibility": "restricted", "principals": ["email:owner:alice@example.com"]}}
    try:
        index.upsert(tenant, event, vector)
        assert index.search(tenant, vector, set(), 10) == []
        assert index.search(tenant, vector, {"email:owner:alice@example.com"}, 10) == ["private-event"]
    finally:
        index._request("DELETE", f"/collections/{index.collection(tenant)}")


@pytest.mark.skipif("INGEST_DATABASE_URL" not in os.environ, reason="Postgres not configured")
def test_memory_projection_query_and_summaries_enforce_source_acl():
    tenant, other = uuid4(), uuid4()
    repo_principal = "github:repo:9"
    email_principal = "email:owner:owner@example.com"
    merged = event(tenant, "pr-merged", "pr.merged", "restricted", [repo_principal],
                   "Export feature merged", "2026-10-28T10:00:00+00:00", f"person:{uuid4()}")
    personal = event(tenant, "private-mail", "mail.message", "restricted", [email_principal],
                     "Secret pricing decision", "2026-10-28T11:00:00+00:00")
    index, embedder, model = Index(), Embedder(), Model()
    admin = os.environ["MIGRATION_DATABASE_URL"]
    ingest = os.environ["INGEST_DATABASE_URL"]
    app = os.environ["DATABASE_URL"]
    with psycopg.connect(admin) as db:
        db.execute("INSERT INTO tenants (id, name) VALUES (%s, 'one'), (%s, 'two')", (tenant, other))
        db.execute("INSERT INTO users (tenant_id, firebase_uid, role) VALUES "
                   "(%s, 'alice', 'member'), (%s, 'bob', 'member')", (tenant, tenant))
        db.execute("INSERT INTO user_principals (tenant_id, firebase_uid, principal) VALUES "
                   "(%s, 'alice', %s), (%s, 'bob', %s)",
                   (tenant, repo_principal, tenant, email_principal))
        for item in (merged, personal):
            db.execute("INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
                       "VALUES (%s, %s, %s, %s, %s, %s)",
                       (tenant, item["event_id"], item["occurred_at"], item["source"], item["type"], Jsonb(item)))
    try:
        for item in (merged, personal):
            body = json.dumps(item).encode()
            attrs = {"tenant_id": str(tenant), "event_id": item["event_id"]}
            assert project_event(body, attrs, ingest, index, embedder)
            assert not project_event(body, attrs, ingest, index, embedder)
        assert len(embedder.calls) == 2
        assert query_memory(tenant, "alice", "count", [], app, model=model)["answer"] == "1"
        assert query_memory(tenant, "bob", "count", [], app, model=model)["answer"] == "0"
        assert query_memory(tenant, "alice", "count", ["bob"], app, model=model)["answer"] == "0"
        recalled = query_memory(tenant, "alice", "export", [], app, model=model,
                                index=index, embedder=embedder)
        assert recalled["route"] == "recall"
        assert [item["event_id"] for item in recalled["citations"]] == ["pr-merged"]
        assert recalled["citations"][0]["url"] == "https://example.test/pr-merged"
        assert run_rollup(tenant, "day", date(2026, 10, 28), ingest, model) == 2
        daily = query_memory(tenant, "alice", "period", [], app, model=model)
        assert len(daily["citations"]) == 1
        assert [item["event_id"] for item in daily["citations"][0]["sources"]] == ["pr-merged"]
        with psycopg.connect(admin) as db:
            edges = db.execute("SELECT predicate, target FROM memory_edges WHERE tenant_id = %s "
                               "AND event_id = 'pr-merged'", (tenant,)).fetchall()
            assert ("owned_by", merged["facts"]["owner_id"]) in edges
        with psycopg.connect(app) as db:
            db.execute("SELECT set_config('app.tenant_id', %s, true)", (str(other),))
            assert db.execute("SELECT count(*) FROM memory_documents").fetchone()[0] == 0
    finally:
        with psycopg.connect(admin) as db:
            for table in ("memory_summaries", "memory_edges", "memory_documents", "event_log",
                          "user_principals", "users"):
                db.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant,))
            db.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (tenant, other))


@pytest.mark.skipif("INGEST_DATABASE_URL" not in os.environ, reason="Postgres not configured")
def test_temporal_owner_handles_out_of_order_events():
    tenant = uuid4()
    owner_a, owner_b = f"person:{uuid4()}", f"person:{uuid4()}"
    earlier = event(tenant, "billing-open", "pr.opened", "restricted", ["github:repo:9"],
                    "Billing migration", "2026-10-28T10:00:00+00:00", owner_a)
    later = event(tenant, "billing-closed", "pr.closed", "restricted", ["github:repo:9"],
                  "Billing migration", "2026-10-28T12:00:00+00:00", owner_b)
    later["objects"] = earlier["objects"]
    earlier["facts"]["owner_label"] = "Alice"
    later["facts"]["owner_label"] = "Bob"
    admin, ingest, app = (os.environ[key] for key in
                          ("MIGRATION_DATABASE_URL", "INGEST_DATABASE_URL", "DATABASE_URL"))
    with psycopg.connect(admin) as db:
        db.execute("INSERT INTO tenants (id, name) VALUES (%s, 'one')", (tenant,))
        db.execute("INSERT INTO users (tenant_id, firebase_uid, role) VALUES (%s, 'alice', 'member')", (tenant,))
        db.execute("INSERT INTO user_principals (tenant_id, firebase_uid, principal) "
                   "VALUES (%s, 'alice', 'github:repo:9')", (tenant,))
        for item in (earlier, later):
            db.execute("INSERT INTO event_log (tenant_id, event_id, occurred_at, source, type, payload) "
                       "VALUES (%s, %s, %s, %s, %s, %s)",
                       (tenant, item["event_id"], item["occurred_at"], item["source"], item["type"], Jsonb(item)))
    class OwnerModel(Model):
        def route(self, question):
            return QueryPlan("ownership", until=datetime(2026, 10, 28, 11, tzinfo=timezone.utc),
                             relation="owned_by", search_query="Billing")
    try:
        for item in (later, earlier):
            assert project_event(json.dumps(item).encode(), {"tenant_id": str(tenant),
                                "event_id": item["event_id"]}, ingest, Index(), Embedder())
        with psycopg.connect(admin) as db:
            rows = db.execute("SELECT event_id, target, valid_to FROM memory_edges WHERE tenant_id = %s "
                              "AND predicate = 'owned_by' ORDER BY valid_from", (tenant,)).fetchall()
            assert rows[0] == ("billing-open", owner_a, datetime(2026, 10, 28, 12, tzinfo=timezone.utc))
            assert rows[1] == ("billing-closed", owner_b, None)
        answer = query_memory(tenant, "alice", "Who owned billing at 11?", [], app, model=OwnerModel())
        assert "Owner: Alice" in answer["answer"]
        assert [item["event_id"] for item in answer["citations"]] == ["billing-open"]
    finally:
        with psycopg.connect(admin) as db:
            for table in ("memory_edges", "memory_documents", "event_log", "user_principals", "users"):
                db.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant,))
            db.execute("DELETE FROM tenants WHERE id = %s", (tenant,))


def test_spoken_hints_pick_source_kind_and_recency():
    from cue.memory.query import _hinted
    assert _hinted("Cue, what was the last commit about?")[:3] == ("github", "commit.", True)
    assert _hinted("Cue, any new emails?")[:3] == ("gmail", None, True)
    source, kind, recent, words = _hinted("Cue, what did we change in BM25 ranking?")
    assert (source, recent) == (None, False) and "BM25" in words and "ranking" in words
