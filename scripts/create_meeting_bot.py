"""Create a visible Recall bot and bind its ID to the intended tenant."""

import argparse
import os
from uuid import UUID, uuid4

import psycopg

from cue.connectors.credentials import Credential
from cue.connectors.recall import RecallConnector


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("secret_ref", help="Recall API credential in Secret Manager")
    parser.add_argument("meeting_url")
    parser.add_argument("--attendee", action="append", required=True)
    parser.add_argument("--join-at")
    args = parser.parse_args()
    if not args.attendee:
        parser.error("At least one attendee is required for the meeting ACL")
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        if database.execute("SELECT 1 FROM tenants WHERE id = %s", (args.tenant_id,)).fetchone() is None:
            raise ValueError("Tenant not found")
    connector = RecallConnector(Credential(args.secret_ref, "recall").token(), os.environ["RECALL_REGION"])
    bot = connector.create_bot(args.meeting_url, args.attendee, args.join_at)
    bot_id = str(UUID(bot["id"]))
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        connection_id = uuid4()
        database.execute(
            "INSERT INTO connector_connections (id, tenant_id, provider, external_id, secret_ref) "
            "VALUES (%s, %s, 'recall', %s, %s)",
            (connection_id, args.tenant_id, bot_id, args.secret_ref),
        )
        database.execute(
            "INSERT INTO source_bindings (provider, external_id, tenant_id, connection_id) "
            "VALUES ('recall', %s, %s, %s)",
            (bot_id, args.tenant_id, connection_id),
        )
    print(bot_id)


if __name__ == "__main__":
    main()
