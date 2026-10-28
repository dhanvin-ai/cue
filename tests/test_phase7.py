import json
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import psycopg
import pytest

from cue.meetings import addressing, service, store, voice
from cue.meetings.models import (MeetingNotesDraft, SpeakerHint, TranscriptSegment,
                                 Turn)
from cue.meetings.notes import RecordingPublisher
from cue.meetings.speech import RecordingPlayback, RecordingTts, ScriptedStt
from cue.meetings.turns import TurnBuffer, detect_turns
from cue.runtime.executor import ToolRegistry, ToolSpec
from cue.runtime.gateway import Completion

MIGRATION = "MIGRATION_DATABASE_URL"


def migration_url() -> str:
    if MIGRATION not in os.environ:
        pytest.skip("Postgres integration database not configured")
    return os.environ[MIGRATION]


@pytest.fixture
def tenants():
    url = migration_url()
    a, b = uuid4(), uuid4()
    with psycopg.connect(url) as database:
        database.execute("INSERT INTO tenants (id, name) VALUES (%s, 'meeting-a'), (%s, 'meeting-b')",
                         (a, b))
        database.execute(
            "INSERT INTO users (tenant_id, firebase_uid, role) VALUES "
            "(%s, 'alice', 'member'), (%s, 'bob', 'member'), (%s, 'mallory', 'member'), "
            "(%s, 'eve', 'member')",
            (a, a, a, b),
        )
        database.execute(
            "INSERT INTO user_principals (tenant_id, firebase_uid, principal) VALUES "
            "(%s, 'alice', 'email:owner:alice@example.com'), "
            "(%s, 'bob', 'email:owner:bob@example.com'), "
            "(%s, 'mallory', 'email:owner:mallory@example.com'), "
            "(%s, 'eve', 'email:owner:eve@example.com')",
            (a, a, a, b),
        )
        database.execute(
            "INSERT INTO identity_claims (tenant_id, alias, firebase_uid) "
            "VALUES (%s, 'gmail:person:bob@example.com', 'bob')",
            (a,),
        )
    yield SimpleNamespace(a=a, b=b)
    with psycopg.connect(url) as database:
        database.execute("DELETE FROM agent_audit WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM meeting_sessions WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM agent_tasks WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM memory_documents WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM user_principals WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM identity_claims WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM users WHERE tenant_id IN (%s, %s)", (a, b))
        database.execute("DELETE FROM tenants WHERE id IN (%s, %s)", (a, b))


class FakeBot:
    def __init__(self):
        self.joined: list[tuple[str, list[str]]] = []
        self.said: list[str] = []

    def join(self, meeting_url: str, attendees: list[str]) -> str:
        self.joined.append((meeting_url, attendees))
        return "bot-1"

    def leave(self, bot_id: str) -> None:
        return None

    def say(self, bot_id: str, text: str) -> None:
        self.said.append(text)


class AgentGateway:
    def __init__(self, reply: str):
        self.reply = reply

    def complete(self, messages, *, model_class="planner"):
        return Completion(json.dumps({"tool_calls": [], "reply": self.reply}), "fake")


class ScriptedNotes:
    def __init__(self, draft: MeetingNotesDraft):
        self.draft = draft
        self.calls = []

    def notes(self, meeting, turns):
        self.calls.append((meeting, turns))
        return self.draft


def attendees():
    return [
        {"id": "spk-a", "email": "alice@example.com", "display_name": "Alice"},
        {"id": "spk-b", "email": "bob@example.com", "display_name": "Bob"},
    ]


def start_meeting(tenants, people=None):
    bot = FakeBot()
    result = service.join_meeting(
        tenants.a, "alice", "https://meet.google.com/abc-defg-hij",
        people or attendees(), title="Release review", bot=bot,
    )
    return UUID(result["meeting_id"]), bot


def segment(speaker: str, text: str, offset: float, duration: float = 1.0, *,
            endpoint: bool = False, is_final: bool = True, base=None):
    start = (base or datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)) + timedelta(seconds=offset)
    return TranscriptSegment(speaker, text, start, start + timedelta(seconds=duration),
                             is_final=is_final, endpoint=endpoint,
                             segment_index=f"{speaker}:{offset}")


def memory(*args):
    return {"summary": "meeting context", "citations": []}


def test_addressing_uses_name_direction_pause_and_follow_up():
    check = addressing.Addressing()
    moment = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    assert check.check("Cue, what shipped?", now=moment)
    assert check.check("and what about today?", now=moment + timedelta(seconds=10))
    assert not check.check("Let's review the roadmap.", now=moment + timedelta(seconds=20))
    assert not check.check("and what about tomorrow?", now=moment + timedelta(seconds=120))

    assert not addressing.is_addressed("What shipped yesterday?", pause_ms=500, holds_answer=True)
    assert addressing.is_addressed("What shipped yesterday?", pause_ms=2500, holds_answer=True)
    assert not addressing.is_addressed("Cue, status?", silent=True)


