"""Dispatch and run due agent tasks. Local stand-in for Cloud Tasks and the worker."""

import argparse
import os
from uuid import UUID

import psycopg

from cue.runtime.executor import ToolRegistry
from cue.runtime.gateway import LiteLLMGateway
from cue.runtime.queue import LocalQueue
from cue.runtime.scheduler import tick
from cue.runtime.service import run_task


def tenant_ids() -> list[UUID]:
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        return [row[0] for row in database.execute("SELECT id FROM tenants").fetchall()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", type=UUID)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    gateway = LiteLLMGateway()
    registry = ToolRegistry()  # Register ToolSpec handlers before enabling writes.
    for tenant_id in ([args.tenant] if args.tenant else tenant_ids()):
        queue = LocalQueue()
        tick(tenant_id, queue, limit=args.limit, proactive=True)
        for _, task_id, _ in queue.drain():
            try:
                print(run_task(tenant_id, task_id, gateway=gateway, registry=registry))
            except Exception as exc:  # noqa: BLE001 - keep the loop alive for other tenants
                print(f"task {task_id} failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
