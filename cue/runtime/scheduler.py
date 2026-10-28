"""Scheduler: dispatch due tasks and enqueue the next occurrence of recurring ones."""

from datetime import datetime, timezone
from uuid import UUID

import psycopg

from cue.runtime import cron, store


def tick(tenant_id: UUID, queue, *, database_url: str | None = None,
         now: datetime | None = None, limit: int = 20,
         proactive: bool = False) -> list[UUID]:
    moment = now or datetime.now(timezone.utc)
    with store.tenant_connection(tenant_id, database_url) as database:
        due = store.due_tasks(database, moment, limit)
        for task_id in due:
            database.execute(
                "UPDATE agent_tasks SET dispatched_at = now(), updated_at = now() "
                "WHERE tenant_id = %s AND id = %s",
                (tenant_id, task_id),
            )
    for task_id in due:
        queue.enqueue(tenant_id, task_id)
    if proactive:
        from cue.proactive import rules
        due.extend(rules.tick(tenant_id, database_url=database_url, queue=queue, now=moment))
    return due


def reschedule(database: psycopg.Connection, tenant_id: UUID, task: dict,
               now: datetime | None = None) -> UUID | None:
    expression = task.get("recurrence")
    if not expression:
        return None
    next_run = cron.next_after(expression, now or datetime.now(timezone.utc))
    task_id, _ = store.create_task(
        database, tenant_id,
        source=task["source"],
        requester_uid=task["requester_uid"],
        request_text=task["request_text"],
        idempotency_key=f"{task['idempotency_key']}:{next_run.isoformat()}",
        channel_ref=task["channel_ref"],
        thread_ref=task["thread_ref"],
        run_at=next_run,
        recurrence=expression,
    )
    return task_id
