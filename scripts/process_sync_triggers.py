"""Run cursor-based Gmail and Calendar sync after verified notifications."""

import logging
import os

import psycopg
from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1

from cue.connectors.backfill import run


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    subscriber = pubsub_v1.SubscriberClient()
    subscription = os.environ["SYNC_TRIGGERS_SUBSCRIPTION"]
    while True:
        try:
            messages = subscriber.pull(request={"subscription": subscription, "max_messages": 1}, timeout=60)
        except DeadlineExceeded:
            continue
        for received in messages.received_messages:
            try:
                attrs = received.message.attributes
                if attrs.get("provider") not in {"gmail", "calendar"}:
                    raise ValueError("Unsupported sync trigger")
                with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as database:
                    row = database.execute(
                        "SELECT tenant_id, connection_id FROM source_bindings "
                        "WHERE provider = %s AND external_id = %s",
                        (attrs["provider"], attrs["external_id"]),
                    ).fetchone()
                if row is None:
                    raise ValueError("Source is not bound")
                run(*row)
                subscriber.acknowledge(request={"subscription": subscription, "ack_ids": [received.ack_id]})
            except Exception:
                logging.exception("Sync trigger failed")
                subscriber.modify_ack_deadline(
                    request={"subscription": subscription, "ack_ids": [received.ack_id], "ack_deadline_seconds": 0}
                )


if __name__ == "__main__":
    main()
