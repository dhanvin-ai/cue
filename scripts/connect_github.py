import argparse
import os
from uuid import UUID, uuid4

import psycopg

from cue.connectors.github import GitHubConnector


def main() -> None:
    parser = argparse.ArgumentParser(description="Bind a GitHub App installation to a Cue tenant")
    parser.add_argument("tenant_id", type=UUID)
    parser.add_argument("installation_id", type=int)
    args = parser.parse_args()

    connector = GitHubConnector()
    connector.authorize(str(args.installation_id))
    connector.subscribe()
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        with database.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(args.tenant_id),))
            cursor.execute("SELECT 1 FROM tenants WHERE id = %s", (args.tenant_id,))
            if cursor.fetchone() is None:
                raise ValueError("Tenant not found")
            connection_id = uuid4()
            cursor.execute(
                "INSERT INTO connector_connections (id, tenant_id, provider, external_id) "
                "VALUES (%s, %s, 'github', %s) ON CONFLICT (provider, external_id) DO NOTHING",
                (connection_id, args.tenant_id, str(args.installation_id)),
            )
            if cursor.rowcount != 1:
                raise ValueError("Installation already linked to a tenant")
            cursor.execute(
                "INSERT INTO github_installation_map (installation_id, tenant_id, connection_id) "
                "VALUES (%s, %s, %s)",
                (args.installation_id, args.tenant_id, connection_id),
            )


if __name__ == "__main__":
    main()
