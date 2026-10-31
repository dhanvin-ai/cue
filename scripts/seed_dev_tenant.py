"""Create the local demo tenant and its admin member. Idempotent; safe to rerun.

Usage: python scripts/seed_dev_tenant.py [--tenant UUID] [--uid dev-local-user] [--name "Demo team"]
"""

import argparse
import os

import psycopg

from _local_env import load_local_env

DEFAULT_TENANT = "11111111-1111-1111-1111-111111111111"


def main() -> None:
    load_local_env()
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", default=os.getenv("CUE_DEV_TENANT_ID") or DEFAULT_TENANT)
    parser.add_argument("--uid", default=os.getenv("CUE_DEV_AUTH_UID") or "dev-local-user")
    parser.add_argument("--name", default="Demo team")
    args = parser.parse_args()
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        database.execute("INSERT INTO tenants (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (args.tenant, args.name))
        database.execute("INSERT INTO users (tenant_id, firebase_uid, role) VALUES (%s, %s, 'admin') "
                         "ON CONFLICT DO NOTHING", (args.tenant, args.uid))
    print(f"tenant {args.tenant}  admin {args.uid}")


if __name__ == "__main__":
    main()
