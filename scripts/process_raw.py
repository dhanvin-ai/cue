"""Run as a long-lived worker subscribed to cue-raw-events."""

import logging
import os
import json

import psycopg

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1

from cue.ingestion import process_raw
from cue.connectors.backfill import run


def sync_finished_transcript(data: bytes, attributes: dict) -> None:
    if attributes.get("source") != "recall":
        return
    event = json.loads(data)
    if event.get("event") != "transcript.done":
        return
    bot_id = attributes["external_id"]
    with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as database:
        row = database.execute(
            "SELECT tenant_id, connection_id FROM source_bindings "
            "WHERE provider = 'recall' AND external_id = %s", (bot_id,)
        ).fetchone()
    if row is None:
        raise ValueError("Recall bot is not bound")
    run(*row)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    subscriber = pubsub_v1.SubscriberClient()
    subscription = os.environ["RAW_EVENTS_SUBSCRIPTION"]
    while True:
        try:
            response = subscriber.pull(request={"subscription": subscription, "max_messages": 10}, timeout=60)
        except DeadlineExceeded:
            continue
        for received in response.received_messages:
            try:
                subscriber.modify_ack_deadline(
                    request={"subscription": subscription, "ack_ids": [received.ack_id], "ack_deadline_seconds": 600}
                )
                inserted = process_raw(
                    received.message.data,
                    dict(received.message.attributes),
                    os.environ["INGEST_DATABASE_URL"],
                )
                sync_finished_transcript(received.message.data, dict(received.message.attributes))
                subscriber.acknowledge(request={"subscription": subscription, "ack_ids": [received.ack_id]})
                logging.info("Processed raw message %s: new=%s", received.message.message_id, inserted)
            except Exception:
                logging.exception("Raw message %s failed; Pub/Sub will retry", received.message.message_id)
                subscriber.modify_ack_deadline(
                    request={"subscription": subscription, "ack_ids": [received.ack_id], "ack_deadline_seconds": 0}
                )


if __name__ == "__main__":
    main()
