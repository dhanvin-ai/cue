"""Pilot status: task health, connector state, controls, and reconciliation freshness."""

from datetime import datetime, timezone
from uuid import UUID

from cue.runtime import store


def tenant_status(tenant_id: UUID, uid: str, *, database_url: str | None = None) -> dict:
    with store.tenant_connection(tenant_id, database_url) as database:
        if store.membership(database, tenant_id, uid) is None:
            raise PermissionError("Requester is not a member of this tenant")
        tasks = database.execute(
            "SELECT status, count(*) FROM agent_tasks WHERE tenant_id = %s GROUP BY status "
            "ORDER BY status", (tenant_id,),
        ).fetchall()
        approvals = database.execute(
            "SELECT count(*) FROM agent_approvals WHERE tenant_id = %s AND status = 'pending'",
            (tenant_id,),
        ).fetchone()[0]
        connectors = database.execute(
            "SELECT provider, status, count(*) FROM connector_connections WHERE tenant_id = %s "
            "GROUP BY provider, status ORDER BY provider, status", (tenant_id,),
        ).fetchall()
        switches = database.execute(
            "SELECT scope, subject, paused, mode FROM kill_switches WHERE tenant_id = %s "
            "AND paused ORDER BY scope, subject", (tenant_id,),
        ).fetchall()
        paused_events = database.execute(
            "SELECT count(*) FROM paused_events WHERE tenant_id = %s AND replayed_at IS NULL",
            (tenant_id,),
        ).fetchone()[0]
        deferred = database.execute(
            "SELECT count(*) FROM proactive_runs WHERE tenant_id = %s AND status = 'deferred'",
            (tenant_id,),
        ).fetchone()[0]
        reconciliation = database.execute(
            "SELECT provider, status, finished_at, missing_count, backfilled_count "
            "FROM reconciliation_runs WHERE tenant_id = %s ORDER BY finished_at DESC NULLS LAST "
            "LIMIT 1", (tenant_id,),
        ).fetchone()
        return {
            "tenant_id": str(tenant_id),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "tasks": {row[0]: row[1] for row in tasks},
            "pending_approvals": approvals,
            "connectors": [{"provider": row[0], "status": row[1], "count": row[2]}
                           for row in connectors],
            "paused": [{"scope": row[0], "subject": row[1], "mode": row[3]}
                       for row in switches],
            "paused_events": paused_events,
            "deferred_proactive": deferred,
            "last_reconciliation": None if reconciliation is None else {
                "provider": reconciliation[0], "status": reconciliation[1],
                "finished_at": reconciliation[2].isoformat() if reconciliation[2] else None,
                "missing": reconciliation[3], "backfilled": reconciliation[4],
            },
        }
