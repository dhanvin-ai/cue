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


class TurnBuffer:
    """Incremental turn detector for a live transcript stream."""

    def __init__(self, *, silence_ms: int = 700, max_turn_ms: int = 60_000):
        self.silence_ms = silence_ms
        self.max_turn_ms = max_turn_ms
        self.current: list[TranscriptSegment] = []

    def push(self, segment: TranscriptSegment) -> list[Turn]:
        if not segment.is_final:
            return []
        closed: list[Turn] = []
        if self.current:
            previous = self.current[-1]
            gap_ms = (segment.started_at - previous.ended_at).total_seconds() * 1000
            duration_ms = (segment.ended_at - self.current[0].started_at).total_seconds() * 1000
            reason = None
            if segment.speaker_id != previous.speaker_id:
                reason = "speaker_change"
            elif gap_ms >= self.silence_ms:
                reason = "silence"
            elif previous.endpoint:
                reason = "endpoint"
            elif duration_ms > self.max_turn_ms:
                reason = "max_duration"
            if reason:
                closed.append(_turn(self.current, reason))
                self.current = []
        self.current.append(segment)
        if segment.endpoint:
            closed.append(_turn(self.current, "endpoint"))
            self.current = []
        return closed

    def flush(self) -> list[Turn]:
        if not self.current:
            return []
        turn = _turn(self.current, "end_of_stream")
        self.current = []
        return [turn]
