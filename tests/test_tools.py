from uuid import uuid4

import psycopg
import pytest

from cue.connectors.base import Tool
from cue.runtime import tools
from tests.test_agent_runtime import FakeGateway, make_task, migration_url, run, tenants  # noqa: F401


class FakeConnector:
    """Records write calls; exposes the same tool tiers as the real connectors."""

    TIERS = {
        "github": (Tool("github.read_issue", 0), Tool("github.create_issue", 2),
                   Tool("github.comment_issue", 2), Tool("github.request_review", 2)),
        "gmail": (Tool("gmail.read_message", 0), Tool("gmail.create_draft", 1),
                  Tool("gmail.send", 3)),
        "calendar": (Tool("calendar.read_event", 0), Tool("calendar.create_event", 2)),
        "calendly": (Tool("calendly.list_event_types", 0),
                     Tool("calendly.create_booking_link", 1)),
        "slack": (Tool("slack.read_channel", 0), Tool("slack.post_message", 1)),
    }

    def __init__(self, provider, external_id, calls):
        self.provider, self.external_id, self.calls = provider, external_id, calls

    def tools(self):
        return self.TIERS[self.provider]

    def create_issue(self, installation, owner, repo, title, body):
        self.calls.append(("create_issue", installation, owner, repo, title))
        return {"number": 7, "html_url": f"https://github.com/{owner}/{repo}/issues/7"}

    def send(self, to, subject, body):
        self.calls.append(("send", self.external_id, to, subject))
        return {"id": "m1"}

    def create_draft(self, to, subject, body):
        self.calls.append(("draft", self.external_id, to))
        return {"id": "d1"}

    def create_booking_link(self, uri):
        self.calls.append(("booking", uri))
        return "https://calendly.com/d/x"


@pytest.fixture
def bound(tenants):
    rows = [("github", f"{uuid4().int % 10**8}"), ("gmail", "cue@team.dev"),
            ("gmail", f"priya-{uuid4().hex[:6]}@team.dev"), ("calendar", "cue@team.dev"),
            ("calendly", f"cal-{uuid4().hex[:6]}@team.dev")]
    ids = []
    with psycopg.connect(migration_url()) as database:
        for provider, external in rows:
            ids.append(uuid4())
            database.execute(
                "INSERT INTO connector_connections (id, tenant_id, provider, external_id) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (provider, external_id) DO NOTHING",
                (ids[-1], tenants.a, provider, external))
    yield tenants
    with psycopg.connect(migration_url()) as database:
        database.execute("DELETE FROM connector_connections WHERE id = ANY(%s)", (ids,))


def registry(tenant, calls, monkeypatch, agent="cue@team.dev"):
    if agent:
        monkeypatch.setenv("CUE_AGENT_EMAIL", agent)
    else:
        monkeypatch.delenv("CUE_AGENT_EMAIL", raising=False)
    monkeypatch.setenv("CUE_DEFAULT_REPO", "dhanvin-ai/demo")
    return tools.build_registry(tenant, "member-a",
                                connector_for=lambda p, e, s: FakeConnector(p, e, calls))


def test_catalog_has_connector_writes_with_connector_tiers(bound, monkeypatch):
    catalog = {item["name"]: item["tier"] for item in registry(bound.a, [], monkeypatch).catalog()}
    assert catalog["memory.query"] == 0
    assert catalog["gmail.create_draft"] == 1 and catalog["gmail.send"] == 3
    assert catalog["github.create_issue"] == 2 and catalog["calendar.create_event"] == 2
    assert catalog["calendly.create_booking_link"] == 1 and catalog["slack.post_message"] == 1
    # Reads without a handler stay out of the catalog rather than failing at run time.
    assert "github.read_issue" not in catalog and "gmail.read_message" not in catalog


def test_writes_use_agent_mailbox_never_a_delegated_one(bound, monkeypatch):
    calls = []
    registry(bound.a, calls, monkeypatch).get("gmail.send").handler(
        {"to": "partner@acme.io", "subject": "Recap", "body": "Notes"})
    assert calls == [("send", "cue@team.dev", "partner@acme.io", "Recap")]
    # Two mailboxes and none is the agent's: no Gmail writes at all.
    assert registry(bound.a, [], monkeypatch, agent="nobody@team.dev").get("gmail.send") is None


def test_github_issue_uses_default_repo_and_returns_link(bound, monkeypatch):
    calls = []
    result = registry(bound.a, calls, monkeypatch).get("github.create_issue").handler(
        {"title": "Flaky login test"})
    assert result == {"number": 7, "url": "https://github.com/dhanvin-ai/demo/issues/7"}
    assert calls[0][2:] == ("dhanvin-ai", "demo", "Flaky login test")
    with pytest.raises(ValueError):
        registry(bound.a, calls, monkeypatch).get("github.create_issue").handler(
            {"repo": "no-slash", "title": "x"})


def test_external_email_waits_for_approval_then_sends_once(bound, monkeypatch):
    from cue.runtime import service

    calls = []
    reg = registry(bound.a, calls, monkeypatch)
    gateway = FakeGateway({"tool_calls": [{"name": "gmail.send", "arguments": {
        "to": "partner@acme.io", "subject": "Recap", "body": "Notes"}}], "reply": None})
    task_id = make_task(bound.a, text="Email the recap to partner@acme.io")
    result = run(bound.a, task_id, gateway, reg)
    assert result["status"] == "awaiting_approval" and calls == []
    service.decide(bound.a, result["approvals"][0]["id"], "member-a", True)
    assert run(bound.a, task_id, gateway, reg)["status"] == "completed"
    assert calls == [("send", "cue@team.dev", "partner@acme.io", "Recap")]
