import base64
import hashlib
import hmac
import json
from uuid import UUID

import httpx

from cue.meetings import attendee, service, store
from cue.runtime.executor import ToolRegistry
from tests.test_phase7 import AgentGateway, attendees, memory, tenants  # noqa: F401


def fake_client(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.url.path, body))
        if request.url.path == "/api/v1/bots":
            return httpx.Response(201, json={"id": "bot_abc", "state": "joining"})
        return httpx.Response(200, json={})
    return attendee.AttendeeClient("http://attendee.test", "key", httpx.Client(
        base_url="http://attendee.test", transport=httpx.MockTransport(handler)))


def joined(tenants, calls):
    bot = attendee.AttendeeMeetingBot(fake_client(calls), "https://cue.test/webhooks/attendee/t",
                                      tts=lambda text: f"mp3:{text}".encode())
    result = service.join_meeting(tenants.a, "alice", "https://meet.google.com/abc-defg-hij",
                                  attendees(), title="Release review", bot=bot)
    return bot, UUID(result["meeting_id"])


def caption(text, *, name="Alice", speaker="spk-1", ms=1_700_000_000_000):
    return {"trigger": "transcript.update", "bot_id": "bot_abc", "data": {
        "speaker_name": name, "speaker_uuid": speaker, "timestamp_ms": ms, "duration_ms": 1500,
        "transcription": {"transcript": text}}}


def spoken(calls):
    return [base64.b64decode(body["data"]).decode() for path, body in calls
            if path.endswith("/output_audio")]


def test_join_creates_named_bot_with_captions_and_speaks_disclosure(tenants):
    calls = []
    joined(tenants, calls)
    path, body = calls[0]
    assert path == "/api/v1/bots" and body["bot_name"] == "Cue"
    assert "meeting_closed_captions" in body["transcription_settings"]
    assert body["webhooks"][0]["triggers"] == ["transcript.update", "bot.state_change"]
    assert spoken(calls) == [f"mp3:{service.DISCLOSURE}"]


def test_signature_matches_attendee_scheme():
    secret = base64.b64encode(b"s3cret").decode()
    payload = caption("hi")
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    good = base64.b64encode(hmac.new(b"s3cret", canonical.encode(), hashlib.sha256).digest()).decode()
    assert attendee.verify(payload, good, secret)
    assert not attendee.verify(payload, good, base64.b64encode(b"other").decode())
    assert not attendee.verify(payload, None, secret)


def test_unaddressed_caption_is_transcribed_silently(tenants):
    calls = []
    bot, meeting_id = joined(tenants, calls)
    calls.clear()
    assert attendee.handle_event(tenants.a, caption("Let's ship Friday."), bot=bot,
                                 gateway=AgentGateway("unused"), registry=ToolRegistry(),
                                 memory=memory) is None
    assert spoken(calls) == []
    with store.tenant_connection(tenants.a) as database:
        rows = store.segments(database, tenants.a, meeting_id)
    assert [(row["speaker_id"], row["text"]) for row in rows] == [("spk-1", "Let's ship Friday.")]


def test_addressed_caption_speaks_filler_then_answer(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    calls.clear()
    result = attendee.handle_event(tenants.a, caption("Cue, what's blocking the release?"),
                                   bot=bot, gateway=AgentGateway("PR 412 awaits review."),
                                   registry=ToolRegistry(), memory=memory)
    assert result["answer"] == "PR 412 awaits review."
    assert spoken(calls) == [f"mp3:{attendee.FILLER}", "mp3:PR 412 awaits review."]


def test_cue_own_captions_and_unknown_bots_are_ignored(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    calls.clear()
    assert attendee.handle_event(tenants.a, caption("Cue, hello", name="Cue"), bot=bot,
                                 gateway=AgentGateway("x"), registry=ToolRegistry()) is None
    other = caption("Cue, hello") | {"bot_id": "bot_other"}
    assert attendee.handle_event(tenants.a, other, bot=bot, gateway=AgentGateway("x"),
                                 registry=ToolRegistry()) is None
    assert spoken(calls) == []
