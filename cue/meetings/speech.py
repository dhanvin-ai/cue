"""Speech interfaces. Real Insurge GPU clients plug in here; fakes keep tests local."""

from collections.abc import Iterable
from typing import Protocol

from cue.meetings.models import TranscriptSegment


class SttClient(Protocol):
    def stream(self, meeting_id: str) -> Iterable[TranscriptSegment]: ...


class TtsClient(Protocol):
    def synthesize(self, text: str) -> bytes: ...

    def cancel(self) -> None: ...


class Playback(Protocol):
    def play(self, audio: bytes) -> None: ...

    def stop(self) -> None: ...


class ScriptedStt:
    """Deterministic transcript stream used by local runs and tests."""

    def __init__(self, segments: Iterable[TranscriptSegment]):
        self.segments = tuple(segments)

    def stream(self, meeting_id: str) -> Iterable[TranscriptSegment]:
        yield from self.segments


class RecordingTts:
    """Records text chunks in call order so streaming can be asserted."""

    def __init__(self):
        self.chunks: list[str] = []
        self.cancelled = False

    def synthesize(self, text: str) -> bytes:
        if self.cancelled:
            raise RuntimeError("TTS was cancelled")
        self.chunks.append(text)
        return f"audio:{text}".encode()

    def cancel(self) -> None:
        self.cancelled = True


class RecordingPlayback:
    def __init__(self):
        self.played: list[bytes] = []
        self.stopped = False

    def play(self, audio: bytes) -> None:
        if self.stopped:
            raise RuntimeError("Playback was stopped")
        self.played.append(audio)

    def stop(self) -> None:
        self.stopped = True
