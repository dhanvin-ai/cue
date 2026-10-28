# Phase 7: meeting voice

Cue joins a meeting through the Phase 4 Recall adapter, consumes diarized transcript segments,
answers only when addressed, and publishes notes with the meeting ACL.

## Flow

`join -> STT stream -> speaker map -> turn detection -> addressing -> Phase 6 runtime -> TTS/playback -> notes`.

- **Join:** `POST /v1/tenants/{id}/meetings` calls `RecallMeetingBot.join` (Recall `create_bot`).
  The visible bot announces recording and attendees become `email:owner:<email>` principals.
- **STT/TTS:** `SttClient` and `TtsClient` in `cue/meetings/speech.py` are the Insurge boundaries.
  `ScriptedStt`, `RecordingTts`, and `RecordingPlayback` are local fakes.
- **Speaker map:** diarized IDs resolve through `identity_claims` or `user_principals`; unmatched
  speakers are stored as `unknown` and never guessed.
- **Turns and addressing:** final segments, silence gaps, endpoint flags, and speaker changes close
  turns. Cue answers a name mention, a direct question, a factual question after a 2s pause, or a
  follow-up inside the active-exchange window. It stays silent otherwise.
- **Replies:** the addressed turn enters the Phase 6 runtime as a `meeting` task. The answer is
  chunked through TTS and played back; a human interruption cancels TTS, stops playback, and stores
  `meeting_replies.status = 'interrupted'` with a cutoff timestamp.
- **Notes:** summary, decisions, action items, source segment links, transcript memory documents, and
  the note memory document all use the meeting ACL. Delivery outbox rows target the linked Slack
  channel and attendee emails. Tool-bearing action items enter the Phase 6 planner and policy engine,
  so tier 2/3 actions become approvals.

## Setup

Apply `007_meetings.sql`. Set `RECALL_API_KEY_SECRET_VERSION`, `RECALL_REGION`,
`STT_ENDPOINT`, and `TTS_ENDPOINT`; the last two are consumed by the deployment's real clients.
`INGEST_DATABASE_URL` is required for the transcript/notes memory publication.
Endpoints: `POST /v1/tenants/{id}/meetings`, `POST /v1/tenants/{id}/meetings/{id}/end`,
`GET /v1/tenants/{id}/meetings/{id}/notes`.

## Swapping in real STT/TTS

Implement `SttClient.stream(meeting_id)` against the Insurge streaming ASR endpoint and
`TtsClient.synthesize(text)` / `cancel()` against the streaming TTS endpoint, then inject them into
`MeetingRuntime` or the worker. Keep the fakes for tests; no vendor call is made by default.
