"""Tenant-scoped persistence for tasks, tool runs, approvals, and audit rows."""

import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID, uuid4

import psycopg

TASK_COLUMNS = (
    "id, source, requester_uid, channel_ref, thread_ref, request_text, status, plan, answer, "
    "error, attempts, max_attempts, run_at, recurrence, created_at"
)


@contextmanager
def tenant_connection(tenant_id: UUID, database_url: str | None = None):
    with psycopg.connect(database_url or os.environ["DATABASE_URL"]) as database:
        database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        yield database


def audit(database: psycopg.Connection, tenant_id: UUID, *, actor: str, action: str,
          task_id: UUID | None = None, tool: str | None = None, tier: int | None = None,
          decision: str | None = None, detail: dict | None = None) -> None:
    database.execute(
        "INSERT INTO agent_audit (tenant_id, task_id, actor, action, tool, tier, decision, detail) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (tenant_id, task_id, actor, action, tool, tier, decision, json.dumps(detail or {})),
    )


def membership(database: psycopg.Connection, tenant_id: UUID, uid: str) -> str | None:
    row = database.execute(
        "SELECT role FROM users WHERE tenant_id = %s AND firebase_uid = %s", (tenant_id, uid)
    ).fetchone()
    return row[0] if row else None


def create_task(database: psycopg.Connection, tenant_id: UUID, *, source: str, requester_uid: str,
                request_text: str, idempotency_key: str, channel_ref: str | None = None,
                thread_ref: str | None = None, run_at: datetime | None = None,
                recurrence: str | None = None) -> tuple[UUID, bool]:
    """Insert a task once per idempotency key. Returns (task id, created)."""
    task_id = uuid4()
    row = database.execute(
        "INSERT INTO agent_tasks (tenant_id, id, source, requester_uid, channel_ref, thread_ref, "
        "request_text, idempotency_key, status, run_at, recurrence) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'queued', %s, %s) "
        "ON CONFLICT (tenant_id, idempotency_key) DO NOTHING RETURNING id",
        (tenant_id, task_id, source, requester_uid, channel_ref, thread_ref, request_text,
         idempotency_key, run_at or datetime.now(timezone.utc), recurrence),
    ).fetchone()
    if row:
        return row[0], True
    existing = database.execute(
        "SELECT id FROM agent_tasks WHERE tenant_id = %s AND idempotency_key = %s",
        (tenant_id, idempotency_key),
    ).fetchone()
    return existing[0], False


def get_task(database: psycopg.Connection, tenant_id: UUID, task_id: UUID) -> dict | None:
    row = database.execute(
        f"SELECT {TASK_COLUMNS} FROM agent_tasks WHERE tenant_id = %s AND id = %s",
        (tenant_id, task_id),
    ).fetchone()
    if row is None:
        return None
    keys = [name.strip() for name in TASK_COLUMNS.split(",")]
    task = dict(zip(keys, row))
    task["tenant_id"] = tenant_id
    return task


def set_status(database: psycopg.Connection, tenant_id: UUID, task_id: UUID, status: str, **fields) -> None:
    assignments = ["status = %s", "updated_at = now()"]
    values: list = [status]
    for column in ("plan", "answer", "error", "run_at", "dispatched_at"):
        if column in fields:
            value = fields[column]
            assignments.append(f"{column} = %s")
            values.append(json.dumps(value) if column == "plan" and value is not None else value)
    values.extend([tenant_id, task_id])
    database.execute(
        f"UPDATE agent_tasks SET {', '.join(assignments)} WHERE tenant_id = %s AND id = %s",
        values,
    )


def bump_attempt(database: psycopg.Connection, tenant_id: UUID, task_id: UUID) -> int:
    return database.execute(
        "UPDATE agent_tasks SET attempts = attempts + 1, updated_at = now() "
        "WHERE tenant_id = %s AND id = %s RETURNING attempts",
        (tenant_id, task_id),
    ).fetchone()[0]


