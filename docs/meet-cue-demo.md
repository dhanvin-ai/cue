# Meet CUE live demo

The landing page's **Meet CUE** button opens `/meet-cue`. A visitor either meets Cue now or schedules a call for later. Cue's own Google account creates a real Google Meet, invites the visitor, and the self-hosted bot (`scripts/face_bot.py`) joins as the animated Cue face. Cue listens, answers out loud, and when the call ends the visitor's session page shows a short summary.

```
browser ── /meet-cue (Next.js) ── /api/meet-cue/* ──X-Demo-Key──▶ demo API (FastAPI, :8780)
                                  httpOnly cookie                  │  Google Calendar (Cue's account)
                                  holds the session token          │  SQLite store (~/.cue-demo)
                                                                   ▼
                     Google Meet ◀── face_bot.py (Chrome, Cue's profile) ──ws + bot key──▶ voice loop
                                                                         faster-whisper → Claude → Kokoro
```

## What is isolated

The demo is a separate app, `cue.demo.app:app`. It does not import the tenant API, connectors, memory, or the agent runtime, and it never opens the Postgres database. It keeps its own SQLite file. Claude runs with a fixed demo persona and no tools, so it can talk about Cue but cannot act. The bot uses a dedicated Google account.

## Security model

- **Google OAuth** is server-side only. The refresh token lives in `~/.cue-demo/google-oauth.json` (mode 0600). The only scope is `calendar.events`.
- **Next.js server to demo API** uses a shared `CUE_DEMO_API_KEY`, sent in the `X-Demo-Key` header. The browser never sees the key.
- **Meeting links** are returned only to the visitor who created the session:
  - The demo API returns a random session token once, at creation.
  - Next.js stores the token in an httpOnly, SameSite=Lax cookie (Secure in production) and strips it from the response.
  - The store keeps only a SHA-256 hash of the token.
  - Without the token, a session id returns 404.
  - The page links only to `https://meet.google.com/…` URLs.
- **The bot** authenticates its WebSocket with a per-session key:
  - The key is passed in the `CUE_FACE_WS_TOKEN` environment variable, never on the command line.
  - The key is rotated every launch.
- **Calendar events** are private, guests can't invite others, and the description discloses that Cue is an AI and that the call is transcribed.
- **Limits** (all configurable):
  - 20-minute calls.
  - 3 sessions per IP per hour, 3 per email per day, 40 per day in total.
  - One live demo at a time, since there is one Chrome profile.
  - Scheduled calls between 10 minutes and 14 days ahead.
  - Cue admits at most 2 people.
  - The bot leaves after 10 minutes if nobody joins, or 60 seconds after everyone leaves.
- **Retention:**
  - Emails and IPs are stored only as peppered hashes, used for rate limits.
  - Transcripts are deleted after 7 days and sessions after 30.
  - Audio is never stored.

## Setup

These steps run on the bot host, a Mac or a Linux machine with a display, because Meet blocks headless Chrome.

1. **Install the Python dependencies.**
   ```bash
   .venv/bin/pip install -e '.[demo]'
   .venv/bin/playwright install chromium
   ```
2. **Download the speech models.** About 400 MB: Kokoro, and faster-whisper `base.en`.
   ```bash
   .venv/bin/python scripts/demo_fetch_models.py
   ```
3. **Sign in to Cue's dedicated Google account** in the bot's Chrome profile (see `face/README.md`). Do it yourself; never share the password.
   ```bash
   .venv/bin/python scripts/face_bot.py login
   ```
4. **Set up the Google Cloud project.**
   - Enable the **Google Calendar API**.
   - Configure the OAuth consent screen. Add Cue's account as a test user, or publish the app.
   - Create an OAuth client of type **Desktop app** and download its JSON.
5. **Authorize Calendar access as Cue.** This opens Google's consent page in Cue's Chrome profile; approve it there.
   ```bash
   .venv/bin/python scripts/demo_google_auth.py --client-secrets ~/Downloads/client_secret_….json
   ```
6. **Configure and run the demo API.**
   ```bash
   export CUE_DEMO_API_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
   export ANTHROPIC_API_KEY=…
   export CUE_DEMO_PUBLIC_URL=https://your-site.example   # used in the invite's link back to the session page
   .venv/bin/uvicorn cue.demo.app:app --host 127.0.0.1 --port 8780
   ```
   `GET /demo/health` with the key reports whether Google and voice are configured.
