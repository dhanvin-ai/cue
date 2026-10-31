"""Bolna voice: the meeting phones Cue, Bolna runs STT/TTS/turn-taking, Cue is the LLM.

Bolna has no native Meet or Zoom join and cannot send DTMF on outbound calls, so Cue does not
dial in. Instead the host uses the meeting's "call a phone" option to ring Cue's Bolna number.
Bolna then calls Cue's OpenAI-compatible endpoint once per caller turn; the bearer key names the
tenant, and the tenant's most recent live Bolna meeting receives the turn.
"""

import hmac
import json
import os
import time
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx

from cue.http import tls_context
from cue.meetings import addressing as addressing_module
from cue.meetings import service, store
from cue.meetings.models import TranscriptSegment, Turn

BOT_PREFIX = "bolna:"
CALLER = "dial-in"
CUE_SPEAKER = "cue"
FILLER = "One sec, pulling that up."
API = "https://api.bolna.ai"

# Follow-up windows must survive across Bolna's per-turn HTTP requests. In-process state is
# enough for a single API instance; move it to Postgres before running more than one.
_checks: dict[UUID, addressing_module.Addressing] = {}


class BolnaMeetingBot:
    """MeetingBot for dial-out meetings: nothing joins; the meeting rings Cue's number."""

    def join(self, meeting_url: str, attendees: list[str]) -> str:
        return f"{BOT_PREFIX}{uuid4().hex}"

    def leave(self, bot_id: str) -> None:
        return None


class TextSink:
    """TTS and playback stand-in: Bolna speaks, so replies are collected as text chunks."""

    def __init__(self):
        self.chunks: list[str] = []

    def synthesize(self, text: str) -> bytes:
        self.chunks.append(text)
        return text.encode()

    def cancel(self) -> None:
        return None

    def play(self, audio: bytes) -> None:
        return None

    def stop(self) -> None:
        return None


class _Addressed:
    """The endpoint already ran the addressing check; handle_turn must not run it twice."""

    def check(self, *args, **kwargs) -> bool:
        return True


def tenant_for_key(key: str) -> UUID | None:
    """BOLNA_LLM_KEYS is `tenant_uuid=key,tenant_uuid=key`; one key per tenant agent."""
    for pair in os.getenv("BOLNA_LLM_KEYS", "").split(","):
        tenant, _, expected = pair.strip().partition("=")
        if expected and hmac.compare_digest(key.encode(), expected.encode()):
            return UUID(tenant)
    return None


def _user_turns(messages: list[dict]) -> list[str]:
    return [str(item.get("content") or "").strip() for item in messages
            if item.get("role") == "user"]


def respond(tenant_id: UUID, messages: list[dict], *, gateway, registry, memory=None,
            database_url: str | None = None, now: datetime | None = None) -> Iterator[str]:
    """Yield spoken text for the latest caller turn; yield nothing to stay silent.

    `registry` may be a callable taking the requester UID. Phone audio has no speaker identity,
    so a dial-in turn always runs as the meeting owner.
    """
    moment = now or datetime.now(timezone.utc)
    utterances = _user_turns(messages)
    if not utterances or not utterances[-1]:
        return
    text = utterances[-1]
    with store.tenant_connection(tenant_id, database_url) as database:
        meeting = store.live_meeting_by_bot_prefix(database, tenant_id, BOT_PREFIX)
    if meeting is None:
        return
    meeting_id = meeting["id"]
    # Bolna resends the whole conversation each turn, so the user-turn count is a stable index.
    service.ingest_segment(tenant_id, meeting_id, TranscriptSegment(
        CALLER, text, moment, moment, endpoint=True,
        segment_index=f"bolna:{meeting_id}:user:{len(utterances)}",
    ), database_url=database_url)
    check = _checks.setdefault(meeting_id, addressing_module.Addressing())
    if not check.check(text, now=moment):
        return
    yield FILLER
    if callable(registry):
        registry = registry(meeting["owner_uid"])
    sink = TextSink()
    result = service.handle_turn(
        tenant_id, meeting_id, Turn(CALLER, text, moment, moment, "endpoint"),
        check=_Addressed(), gateway=gateway, registry=registry, tts=sink, playback=sink,
        memory=memory, database_url=database_url, now=moment,
    )
    if result is None:
        return
    service.ingest_segment(tenant_id, meeting_id, TranscriptSegment(
        CUE_SPEAKER, result["answer"], moment, moment,
        segment_index=f"bolna:{meeting_id}:cue:{len(utterances)}",
    ), database_url=database_url)
    for chunk in sink.chunks:
        yield " " + chunk


