"""Publish committed canonical events; safe to rerun after a publish failure."""

import os
import time

from google.cloud import pubsub_v1

from cue.outbox import publish_pending


def main() -> None:
    publisher = pubsub_v1.PublisherClient()
    while True:
        publish_pending(os.environ["INGEST_DATABASE_URL"], publisher, os.environ["CANONICAL_EVENTS_TOPIC"])
        time.sleep(5)


if __name__ == "__main__":
    main()
