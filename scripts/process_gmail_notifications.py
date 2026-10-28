"""Translate Gmail's Pub/Sub mailbox notifications into sync triggers."""

import json
import logging
import os

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    subscriber, publisher = pubsub_v1.SubscriberClient(), pubsub_v1.PublisherClient()
    subscription = os.environ["GMAIL_PUSH_SUBSCRIPTION"]
    while True:
        try:
            messages = subscriber.pull(request={"subscription": subscription, "max_messages": 10}, timeout=60)
        except DeadlineExceeded:
            continue
        for received in messages.received_messages:
            try:
                email = json.loads(received.message.data)["emailAddress"]
                publisher.publish(
                    os.environ["SYNC_TRIGGERS_TOPIC"], b"", provider="gmail", external_id=email
                ).result(timeout=30)
                subscriber.acknowledge(request={"subscription": subscription, "ack_ids": [received.ack_id]})
            except Exception:
                logging.exception("Gmail notification failed")
                subscriber.modify_ack_deadline(
                    request={"subscription": subscription, "ack_ids": [received.ack_id], "ack_deadline_seconds": 0}
                )


if __name__ == "__main__":
    main()