def test_turn_detection_uses_silence_endpoint_and_speaker_changes():
    base = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    segments = [
        segment("a", "hello", 0, base=base),
        segment("a", "there", 1.2, base=base),
        segment("a", "next", 3.2, base=base),
        segment("b", "yep", 4.1, base=base, endpoint=True),
        segment("a", "partial", 5.1, base=base, is_final=False),
        segment("a", "done", 6.2, base=base),
    ]
    turns = detect_turns(segments)
    assert [turn.text for turn in turns] == ["hello there", "next", "yep", "done"]
    assert [turn.end_reason for turn in turns] == [
        "silence", "speaker_change", "endpoint", "end_of_stream"]

    buffer = TurnBuffer()
    closed = []
    for item in segments:
        closed.extend(buffer.push(item))
    closed.extend(buffer.flush())
    assert [turn.text for turn in closed] == ["hello there", "next", "yep", "done"]


def test_speaker_mapping_keeps_unknown_speakers_unknown(tenants):
    meeting_id, _ = start_meeting(tenants)
    with store.tenant_connection(tenants.a) as database:
        mapped = {item.speaker_id: item for item in service.speakers.map_speakers(
            database, tenants.a, meeting_id,
            [SpeakerHint("spk-a", "Alice", "alice@example.com"),
             SpeakerHint("spk-b", "Bob", "bob@example.com"),
             SpeakerHint("spk-x", "Mystery", None)],
        )}
    assert mapped["spk-a"].label == "known" and mapped["spk-a"].firebase_uid == "alice"
    assert mapped["spk-b"].label == "known" and mapped["spk-b"].firebase_uid == "bob"
    assert mapped["spk-x"].label == "unknown" and mapped["spk-x"].firebase_uid is None


def test_streamed_reply_chunks_reach_tts_in_order(tenants):
    meeting_id, _ = start_meeting(tenants)
    answer = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    tts, playback = RecordingTts(), RecordingPlayback()
    with store.tenant_connection(tenants.a) as database:
        reply_id = store.record_reply(
            database, tenants.a, meeting_id, task_id=None, speaker_id="spk-a",
            request_text="Cue, summarize?", answer=answer)
        result = voice.stream_reply(
            database, tenants.a, meeting_id, reply_id, answer,
            tts=tts, playback=playback, interrupted=lambda: False)
    assert result.status == "completed"
    assert tts.chunks == voice.chunk_text(answer)
    assert playback.played == [f"audio:{chunk}".encode() for chunk in tts.chunks]
    with store.tenant_connection(tenants.a) as database:
        row = database.execute(
            "SELECT status, chunks_sent FROM meeting_replies WHERE tenant_id = %s AND id = %s",
            (tenants.a, reply_id)).fetchone()
    assert row == ("completed", len(tts.chunks))


def test_human_interruption_stops_tts_and_records_cutoff(tenants):
    meeting_id, _ = start_meeting(tenants)
    answer = ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
              "fifteen sixteen seventeen eighteen nineteen twenty")
    tts, playback = RecordingTts(), RecordingPlayback()
    calls = {"count": 0}

    def interrupted():
        calls["count"] += 1
        return calls["count"] > 2

    turn = Turn("spk-a", "Cue, summarize the release.", datetime(2026, 10, 28, 9, 0,
                 tzinfo=timezone.utc), datetime(2026, 10, 28, 9, 0, 2, tzinfo=timezone.utc),
                "endpoint")
    result = service.handle_turn(
        tenants.a, meeting_id, turn, check=addressing.Addressing(),
        gateway=AgentGateway(answer), registry=ToolRegistry(), tts=tts,
        playback=playback, interrupted=interrupted, memory=memory,
    )
    assert result is not None and result["reply"].status == "interrupted"
    assert result["reply"].chunks_sent == 2
    assert tts.cancelled and playback.stopped
    assert len(tts.chunks) == 2
    with store.tenant_connection(tenants.a) as database:
        row = database.execute(
            "SELECT status, chunks_sent, cutoff_at FROM meeting_replies "
            "WHERE tenant_id = %s AND meeting_id = %s", (tenants.a, meeting_id)).fetchone()
    assert row[0] == "interrupted" and row[1] == 2 and row[2] is not None


