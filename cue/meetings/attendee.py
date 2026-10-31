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
import random
import re
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

import httpx

from cue.http import tls_context
from cue.meetings import addressing as addressing_module
from cue.meetings import service, speakers, store
from cue.meetings.bolna import TextSink, _Addressed
from cue.meetings.models import SpeakerHint, TranscriptSegment, Turn

BOT_PREFIX = "attendee:"
BOT_NAME = "Cue"
VOICE = "en-US-AvaMultilingualNeural"
FILLERS = ("Hmm, let me check.", "One sec.", "Let me look.", "Mm, let me think.",
           "Good question, checking.", "Let me pull that up.")

# Follow-up windows per meeting; in-process like the Bolna line.
_checks: dict[UUID, addressing_module.Addressing] = {}
# Human voices heard per meeting, to tell a one-on-one with Cue from a group call.
_speakers: dict[UUID, set[str]] = {}
# Start time of each speaker's newest addressed caption; an older one still being answered
# is superseded by it, so a question split across two captions gets one answer.
_newest: dict[tuple[UUID, str], datetime] = {}
# When the last filler played per meeting; two quick captions should not stack two fillers.
_filled: dict[UUID, float] = {}
FILLER_GAP = 4.0


CAPTIONS = {"meeting_closed_captions": {"google_meet_language": "en-US"}}


def _listening(url: str) -> bool:
    """Whether the STT server's port accepts connections, checked from where Cue runs."""
    parsed = urlparse(url)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=0.5):
            return True
    except OSError:
        return False


# Whisper takes a prompt of words it should expect; naming Cue there is what stops "Hey Cue"
# arriving as "Take you" or "Thank you".
WHISPER_MODEL = "deepdml/faster-whisper-large-v3-turbo-ct2"
WHISPER_PROMPT = "Hey Cue. Hello Cue, what are the latest commits? Hi Cue, check the open issues."


def transcription_settings() -> dict:
    """Pick how Attendee turns meeting audio into text; Meet captions are the fallback.

    - whisper: self-hosted faster-whisper (Speaches) on the GPU, prompted with Cue's name.
    - kyutai: self-hosted Kyutai streaming STT; fast, but cannot be told the name.
    - captions: Meet's own captions; free, but often mishear a one-syllable name.
    A join never fails because the GPU server is down: it falls back to captions.
    """
    chosen = os.getenv("CUE_TRANSCRIBER", "captions")
    if chosen == "whisper" and _listening(os.getenv("WHISPER_HEALTH_URL", "http://localhost:8091")):
        return {"openai": {"model": os.getenv("WHISPER_MODEL", WHISPER_MODEL),
                           "prompt": WHISPER_PROMPT, "language": "en"}}
    if chosen == "kyutai" and _listening(os.getenv("KYUTAI_HEALTH_URL", "http://localhost:8090")):
        # Cue checks its own view of the server; Attendee's containers reach it by another host.
        return {"kyutai": {"server_url": os.getenv(
            "KYUTAI_SERVER_URL", "ws://host.docker.internal:8090/api/asr-streaming")}}
    return CAPTIONS


class AttendeeClient:
    def __init__(self, base_url: str, api_key: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(verify=tls_context(), 
            base_url=base_url.rstrip("/"), timeout=30,
            headers={"Authorization": f"Token {api_key}"})

    def create_bot(self, meeting_url: str, *, webhook_url: str, name: str = BOT_NAME) -> dict:
        response = self.client.post("/api/v1/bots", json={
            "meeting_url": meeting_url,
            "bot_name": name,
            "transcription_settings": transcription_settings(),
            "recording_settings": {"format": "none"},
            "webhooks": [{"url": webhook_url, "triggers": [
                "transcript.update", "bot.state_change", "chat_messages.update"]}],
        })
        response.raise_for_status()
        return response.json()

    def output_audio(self, bot_id: str, mp3: bytes) -> None:
        response = self.client.post(f"/api/v1/bots/{bot_id}/output_audio", json={
            "type": "audio/mp3", "data": base64.b64encode(mp3).decode()})
        response.raise_for_status()

    def leave(self, bot_id: str) -> None:
        self.client.post(f"/api/v1/bots/{bot_id}/leave").raise_for_status()

    def send_chat(self, bot_id: str, text: str) -> None:
        self.client.post(f"/api/v1/bots/{bot_id}/send_chat_message",
                         json={"text": text}).raise_for_status()


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


HEYGEN_MODEL = "heygen/heygen-voice-1-turbo:free"


def pcm_to_mp3(pcm: bytes, rate: int = 44100) -> bytes:
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_bit_rate(64)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm) + encoder.flush())


