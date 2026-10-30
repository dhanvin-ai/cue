"""Run agent tasks locally with the read-only tool catalog registered.

scripts/run_tasks.py is the production-shaped dispatcher but registers no tool
handlers, so tier 0 reads fail there until a deployment wires them up. This
worker adds the memory read tool so the web console can be exercised end to end
without any external write capability.

Usage:  python scripts/run_local_worker.py [--tenant UUID] [--interval SECONDS]
"""

import argparse
import os
import time
from uuid import UUID

from cue.memory.query import query_memory
from cue.runtime.executor import ToolRegistry, ToolSpec
from cue.runtime.gateway import LiteLLMGateway
from cue.runtime.queue import LocalQueue
from cue.runtime.scheduler import tick
from cue.runtime.service import run_task
from cue.runtime import store

from _local_env import load_local_env


def local_registry(tenant: UUID, requester: str,
                   database_url: str | None = None) -> ToolRegistry:
    """Tier 0 only: reading team memory inside the requester's own permissions.

    Built per task so the tool can never run as someone other than the asker.
    """

    def memory_query(arguments: dict):
        result = query_memory(
            tenant, requester,
            str(arguments.get("question") or ""),
            list(arguments.get("participants") or []),
            database_url or os.environ["DATABASE_URL"],
        )
        return {
            "route": result["route"],
            "answer": result.get("answer"),
            "citations": [
                {"number": item["number"], "source": item.get("source"),
                 "type": item.get("type"), "url": item.get("url"),
                 "text": (item.get("text") or "")[:400]}
                for item in result.get("citations", [])[:8]
            ],
        }

    def linear_create_issue(arguments: dict):
        # Tier 2 stands in for a real tracker write: it proves the approval gate
        # without touching an external system from a local run.
        return {"created": True, "title": arguments.get("title"),
                "url": "https://linear.example/cue/issue/local-stub"}

    return ToolRegistry([
        ToolSpec("memory.query", 0, memory_query, "Search ACL-filtered team memory"),
        ToolSpec("linear.create_issue", 2, linear_create_issue,
                 "Create a tracker issue"),
    ])


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", type=UUID)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    gateway = LiteLLMGateway()
    import psycopg
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        tenants = [args.tenant] if args.tenant else [
            row[0] for row in database.execute("SELECT id FROM tenants").fetchall()]

    while True:
        for tenant_id in tenants:
            queue = LocalQueue()
            tick(tenant_id, queue, proactive=True)
            for _, task_id, _ in queue.drain():
                try:
                    with store.tenant_connection(tenant_id) as database:
                        task = store.get_task(database, tenant_id, task_id)
                    if task is None:
                        continue
                    registry = local_registry(tenant_id, task["requester_uid"])
                    result = run_task(tenant_id, task_id, gateway=gateway, registry=registry)
                    print(f"{task_id} -> {result['status']}", flush=True)
                except Exception as exc:  # noqa: BLE001 - keep the loop alive
                    print(f"{task_id} failed: {type(exc).__name__}: {exc}", flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
