# Spike: can attendee-labs/attendee stream Cue's mascot into Google Meet?

Date: 2026-10-30. Source reviewed: `attendee-labs/attendee` at `main` commit `06eb857db8`
(2026-10-29): `docs/voice_agents.md`, `docs/realtime_audio.md`, `README.md`, `LICENSE`,
`dev.docker-compose.yaml`, `bots/webpage_streamer/webpage_streamer.py` and
`bots/bot_controller/webpage_streamer_manager.py`.

**Result: yes, Attendee can stream custom video and audio, but not at the quality, latency or
operational cost Cue's acceptance criteria need. We build the Playwright + Chromium bot
(`scripts/face_bot.py`) as the primary path and keep the face page Attendee-compatible, so
switching is a configuration change.**

This was a source and documentation review, not a live run. The Docker daemon was not running
on the dev machine, and a live run would also need a Google Meet with an admitting host.

## What Attendee offers

- **Voice agents via a webpage.** `POST /api/v1/bots` with
  `voice_agent_settings: {"url": "https://..."}` loads that page in a separate
  `webpage-streamer` container. Its audio and video become the bot's webcam and microphone, and
  meeting audio is fed back into the page as its microphone. `screenshare_url` sends it as a
  screenshare instead. The docs require a public HTTPS page that starts without a click and is
  designed for 1280×720.
- **Self-hosting.** One Django image plus Postgres and Redis. Local dev uses
  `dev.docker-compose.yaml`, with `attendee-webpage-streamer-local` as its own service.
  Production uses Kubernetes with one pod per bot; the official Kubernetes directions are part of
  a paid self-hosting plan.
- **Realtime audio over WebSocket** (`docs/realtime_audio.md`). This carries audio only, so it
  cannot carry the mascot video.

## How the webpage streamer works (from source)

`webpage_streamer.py` opens the URL in Selenium-driven Chrome on an X display (Xvfb if none), then:

```
ximagesrc ... framerate=15/1,width=1280,height=720   -> aiortc video track
alsasrc   ... S16LE, channels=1, rate=16000          -> aiortc audio track
```

Those tracks travel over a WebRTC peer connection to the bot container, which plays them into
Meet's camera and microphone.

## Fit against Cue's acceptance criteria

| Criterion | Attendee webpage streamer | Playwright bot (`face_bot.py`) |
|---|---|---|
| Custom video + audio | Yes, via screen capture | Yes, `canvas.captureStream(30)` + `MediaStreamDestination` |
| Smooth, premium motion | **15 fps hard-coded** in the capture pipeline | 30 fps straight from the canvas |
| Voice quality | **16 kHz mono** capture, then Opus | 48 kHz Web Audio straight into WebRTC/Opus |
| Mouth synced to audio | Two capture paths (X11 and ALSA) with separate queues; sync not controlled by us | Video and audio come from one page and clock |
| `stop` silent within 200 ms | Page goes silent in ~15 ms, but up to 8000 queued ALSA buffers plus an aiortc hop sit after it; not verifiable | Silence at the source, measured < 200 ms in tests |
| Infra to run one bot | Django, Postgres, Redis, bot worker, streamer container (Docker or Kubernetes) | One Python process + Chrome |
| Page hosting | Must be a public HTTPS URL | Injected locally; nothing to host |
| License | Elastic License 2.0: self-hosting allowed, but it may not be offered to third parties as a hosted or managed service. Needs a legal read for Cue's SaaS. | Playwright is Apache-2.0; our own code |
| Other platforms | Zoom and Teams supported | Google Meet only |

## Decision

1. Ship `scripts/face_bot.py` (Playwright + Chromium) for Google Meet now.
2. Keep `face/index.html` usable as Attendee's `voice_agent_settings.url`. It renders at
   1280×720, starts with no click (`?ws=wss://...` connects to the backend; autoplay is allowed
   in Attendee's container), and draws cards and captions on the canvas, so screen capture picks
   them up. Revisit Attendee if Cue needs Zoom or Teams, after a legal review of ELv2 and a live
   test of its 15 fps output.
3. No Recall.ai or other paid bot service is involved in either path.

## To verify if we revisit

- Run `docker compose -f dev.docker-compose.yaml up` and create a bot with
  `voice_agent_settings.url` set to the hosted face page with `?mock=1`. Measure frame rate and
  stop-to-silence on the receiving side.
- Check whether a newer Attendee release makes the 15 fps / 16 kHz capture configurable.
