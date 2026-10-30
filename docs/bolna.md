# Bolna meeting voice

Bolna runs Cue's voice in meetings. It handles speech-to-text, endpointing, TTS, and barge-in. Cue
is the agent's LLM: Bolna sends each caller turn to Cue's OpenAI-compatible endpoint, and Cue
answers from memory and tools through the Phase 6 runtime.

## Why the meeting calls Cue

Bolna places and receives phone calls; it has no Meet or Zoom join, and it cannot send DTMF on
outbound calls, so it cannot enter a meeting PIN. The meeting dials out instead: in Google Meet use
**Add people → Call** (Workspace plans with Meet phone support), in Zoom use **Invite → Phone**
(requires the Zoom audio plan). Cue's Bolna number answers and speaks the recording disclosure.

## Flow

`POST /meetings {"voice": "bolna"}` → host rings `BOLNA_PHONE_NUMBER` from the meeting → Bolna
transcribes each turn → `POST /bolna/v1/chat/completions` → transcript segment stored →
addressing check → silent, or "One sec, pulling that up." followed by the runtime answer →
Bolna speaks it → `POST /meetings/{id}/end` writes notes, decisions, and action items.

- The bearer key Bolna sends identifies the tenant (`BOLNA_LLM_KEYS`). The tenant's most recent
  live Bolna meeting receives the turn.
- Phone audio is a single mixed stream, so every human turn is speaker `dial-in`, and requests run
  as the meeting owner, limited to what all participants can see. For per-speaker attribution,
  run a Recall bot in the same meeting for the transcript.
- Follow-up windows are kept in process. Run one API instance until they move to Postgres.

## Setup

1. Expose the API publicly (Cloud Run, or `ngrok http 8000` locally).
2. `BOLNA_API_KEY=... python scripts/bolna_setup.py TENANT_UUID https://your-host` registers the
   custom model and creates the agent, then prints `BOLNA_LLM_KEYS`.
3. In Bolna, buy or attach a number and set this agent as its inbound agent.
4. Set `BOLNA_LLM_KEYS` and `BOLNA_PHONE_NUMBER` on the API, plus the model gateway variables.

## Verify before the demo

These behaviours come from Bolna's docs and have not been exercised on a live call:

- An empty streamed reply keeps the agent silent. Bolna may instead play a fallback line.
- Bolna's end-of-call and voicemail checks also go through this endpoint. They land as unaddressed
  turns and produce no reply.
- Time to first audio. The filler line streams immediately, but the answer waits for the planner.
- Whether the `/v2/agent` custom LLM fields match the dashboard's saved agent. If not, create the
  agent in the dashboard and select the `cue-TENANT` custom model.

`pytest -q tests/test_bolna.py` covers the stream format, key lookup, silent unaddressed turns,
filler then answer, retry deduplication, and the no-live-meeting case.