def test_post_meeting_notes_link_sources_and_publish_with_meeting_acl(tenants):
    meeting_id, _ = start_meeting(tenants)
    base = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    for index, item in enumerate([
        segment("spk-a", "We reviewed the release.", 0, base=base, endpoint=True),
        segment("spk-b", "Ship on Friday.", 1.2, base=base, endpoint=True),
        segment("spk-a", "File the remaining bug.", 2.4, base=base, endpoint=True),
    ]):
        service.ingest_segment(tenants.a, meeting_id, item,
                               hint=SpeakerHint(item.speaker_id))
    draft = MeetingNotesDraft(
        "Release reviewed and scheduled.",
        ("Ship on Friday",),
        ({"text": "File the remaining bug", "owner": "Alice", "owner_uid": "alice",
          "tool": "linear.create_issue", "arguments": {"title": "Remaining bug"}},),
        (0, 1),
    )
    registry = ToolRegistry([ToolSpec("linear.create_issue", 2, lambda args: {"id": "L1"},
                                      "create an issue")])
    publisher = RecordingPublisher()
    result = service.end_meeting(
        tenants.a, meeting_id, notes_model=ScriptedNotes(draft), registry=registry,
        publisher=publisher, slack_channel="C123",
    )
    note = result["note"]
    assert note["summary"] == "Release reviewed and scheduled."
    assert [source["position"] for source in note["sources"]] == [0, 1]
    assert note["action_items"][0]["task_id"]
    assert result["actions"][0]["status"] == "awaiting_approval"
    assert result["actions"][0]["approvals"][0]["status"] == "pending"
    assert {item["destination"] for item in publisher.deliveries} == {"slack", "email"}
    assert service.get_notes(tenants.a, meeting_id, "alice") is not None
    assert service.get_notes(tenants.a, meeting_id, "bob") is not None
    assert service.get_notes(tenants.a, meeting_id, "mallory") is None
    assert service.get_notes(tenants.b, meeting_id, "eve") is None
    with store.tenant_connection(tenants.a) as database:
        published = database.execute(
            "SELECT visibility, principals FROM memory_documents "
            "WHERE tenant_id = %s AND type = 'meeting.notes'", (tenants.a,)).fetchone()
        transcript_count = database.execute(
            "SELECT count(*) FROM memory_documents WHERE tenant_id = %s "
            "AND type = 'meeting.transcript'", (tenants.a,)).fetchone()[0]
    assert published[0] == "restricted"
    assert set(published[1]) == {"email:owner:alice@example.com", "email:owner:bob@example.com"}
    assert transcript_count == 3


def test_meeting_rows_are_tenant_isolated(tenants):
    meeting_id, _ = start_meeting(tenants)
    with store.tenant_connection(tenants.b) as database:
        assert store.get_meeting(database, tenants.b, meeting_id) is None
        assert database.execute("SELECT count(*) FROM meeting_sessions").fetchone()[0] == 0
    with store.tenant_connection(tenants.a) as database:
        assert store.get_meeting(database, tenants.a, meeting_id) is not None


def test_scripted_meeting_end_to_end_from_join_to_notes(tenants):
    meeting_id, bot = start_meeting(tenants)
    assert bot.joined and bot.said
    script = [
        segment("spk-a", "Let's review the roadmap.", 0, endpoint=True),
        segment("spk-a", "Cue, what shipped yesterday?", 1.2, endpoint=True),
        segment("spk-b", "Thanks.", 2.4, endpoint=True),
    ]
    tts, playback = RecordingTts(), RecordingPlayback()
    runtime = service.MeetingRuntime(
        tenants.a, meeting_id, stt=ScriptedStt(script), tts=tts, playback=playback,
        gateway=AgentGateway("We shipped the billing fix."), registry=ToolRegistry(),
        memory=memory,
    )
    results = runtime.run()
    assert len(results) == 1 and results[0]["answer"] == "We shipped the billing fix."
    assert tts.chunks == voice.chunk_text("We shipped the billing fix.")
    draft = MeetingNotesDraft("The team reviewed the roadmap.", ("Ship the billing fix",),
                              (), (0, 1))
    result = service.end_meeting(tenants.a, meeting_id, notes_model=ScriptedNotes(draft))
    assert result["note"]["summary"] == "The team reviewed the roadmap."
    assert [source["position"] for source in result["note"]["sources"]] == [0, 1]
    assert service.get_notes(tenants.a, meeting_id, "alice") is not None
    with store.tenant_connection(tenants.a) as database:
        status = database.execute(
            "SELECT status FROM meeting_sessions WHERE tenant_id = %s AND id = %s",
            (tenants.a, meeting_id)).fetchone()[0]
    assert status == "ended"
