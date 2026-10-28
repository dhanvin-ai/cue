"""Permissioned audit export and the admin access report."""

import csv
import io
from datetime import datetime, timezone
from uuid import UUID

from cue.runtime import store

AUDIT_FIELDS = ("id", "task_id", "actor", "action", "tool", "tier", "decision", "detail",
                "created_at")
AGENT_TOOLS = (
    {"name": "memory.query", "tier": 0, "description": "Search ACL-filtered team memory"},
    {"name": "github.read_issue", "tier": 0, "description": "Read a GitHub issue or PR"},
    {"name": "gmail.read_thread", "tier": 0, "description": "Read a Gmail thread"},
    {"name": "calendar.read_event", "tier": 0, "description": "Read a calendar event"},
    {"name": "slack.post_message", "tier": 1, "description": "Post to a team channel"},
    {"name": "linear.create_issue", "tier": 2, "description": "Create a tracker issue"},
    {"name": "gmail.send", "tier": 3, "description": "Send external email"},
    {"name": "github.comment", "tier": 3, "description": "Comment on a public repo"},
)


def _admin(database, tenant_id: UUID, uid: str) -> None:
    role = store.membership(database, tenant_id, uid)
    if role is None:
        raise PermissionError("Requester is not a member of this tenant")
    if role != "admin":
        raise PermissionError("Admin role required")


def export_audit(tenant_id: UUID, uid: str, since: datetime, until: datetime, *,
                 database_url: str | None = None, fmt: str = "json") -> dict | str:
    if since.tzinfo is None or until.tzinfo is None:
        raise ValueError("Audit export needs timezone-aware timestamps")
    if since >= until:
        raise ValueError("Audit export start must be before end")
    if (until - since).days > 366:
        raise ValueError("Audit export supports at most 366 days")
    with store.tenant_connection(tenant_id, database_url) as database:
        _admin(database, tenant_id, uid)
        rows = database.execute(
            "SELECT id, task_id, actor, action, tool, tier, decision, detail, created_at "
            "FROM agent_audit WHERE tenant_id = %s AND created_at >= %s AND created_at < %s "
            "ORDER BY created_at, id", (tenant_id, since, until),
        ).fetchall()
        records = [dict(zip(AUDIT_FIELDS, row)) for row in rows]
        store.audit(database, tenant_id, actor=uid, action="export", decision="exported",
                    detail={"since": since.isoformat(), "until": until.isoformat(),
                            "records": len(records), "format": fmt})
    for record in records:
        record["id"] = int(record["id"])
        if record["task_id"] is not None:
            record["task_id"] = str(record["task_id"])
        if record["created_at"] is not None:
            record["created_at"] = record["created_at"].isoformat()
    payload = {"tenant_id": str(tenant_id), "since": since.isoformat(),
               "until": until.isoformat(), "records": records}
    if fmt == "json":
        return payload
    if fmt != "csv":
        raise ValueError("Unsupported audit export format")
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=AUDIT_FIELDS)
    writer.writeheader()
    for record in records:
        writer.writerow({key: record.get(key) for key in AUDIT_FIELDS})
    return output.getvalue()


def access_report(tenant_id: UUID, uid: str, *, database_url: str | None = None,
                  tools: list[dict] | None = None) -> dict:
    with store.tenant_connection(tenant_id, database_url) as database:
        _admin(database, tenant_id, uid)
        users = database.execute(
            "SELECT u.firebase_uid, u.role, u.revoked_at, "
            "COALESCE(array_agg(p.principal) FILTER (WHERE p.principal IS NOT NULL), '{}') "
            "FROM users AS u LEFT JOIN user_principals AS p ON p.tenant_id = u.tenant_id "
            "AND p.firebase_uid = u.firebase_uid WHERE u.tenant_id = %s "
            "GROUP BY u.firebase_uid, u.role, u.revoked_at ORDER BY u.firebase_uid",
            (tenant_id,),
        ).fetchall()
        connectors = database.execute(
            "SELECT c.id, c.provider, c.external_id, c.status, c.last_error, "
            "COALESCE(k.paused, false), k.mode "
            "FROM connector_connections AS c LEFT JOIN kill_switches AS k "
            "ON k.tenant_id = c.tenant_id AND k.scope = 'connector' AND k.subject = c.id::text "
            "WHERE c.tenant_id = %s ORDER BY c.provider, c.id", (tenant_id,),
        ).fetchall()
        documents = database.execute(
            "SELECT source, visibility, count(*) FROM memory_documents WHERE tenant_id = %s "
            "GROUP BY source, visibility ORDER BY source, visibility", (tenant_id,),
        ).fetchall()
        counts = {
            "documents": database.execute(
                "SELECT count(*) FROM memory_documents WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()[0],
            "edges": database.execute(
                "SELECT count(*) FROM memory_edges WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()[0],
            "summaries": database.execute(
                "SELECT count(*) FROM memory_summaries WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()[0],
            "meetings": database.execute(
                "SELECT count(*) FROM meeting_sessions WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()[0],
            "notes": database.execute(
                "SELECT count(*) FROM meeting_notes WHERE tenant_id = %s", (tenant_id,)
            ).fetchone()[0],
        }
        switches = database.execute(
            "SELECT scope, subject, paused, mode, reason, changed_by, changed_at "
            "FROM kill_switches WHERE tenant_id = %s ORDER BY scope, subject", (tenant_id,),
        ).fetchall()
        policies = database.execute(
            "SELECT scope, subject, mode FROM agent_policies WHERE tenant_id = %s "
            "ORDER BY scope, subject", (tenant_id,),
        ).fetchall()
        revocations = database.execute(
            "SELECT kind, subject, reason, revoked_by, created_at FROM access_revocations "
            "WHERE tenant_id = %s ORDER BY created_at DESC", (tenant_id,),
        ).fetchall()
        queued = database.execute(
            "SELECT count(*) FROM paused_events WHERE tenant_id = %s AND replayed_at IS NULL",
            (tenant_id,),
        ).fetchone()[0]
        return {
            "tenant_id": str(tenant_id),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "users": [{"firebase_uid": row[0], "role": row[1],
                       "revoked_at": row[2].isoformat() if row[2] else None,
                       "principals": row[3]} for row in users],
            "connectors": [{"id": str(row[0]), "provider": row[1], "external_id": row[2],
                            "status": row[3], "last_error": row[4], "paused": row[5],
                            "mode": row[6]} for row in connectors],
            "switches": [{"scope": row[0], "subject": row[1], "paused": row[2],
                          "mode": row[3], "reason": row[4], "changed_by": row[5],
                          "changed_at": row[6].isoformat()} for row in switches],
            "policies": [{"scope": row[0], "subject": row[1], "mode": row[2]}
                         for row in policies],
            "revocations": [{"kind": row[0], "subject": row[1], "reason": row[2],
                             "revoked_by": row[3], "created_at": row[4].isoformat()}
                            for row in revocations],
            "can_read": {"totals": counts,
                         "by_source": [{"source": row[0], "visibility": row[1],
                                        "count": row[2]} for row in documents]},
            "can_do": tools or [],
            "paused_events": queued,
        }