@lru_cache(maxsize=64)
def openrouter_tts(text: str, voice: str = "nadine") -> bytes:
    """HeyGen Voice Turbo through OpenRouter's speech endpoint. Returns MP3.

    HeyGen only emits 16-bit mono PCM (rate in the Content-Type); Attendee plays MP3.
    """
    from cue.connectors import secret_store

    key = secret_store.read(os.environ["OPENROUTER_API_KEY_SECRET_VERSION"]).decode().strip()
    response = httpx.post("https://openrouter.ai/api/v1/audio/speech", timeout=30,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": os.getenv("CUE_TTS_MODEL", HEYGEN_MODEL), "input": text,
                                "voice": os.getenv("CUE_TTS_VOICE", voice)})
    response.raise_for_status()
    rate = response.headers.get("content-type", "").partition("rate=")[2].partition(";")[0]
    return pcm_to_mp3(response.content, int(rate or 44100))


KOKORO_MODEL = "speaches-ai/Kokoro-82M-v1.0-ONNX"
_local = httpx.Client(verify=tls_context(), timeout=10)


@lru_cache(maxsize=128)
def kokoro_tts(text: str) -> bytes:
    """Kokoro on the local GPU through Speaches: ~0.2 s a sentence, no network round trip."""
    response = _local.post(os.getenv("KOKORO_URL", "http://localhost:8091") + "/v1/audio/speech", json={
        "model": os.getenv("KOKORO_MODEL", KOKORO_MODEL), "voice": os.getenv("CUE_VOICE", "af_heart"),
        "input": text, "response_format": "mp3"})
    response.raise_for_status()
    return response.content


def default_tts(text: str) -> bytes:
    """Local Kokoro when configured, then HeyGen, then free Edge voices as the last resort."""
    if os.getenv("CUE_TTS") == "kokoro":
        try:
            return kokoro_tts(text)
        except httpx.HTTPError:
            pass
    if os.getenv("OPENROUTER_API_KEY_SECRET_VERSION"):
        try:
            return openrouter_tts(text)
        except (httpx.HTTPError, OSError):
            pass
    return edge_tts(text)


def _external(bot_id: str) -> str:
    return bot_id.removeprefix(BOT_PREFIX)


class AttendeeMeetingBot:
    """MeetingBot that joins through a self-hosted Attendee instance."""

    # Speaking before the host admits the bot plays to nobody; handle_event speaks on admit.
    disclose_on_admit = True

    def __init__(self, client: AttendeeClient, webhook_url: str, tts=default_tts):
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

    def say_sentences(self, bot_id: str, text: str) -> None:
        """Speak the first sentence as soon as it is synthesized; the rest render meanwhile.

        Attendee queues audio requests and plays them in order, so later clips follow on.
        """
        parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p] or [text]
        if len(parts) == 1:
            return self.say(bot_id, parts[0])
        with ThreadPoolExecutor(max_workers=len(parts)) as pool:
            for clip in pool.map(self.tts, parts):
                try:
                    self.client.output_audio(_external(bot_id), clip)
                except httpx.HTTPError:
                    return


CITATION = re.compile(r"\s*\[\d+(?:,\s*\d+)*\]")


class SpeechStream:
    """Speaks a reply sentence by sentence while the model is still writing it.

    Each finished sentence is synthesized at once (several in parallel) and posted to the bot
    in order, so the first sentence plays while later ones are still being generated.
    """

    def __init__(self, bot: "AttendeeMeetingBot", bot_id: str, superseded=lambda: False):
        self.bot, self.bot_id, self.superseded = bot, bot_id, superseded
        self.buffer = ""
        self.spoke = False
        self._synth = ThreadPoolExecutor(max_workers=4)
        self._post = ThreadPoolExecutor(max_workers=1)  # one worker keeps clips in order

    def feed(self, piece: str) -> None:
        self.buffer += piece
        while match := re.search(r"(?<=[.!?])\s+", self.buffer):
            sentence, self.buffer = self.buffer[:match.start()], self.buffer[match.end():]
            self._say(sentence)

    def _say(self, sentence: str) -> None:
        sentence = CITATION.sub("", sentence).strip()
        if not sentence or self.superseded():
            return
        self.spoke = True
        clip = self._synth.submit(self.bot.tts, sentence)

        def post():
            try:
                self.bot.client.output_audio(_external(self.bot_id), clip.result())
            except httpx.HTTPError:
                pass

        self._post.submit(post)

    def close(self) -> None:
        """Speak whatever trailed the last full stop, then wait until every clip is posted."""
        self._say(self.buffer)
        self.buffer = ""
        self._post.shutdown(wait=True)
        self._synth.shutdown(wait=True)


