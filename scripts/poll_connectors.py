"""Local stand-in for push channels: backfill every active connection on an interval.

Gmail push needs a real Pub/Sub topic Google can publish to, so local runs poll instead. Each
connector's cursor makes repeated runs incremental.

Usage: python scripts/poll_connectors.py TENANT_UUID [--interval SECONDS] [--once]
"""

import argparse
import os
import time
from uuid import UUID

import psycopg

from cue.connectors.backfill import run

from _local_env import load_local_env


def connections(tenant_id: UUID) -> list[tuple[UUID, str]]:
    with psycopg.connect(os.environ["DATABASE_URL"]) as database:
        database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        return database.execute(
            "SELECT id, provider FROM connector_connections WHERE status != 'disabled' "
            "ORDER BY provider").fetchall()


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        for connection_id, provider in connections(args.tenant_id):
            try:
                print(f"{provider}: published {run(args.tenant_id, connection_id)}", flush=True)
            except Exception as exc:  # keep polling the others; one bad grant must not stop all
                print(f"{provider}: {type(exc).__name__}: {exc}", flush=True)
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
