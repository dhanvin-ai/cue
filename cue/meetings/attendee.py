"""Attendee voice: a self-hosted bot joins Meet as a named participant.

Attendee (open source, self-hosted) runs the Meet client. Cue reads Meet's own closed captions,
which arrive per utterance with the speaker's name, through Attendee's `transcript.update`
webhook, and speaks by posting MP3 audio to the bot. Captions cost nothing and keep per-speaker
identity, which the Bolna phone line cannot.
"""

import asyncio
import base64
import hashlib
import hmac
import json
import os
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from uuid import UUID

import httpx

from cue.meetings import addressing as addressing_module
from cue.meetings import service, speakers, store
from cue.meetings.bolna import FILLER, TextSink, _Addressed
from cue.meetings.models import SpeakerHint, TranscriptSegment, Turn

BOT_PREFIX = "attendee:"
BOT_NAME = "Cue"
VOICE = "en-US-AvaMultilingualNeural"

# Follow-up windows per meeting; in-process like the Bolna line.
_checks: dict[UUID, addressing_module.Addressing] = {}


class AttendeeClient:
    def __init__(self, base_url: str, api_key: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(
            base_url=base_url.rstrip("/"), timeout=30,
            headers={"Authorization": f"Token {api_key}"})

    def create_bot(self, meeting_url: str, *, webhook_url: str, name: str = BOT_NAME) -> dict:
        response = self.client.post("/api/v1/bots", json={
            "meeting_url": meeting_url,
            "bot_name": name,
            "transcription_settings": {"meeting_closed_captions": {"google_meet_language": "en-US"}},
            "recording_settings": {"format": "none"},
            "webhooks": [{"url": webhook_url, "triggers": ["transcript.update", "bot.state_change"]}],
        })
        response.raise_for_status()
        return response.json()

    def output_audio(self, bot_id: str, mp3: bytes) -> None:
        response = self.client.post(f"/api/v1/bots/{bot_id}/output_audio", json={
            "type": "audio/mp3", "data": base64.b64encode(mp3).decode()})
        response.raise_for_status()

    def leave(self, bot_id: str) -> None:
        self.client.post(f"/api/v1/bots/{bot_id}/leave").raise_for_status()


@lru_cache(maxsize=64)
def edge_tts(text: str, voice: str = VOICE) -> bytes:
    """Free neural TTS (Microsoft Edge voices, no key). Returns MP3; repeats are cached."""
    import edge_tts as edge

    async def run() -> bytes:
        audio = bytearray()
        async for chunk in edge.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
        return bytes(audio)

    return asyncio.run(run())


def _external(bot_id: str) -> str:
    return bot_id.removeprefix(BOT_PREFIX)


class AttendeeMeetingBot:
    """MeetingBot that joins through a self-hosted Attendee instance."""

    def __init__(self, client: AttendeeClient, webhook_url: str, tts=edge_tts):
        self.client, self.webhook_url, self.tts = client, webhook_url, tts

    def join(self, meeting_url: str, attendees: list[str]) -> str:
        bot = self.client.create_bot(meeting_url, webhook_url=self.webhook_url)
        return f"{BOT_PREFIX}{bot['id']}"

    def leave(self, bot_id: str) -> None:
        self.client.leave(_external(bot_id))

    def say(self, bot_id: str, text: str) -> None:
        # The bot is not in the call until the host admits it; the disclosure must not fail the join.
        try:
            self.client.output_audio(_external(bot_id), self.tts(text))
        except httpx.HTTPError:
            pass


def attendee_bot(tenant_id: UUID) -> AttendeeMeetingBot:
    base = os.environ["CUE_PUBLIC_URL"].rstrip("/")
    client = AttendeeClient(os.getenv("ATTENDEE_URL", "http://localhost:8000"),
                            os.environ["ATTENDEE_API_KEY"])
    return AttendeeMeetingBot(client, f"{base}/webhooks/attendee/{tenant_id}")


def verify(payload: dict, signature: str | None, secret_b64: str | bytes) -> bool:
    """Attendee signs canonical JSON with HMAC-SHA256 over the base64-decoded secret."""
    if not signature:
        return False
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hmac.new(base64.b64decode(secret_b64), canonical.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def handle_event(tenant_id: UUID, payload: dict, *, bot: AttendeeMeetingBot, gateway, registry,
                 memory=None, database_url: str | None = None) -> dict | None:
    """Ingest one caption utterance; answer aloud when Cue is addressed."""
    if payload.get("trigger") != "transcript.update":
        return None
    data = payload.get("data") or {}
    text = str((data.get("transcription") or {}).get("transcript") or "").strip()
    speaker_id = str(data.get("speaker_uuid") or "unknown")
    name = data.get("speaker_name")
    if not text or name == BOT_NAME:
        return None
    bot_id = f"{BOT_PREFIX}{payload.get('bot_id')}"
    with store.tenant_connection(tenant_id, database_url) as database:
        meeting = store.live_meeting_by_bot(database, tenant_id, bot_id)
    if meeting is None:
        return None
    meeting_id = meeting["id"]
    started = datetime.fromtimestamp(int(data.get("timestamp_ms") or 0) / 1000, timezone.utc)
    ended = started + timedelta(milliseconds=int(data.get("duration_ms") or 0))
    service.ingest_segment(tenant_id, meeting_id, TranscriptSegment(
        speaker_id, text, started, ended, endpoint=True,
        segment_index=f"{bot_id}:{speaker_id}:{data.get('timestamp_ms')}",
    ), hint=SpeakerHint(speaker_id, name), database_url=database_url)
    check = _checks.setdefault(meeting_id, addressing_module.Addressing())
    if not check.check(text, now=ended):
        return None
    bot.say(bot_id, FILLER)
    if callable(registry):
        # Captions name the speaker, so tools run with that member's permissions when known.
        with store.tenant_connection(tenant_id, database_url) as database:
            uid = speakers.speaker_uid(database, tenant_id, meeting_id, speaker_id)
        registry = registry(uid or meeting["owner_uid"])
    sink = TextSink()
    result = service.handle_turn(
        tenant_id, meeting_id, Turn(speaker_id, text, started, ended, "endpoint"),
        check=_Addressed(), gateway=gateway, registry=registry, tts=sink, playback=sink,
        memory=memory, database_url=database_url, now=ended,
    )
    if result is not None:
        # One clip per answer: Attendee plays each output_audio request as a whole.
        bot.say(bot_id, result["answer"])
    return result
