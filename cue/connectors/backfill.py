import json
import os
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from google.cloud import pubsub_v1

from cue.connectors.factory import make_connector


def run(tenant_id: UUID, connection_id: UUID, publisher=None, connector=None) -> int:
    publisher = publisher or pubsub_v1.PublisherClient()
    topic = os.environ["RAW_EVENTS_TOPIC"]
    with psycopg.connect(os.environ["DATABASE_URL"]) as database:
        with database.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            cursor.execute(
                "SELECT provider, external_id, cursor, secret_ref FROM connector_connections "
                "WHERE id = %s AND status != 'disabled'",
                (connection_id,),
            )
            row = cursor.fetchone()
    if row is None:
        raise ValueError("Active connector connection not found")
    provider, external_id, checkpoint, secret_ref = row
    connector = connector or make_connector(provider, external_id, secret_ref)
    if provider != connector.provider:
        raise ValueError("Connector provider mismatch")
    since = datetime.fromisoformat(checkpoint) if checkpoint else datetime.now(timezone.utc) - timedelta(days=365)
    started = datetime.now(timezone.utc)
    count = 0
    try:
        connector.authorize(external_id)
        if provider == "github":
            connector.subscribe()
        for raw in connector.backfill(external_id, since):
            event = connector.normalize(raw, tenant_id)
            publisher.publish(
                topic,
                json.dumps(raw).encode(),
                source=connector.provider,
                tenant_id=str(tenant_id),
                connection_id=str(connection_id),
                external_id=external_id,
                event_id=event.event_id,
            ).result(timeout=30)
            count += 1
    except Exception as exc:
        with psycopg.connect(os.environ["DATABASE_URL"]) as database:
            with database.cursor() as cursor:
                cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
                cursor.execute(
                    "UPDATE connector_connections SET status = 'error', last_error = %s "
                    "WHERE id = %s AND cursor IS NOT DISTINCT FROM %s AND status != 'disabled'",
                    (str(exc)[:500], connection_id, checkpoint),
                )
        raise
    with psycopg.connect(os.environ["DATABASE_URL"]) as database:
        with database.cursor() as cursor:
            cursor.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
            cursor.execute(
                "UPDATE connector_connections SET cursor = %s, status = 'active', last_error = NULL "
                "WHERE id = %s AND cursor IS NOT DISTINCT FROM %s AND status != 'disabled'",
                (started.isoformat(), connection_id, checkpoint),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Connector checkpoint changed during backfill")
    return count