def warm_tts() -> None:
    """Pay every first-request cost at startup: voice clips for the fillers, model loads."""
    try:
        for line in FILLERS:
            clip = default_tts(line)
        if os.getenv("CUE_TRANSCRIBER") == "whisper":
            # The first transcription after a restart loads the model (~3 s); do it now.
            _local.post(os.getenv("KOKORO_URL", "http://localhost:8091") + "/v1/audio/transcriptions",
                        files={"file": ("warm.mp3", clip, "audio/mpeg")},
                        data={"model": os.getenv("WHISPER_MODEL", WHISPER_MODEL)}, timeout=60)
    except Exception:  # Warm-up is best effort; a real reply retries for itself.
        pass


def attendee_bot(tenant_id: UUID) -> AttendeeMeetingBot:
    # Attendee runs beside Cue, so its webhooks can skip the public tunnel (1-1.6 s per caption);
    # CUE_PUBLIC_URL stays the fallback for an Attendee that is not on this machine.
    base = (os.getenv("ATTENDEE_WEBHOOK_BASE_URL") or os.environ["CUE_PUBLIC_URL"]).rstrip("/")
    from cue.connectors import secret_store

    key = secret_store.read(os.environ["ATTENDEE_API_KEY_SECRET_VERSION"]).decode().strip()
    client = AttendeeClient(os.getenv("ATTENDEE_URL", "http://localhost:8000"), key)
    return AttendeeMeetingBot(client, f"{base}/webhooks/attendee/{tenant_id}")


def verify(payload: dict, signature: str | None, secret_b64: str | bytes) -> bool:
    """Attendee signs canonical JSON with HMAC-SHA256 over the base64-decoded secret."""
    if not signature:
        return False
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hmac.new(base64.b64decode(secret_b64.strip()), canonical.encode(), hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature)


def handle_event(tenant_id: UUID, payload: dict, *, bot: AttendeeMeetingBot, gateway, registry,
                 memory=None, database_url: str | None = None) -> dict | None:
    """Ingest one caption utterance; answer aloud when Cue is addressed."""
    data = payload.get("data") or {}
    if payload.get("trigger") == "bot.state_change":
        # The bot cannot be heard until the host admits it, so the disclosure waits for this.
        if data.get("new_state") == "joined_recording":
            bot.say(f"{BOT_PREFIX}{payload.get('bot_id')}", service.DISCLOSURE)
        return None
    chat = payload.get("trigger") == "chat_messages.update"
    if not chat and payload.get("trigger") != "transcript.update":
        return None
    if chat:
        # Typed questions cannot be misheard: "@Cue what changed today?" in Meet chat.
        text = str(data.get("text") or "").strip()
        speaker_id = str(data.get("sender_uuid") or "unknown")
        name = data.get("sender_name")
    else:
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
    piece = Piece(text, started, ended)

    def answer(whole: Piece) -> dict | None:
        return _utterance(tenant_id, meeting, bot_id, speaker_id, name, whole, bot=bot,
                          gateway=gateway, registry=registry, memory=memory,
                          database_url=database_url, chat=chat)

    if chat:
        if not addressing_module._mentions(text, "Cue"):
            return None
        return answer(piece)
    return _assemble((meeting_id, speaker_id), piece, answer)


@dataclass(frozen=True)
class Piece:
    text: str
    started: datetime
    ended: datetime


# A streaming transcriber ends a line at every breath ("What can you do" / "right" / "now?").
# Pieces from one speaker are joined until one ends a sentence, or until they stop coming.
HOLD_SECONDS = 1.2
JOIN_GAP = timedelta(seconds=4)
_pending: dict[tuple[UUID, str], tuple[int, Piece]] = {}
_pending_lock = threading.Lock()
# Speech models invent these on silence or noise; alone they are never worth a line.
HALLUCINATED = re.compile(r"(?i)\s*(?:thank you|thanks|thank|you|bye|okay|uh|um)[.!?]?\s*")


