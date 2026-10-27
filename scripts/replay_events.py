"""Requeue a bounded slice of the immutable event log for downstream rebuilds."""

import argparse
import os
from datetime import datetime
from uuid import UUID

import psycopg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("since", type=datetime.fromisoformat, help="Inclusive ISO timestamp with timezone")
    parser.add_argument("until", type=datetime.fromisoformat, help="Exclusive ISO timestamp with timezone")
    args = parser.parse_args()
    if args.since.tzinfo is None or args.until.tzinfo is None or args.since >= args.until:
        parser.error("Use timezone-aware timestamps with since < until")
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        cursor = database.execute(
            "INSERT INTO event_outbox (tenant_id, event_id, payload, published_at) "
            "SELECT tenant_id, event_id, payload, NULL FROM event_log "
            "WHERE tenant_id = %s AND occurred_at >= %s AND occurred_at < %s "
            "ON CONFLICT (tenant_id, event_id) DO UPDATE SET published_at = NULL",
            (args.tenant_id, args.since, args.until),
        )
        print(f"Requeued {cursor.rowcount} events")


if __name__ == "__main__":
    main()
