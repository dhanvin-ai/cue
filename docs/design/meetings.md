# Meetings

Cue takes part in meetings as a named participant. It transcribes the call, answers aloud only
when it is addressed, and writes notes afterwards. Three voice paths share the same turn logic:

| Path | Joins via | Hears | Speaks | Use |
|---|---|---|---|---|
| **Attendee** (default) | Self-hosted bot in headless Chrome | Whisper or Kyutai on the GPU, or Meet captions | Kokoro on the GPU, or Edge TTS | Google Meet, free and self-hosted |
| **Bolna** | The meeting dials Cue's phone number | Bolna STT | Bolna TTS, with barge-in | Any meeting with dial-out |
| **Recall** | Recall.ai bot | Diarized Recall transcript | pluggable `TtsClient` | Hosted alternative |

## Turn pipeline

```
join → transcribe → assemble utterance → map speaker → addressing → runtime → TTS → playback
                                                                                  ↓
                                                         meeting end → notes, decisions, action items
```

- **Join.** `POST /v1/tenants/{t}/meetings` with `"voice": "attendee" | "bolna" | "recall"`, or
  `scripts/join_meet.py`. Cue announces that it is recording. Attendees become
  `email:owner:<email>` principals for the meeting.
- **Assembly** (`cue/meetings/attendee.py`). Streaming transcribers end a line at every breath.
  Pieces from one speaker are joined until one ends a sentence: a piece is held for 1.2 s, and
  pieces less than 4 s apart are joined. Lines that speech models invent on silence ("thank you",
  "bye") are dropped.
- **Speaker map.** Diarized IDs or caption names resolve through `identity_claims` or
  `user_principals`. A speaker who doesn't match is stored as `unknown` and never guessed. Each
  turn runs with the speaker's own permissions.
- **Addressing** (`cue/meetings/addressing.py`). Cue answers when one of these is true:
  - its name, or a sound-alike ("Q", "queue", "kyu"), is the first word, optionally after a greeting;
  - the line asks it directly: "can you…", "do you think…", "what do you…";
  - the line is a factual question after a 2 s pause;
  - the line is a question or follow-up ("and…", "what about…") within 45 s of Cue's last answer.

  Otherwise Cue stays silent.
- **Reply.** The turn enters the agent runtime as a `meeting` task, using `planner.plan_streaming`
  with native tool calling. Speech starts at the first finished sentence. Replies are one or two
  spoken sentences, and the prompt corrects common mishearings using the meeting's vocabulary.
- **Interruption.** On the Recall path, a human speaking cancels TTS and stops playback, and the
  reply is stored as `interrupted` with a cutoff time.
- **Notes** (`cue/meetings/notes.py`). When the meeting ends, Cue writes a summary, decisions and
  action items, linked to transcript segments and stored under the meeting ACL. An action item that
  needs a tool goes through the planner and policy engine, so tier 2 and 3 actions become
  approvals.

Endpoints: `POST /v1/tenants/{t}/meetings`, `POST /v1/tenants/{t}/meetings/{id}/end`,
`GET /v1/tenants/{t}/meetings/{id}/notes`.

## Attendee

[Attendee](https://github.com/attendee-labs/attendee) is open source (Elastic 2.0, free to
self-host for your own use). Setup is in [setup/SETUP.md](../../setup/SETUP.md#8-meeting-bot-attendee-voice-and-the-tunnel).

- Transcripts arrive at `/webhooks/attendee/{tenant}`, signed with the Attendee webhook secret.
- Audio plays through `POST /api/v1/bots/{id}/output_audio`.
- `CUE_TRANSCRIBER` selects `whisper`, `kyutai` or `captions`. If a GPU server is down, Cue falls
  back to captions.
- `CUE_TTS=kokoro` uses the Speaches container on port 8091. If it is down, Cue falls back to
  Edge TTS. Short phrases are cached.
- With Attendee on the same machine, `ATTENDEE_WEBHOOK_BASE_URL=http://host.docker.internal:8080`
  skips the public tunnel.

**Limits:**
- `output_audio` plays a whole clip, so barge-in does not cut Cue off yet. Streaming through
  Attendee's audio websocket would fix this.
- Speakers are matched to members by display name, so attendees with a calendar invite match best.

## Bolna

Bolna places and receives phone calls but cannot join Meet or Zoom, and cannot send DTMF to enter
a meeting PIN. So the meeting dials Cue instead:

- in Google Meet, use **Add people → Call** (Workspace plans with phone support);
- in Zoom, use **Invite → Phone** (needs the audio plan).

Cue acts as the Bolna agent's LLM. Each turn arrives at `POST /bolna/v1/chat/completions`. The
bearer key identifies the tenant (`BOLNA_LLM_KEYS`), and the tenant's most recent live Bolna meeting
receives the turn. An unaddressed turn returns an empty stream. An addressed turn streams a short
filler line, then the answer.

Setup:

1. Expose the API publicly.
2. Run `BOLNA_API_KEY=... python scripts/bolna_setup.py TENANT https://your-host`. It registers the
   custom model and creates the agent, then prints `BOLNA_LLM_KEYS`.
3. In Bolna, attach a number and set the agent as its inbound agent.
4. Set `BOLNA_LLM_KEYS` and `BOLNA_PHONE_NUMBER` on the API.

**Limits:**
- Phone audio is one mixed stream. Every turn is speaker `dial-in`, and requests run as the meeting
  owner, limited to what all participants can see.
- Follow-up windows live in process memory, so run a single API instance.
- Not yet exercised on a live call:
  - whether an empty reply stays silent or Bolna plays a fallback line;
  - time to first audio;
  - whether the `/v2/agent` custom-LLM fields match the dashboard.

## Recall

`RecallMeetingBot` creates a Recall bot with a visible AI name. `scripts/create_meeting_bot.py`
binds the bot to the tenant. Real-time `transcript.data` webhooks feed turns. When the meeting ends,
`transcript.done` triggers retrieval of the final transcript for memory. `SttClient` and
`TtsClient` in `cue/meetings/speech.py` are the speech boundaries. `ScriptedStt`, `RecordingTts`
and `RecordingPlayback` are the test fakes.