def sse(pieces: Iterable[str], model: str) -> Iterator[str]:
    """Wrap text pieces as OpenAI chat-completion stream chunks ending in [DONE]."""
    ident = f"chatcmpl-{uuid4().hex}"
    created = int(time.time())

    def chunk(delta: dict, finish: str | None = None) -> str:
        body = {"id": ident, "object": "chat.completion.chunk", "created": created,
                "model": model, "choices": [{"index": 0, "delta": delta,
                                             "finish_reason": finish}]}
        return f"data: {json.dumps(body)}\n\n"

    yield chunk({"role": "assistant", "content": ""})
    for piece in pieces:
        yield chunk({"content": piece})
    yield chunk({}, "stop")
    yield "data: [DONE]\n\n"


def completion(pieces: Iterable[str], model: str) -> dict:
    """Non-streaming response, used by Bolna's save-time checks and by curl."""
    return {"id": f"chatcmpl-{uuid4().hex}", "object": "chat.completion",
            "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "".join(pieces).strip()}}]}


class BolnaClient:
    """Provisioning calls against the Bolna REST API."""

    def __init__(self, api_key: str, client: httpx.Client | None = None):
        self.client = client or httpx.Client(verify=tls_context(), base_url=API, timeout=30,
                                             headers={"Authorization": f"Bearer {api_key}"})

    def add_custom_model(self, name: str, base_url: str, key: str) -> dict:
        response = self.client.post("/user/model/custom", json={
            "custom_model_name": name, "custom_model_url": base_url,
            "custom_model_key": key, "custom_model_family": "openai",
        })
        response.raise_for_status()
        return response.json()

    def create_agent(self, config: dict) -> dict:
        response = self.client.post("/v2/agent", json=config)
        response.raise_for_status()
        return response.json()


def agent_config(*, name: str, base_url: str, model: str, voice: dict,
                 telephony: str = "plivo") -> dict:
    """Agent whose LLM is Cue. Bolna owns transcription, endpointing, TTS, and barge-in."""
    return {
        "agent_config": {
            "agent_name": name,
            "agent_welcome_message": service.DISCLOSURE,
            "tasks": [{
                "task_type": "conversation",
                "toolchain": {"execution": "sequential",
                              "pipelines": [["transcriber", "llm", "synthesizer"]]},
                "tools_config": {
                    "llm_agent": {
                        "agent_type": "simple_llm_agent",
                        "agent_flow_type": "streaming",
                        "llm_config": {"provider": "custom", "model": model,
                                       "base_url": base_url, "family": "openai",
                                       "max_tokens": 150, "temperature": 0.2},
                    },
                    "transcriber": {"provider": "deepgram", "model": "nova-3",
                                    "language": "en", "stream": True,
                                    "encoding": "linear16", "sampling_rate": 16000,
                                    "endpointing": 250},
                    "synthesizer": {**voice, "stream": True, "buffer_size": 250,
                                    "audio_format": "wav"},
                    "input": {"provider": telephony, "format": "wav"},
                    "output": {"provider": telephony, "format": "wav"},
                },
                # Meetings run long and go quiet while humans talk to each other.
                "task_config": {"call_terminate": 3600, "hangup_after_silence": 600},
            }],
        },
        "agent_prompts": {"task_1": {"system_prompt":
            "You are Cue, an AI teammate on a meeting line. Cue's server writes every reply."}},
    }
