"""Run agent tasks locally with the tenant's connector tools registered.

Like scripts/run_tasks.py, but it loops and adds a stub tracker write when no
Linear connection is bound, so the console can show approvals end to end.

Usage:  python scripts/run_local_worker.py [--tenant UUID] [--interval SECONDS]
"""

import argparse
import os
import time
from uuid import UUID

from cue.runtime.executor import ToolRegistry, ToolSpec
from cue.runtime.gateway import LiteLLMGateway
from cue.runtime.queue import LocalQueue
from cue.runtime.scheduler import tick
from cue.runtime.service import run_task
from cue.runtime import store
from cue.runtime.tools import build_registry

from _local_env import load_local_env


def local_registry(tenant: UUID, requester: str,
                   database_url: str | None = None) -> ToolRegistry:
    """The real per-task catalog from bound connections, plus a stub tracker write.

    Without a Linear connection, a tier 2 stub keeps the approval gate demonstrable
    without touching an external system.
    """
    registry = build_registry(tenant, requester, database_url=database_url)
    if registry.get("linear.create_issue") is None:
        registry.add(ToolSpec(
            "linear.create_issue", 2,
            lambda arguments: {"created": True, "title": arguments.get("title"),
                               "url": "https://linear.example/cue/issue/local-stub"},
            "Create a tracker issue (local stub)"))
    return registry


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
