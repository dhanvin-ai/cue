import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest

from cue.connectors import secret_store
from cue.connectors.calendly import CalendlyConnector
from cue.connectors.credentials import Credential

USER = {"uri": "https://api.calendly.com/users/U1", "email": "Rohith@Example.com",
        "scheduling_url": "https://calendly.com/rohith"}
EVENT = {"uri": "https://api.calendly.com/scheduled_events/E1", "name": "Design partner call",
         "status": "active", "start_time": "2026-11-02T10:00:00Z",
         "end_time": "2026-11-02T10:30:00Z", "updated_at": "2026-10-30T08:00:00Z",
         "location": {"join_url": "https://meet.google.com/abc-defg-hij"}}


def test_file_store_reads_writes_and_refuses_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("CUE_SECRETS_DIR", str(tmp_path))
    ref = secret_store.FileSecretStore().write("calendly-rohith", b'{"access_token": "pat"}')
    assert ref == "file:calendly-rohith/versions/latest"
    assert secret_store.read(ref) == b'{"access_token": "pat"}'
    assert Credential(ref, "calendly").token() == "pat"
    for bad in ("file:../x/versions/latest", "file:.env/versions/latest", "file:/versions/latest"):
        with pytest.raises(ValueError):
            secret_store.read(bad)


def calendly(tmp_path, monkeypatch, handler):
    monkeypatch.setenv("CUE_SECRETS_DIR", str(tmp_path))
    ref = secret_store.FileSecretStore().write("calendly", b'{"access_token": "pat"}')
    return CalendlyConnector(Credential(ref, "calendly"),
                             client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_calendly_backfill_pages_and_normalizes_with_invitee_acl(tmp_path, monkeypatch):
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        assert request.headers["Authorization"] == "Bearer pat"
        path = request.url.path
        if path == "/users/me":
            return httpx.Response(200, json={"resource": USER})
        if path == "/scheduled_events" and "page_token" not in str(request.url):
            assert request.url.params["user"] == USER["uri"]
            return httpx.Response(200, json={"collection": [EVENT], "pagination": {
                "next_page": "https://api.calendly.com/scheduled_events?page_token=2"}})
        if path == "/scheduled_events":
            return httpx.Response(200, json={"collection": [], "pagination": {}})
        if path == "/scheduled_events/E1/invitees":
            return httpx.Response(200, json={"collection": [
                {"email": "Priya@Partner.io", "name": "Priya"}], "pagination": {}})
        raise AssertionError(path)

    connector = calendly(tmp_path, monkeypatch, handler)
    connector.authorize("rohith@example.com")
    with pytest.raises(ValueError):
        connector.authorize("someone@example.com")
    raws = list(connector.backfill("rohith@example.com", datetime(2026, 10, 1, tzinfo=timezone.utc)))
    assert len(raws) == 1
    event = connector.normalize(raws[0], uuid4())
    assert event.event_id == "calendly:rohith@example.com:E1:2026-10-30T08:00:00Z"
    assert event.type == "calendly.active"
    assert event.actors == ("gmail:person:priya@partner.io",)
    assert event.acl.principals == ("email:owner:priya@partner.io", "email:owner:rohith@example.com")
    assert event.facts["join_url"] == "https://meet.google.com/abc-defg-hij"


def test_calendly_tools_list_types_and_create_single_use_link(tmp_path, monkeypatch):
    def handler(request: httpx.Request):
        if request.url.path == "/users/me":
            return httpx.Response(200, json={"resource": USER})
        if request.url.path == "/event_types":
            return httpx.Response(200, json={"collection": [{
                "name": "30 min", "duration": 30, "uri": "https://api.calendly.com/event_types/T1",
                "scheduling_url": "https://calendly.com/rohith/30min"}], "pagination": {}})
        if request.url.path == "/scheduling_links":
            body = json.loads(request.content)
            assert body == {"max_event_count": 1, "owner": "https://api.calendly.com/event_types/T1",
                            "owner_type": "EventType"}
            return httpx.Response(201, json={"resource": {"booking_url": "https://calendly.com/d/x"}})
        raise AssertionError(request.url.path)

    connector = calendly(tmp_path, monkeypatch, handler)
    assert connector.list_event_types()[0]["scheduling_url"] == "https://calendly.com/rohith/30min"
    assert connector.create_booking_link("https://api.calendly.com/event_types/T1") == \
        "https://calendly.com/d/x"
    assert {tool.name: tool.risk_tier for tool in connector.tools()} == {
        "calendly.list_event_types": 0, "calendly.create_booking_link": 1}
