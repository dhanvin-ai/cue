"""Project canonical Pub/Sub deliveries into Postgres graph and Qdrant."""

import logging
import os

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1

from cue.memory.project import project_event


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    subscriber = pubsub_v1.SubscriberClient()
    subscription = os.environ["CANONICAL_EVENTS_SUBSCRIPTION"]
    while True:
        try:
            response = subscriber.pull(request={"subscription": subscription, "max_messages": 10}, timeout=60)
        except DeadlineExceeded:
            continue
        for received in response.received_messages:
            try:
                subscriber.modify_ack_deadline(request={"subscription": subscription,
                    "ack_ids": [received.ack_id], "ack_deadline_seconds": 600})
                project_event(received.message.data, dict(received.message.attributes),
                              os.environ["INGEST_DATABASE_URL"])
                subscriber.acknowledge(request={"subscription": subscription,
                    "ack_ids": [received.ack_id]})
            except Exception:
                logging.exception("Memory projection failed for message %s", received.message.message_id)
                subscriber.modify_ack_deadline(request={"subscription": subscription,
                    "ack_ids": [received.ack_id], "ack_deadline_seconds": 0})


if __name__ == "__main__":
    main()
