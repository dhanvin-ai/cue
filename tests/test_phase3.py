import json
import os
from uuid import uuid4

import psycopg
import pytest

from cue.connectors.github import GitHubConnector
from cue.ingestion import process_raw
from cue.outbox import publish_pending


def snapshot():
    return {
        "event": "snapshot",
        "repository": {"id": 901, "private": True},
        "issue": {
            "id": 12345,
            "title": "Fix login",
            "body": "Expired session",
            "updated_at": "2026-10-28T10:00:00Z",
            "user": {"id": 77},
        },
    }


class Storage:
    def __init__(self):
        self.uploads = []

    def bucket(self, name):
        self.name = name
        return self

    def blob(self, key):
        self.key = key
        return self

    def upload_from_string(self, data, **kwargs):
        self.uploads.append((self.name, self.key, data, kwargs))


@pytest.mark.skipif("INGEST_DATABASE_URL" not in os.environ, reason="Postgres not configured")
def test_event_ingestion_dedupes_and_outbox_retries(monkeypatch):
    tenant_id, other_tenant, connection_id = uuid4(), uuid4(), uuid4()
    installation_id = 900000 + int(uuid4().int % 100000)
    monkeypatch.setenv("RAW_GCS_BUCKET", "cue-test-raw")
    with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
        database.execute(
            "INSERT INTO tenants (id, name) VALUES (%s, 'one'), (%s, 'two')",
            (tenant_id, other_tenant),
        )
        database.execute(
            "INSERT INTO connector_connections (id, tenant_id, provider, external_id) "
            "VALUES (%s, %s, 'github', %s)",
            (connection_id, tenant_id, str(installation_id)),
        )
        database.execute(
            "INSERT INTO github_installation_map (installation_id, tenant_id, connection_id) "
            "VALUES (%s, %s, %s)",
            (installation_id, tenant_id, connection_id),
        )
    try:
        raw = snapshot()
        body = json.dumps(raw).encode()
        event_id = GitHubConnector().normalize(raw, tenant_id).event_id
        attributes = {
            "source": "github",
            "connection_id": str(connection_id),
            "tenant_id": str(tenant_id),
            "event_id": event_id,
        }
        storage = Storage()
        assert process_raw(body, attributes, os.environ["INGEST_DATABASE_URL"], storage)
        assert not process_raw(body, attributes, os.environ["INGEST_DATABASE_URL"], storage)
        assert storage.uploads[0][0] == "cue-test-raw"
        assert storage.uploads[0][3]["if_generation_match"] == 0
        with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
            rows = database.execute(
                "SELECT payload FROM event_log WHERE tenant_id = %s", (tenant_id,)
            ).fetchall()
            assert len(rows) == 1
            payload = rows[0][0]
            assert payload["raw_ref"].startswith(f"gs://cue-test-raw/raw/{tenant_id}/github/")
            assert payload["actors"][0].startswith("person:")
            assert payload["objects"][1].startswith("repo:")
            assert payload["acl"] == {"visibility": "restricted", "principals": ["github:repo:901"]}
        with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as database:
            database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(other_tenant),))
            assert database.execute("SELECT count(*) FROM event_log").fetchone()[0] == 0

        class Publisher:
            fail = True
            messages = []

            def publish(self, topic, data, **attrs):
                self.messages.append((topic, json.loads(data), attrs))

                class Future:
                    def result(inner, timeout):
                        if self.fail:
                            raise RuntimeError("publish failed")

                return Future()

        publisher = Publisher()
        with pytest.raises(RuntimeError, match="publish failed"):
            publish_pending(os.environ["INGEST_DATABASE_URL"], publisher, "canonical-topic")
        with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
            assert database.execute(
                "SELECT published_at FROM event_outbox WHERE tenant_id = %s AND event_id = %s",
                (tenant_id, event_id),
            ).fetchone()[0] is None
        publisher.fail = False
        assert publish_pending(os.environ["INGEST_DATABASE_URL"], publisher, "canonical-topic") == 1
        assert publisher.messages[-1][2] == {"tenant_id": str(tenant_id), "event_id": event_id}
        assert publish_pending(os.environ["INGEST_DATABASE_URL"], publisher, "canonical-topic") == 0
    finally:
        with psycopg.connect(os.environ["MIGRATION_DATABASE_URL"]) as database:
            for table in ("event_outbox", "event_log", "event_dedupe", "entity_aliases", "entities"):
                database.execute(f"DELETE FROM {table} WHERE tenant_id = %s", (tenant_id,))
            database.execute("DELETE FROM github_installation_map WHERE connection_id = %s", (connection_id,))
            database.execute("DELETE FROM connector_connections WHERE id = %s", (connection_id,))
            database.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (tenant_id, other_tenant))


def test_webhook_identity_and_event_type():
    raw = snapshot()
    raw["action"] = "closed"
    raw["pull_request"] = {**raw.pop("issue"), "merged": True, "merged_at": "2026-10-28T10:05:00Z"}
    raw["sender"] = {"id": 88}
    event = GitHubConnector().normalize(raw, uuid4())
    assert event.type == "pr.merged"
    assert event.actors == ("github:user:88",)