def call_key(index: int, tool: str, arguments: dict) -> str:
    payload = json.dumps(arguments, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{index}:{tool}:{payload}".encode()).hexdigest()


def claim_tool_run(database: psycopg.Connection, tenant_id: UUID, task_id: UUID,
                   key: str, tool: str) -> tuple[bool, object]:
    """Claim a call. Returns (already_completed, stored_result)."""
    existing = database.execute(
        "SELECT status, result FROM agent_tool_runs WHERE tenant_id = %s AND task_id = %s AND call_key = %s",
        (tenant_id, task_id, key),
    ).fetchone()
    if existing is None:
        database.execute(
            "INSERT INTO agent_tool_runs (tenant_id, task_id, call_key, tool, status) "
            "VALUES (%s, %s, %s, %s, 'running')",
            (tenant_id, task_id, key, tool),
        )
        return False, None
    if existing[0] == "completed":
        return True, existing[1]
    database.execute(
        "UPDATE agent_tool_runs SET status = 'running', updated_at = now() "
        "WHERE tenant_id = %s AND task_id = %s AND call_key = %s",
        (tenant_id, task_id, key),
    )
    return False, None


def finish_tool_run(database: psycopg.Connection, tenant_id: UUID, task_id: UUID, key: str,
                    status: str, result=None) -> None:
    database.execute(
        "UPDATE agent_tool_runs SET status = %s, result = %s, updated_at = now() "
        "WHERE tenant_id = %s AND task_id = %s AND call_key = %s",
        (status, json.dumps(result) if result is not None else None, tenant_id, task_id, key),
    )


def create_approval(database: psycopg.Connection, tenant_id: UUID, task_id: UUID, *,
                    tool: str, arguments: dict, tier: int) -> UUID:
    approval_id = uuid4()
    database.execute(
        "INSERT INTO agent_approvals (tenant_id, id, task_id, tool, arguments, tier, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, 'pending') "
        "ON CONFLICT (tenant_id, task_id, tool, arguments) DO NOTHING",
        (tenant_id, approval_id, task_id, tool, json.dumps(arguments), tier),
    )
    row = database.execute(
        "SELECT id FROM agent_approvals WHERE tenant_id = %s AND task_id = %s AND tool = %s AND arguments = %s",
        (tenant_id, task_id, tool, json.dumps(arguments)),
    ).fetchone()
    return row[0]


def decide_approval(database: psycopg.Connection, tenant_id: UUID, approval_id: UUID,
                    uid: str, approved: bool) -> dict | None:
    status = "approved" if approved else "rejected"
    row = database.execute(
        "UPDATE agent_approvals SET status = %s, decided_by = %s, decided_at = now() "
        "WHERE tenant_id = %s AND id = %s AND status = 'pending' RETURNING task_id, tool, tier",
        (status, uid, tenant_id, approval_id),
    ).fetchone()
    if row is None:
        return None
    return {"task_id": row[0], "tool": row[1], "tier": row[2], "status": status}


def task_approvals(database: psycopg.Connection, tenant_id: UUID, task_id: UUID) -> list[tuple]:
    return database.execute(
        "SELECT id, tool, tier, status, arguments FROM agent_approvals "
        "WHERE tenant_id = %s AND task_id = %s ORDER BY created_at",
        (tenant_id, task_id),
    ).fetchall()


def approved(database: psycopg.Connection, tenant_id: UUID, task_id: UUID, tool: str,
             arguments: dict) -> bool:
    row = database.execute(
        "SELECT status FROM agent_approvals WHERE tenant_id = %s AND task_id = %s "
        "AND tool = %s AND arguments = %s",
        (tenant_id, task_id, tool, json.dumps(arguments)),
    ).fetchone()
    return row is not None and row[0] == "approved"


def due_tasks(database: psycopg.Connection, now: datetime, limit: int = 20) -> list[UUID]:
    rows = database.execute(
        "SELECT id FROM agent_tasks WHERE status = 'queued' AND run_at <= %s "
        "AND dispatched_at IS NULL ORDER BY run_at LIMIT %s",
        (now, limit),
    ).fetchall()
    return [row[0] for row in rows]
