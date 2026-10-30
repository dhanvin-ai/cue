"""The tool catalog the planner sees, built from the tenant's bound connections.

Tiers come from each connector's own `tools()`, so the policy engine and the connector agree.
Writes act as the agent's own accounts: the Gmail and Calendar connection named by
CUE_AGENT_EMAIL, or the tenant's only one. Cue never sends from a member's delegated mailbox.
"""

import os
from typing import Any, Callable
from uuid import UUID

from cue.connectors.factory import make_connector
from cue.memory.query import query_memory
from cue.runtime import store
from cue.runtime.executor import ToolRegistry, ToolSpec

# name -> (description shown to the planner, handler(connector, external_id, arguments))
Handler = Callable[[Any, str, dict], Any]


def _repo(arguments: dict) -> tuple[str, str]:
    owner, _, name = str(arguments.get("repo") or os.getenv("CUE_DEFAULT_REPO", "")).partition("/")
    if not owner or not name:
        raise ValueError("repo must be owner/name")
    return owner, name


def _issue_ref(result: Any) -> dict:
    return {"number": result.get("number"), "url": result.get("html_url")}


WRITES: dict[str, tuple[str, Handler]] = {
    "github.create_issue": (
        'Open a GitHub issue. Arguments: {"repo": "owner/name", "title": str, "body": str}',
        lambda c, ext, a: _issue_ref(c.create_issue(ext, *_repo(a), a["title"], a.get("body", ""))),
    ),
    "github.comment_issue": (
        'Comment on a GitHub issue or PR. Arguments: {"repo": "owner/name", "number": int, '
        '"body": str}',
        lambda c, ext, a: {"url": c.comment_issue(ext, *_repo(a), int(a["number"]),
                                                  a["body"]).get("html_url")},
    ),
    "github.request_review": (
        'Request PR reviewers. Arguments: {"repo": "owner/name", "number": int, '
        '"reviewers": [github_login]}',
        lambda c, ext, a: {"requested": [r.get("login") for r in c.request_review(
            ext, *_repo(a), int(a["number"]), list(a["reviewers"])).get("requested_reviewers", [])]},
    ),
    "gmail.create_draft": (
        'Draft an email in Cue\'s mailbox. Arguments: {"to": email, "subject": str, "body": str}',
        lambda c, ext, a: {"draft_id": c.create_draft(a["to"], a["subject"], a["body"]).get("id")},
    ),
    "gmail.send": (
        'Send an email from Cue\'s mailbox. Arguments: {"to": email, "subject": str, "body": str}',
        lambda c, ext, a: {"message_id": c.send(a["to"], a["subject"], a["body"]).get("id")},
    ),
    "calendar.create_event": (
        'Schedule a meeting on Cue\'s calendar and invite attendees. Arguments: {"summary": str, '
        '"start": RFC3339, "end": RFC3339, "attendees": [email]}',
        lambda c, ext, a: {"event_id": c.create_event(
            ext, a["summary"], a["start"], a["end"], list(a.get("attendees") or [])).get("id")},
    ),
    "calendly.list_event_types": (
        "List Calendly meeting types with their public booking URLs. Arguments: {}",
        lambda c, ext, a: c.list_event_types(),
    ),
    "calendly.create_booking_link": (
        'Create a single-use Calendly booking link. Arguments: {"event_type_uri": str} '
        "from calendly.list_event_types",
        lambda c, ext, a: {"booking_url": c.create_booking_link(a["event_type_uri"])},
    ),
    "slack.post_message": (
        'Post in a Slack channel Cue belongs to. Arguments: {"channel": id, "text": str}',
        lambda c, ext, a: {"ts": c.post_message(a["channel"], a["text"]).get("ts")},
    ),
    "linear.create_issue": (
        'Create a Linear issue. Arguments: {"team_id": str, "title": str, "description": str}',
        lambda c, ext, a: c.create_issue(a["team_id"], a["title"], a.get("description", "")),
    ),
}

# Providers whose writes act as a mailbox owner; only the agent's own account may be used.
AGENT_OWNED = {"gmail", "calendar"}


def connections(database, tenant_id) -> list[tuple[str, str, str | None]]:
    return database.execute(
        "SELECT provider, external_id, secret_ref FROM connector_connections "
        "WHERE tenant_id = %s AND status != 'disabled' ORDER BY provider, external_id",
        (tenant_id,),
    ).fetchall()


def _choose(rows: list[tuple[str, str, str | None]]) -> dict[str, tuple[str, str | None]]:
    agent = (os.getenv("CUE_AGENT_EMAIL") or "").casefold()
    chosen: dict[str, tuple[str, str | None]] = {}
    by_provider: dict[str, list[tuple[str, str | None]]] = {}
    for provider, external_id, secret_ref in rows:
        by_provider.setdefault(provider, []).append((external_id, secret_ref))
    for provider, items in by_provider.items():
        if provider in AGENT_OWNED:
            mine = [item for item in items if item[0].casefold() == agent]
            if mine or len(items) == 1:
                chosen[provider] = (mine or items)[0]
        else:
            chosen[provider] = items[0]
    return chosen


def build_registry(tenant_id: UUID, requester_uid: str, *, database_url: str | None = None,
                   connector_for: Callable[[str, str, str | None], Any] = make_connector
                   ) -> ToolRegistry:
    """Built per task, so the memory tool can never read as anyone but the requester."""

    def memory(arguments: dict):
        result = query_memory(tenant_id, requester_uid, str(arguments.get("question") or ""),
                              list(arguments.get("participants") or []),
                              database_url or os.environ["DATABASE_URL"])
        return {"route": result["route"], "answer": result.get("answer"),
                "citations": [{"number": item["number"], "source": item.get("source"),
                               "type": item.get("type"), "url": item.get("url"),
                               "text": (item.get("text") or "")[:400]}
                              for item in result.get("citations", [])[:8]]}

    registry = ToolRegistry([ToolSpec(
        "memory.query", 0, memory,
        'Search team memory within the asker\'s permissions. Arguments: {"question": str}')])
    with store.tenant_connection(tenant_id, database_url) as database:
        rows = connections(database, tenant_id)
    for provider, (external_id, secret_ref) in _choose(rows).items():
        connector = connector_for(provider, external_id, secret_ref)
        for tool in connector.tools():
            entry = WRITES.get(tool.name)
            if entry is None:
                continue
            description, handler = entry
            registry.add(ToolSpec(
                tool.name, tool.risk_tier,
                lambda arguments, h=handler, c=connector, e=external_id: h(c, e, arguments),
                description,
            ))
    return registry
