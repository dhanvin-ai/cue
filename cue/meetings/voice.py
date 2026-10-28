"""Stream reply text through TTS and stop cleanly when a human interrupts."""

from datetime import datetime, timezone

from cue.meetings import store
from cue.meetings.models import ReplyResult
from cue.meetings.speech import Playback, TtsClient


def chunk_text(text: str, *, size: int = 32) -> list[str]:
    """Split on word boundaries while preserving order."""
    chunks: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > size:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def stream_reply(database, tenant_id, meeting_id, reply_id, text: str, *,
                 tts: TtsClient, playback: Playback, interrupted,
                 chunk_size: int = 32, now: datetime | None = None) -> ReplyResult:
    """Synthesize and play one chunk at a time; cutoff is durable and idempotent."""
    moment = now or datetime.now(timezone.utc)
    chunks = chunk_text(text, size=chunk_size)
    sent = 0
    for chunk in chunks:
        if interrupted():
            tts.cancel()
            playback.stop()
            store.finish_reply(database, tenant_id, reply_id, "interrupted", sent, moment)
            return ReplyResult(str(reply_id), "interrupted", sent, moment)
        playback.play(tts.synthesize(chunk))
        sent += 1
    if interrupted():
        tts.cancel()
        playback.stop()
        store.finish_reply(database, tenant_id, reply_id, "interrupted", sent, moment)
        return ReplyResult(str(reply_id), "interrupted", sent, moment)
    store.finish_reply(database, tenant_id, reply_id, "completed", sent)
    return ReplyResult(str(reply_id), "completed", sent)
