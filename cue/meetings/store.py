"""Tenant-scoped persistence for meetings, transcript, replies, and notes."""

import json
from datetime import datetime
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from cue.runtime.store import membership, tenant_connection

__all__ = ["tenant_connection", "membership"]


def create_meeting(database: psycopg.Connection, tenant_id: UUID, *, meeting_url: str,
                   owner_uid: str, title: str | None, principals: list[str],
                   disclosure: str) -> UUID:
    meeting_id = uuid4()
    database.execute(
        "INSERT INTO meeting_sessions (tenant_id, id, meeting_url, title, owner_uid, status, "
        "visibility, principals, disclosure) VALUES (%s, %s, %s, %s, %s, 'joining', "
        "'restricted', %s, %s)",
        (tenant_id, meeting_id, meeting_url, title, owner_uid, sorted(set(principals)), disclosure),
    )
    return meeting_id


def mark_joined(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID, bot_id: str,
                now: datetime) -> None:
    database.execute(
        "UPDATE meeting_sessions SET status = 'live', bot_id = %s, started_at = %s, "
        "consent_announced_at = %s WHERE tenant_id = %s AND id = %s",
        (bot_id, now, now, tenant_id, meeting_id),
    )


def get_meeting(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID) -> dict | None:
    row = database.execute(
        "SELECT id, bot_id, meeting_url, title, owner_uid, status, visibility, principals, "
        "disclosure, started_at, ended_at FROM meeting_sessions WHERE tenant_id = %s AND id = %s",
        (tenant_id, meeting_id),
    ).fetchone()
    if row is None:
        return None
    keys = ["id", "bot_id", "meeting_url", "title", "owner_uid", "status", "visibility",
            "principals", "disclosure", "started_at", "ended_at"]
    return dict(zip(keys, row))


def end_meeting(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID,
                now: datetime) -> None:
    database.execute(
        "UPDATE meeting_sessions SET status = 'ended', ended_at = %s "
        "WHERE tenant_id = %s AND id = %s",
        (now, tenant_id, meeting_id),
    )


def add_segment(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID,
                position: int, segment_index: str, speaker_id: str, text: str,
                started_at: datetime, ended_at: datetime, is_final: bool = True,
                endpoint: bool = False) -> None:
    database.execute(
        "INSERT INTO meeting_transcript_segments (tenant_id, meeting_id, position, segment_index, "
        "speaker_id, text, started_at, ended_at, is_final, endpoint) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (tenant_id, meeting_id, position, segment_index, speaker_id, text, started_at, ended_at,
         is_final, endpoint),
    )


def next_position(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID) -> int:
    row = database.execute(
        "SELECT COALESCE(MAX(position), -1) + 1 FROM meeting_transcript_segments "
        "WHERE tenant_id = %s AND meeting_id = %s",
        (tenant_id, meeting_id),
    ).fetchone()
    return row[0]


def segments(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID) -> list[dict]:
    rows = database.execute(
        "SELECT position, segment_index, speaker_id, text, started_at, ended_at, is_final, endpoint "
        "FROM meeting_transcript_segments WHERE tenant_id = %s AND meeting_id = %s "
        "ORDER BY position",
        (tenant_id, meeting_id),
    ).fetchall()
    keys = ["position", "segment_index", "speaker_id", "text", "started_at", "ended_at",
            "is_final", "endpoint"]
    return [dict(zip(keys, row)) for row in rows]


def create_note(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID, *,
                summary: str, decisions: list[str], action_items: list[dict],
                visibility: str, principals: list[str]) -> UUID:
    note_id = uuid4()
    row = database.execute(
        "INSERT INTO meeting_notes (tenant_id, id, meeting_id, summary, decisions, action_items, "
        "visibility, principals) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (tenant_id, meeting_id) DO UPDATE SET summary = EXCLUDED.summary, "
        "decisions = EXCLUDED.decisions, action_items = EXCLUDED.action_items, "
        "visibility = EXCLUDED.visibility, principals = EXCLUDED.principals "
        "RETURNING id",
        (tenant_id, note_id, meeting_id, summary, Jsonb(decisions), Jsonb(action_items),
         visibility, sorted(set(principals))),
    ).fetchone()
    return row[0]


def link_note_sources(database: psycopg.Connection, tenant_id: UUID, note_id: UUID,
                      meeting_id: UUID, positions: list[int]) -> None:
    for position in sorted(set(positions)):
        row = database.execute(
            "SELECT text FROM meeting_transcript_segments WHERE tenant_id = %s AND meeting_id = %s "
            "AND position = %s",
            (tenant_id, meeting_id, position),
        ).fetchone()
        if row is None:
            continue
        database.execute(
            "INSERT INTO meeting_note_sources (tenant_id, note_id, meeting_id, position, quote) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (tenant_id, note_id, meeting_id, position, row[0]),
        )


def update_note_action_items(database: psycopg.Connection, tenant_id: UUID, note_id: UUID,
                             action_items: list[dict]) -> None:
    database.execute(
        "UPDATE meeting_notes SET action_items = %s WHERE tenant_id = %s AND id = %s",
        (Jsonb(action_items), tenant_id, note_id),
    )


