"""Turn detection from final transcript segments, silence, and endpoint signals."""

from cue.meetings.models import TranscriptSegment, Turn


def _turn(segments: list[TranscriptSegment], reason: str) -> Turn:
    return Turn(
        speaker_id=segments[0].speaker_id,
        text=" ".join(segment.text.strip() for segment in segments if segment.text.strip()),
        started_at=segments[0].started_at,
        ended_at=segments[-1].ended_at,
        end_reason=reason,
        segments=tuple(segments),
    )


def detect_turns(segments: list[TranscriptSegment], *, silence_ms: int = 700,
                 max_turn_ms: int = 60_000) -> list[Turn]:
    """Group final segments into turns; partial results never end a turn."""
    ordered = sorted((segment for segment in segments if segment.is_final),
                     key=lambda segment: (segment.started_at, segment.ended_at))
    turns: list[Turn] = []
    current: list[TranscriptSegment] = []
    for segment in ordered:
        if not current:
            current = [segment]
        else:
            previous = current[-1]
            gap_ms = (segment.started_at - previous.ended_at).total_seconds() * 1000
            duration_ms = (segment.ended_at - current[0].started_at).total_seconds() * 1000
            if segment.speaker_id != previous.speaker_id:
                turns.append(_turn(current, "speaker_change"))
                current = [segment]
            elif gap_ms >= silence_ms:
                turns.append(_turn(current, "silence"))
                current = [segment]
            elif previous.endpoint:
                turns.append(_turn(current, "endpoint"))
                current = [segment]
            elif duration_ms > max_turn_ms:
                turns.append(_turn(current, "max_duration"))
                current = [segment]
            else:
                current.append(segment)
        if segment.endpoint:
            turns.append(_turn(current, "endpoint"))
            current = []
    if current:
        turns.append(_turn(current, "end_of_stream"))
    return turns