7. **Configure the frontend.** In `frontend/.env.local`, or your host's environment, set `CUE_DEMO_API_URL` (for example `http://127.0.0.1:8780`) and the same `CUE_DEMO_API_KEY`.

If the Next.js server and the demo API run on different machines, put the demo API behind HTTPS. The bot's WebSocket URL is `CUE_DEMO_INTERNAL_WS` (default `ws://127.0.0.1:8780`).

### Optional settings

| Variable | Default |
| --- | --- |
| `CUE_DEMO_DB` | `~/.cue-demo/demo.sqlite3` |
| `CUE_DEMO_GOOGLE_TOKEN_FILE` | `~/.cue-demo/google-oauth.json` |
| `CUE_DEMO_CALENDAR_ID` | `primary` |
| `CUE_FACE_PROFILE` | the bot's Chrome profile |
| `CUE_DEMO_BOT` | `1`; set `0` to create meetings without launching the bot |
| `CUE_DEMO_BOT_ARGS` | extra `face_bot.py join` flags |
| `CUE_DEMO_AUTO_ADMIT` | `2` |
| `CUE_DEMO_MODEL` | `claude-opus-5-5` |
| `CUE_DEMO_STT_MODEL` | `base.en` |
| `CUE_DEMO_TTS_DIR` | `~/.cue-demo/kokoro` |
| `CUE_DEMO_TTS_VOICE` | `af_heart` |

Limits come from these variables:

| Variable | Default |
| --- | --- |
| `CUE_DEMO_SESSION_MINUTES` | 20 |
| `CUE_DEMO_PER_IP_PER_HOUR` | 3 |
| `CUE_DEMO_PER_EMAIL_PER_DAY` | 3 |
| `CUE_DEMO_PER_DAY` | 40 |
| `CUE_DEMO_MAX_SCHEDULE_DAYS` | 14 |

Bot logs are written to `~/.cue-demo/logs/<session>.log`.

## How a call works

1. **Create.** `POST /demo/sessions` validates consent, email, timezone and time, and applies the rate limits. It then creates the Calendar event with Meet conferencing, inviting the visitor (`sendUpdates=all`).
2. **Start the bot.** "Meet now" starts the bot immediately. A scheduled session starts 60 seconds before its start time.
3. **Join.** The bot opens Meet as Cue, the meeting's host. It admits the visitor and reports its status (`bot_joining`, `bot_waiting`, `bot_in_call`, `live`). The session page shows the same steps and offers the Meet link straight away.
4. **Converse.**
   - The face page mixes the other participants' audio to 16 kHz PCM and streams it as `audio_in`.
   - An energy-based endpointer cuts utterances.
   - faster-whisper transcribes them and Claude streams a reply.
   - Live replies use `fallbacks: "default"` (server-side refusal fallback).
   - Kokoro speaks the reply sentence by sentence, and the mouth follows the audio.
   - If the visitor talks over Cue for about 350 ms, Cue stops speaking.
   - Typical reply latency is 2 to 4 seconds on an M-series Mac.
5. **End.** At the time limit, the scheduler stops the bot, which leaves the call. The bot also leaves on its own when everyone has gone.
6. **Summarize.** Claude summarizes the transcript with a JSON-schema response, and the session page shows it.

If voice isn't configured, because the Anthropic key or the models are missing, the session reports `voice.available: false`. The page and the in-call caption say so plainly; Cue never pretends to listen.

## Tests

The commands below exercise everything except real Google, Claude and Meet.

Unit and API tests, with fakes for Calendar, the bot, the speech engines and Claude:
```bash
.venv/bin/pytest tests/demo -q
```

End to end on this machine: real `face_bot.py`, a fake Meet page, real Whisper and Kokoro, and a scripted Claude.
```bash
CUE_DEMO_E2E=1 .venv/bin/pytest tests/demo/test_demo_e2e.py -q -s
```

Face and bot tests:
```bash
cd face && ../.venv/bin/pytest -q
```

## Known limits

- **One bot at a time:** there is one signed-in Chrome profile. Run more bot hosts with their own Cue accounts to scale.
- **Meet's UI can change:** joining, admitting guests and leaving rely on Meet's accessible button names. Check `face_bot.py` after Meet updates.
- **Mixed audio:** all participants' audio is mixed before transcription, and Cue answers whoever spoke last.