def note_for_user(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID,
                  uid: str) -> dict | None:
    """Return notes only when the requester holds one of the meeting ACL principals."""
    role = membership(database, tenant_id, uid)
    if role is None:
        raise PermissionError("Requester is not a member of this tenant")
    grants = {row[0] for row in database.execute(
        "SELECT principal FROM user_principals WHERE tenant_id = %s AND firebase_uid = %s",
        (tenant_id, uid),
    ).fetchall()}
    if role == "admin":
        grants.add("cue:admins")
    row = database.execute(
        "SELECT id, summary, decisions, action_items, visibility, principals, published_at, created_at "
        "FROM meeting_notes WHERE tenant_id = %s AND meeting_id = %s "
        "AND (visibility = 'public' OR principals && %s::text[])",
        (tenant_id, meeting_id, sorted(grants)),
    ).fetchone()
    if row is None:
        return None
    keys = ["id", "summary", "decisions", "action_items", "visibility", "principals",
            "published_at", "created_at"]
    note = dict(zip(keys, row))
    note_id = note["id"]
    note["id"] = str(note_id)
    note["sources"] = [
        {"position": item[0], "quote": item[1]} for item in database.execute(
            "SELECT position, quote FROM meeting_note_sources WHERE tenant_id = %s AND note_id = %s "
            "ORDER BY position",
            (tenant_id, note_id),
        ).fetchall()
    ]
    return note


def record_reply(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID, *,
                 task_id: UUID | None, speaker_id: str, request_text: str,
                 answer: str) -> UUID:
    reply_id = uuid4()
    database.execute(
        "INSERT INTO meeting_replies (tenant_id, id, meeting_id, task_id, speaker_id, "
        "request_text, answer, status, chunks_sent) VALUES (%s, %s, %s, %s, %s, %s, %s, "
        "'streaming', 0)",
        (tenant_id, reply_id, meeting_id, task_id, speaker_id, request_text, answer),
    )
    return reply_id


def finish_reply(database: psycopg.Connection, tenant_id: UUID, reply_id: UUID, status: str,
                 chunks_sent: int, cutoff_at: datetime | None = None) -> None:
    database.execute(
        "UPDATE meeting_replies SET status = %s, chunks_sent = %s, cutoff_at = %s "
        "WHERE tenant_id = %s AND id = %s",
        (status, chunks_sent, cutoff_at, tenant_id, reply_id),
    )


def publish_memory(database: psycopg.Connection, tenant_id: UUID, meeting: dict,
                   segments: list[dict], note: dict) -> None:
    """Publish transcript and notes into the Phase 5 memory layer with meeting ACLs."""
    meeting_id = meeting["id"]
    visibility, principals = meeting["visibility"], sorted(set(meeting["principals"]))
    for segment in segments:
        event_id = f"meeting:{meeting_id}:segment:{segment['position']}"
        database.execute(
            "INSERT INTO memory_documents (tenant_id, event_id, source, type, occurred_at, actors, "
            "objects, facts, text, visibility, principals, raw_ref) "
            "VALUES (%s, %s, 'recall', 'meeting.transcript', %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            (tenant_id, event_id, segment["started_at"],
             [f"recall:person:{segment['speaker_id']}"], [f"meeting:{meeting_id}"],
             Jsonb({}), segment["text"], visibility, principals,
             f"cue://meetings/{meeting_id}/segments/{segment['position']}"),
        )
    text = note["summary"]
    if note["decisions"]:
        text += "\nDecisions:\n" + "\n".join(f"- {item}" for item in note["decisions"])
    if note["action_items"]:
        text += "\nAction items:\n" + "\n".join(
            f"- {item.get('text', '')}" for item in note["action_items"])
    database.execute(
        "INSERT INTO memory_documents (tenant_id, event_id, source, type, occurred_at, actors, "
        "objects, facts, text, visibility, principals, raw_ref) "
        "VALUES (%s, %s, 'recall', 'meeting.notes', %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT DO NOTHING",
        (tenant_id, f"meeting:{meeting_id}:notes", meeting["ended_at"] or datetime.now(),
         [], [f"meeting:{meeting_id}"],
         Jsonb({"decisions": note["decisions"], "action_items": note["action_items"]}),
         text, visibility, principals, f"cue://meetings/{meeting_id}/notes"),
    )


def queue_deliveries(database: psycopg.Connection, tenant_id: UUID, note_id: UUID,
                     *, slack_channel: str | None, emails: list[str], payload: dict) -> None:
    if slack_channel:
        database.execute(
            "INSERT INTO meeting_note_deliveries (tenant_id, note_id, destination, target, payload) "
            "VALUES (%s, %s, 'slack', %s, %s) ON CONFLICT DO NOTHING",
            (tenant_id, note_id, slack_channel, Jsonb(payload)),
        )
    for email in sorted(set(emails)):
        database.execute(
            "INSERT INTO meeting_note_deliveries (tenant_id, note_id, destination, target, payload) "
            "VALUES (%s, %s, 'email', %s, %s) ON CONFLICT DO NOTHING",
            (tenant_id, note_id, email, Jsonb(payload)),
        )


def live_meeting_by_bot_prefix(database: psycopg.Connection, tenant_id: UUID,
                               prefix: str) -> dict | None:
    """Most recent live meeting whose bot ID carries the given provider prefix."""
    row = database.execute(
        "SELECT id FROM meeting_sessions WHERE tenant_id = %s AND status = 'live' "
        "AND bot_id LIKE %s ORDER BY started_at DESC NULLS LAST LIMIT 1",
        (tenant_id, prefix + "%"),
    ).fetchone()
    return None if row is None else get_meeting(database, tenant_id, row[0])


def live_meeting_by_bot(database: psycopg.Connection, tenant_id: UUID, bot_id: str) -> dict | None:
    row = database.execute(
        "SELECT id FROM meeting_sessions WHERE tenant_id = %s AND status = 'live' AND bot_id = %s",
        (tenant_id, bot_id),
    ).fetchone()
    return None if row is None else get_meeting(database, tenant_id, row[0])
