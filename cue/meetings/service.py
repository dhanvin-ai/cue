"""Meeting lifecycle: join through Recall, live turns, streamed replies, and notes."""

import os
from datetime import datetime, timezone
from typing import Protocol

import psycopg

from cue.connectors.recall import RecallConnector
from cue.meetings import addressing as addressing_module
from cue.meetings import notes, speakers, store, turns, voice
from cue.meetings.models import (MeetingNotesDraft, ReplyResult, SpeakerHint,
                                 TranscriptSegment, Turn)
from cue.runtime import context as context_builder
from cue.runtime import ingress as agent_ingress
from cue.runtime import service as agent_service

DISCLOSURE = "Cue is an AI teammate. This meeting is being recorded and transcribed."


class MeetingBot(Protocol):
    def join(self, meeting_url: str, attendees: list[str]) -> str: ...

    def leave(self, bot_id: str) -> None: ...


class RecallMeetingBot:
    def __init__(self, connector: RecallConnector):
        self.connector = connector

    def join(self, meeting_url: str, attendees: list[str]) -> str:
        return self.connector.create_bot(meeting_url, attendees)["id"]

    def leave(self, bot_id: str) -> None:
        return None

    def transcript_events(self, bot_id: str):
        """Yield Recall's transcript segments; the worker feeds audio to the SttClient."""
        return self.connector.backfill(bot_id, datetime.now(timezone.utc))


def recall_bot() -> RecallMeetingBot:
    from cue.connectors.credentials import Credential

    token = Credential(os.environ["RECALL_API_KEY_SECRET_VERSION"], "recall").token()
    return RecallMeetingBot(RecallConnector(token, os.environ["RECALL_REGION"]))


def _attendee(item) -> dict:
    if isinstance(item, str):
        return {"id": item, "email": item if "@" in item else None, "display_name": None}
    return {"id": item.get("id"), "email": item.get("email"),
            "display_name": item.get("display_name") or item.get("name")}


def _principals(attendees: list[dict]) -> list[str]:
    emails = {item["email"].casefold() for item in attendees if item.get("email")}
    return ([f"email:owner:{email}" for email in sorted(emails)] or ["cue:admins"])


