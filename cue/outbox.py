"""Retryable publication of committed canonical events."""

import json

import psycopg

from cue.controls import switches


def publish_pending(database_url: str, publisher, topic: str) -> int:
    count = 0
    with psycopg.connect(database_url, autocommit=True) as database:
        tenants = database.execute(
            "SELECT tenant_id FROM github_installation_map UNION SELECT tenant_id FROM source_bindings"
        ).fetchall()
        for (tenant_id,) in tenants:
            with database.transaction():
                database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                if switches.tenant_paused(database, tenant_id):
                    continue
                pending = database.execute(
                    "SELECT event_id, payload FROM event_outbox WHERE published_at IS NULL "
                    "ORDER BY event_id LIMIT 100"
                ).fetchall()
            for event_id, payload in pending:
                publisher.publish(
                    topic,
                    json.dumps(payload).encode(),
                    tenant_id=str(tenant_id),
                    event_id=event_id,
                ).result(timeout=30)
                with database.transaction():
                    database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                    database.execute(
                        "UPDATE event_outbox SET published_at = now() "
                        "WHERE tenant_id = %s AND event_id = %s AND published_at IS NULL",
                        (tenant_id, event_id),
                    )
                count += 1
    return count
