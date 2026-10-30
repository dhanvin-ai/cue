# Meeting bot: Attendee

Cue joins Google Meet as a named participant ("Cue") through a self-hosted
[Attendee](https://github.com/attendee-labs/attendee) instance. Everything in this path is free:

| Part | Choice |
|---|---|
| Joining Meet | Attendee bot, headless Chrome, self-hosted with Docker |
| Hearing | Meet's own closed captions, delivered per utterance with the speaker's name (`transcript.update` webhook) |
| Speaking | Edge TTS (`edge-tts`, no key) → MP3 → `POST /api/v1/bots/{id}/output_audio` |
| Thinking | Cue's normal turn pipeline: addressing check, memory, tools, approvals |

Captions carry speaker identity, so unlike the Bolna phone line each turn runs with the speaker's own
permissions when their name matches a meeting attendee.

## Flow

1. `POST /v1/tenants/{tenant}/meetings` with `"voice": "attendee"` (the default) creates the bot.
2. The host admits "Cue". Cue speaks the recording disclosure.
3. Each caption utterance arrives at `/webhooks/attendee/{tenant}`, is verified, stored in the
   transcript, and checked for whether Cue was addressed.
4. If addressed, Cue says "One sec, pulling that up.", runs the turn, then speaks the answer.

## Setup

Attendee license is Elastic 2.0: free to self-host for our own use, not to resell as a service.

```sh
git clone https://github.com/attendee-labs/attendee && cd attendee
docker compose -f dev.docker-compose.yaml build
docker compose -f dev.docker-compose.yaml run --rm attendee-app-local python init_env.py > .env
docker compose -f dev.docker-compose.yaml up
docker compose -f dev.docker-compose.yaml exec attendee-app-local python manage.py migrate
```

Open http://localhost:8000, sign up (the confirmation link is in the server log), create an API
key, and add a webhook secret. Attendee wants S3 for recordings even with recording off; point
`AWS_ENDPOINT_URL` at a local MinIO if it complains.

Cue's webhook must be HTTPS, so expose the API with ngrok:

```sh
ngrok http 8080        # Cue API port
printf '%s' 'ATTENDEE_WEBHOOK_SECRET' > .secrets/attendee-webhook.txt
# .env: CUE_PUBLIC_URL, ATTENDEE_URL, ATTENDEE_API_KEY, ATTENDEE_WEBHOOK_SECRET_VERSION
```

## Known limits

- Captions land after each utterance ends, so Cue hears a sentence about 1 to 2 s late.
- Edge TTS takes about 1 s per answer once warm, but the first call can take up to 7 s. Short
  phrases are cached.
- `output_audio` plays a whole clip, so barge-in does not cut Cue off yet. Streaming over
  Attendee's audio websocket fixes this in phase 2.
- Speaker-to-member matching is by display name; attendees with a calendar invite match best.
- Not yet run against a live Meet.
