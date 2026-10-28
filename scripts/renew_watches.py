"""Run daily to renew Gmail and Calendar notification watches."""

import os

import psycopg

from cue.connectors.factory import make_connector


def main() -> None:
    with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as routing:
        bindings = routing.execute(
            "SELECT provider, external_id, tenant_id, connection_id FROM source_bindings "
            "WHERE provider IN ('gmail', 'calendar')"
        ).fetchall()
    for provider, external_id, tenant_id, connection_id in bindings:
        with psycopg.connect(os.environ["DATABASE_URL"]) as database:
            database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            row = database.execute(
                "SELECT secret_ref FROM connector_connections WHERE id = %s AND status = 'active'",
                (connection_id,),
            ).fetchone()
        if row:
            make_connector(provider, external_id, row[0]).subscribe()


if __name__ == "__main__":
    main()