def join_meeting(tenant_id, uid: str, meeting_url: str, attendees: list,
                 *, title: str | None = None, bot: MeetingBot | None = None,
                 database_url: str | None = None, now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    people = [_attendee(item) for item in attendees]
    principals = _principals(people)
    with store.tenant_connection(tenant_id, database_url) as database:
        if store.membership(database, tenant_id, uid) is None:
            raise PermissionError("Requester is not a member of this tenant")
        meeting_id = store.create_meeting(
            database, tenant_id, meeting_url=meeting_url, owner_uid=uid, title=title,
            principals=principals, disclosure=DISCLOSURE,
        )
        hints = [SpeakerHint(str(item["id"] or item["email"] or f"attendee-{index}"),
                             item["display_name"], item["email"])
                 for index, item in enumerate(people)]
        if hints:
            speakers.map_speakers(database, tenant_id, meeting_id, hints)
    chosen = bot or recall_bot()
    bot_id = chosen.join(meeting_url, [item["email"] for item in people if item.get("email")])
    say = getattr(chosen, "say", None)
    if say is not None:
        say(bot_id, DISCLOSURE)
    with store.tenant_connection(tenant_id, database_url) as database:
        store.mark_joined(database, tenant_id, meeting_id, str(bot_id), moment)
    return {"meeting_id": str(meeting_id), "bot_id": str(bot_id), "status": "live",
            "principals": principals, "disclosure": DISCLOSURE}


def ingest_segment(tenant_id, meeting_id, segment: TranscriptSegment,
                   *, hint: SpeakerHint | None = None,
                   database_url: str | None = None) -> int:
    with store.tenant_connection(tenant_id, database_url) as database:
        meeting = store.get_meeting(database, tenant_id, meeting_id)
        if meeting is None:
            raise LookupError("Meeting not found")
        position = store.next_position(database, tenant_id, meeting_id)
        store.add_segment(
            database, tenant_id, meeting_id, position,
            segment.segment_index or f"{meeting_id}:{position}", segment.speaker_id,
            segment.text, segment.started_at, segment.ended_at, segment.is_final,
            segment.endpoint,
        )
        speakers.map_speakers(database, tenant_id, meeting_id,
                              [hint or SpeakerHint(segment.speaker_id)])
    return position


def handle_turn(tenant_id, meeting_id, turn: Turn, *, check: addressing_module.Addressing,
                gateway, registry, tts, playback, interrupted=None, memory=None,
                database_url: str | None = None, now: datetime | None = None,
                pause_ms: int | None = None) -> dict | None:
    moment = now or datetime.now(timezone.utc)
    with store.tenant_connection(tenant_id, database_url) as database:
        meeting = store.get_meeting(database, tenant_id, meeting_id)
        if meeting is None:
            raise LookupError("Meeting not found")
        if meeting["status"] != "live":
            return None
        paused = pause_ms if pause_ms is not None else (2000 if turn.end_reason == "silence" else 0)
        if not check.check(turn.text, pause_ms=paused, holds_answer=True, now=moment):
            return None
        uid = speakers.speaker_uid(database, tenant_id, meeting_id, turn.speaker_id)
        requester = uid or meeting["owner_uid"]
        participant_uids = speakers.participant_uids(database, tenant_id, meeting_id)
    request = agent_ingress.RuntimeRequest(
        tenant_id=tenant_id, source="meeting", requester_uid=requester,
        text=turn.text, idempotency_key=f"meeting:{meeting_id}:turn:{turn.started_at.isoformat()}",
        channel_ref=str(meeting_id), thread_ref=f"turn:{turn.started_at.isoformat()}",
        metadata={"speaker_id": turn.speaker_id, "speaker_known": bool(uid)},
    )
    task_id, _ = agent_ingress.submit(request, database_url=database_url)

    def meeting_memory(tenant, requester_uid, question, participants):
        if memory is not None:
            return memory(tenant, requester_uid, question, participants)
        return context_builder.build_context(
            tenant, requester_uid, question, participant_uids, database_url=database_url)

    result = agent_service.run_task(
        tenant_id, task_id, gateway=gateway, registry=registry,
        database_url=database_url, memory=meeting_memory,
    )
    answer = result.get("answer")
    if not answer:
        answer = ("I need approval before I can do that."
                  if result["status"] == "awaiting_approval"
                  else "I couldn't complete that request.")
    with store.tenant_connection(tenant_id, database_url) as database:
        reply_id = store.record_reply(
            database, tenant_id, meeting_id, task_id=task_id, speaker_id=turn.speaker_id,
            request_text=turn.text, answer=answer,
        )
        reply = voice.stream_reply(
            database, tenant_id, meeting_id, reply_id, answer,
            tts=tts, playback=playback, interrupted=interrupted or (lambda: False),
            now=moment,
        )
    return {"addressed": True, "task_id": str(task_id), "task_status": result["status"],
            "reply": reply, "answer": answer}


def get_notes(tenant_id, meeting_id, uid: str, *, database_url: str | None = None) -> dict | None:
    with store.tenant_connection(tenant_id, database_url) as database:
        return store.note_for_user(database, tenant_id, meeting_id, uid)


class MeetingRuntime:
    """Consumes a live segment stream and answers only when Cue is addressed."""

    def __init__(self, tenant_id, meeting_id, *, stt, tts, playback, gateway, registry,
                 database_url: str | None = None, memory=None,
                 speaker_hints: dict[str, SpeakerHint] | None = None,
                 check: addressing_module.Addressing | None = None):
        self.tenant_id = tenant_id
        self.meeting_id = meeting_id
        self.stt = stt
        self.tts = tts
        self.playback = playback
        self.gateway = gateway
        self.registry = registry
        self.database_url = database_url
        self.memory = memory
        self.speaker_hints = speaker_hints or {}
        self.check = check or addressing_module.Addressing()
        self.buffer = turns.TurnBuffer()

    def run(self, *, interrupted=None) -> list[dict]:
        results = []
        for segment in self.stt.stream(str(self.meeting_id)):
            ingest_segment(self.tenant_id, self.meeting_id, segment,
                           hint=self.speaker_hints.get(segment.speaker_id),
                           database_url=self.database_url)
            for turn in self.buffer.push(segment):
                result = self.handle(turn, interrupted=interrupted)
                if result:
                    results.append(result)
        for turn in self.buffer.flush():
            result = self.handle(turn, interrupted=interrupted)
            if result:
                results.append(result)
        return results

    def handle(self, turn: Turn, *, interrupted=None) -> dict | None:
        return handle_turn(
            self.tenant_id, self.meeting_id, turn, check=self.check,
            gateway=self.gateway, registry=self.registry, tts=self.tts,
            playback=self.playback, interrupted=interrupted, memory=self.memory,
            database_url=self.database_url,
        )


def end_meeting(tenant_id, meeting_id, *, notes_model: notes.NotesModel,
                registry=None, publisher: notes.NotesPublisher | None = None,
                slack_channel: str | None = None, database_url: str | None = None,
                now: datetime | None = None) -> dict:
    moment = now or datetime.now(timezone.utc)
    with store.tenant_connection(tenant_id, database_url) as database:
        meeting = store.get_meeting(database, tenant_id, meeting_id)
        if meeting is None:
            raise LookupError("Meeting not found")
        rows = store.segments(database, tenant_id, meeting_id)
        segments = [TranscriptSegment(
            speaker_id=row["speaker_id"], text=row["text"], started_at=row["started_at"],
            ended_at=row["ended_at"], is_final=row["is_final"], endpoint=row["endpoint"],
            segment_index=row["segment_index"],
        ) for row in rows]
        matched = turns.detect_turns(segments)
        draft: MeetingNotesDraft = notes_model.notes(meeting, matched)
        existing = database.execute(
            "SELECT id FROM meeting_notes WHERE tenant_id = %s AND meeting_id = %s",
            (tenant_id, meeting_id),
        ).fetchone()
        if existing is not None:
            note = store.note_for_user(database, tenant_id, meeting_id, meeting["owner_uid"])
            if note is not None:
                return {"meeting_id": str(meeting_id), "note": note, "actions": []}
        store.end_meeting(database, tenant_id, meeting_id, moment)
        meeting["status"] = "ended"
        meeting["ended_at"] = moment
        principals = list(meeting["principals"])
        note_id = store.create_note(
            database, tenant_id, meeting_id, summary=draft.summary,
            decisions=list(draft.decisions), action_items=[dict(item) for item in draft.action_items],
            visibility=meeting["visibility"], principals=principals,
        )
        positions = list(draft.source_positions) or [row["position"] for row in rows]
        store.link_note_sources(database, tenant_id, note_id, meeting_id, positions)
        note = {"id": str(note_id), "summary": draft.summary,
                "decisions": list(draft.decisions),
                "action_items": [dict(item) for item in draft.action_items],
                "visibility": meeting["visibility"], "principals": principals,
                "sources": [{"position": row["position"], "quote": row["text"]}
                            for row in rows if row["position"] in positions]}
        emails = [row[0] for row in database.execute(
            "SELECT DISTINCT email FROM meeting_participants WHERE tenant_id = %s "
            "AND meeting_id = %s AND email IS NOT NULL", (tenant_id, meeting_id)).fetchall()]
        store.queue_deliveries(
            database, tenant_id, note_id, slack_channel=slack_channel, emails=emails,
            payload={"summary": draft.summary, "decisions": list(draft.decisions),
                     "action_items": [dict(item) for item in draft.action_items]},
        )
        action_rows = [dict(item) for item in draft.action_items]
        participant_uids = speakers.participant_uids(database, tenant_id, meeting_id)
    with psycopg.connect(os.environ["INGEST_DATABASE_URL"]) as memory_database:
        memory_database.execute("SELECT set_config('app.tenant_id', %s, true)", (str(tenant_id),))
        store.publish_memory(memory_database, tenant_id, meeting, rows, note)
    if publisher is not None:
        with store.tenant_connection(tenant_id, database_url) as delivery_database:
            notes.publish_pending(delivery_database, tenant_id, publisher)
    actions = _run_actions(
        tenant_id, meeting, note_id, action_rows, registry=registry,
        database_url=database_url, participant_uids=participant_uids,
    )
    if actions:
        with store.tenant_connection(tenant_id, database_url) as database:
            store.update_note_action_items(database, tenant_id, note_id, action_rows)
    note["action_items"] = action_rows
    return {"meeting_id": str(meeting_id), "note": note, "actions": actions}


def _run_actions(tenant_id, meeting: dict, note_id, action_items: list[dict], *, registry,
                 database_url: str | None, participant_uids: list[str]) -> list[dict]:
    if registry is None:
        return []
    results = []
    for index, item in enumerate(action_items):
        tool = item.get("tool")
        if not tool:
            continue
        if registry.get(tool) is None:
            item["action_status"] = "unsupported"
            continue
        requester = item.get("owner_uid") or meeting["owner_uid"]
        request = agent_ingress.RuntimeRequest(
            tenant_id=tenant_id, source="meeting", requester_uid=requester,
            text=f"Action item: {item.get('text', '')}",
            idempotency_key=f"meeting:{meeting['id']}:action:{index}",
            channel_ref=str(meeting["id"]), thread_ref=f"action:{index}",
        )
        try:
            task_id, _ = agent_ingress.submit(request, database_url=database_url)
        except PermissionError:
            item["action_status"] = "requester_unknown"
            continue
        result = agent_service.run_task(
            tenant_id, task_id, gateway=notes.SingleActionGateway(tool, item.get("arguments") or {}),
            registry=registry, database_url=database_url,
            memory=lambda *args: {"summary": "meeting action item", "citations": []},
        )
        item["task_id"] = str(task_id)
        item["action_status"] = result["status"]
        results.append({"tool": tool, "task_id": str(task_id), "status": result["status"],
                        "approvals": result["approvals"]})
    return results
