"""Shared value objects for the meeting voice pipeline."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TranscriptSegment:
    speaker_id: str
    text: str
    started_at: datetime
    ended_at: datetime
    is_final: bool = True
    endpoint: bool = False
    segment_index: str | None = None


@dataclass(frozen=True)
class Turn:
    speaker_id: str
    text: str
    started_at: datetime
    ended_at: datetime
    end_reason: str
    segments: tuple[TranscriptSegment, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SpeakerHint:
    speaker_id: str
    display_name: str | None = None
    email: str | None = None


@dataclass(frozen=True)
class SpeakerMatch:
    speaker_id: str
    participant_id: str
    firebase_uid: str | None
    label: str
    display_name: str | None = None


@dataclass(frozen=True)
class MeetingNotesDraft:
    summary: str
    decisions: tuple[str, ...] = ()
    action_items: tuple[dict, ...] = ()
    source_positions: tuple[int, ...] = ()


@dataclass(frozen=True)
class ReplyResult:
    reply_id: str
    status: str
    chunks_sent: int
    cutoff_at: datetime | None = None
