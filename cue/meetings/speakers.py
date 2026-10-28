"""Map diarized speakers to tenant members, preserving unknown speakers."""

from uuid import UUID

import psycopg

from cue.meetings.models import SpeakerHint, SpeakerMatch

KNOWN = "known"
UNKNOWN = "unknown"


def _principal_uid(database: psycopg.Connection, tenant_id: UUID, email: str) -> str | None:
    address = email.casefold()
    row = database.execute(
        "SELECT firebase_uid FROM identity_claims WHERE tenant_id = %s AND alias = %s",
        (tenant_id, f"gmail:person:{address}"),
    ).fetchone()
    if row is None:
        row = database.execute(
            "SELECT firebase_uid FROM user_principals WHERE tenant_id = %s AND principal = %s",
            (tenant_id, f"email:owner:{address}"),
        ).fetchone()
    return row[0] if row else None


def map_speakers(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID,
                 hints: list[SpeakerHint]) -> list[SpeakerMatch]:
    """Resolve each diarized speaker once and persist the mapping for the meeting."""
    matches = []
    for hint in hints:
        existing = database.execute(
            "SELECT m.firebase_uid, p.display_name FROM meeting_speaker_map AS m "
            "LEFT JOIN meeting_participants AS p ON p.tenant_id = m.tenant_id "
            "AND p.meeting_id = m.meeting_id AND p.participant_id = m.participant_id "
            "WHERE m.tenant_id = %s AND m.meeting_id = %s AND m.speaker_id = %s",
            (tenant_id, meeting_id, hint.speaker_id),
        ).fetchone()
        uid = _principal_uid(database, tenant_id, hint.email) if hint.email else None
        if uid is None and hint.email is None and existing is not None:
            uid = existing[0]
        display_name = hint.display_name or (existing[1] if existing else None)
        kind = "attendee" if uid else "unknown"
        database.execute(
            "INSERT INTO meeting_participants (tenant_id, meeting_id, participant_id, display_name, "
            "email, firebase_uid, kind) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, meeting_id, participant_id) DO UPDATE SET "
            "display_name = COALESCE(EXCLUDED.display_name, meeting_participants.display_name), "
            "email = COALESCE(EXCLUDED.email, meeting_participants.email), "
            "firebase_uid = COALESCE(EXCLUDED.firebase_uid, meeting_participants.firebase_uid), "
            "kind = CASE WHEN COALESCE(EXCLUDED.firebase_uid, meeting_participants.firebase_uid) "
            "IS NOT NULL THEN 'attendee' ELSE EXCLUDED.kind END",
            (tenant_id, meeting_id, hint.speaker_id, display_name, hint.email, uid, kind),
        )
        label = KNOWN if uid else UNKNOWN
        database.execute(
            "INSERT INTO meeting_speaker_map (tenant_id, meeting_id, speaker_id, participant_id, "
            "firebase_uid, label, confidence) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (tenant_id, meeting_id, speaker_id) DO UPDATE SET "
            "participant_id = EXCLUDED.participant_id, firebase_uid = EXCLUDED.firebase_uid, "
            "label = EXCLUDED.label, confidence = EXCLUDED.confidence",
            (tenant_id, meeting_id, hint.speaker_id, hint.speaker_id, uid, label,
             1.0 if uid else 0.0),
        )
        matches.append(SpeakerMatch(hint.speaker_id, hint.speaker_id, uid, label,
                                    display_name))
    return matches


def speaker_uid(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID,
                speaker_id: str) -> str | None:
    row = database.execute(
        "SELECT firebase_uid FROM meeting_speaker_map "
        "WHERE tenant_id = %s AND meeting_id = %s AND speaker_id = %s",
        (tenant_id, meeting_id, speaker_id),
    ).fetchone()
    return row[0] if row else None


def participant_uids(database: psycopg.Connection, tenant_id: UUID, meeting_id: UUID) -> list[str]:
    rows = database.execute(
        "SELECT DISTINCT firebase_uid FROM meeting_participants "
        "WHERE tenant_id = %s AND meeting_id = %s AND firebase_uid IS NOT NULL "
        "ORDER BY firebase_uid",
        (tenant_id, meeting_id),
    ).fetchall()
    return [row[0] for row in rows]
