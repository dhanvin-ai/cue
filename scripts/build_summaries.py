"""Cloud Scheduler entry point for permission-preserving memory rollups."""

import argparse
import os
from datetime import date, timedelta
from uuid import UUID

import psycopg

from cue.memory.summary import run_rollup


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--period", choices=("day", "week", "month", "year"), default="day")
    parser.add_argument("--start", type=date.fromisoformat, default=date.today() - timedelta(days=1))
    parser.add_argument("--tenant", type=UUID)
    args = parser.parse_args()
    if args.tenant:
        tenants = [args.tenant]
    else:
        with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as database:
            tenants = [row[0] for row in database.execute(
                "SELECT tenant_id FROM github_installation_map UNION SELECT tenant_id FROM source_bindings"
            ).fetchall()]
    for tenant in tenants:
        count = run_rollup(tenant, args.period, args.start, os.environ["INGEST_DATABASE_URL"])
        print(f"{tenant}: {count} {args.period} summaries")


if __name__ == "__main__":
    main()
