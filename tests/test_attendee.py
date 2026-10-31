import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
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


def test_join_creates_named_bot_and_discloses_only_once_admitted(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    path, body = calls[0]
    assert path == "/api/v1/bots" and body["bot_name"] == "Cue"
    assert "meeting_closed_captions" in body["transcription_settings"]
    assert body["webhooks"][0]["triggers"] == [
        "transcript.update", "bot.state_change", "chat_messages.update"]
    assert spoken(calls) == []
    for state in ("joining", "joined_recording"):
        attendee.handle_event(tenants.a, {"trigger": "bot.state_change", "bot_id": "bot_abc",
                                          "data": {"new_state": state}},
                              bot=bot, gateway=None, registry=None)
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


def test_addressed_caption_acknowledges_then_answers(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    calls.clear()
    result = attendee.handle_event(tenants.a, caption("Cue, what's blocking the release?"),
                                   bot=bot, gateway=AgentGateway("PR 412 awaits review."),
                                   registry=ToolRegistry(), memory=memory)
    assert result["answer"] == "PR 412 awaits review."
    filler, answer = spoken(calls)
    assert filler.removeprefix("mp3:") in attendee.FILLERS and answer == "mp3:PR 412 awaits review."


def test_failed_turn_apologises_aloud(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    calls.clear()

    class Broken:
        def complete(self, *args, **kwargs):
            raise RuntimeError("gateway 401")

    try:
        attendee.handle_event(tenants.a, caption("Cue, status?"), bot=bot, gateway=Broken(),
                              registry=ToolRegistry(), memory=memory)
    except Exception:
        pass
    assert spoken(calls)[-1] == "mp3:Sorry, I hit an error on that one."


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


def test_long_answer_is_spoken_one_sentence_per_clip_in_order():
    calls = []
    bot = attendee.AttendeeMeetingBot(fake_client(calls), "https://cue.test/webhooks/attendee/t",
                                      tts=lambda text: f"mp3:{text}".encode())
    bot.say_sentences("attendee:bot_abc", "We ship Friday. Load test passed! Any blockers?")
    assert spoken(calls) == ["mp3:We ship Friday.", "mp3:Load test passed!", "mp3:Any blockers?"]


def test_small_talk_skips_the_memory_search():
    for line in ["Cue, are you there?", "Hey Cue, um, can you hear me?", "cue hello", "Hello, Cue!"]:
        assert service.SMALL_TALK.fullmatch(line), line
    assert not service.SMALL_TALK.fullmatch("Cue, are you there blockers on the launch?")


def test_misheard_name_still_addresses_cue_but_ordinary_queue_talk_does_not():
    from cue.meetings.addressing import _mentions
    for line in ["Eq are reactive.", "Q, what's open?", "Hey queue, are you there?"]:
        assert _mentions(line, "Cue"), line
    for line in ["The job queue is stuck", "Queue is backed up again", "Equity is up"]:
        assert not _mentions(line, "Cue"), line


def test_filler_before_misheard_name_still_addresses_cue():
    from cue.meetings.addressing import _mentions
    assert _mentions("Uh, Hey, Q what are the last comments?", "Cue")


def test_one_on_one_question_needs_no_name_but_group_call_does(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    result = attendee.handle_event(tenants.a, caption("Take you. What are the last commits?"),
                                   bot=bot, gateway=AgentGateway("Bumped the test timeout."),
                                   registry=ToolRegistry(), memory=memory)
    assert result["answer"] == "Bumped the test timeout."
    attendee.handle_event(tenants.a, caption("Morning all.", name="Bob", speaker="spk-2",
                                             ms=1_700_000_010_000),
                          bot=bot, gateway=AgentGateway("x"), registry=ToolRegistry(), memory=memory)
    assert attendee.handle_event(tenants.a, caption("What's the plan?", ms=1_700_000_020_000),
                                 bot=bot, gateway=AgentGateway("x"), registry=ToolRegistry(),
                                 memory=memory) is None


def test_question_split_across_captions_is_answered_once(tenants):
    calls = []
    bot, meeting_id = joined(tenants, calls)
    calls.clear()
    later = caption("Cue, can you summarize me the last commits?", ms=1_700_000_001_000)

    class Overtaken(AgentGateway):
        # The rest of the sentence arrives while the first half is still being answered.
        def complete(self, messages, *, model_class="planner"):
            attendee._newest[(meeting_id, "spk-1")] = datetime.fromtimestamp(
                later["data"]["timestamp_ms"] / 1000, timezone.utc)
            return super().complete(messages, model_class=model_class)

    first = attendee.handle_event(tenants.a, caption("Cue, can you summarize?"), bot=bot,
                                  gateway=Overtaken("There is nothing to summarize yet."),
                                  registry=ToolRegistry(), memory=memory)
    second = attendee.handle_event(tenants.a, later, bot=bot,
                                   gateway=AgentGateway("Three commits fixed the release tests."),
                                   registry=ToolRegistry(), memory=memory)
    assert first["reply"].status == "interrupted" and second["reply"].status == "completed"
    said = spoken(calls)
    assert said[-1] == "mp3:Three commits fixed the release tests."
    assert "mp3:There is nothing to summarize yet." not in said
    assert sum(line.removeprefix("mp3:") in attendee.FILLERS for line in said) == 1
    with store.tenant_connection(tenants.a) as database:
        replies = [e["text"] for e in store.timeline(database, tenants.a, meeting_id) if e["kind"] == "cue"]
    assert replies == ["Three commits fixed the release tests."]


def test_kyutai_is_used_only_while_its_server_is_up(monkeypatch):
    monkeypatch.setenv("CUE_TRANSCRIBER", "kyutai")
    monkeypatch.setattr(attendee, "_listening", lambda url: True)
    assert "kyutai" in attendee.transcription_settings()
    monkeypatch.setattr(attendee, "_listening", lambda url: False)
    assert attendee.transcription_settings() == attendee.CAPTIONS
    monkeypatch.setenv("CUE_TRANSCRIBER", "captions")
    assert attendee.transcription_settings() == attendee.CAPTIONS


def test_whisper_is_prompted_with_cues_name(monkeypatch):
    monkeypatch.setenv("CUE_TRANSCRIBER", "whisper")
    monkeypatch.setattr(attendee, "_listening", lambda url: True)
    settings = attendee.transcription_settings()["openai"]
    assert "Cue" in settings["prompt"] and settings["language"] == "en"
    monkeypatch.setattr(attendee, "_listening", lambda url: False)
    assert attendee.transcription_settings() == attendee.CAPTIONS


class StreamingGateway:
    """Speaks the OpenAI SSE format, so the meeting takes the streamed path."""
    models = ["fake-stream", "fake-fallback"]

    def __init__(self, pieces):
        self.pieces = pieces
        self.client = self

    def _route(self, index):
        return "https://gateway.test/v1/chat/completions", {}

    def stream(self, method, url, **kwargs):
        pieces = self.pieces

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def raise_for_status(self):
                pass

            def iter_lines(self):
                for piece in pieces:
                    yield "data: " + json.dumps({"choices": [{"delta": {"content": piece}}]})
                yield "data: [DONE]"

        return Response()


def test_streamed_answer_is_spoken_sentence_by_sentence_once(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    calls.clear()
    result = attendee.handle_event(
        tenants.a, caption("Cue, when do we ship?"), bot=bot,
        gateway=StreamingGateway(["We ship ", "Friday. Load tests ", "passed [1]."]),
        registry=ToolRegistry(), memory=memory)
    assert result["answer"] == "We ship Friday. Load tests passed."
    said = spoken(calls)
    assert said[0].removeprefix("mp3:") in attendee.FILLERS
    assert said[1:] == ["mp3:We ship Friday.", "mp3:Load tests passed."]


def test_local_voice_falls_back_to_edge_when_kokoro_is_down(monkeypatch):
    monkeypatch.setenv("CUE_TTS", "kokoro")
    monkeypatch.delenv("OPENROUTER_API_KEY_SECRET_VERSION", raising=False)

    def down(text):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(attendee, "kokoro_tts", down)
    monkeypatch.setattr(attendee, "edge_tts", lambda text: b"edge:" + text.encode())
    assert attendee.default_tts("One sec.") == b"edge:One sec."
    monkeypatch.setattr(attendee, "kokoro_tts", lambda text: b"kokoro:" + text.encode())
    assert attendee.default_tts("One sec.") == b"kokoro:One sec."


def chat(text, *, name="Alice", sender="spk-1", ms=1_700_000_002_000):
    return {"trigger": "chat_messages.update", "bot_id": "bot_abc", "data": {
        "text": text, "sender_name": name, "sender_uuid": sender, "timestamp_ms": ms, "to": "everyone"}}


def test_typed_mention_in_meet_chat_is_answered_aloud_and_in_chat(tenants):
    calls = []
    bot, _ = joined(tenants, calls)
    calls.clear()
    assert attendee.handle_event(tenants.a, chat("lunch at one?"), bot=bot,
                                 gateway=AgentGateway("x"), registry=ToolRegistry(), memory=memory) is None
    result = attendee.handle_event(tenants.a, chat("@Cue what's blocking the release?"), bot=bot,
                                   gateway=AgentGateway("PR 412 awaits review."),
                                   registry=ToolRegistry(), memory=memory)
    assert result["answer"] == "PR 412 awaits review."
    assert spoken(calls)[-1] == "mp3:PR 412 awaits review."
    typed = [body["text"] for path, body in calls if path.endswith("/send_chat_message")]
    assert typed == ["PR 412 awaits review."]


def test_any_greeting_wakes_cue_including_fused_and_misheard_forms():
    from cue.meetings.addressing import is_addressed
    for text in ("Hello Q, what are the last commits?", "HiQ, what are the last commits?",
                 "OK Q what are the last commits?", "Hello Cue, what changed?"):
        assert is_addressed(text), text
    for text in ("Hello everyone, the queue is stuck.", "Hi, the queue is backed up.",
                 "Okay, so what about the release?"):
        assert not is_addressed(text), text
