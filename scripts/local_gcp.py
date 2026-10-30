"""Create the Pub/Sub topics, subscriptions, and raw bucket on the local emulators.

Run after `docker compose up -d pubsub gcs`, with PUBSUB_EMULATOR_HOST and STORAGE_EMULATOR_HOST
set. Idempotent; safe to rerun.
"""

import os

from google.api_core.exceptions import AlreadyExists, Conflict
from google.cloud import pubsub_v1, storage

from _local_env import load_local_env

PAIRS = (
    ("RAW_EVENTS_TOPIC", "RAW_EVENTS_SUBSCRIPTION"),
    ("CANONICAL_EVENTS_TOPIC", "CANONICAL_EVENTS_SUBSCRIPTION"),
    ("SYNC_TRIGGERS_TOPIC", "SYNC_TRIGGERS_SUBSCRIPTION"),
)


def main() -> None:
    load_local_env()
    for name in ("PUBSUB_EMULATOR_HOST", "STORAGE_EMULATOR_HOST"):
        if not os.getenv(name):
            raise SystemExit(f"{name} is not set; refusing to touch a real GCP project")
    publisher, subscriber = pubsub_v1.PublisherClient(), pubsub_v1.SubscriberClient()
    for topic_env, subscription_env in PAIRS:
        topic, subscription = os.environ[topic_env], os.environ[subscription_env]
        try:
            publisher.create_topic(name=topic)
        except AlreadyExists:
            pass
        try:
            subscriber.create_subscription(name=subscription, topic=topic)
        except AlreadyExists:
            pass
        print("ready", topic, "->", subscription)
    try:
        storage.Client(project="cue-local").create_bucket(os.environ["RAW_GCS_BUCKET"])
    except Conflict:
        pass
    print("ready bucket", os.environ["RAW_GCS_BUCKET"])


if __name__ == "__main__":
    main()