def _schedule(delay: float, callback) -> None:
    timer = threading.Timer(delay, callback)
    timer.daemon = True
    timer.start()


def _assemble(key, piece: Piece, answer) -> dict | None:
    with _pending_lock:
        held = _pending.pop(key, None)
        if held and piece.started - held[1].ended <= JOIN_GAP:
            piece = Piece(f"{held[1].text} {piece.text}", held[1].started, piece.ended)
        if not re.search(r"[.?!]\s*$", piece.text):
            # Mid-sentence: wait briefly for the rest; flush as-is if nothing follows.
            seq = (held[0] + 1) if held else 1
            _pending[key] = (seq, piece)

            def flush():
                with _pending_lock:
                    current = _pending.get(key)
                    if not current or current[0] != seq:
                        return
                    del _pending[key]
                answer(piece)

            _schedule(HOLD_SECONDS, flush)
            return None
    return answer(piece)


def _utterance(tenant_id: UUID, meeting: dict, bot_id: str, speaker_id: str, name, piece: Piece, *,
               bot: AttendeeMeetingBot, gateway, registry, memory=None,
               database_url: str | None = None, chat: bool = False) -> dict | None:
    """One whole utterance: transcribe it, and answer aloud when Cue is addressed."""
    if HALLUCINATED.fullmatch(piece.text):
        return None
    meeting_id = meeting["id"]
    text, started, ended = piece.text, piece.started, piece.ended
    service.ingest_segment(tenant_id, meeting_id, TranscriptSegment(
        speaker_id, text, started, ended, endpoint=True,
        segment_index=f"{bot_id}:{speaker_id}:{int(started.timestamp() * 1000)}",
    ), hint=SpeakerHint(speaker_id, name), database_url=database_url)
    check = _checks.setdefault(meeting_id, addressing_module.Addressing())
    voices = _speakers.setdefault(meeting_id, set())
    voices.add(speaker_id)
    # Captions mangle a one-syllable name ("Hey Cue" -> "Take you"). With one person in the
    # call there is nobody else to ask, so any question is for Cue.
    solo_question = len(voices) == 1 and text.rstrip().endswith("?")
    if not (chat or check.check(text, now=ended) or solo_question):
        return None
    # A person answering makes a sound straight away; silence while the model works reads as
    # broken. Varied, pre-rendered lines hide the wait without sounding like one stock phrase.
    key = (meeting_id, speaker_id)
    if started >= _newest.get(key, started):
        _newest[key] = started
    superseded = lambda: _newest.get(key, started) > started  # noqa: E731
    clock = time.monotonic()
    if not service.SMALL_TALK.fullmatch(text) and clock - _filled.get(meeting_id, -FILLER_GAP) >= FILLER_GAP:
        _filled[meeting_id] = clock
        bot.say(bot_id, random.choice(FILLERS))
    if callable(registry):
        # Captions name the speaker, so tools run with that member's permissions when known.
        with store.tenant_connection(tenant_id, database_url) as database:
            uid = speakers.speaker_uid(database, tenant_id, meeting_id, speaker_id)
        registry = registry(uid or meeting["owner_uid"])
    sink = TextSink()
    speech = SpeechStream(bot, bot_id, superseded)
    try:
        result = service.handle_turn(
            tenant_id, meeting_id, Turn(speaker_id, text, started, ended, "endpoint"),
            check=_Addressed(), gateway=gateway, registry=registry, tts=sink, playback=sink,
            interrupted=superseded, memory=memory, database_url=database_url, now=ended,
            on_text=speech.feed,
        )
    except Exception:
        speech.close()
        # Silence after a question reads as broken; say so, then surface the error in logs.
        bot.say(bot_id, "Sorry, I hit an error on that one.")
        raise
    speech.close()
    if result is not None and result["reply"].status == "completed" and not speech.spoke:
        # Not streamed (a tool ran, or the planner fell back): speak the composed answer.
        bot.say_sentences(bot_id, CITATION.sub("", result["answer"]))
    if chat and result is not None:
        # A typed question gets the answer typed back too, so links and names can be copied.
        try:
            bot.client.send_chat(_external(bot_id), result["answer"])
        except httpx.HTTPError:
            pass
    return result
