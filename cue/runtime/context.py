"""Context builder: tenant- and ACL-filtered evidence from the Phase 5 memory layer."""

import os

import psycopg

from cue.memory.query import query_memory
from cue.runtime import store


def channel_participants(database: psycopg.Connection, tenant_id, principal: str) -> list[str]:
    """Tenant members who hold a source principal, used for the shared-ACL intersection."""
    rows = database.execute(
        "SELECT firebase_uid FROM user_principals WHERE tenant_id = %s AND principal = %s "
        "ORDER BY firebase_uid LIMIT 20",
        (tenant_id, principal),
    ).fetchall()
    return [row[0] for row in rows]


def build_context(tenant_id, requester: str, question: str, participants: list[str], *,
                  database_url: str | None = None, model=None, index=None, embedder=None,
                  fast: bool = False) -> dict:
    """Return the Phase 5 answer plus citations for the planner.

    `query_memory` already intersects every participant's principals, so a shared
    Slack channel or meeting never widens access beyond the least-privileged member.
    """
    result = query_memory(
        tenant_id, requester, question, participants,
        database_url or os.environ["DATABASE_URL"],
        model=model, index=index, embedder=embedder, fast=fast,
    )
    return {
        "summary": result["answer"],
        "route": result["route"],
        "citations": result["citations"],
    }


def participants_for(tenant_id, source: str, channel_ref: str | None, requested: tuple[str, ...],
                     database_url: str | None = None) -> list[str]:
    if requested:
        return list(dict.fromkeys(requested))
    if source != "slack" or not channel_ref:
        return []
    with store.tenant_connection(tenant_id, database_url) as database:
        return channel_participants(database, tenant_id, f"slack:channel:{channel_ref}")
