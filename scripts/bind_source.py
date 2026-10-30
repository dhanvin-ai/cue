"""Trusted operator binds a verified vendor identity and Secret Manager credential to a tenant."""

import argparse
import os
from uuid import UUID, uuid4

import psycopg

from cue.connectors.factory import make_connector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("provider", choices=("gmail", "calendar", "calendly", "slack", "linear", "recall"))
    parser.add_argument("external_id", help="Mailbox, calendar, workspace, organization, or Recall bot ID")
    parser.add_argument("secret_ref", help="Secret Manager resource or file: ref ending in /versions/latest")
    parser.add_argument("--no-subscribe", action="store_true",
                        help="Skip push channels; poll with scripts/poll_connectors.py instead")
    args = parser.parse_args()
    connector = make_connector(args.provider, args.external_id, args.secret_ref)
    connector.authorize(args.external_id)
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        if database.execute("SELECT 1 FROM tenants WHERE id = %s", (args.tenant_id,)).fetchone() is None:
            raise ValueError("Tenant not found")
        connection_id = uuid4()
        database.execute(
            "INSERT INTO connector_connections (id, tenant_id, provider, external_id, secret_ref) "
            "VALUES (%s, %s, %s, %s, %s)",
            (connection_id, args.tenant_id, args.provider, args.external_id, args.secret_ref),
        )
        database.execute(
            "INSERT INTO source_bindings (provider, external_id, tenant_id, connection_id) "
            "VALUES (%s, %s, %s, %s)",
            (args.provider, args.external_id, args.tenant_id, connection_id),
        )
    if args.provider in {"gmail", "calendar"} and not args.no_subscribe:
        connector.subscribe()
    print(connection_id)


if __name__ == "__main__":
    main()
