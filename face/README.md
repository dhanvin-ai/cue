# Cue face: the animated mascot in Google Meet

Cue joins Google Meet as a participant named **Cue**. Its camera is an original animated mascot and
its microphone carries Cue's speech. The mascot reacts to five states, moves its mouth to the real
speech audio, and shows action cards, approval status and optional captions. The video tile labels
Cue as an **AI teammate** at all times.

Everything is self-hosted and open source: a canvas + Web Audio page, and a Playwright + Chromium
bot. No Recall.ai or other paid meeting-bot service is involved. Attendee was evaluated first; see
[ATTENDEE_SPIKE.md](ATTENDEE_SPIKE.md) for why the Playwright bot is the primary path.

This module only renders and transports. Speech recognition, reasoning, TTS and approval decisions
stay in the backend, which drives the face through the WebSocket contract below.

```
backend ──ws: state / speak / stop / action / caption──▶ face_bot.py ──page.evaluate──▶ face (in the Meet tab)
        ◀─ws: bot_status / speak_started / speak_ended ─┘                                │
                                                     canvas.captureStream(30) ──▶ Meet camera
                                     speech → AnalyserNode → MediaStreamDestination ──▶ Meet microphone
                                                                  └─▶ mouth movement
```

## Files

| Path | What it is |
|---|---|
| `index.html` | Standalone 1280×720 page (mock demo, local dev, Attendee `voice_agent_settings.url`) |
| `src/core.js` | Palette, springs, noise, and the contract validator `normalizeEvent` |
| `src/speech.js` | Decodes and schedules speech; AnalyserNode metering; stop in ~15 ms |
| `src/mascot.js` | The mascot: head, eyes, brows, mouth, the C ring and lime dot, five poses |
| `src/overlay.js` | AI-teammate badge, status pill, action cards, captions, background |
| `src/app.js` | `FaceApp`: render loop, `dispatch()`, outbound events, `mediaStream()` |
| `src/mock.js` | `?mock=1` scripted meeting with an original synthesised babble voice |
| `src/boot.js` | Page mode vs. embedded-in-Meet mode; `getUserMedia` override; ws client |
| `dev_server.py` | Local backend stand-in: serves this folder and a WebSocket hub at `/ws` |
| `../scripts/face_bot.py` | Joins a Meet URL with the face as camera and mic |
| `tests/` | Browser and bot tests; `fake_meet.html` mimics Meet's join flow |
| `assets/` | CUE mark, Geist font (SIL OFL 1.1, see `assets/OFL.txt`) |

No build step and no framework: plain classic scripts sharing a `CueFace` namespace. That way the
same files run in the page and when the bot injects them into Meet.

## The mascot

The mascot is an ink "pebble" head inside the open **C** of the CUE mark, with the lime dot in the
C's mouth. All features run on damped springs, so states blend instead of snapping. Idle layers keep
it alive between events: breathing, sway, blinks (sometimes double), eye saccades and small "mm-hm"
nods.

| State | How to recognise it |
|---|---|
| `listening` | Soft smile, wandering gaze, occasional nods, faint static C ring, dot resting in the gap |
| `thinking` | Eyes up and to the side, squint, one brow raised, mouth pursed to the side; the C spins with the dot riding it |
| `talking` | Mouth driven by the audio (opening by loudness, wide or round by spectrum), brows pop on syllables, head bobs with the voice, glow brightens |
| `acting` | Focused squint toward the cards, lowered brows; a lime progress sweep races around the C |
| `waiting_approval` | Wide hopeful eyes and raised inner brows, head tilt, small "o" mouth; the C turns so the dot sits up and to the right like a raised hand, with ripples |

The status pill under the mascot names the state in words. A finished action triggers happy arc eyes
and a hop; a failed one triggers a worried brow and a small head shake.

The layout is safe for Meet's tiles: essentials stay inside the centre 4:3 area. When cards appear,
the mascot glides left to make room.

## WebSocket contract

The backend sends JSON text frames. Unknown fields are ignored, and invalid events are rejected with
an outbound `error` while the face keeps running.

```jsonc
{"type": "state", "state": "listening"}   // listening | thinking | talking | acting | waiting_approval
                                          // aliases: idle, speaking, working, approval, ...

{"type": "speak", "id": "utt-42",         // chunks with the same id form one utterance
 "audio": "<base64>",                     // or "audio_url": "https://..."
 "format": "wav",                         // anything decodeAudioData handles (wav, mp3, ogg, ...) or "pcm_s16le"
 "sample_rate": 24000, "channels": 1,     // pcm_s16le only
 "seq": 0, "final": true,                 // optional; chunks may arrive out of order
 "text": "Sure, I'll file it.",           // optional; shown as Cue's caption when its audio starts
 "interrupt": false}                      // true: stop everything else first; otherwise queue

{"type": "stop"}                          // silence all speech now (barge-in), or {"type": "stop", "id": "utt-42"}

{"type": "action", "id": "gh-1", "status": "running",   // running | done | failed | needs_approval
 "title": "Create GitHub issue", "detail": "cue/api · Login timeouts", "tool": "github"}
{"type": "action", "id": "gh-1", "remove": true}

{"type": "caption", "speaker": "Priya", "text": "Cue, can you file that?", "final": true}
{"type": "caption", "text": ""}           // clear
```

Behaviour notes:

- While speech audio plays, the face shows `talking` whatever the last `state` was, then returns to
  that state. A `state: talking` sent before the audio ends falls back to `listening` when the
  utterance finishes.
- `stop` ramps the utterance to silence in 12 ms and stops its sources, and chunks of a stopped
  utterance that arrive later are dropped. The tests measure under 200 ms to silence on the
  analyser, which is the exact signal the meeting receives.
- Cards update in place by `id`. `done` cards leave after 9 s and `failed` after 14 s;
  `running` and `needs_approval` stay until updated or removed. At most 4 are shown.
- `caption` events are optional live captions. `?captions=0` (page) or `--no-captions` (bot)
  hides all captions.

The face also sends these outbound messages, for the backend to use or ignore:

```jsonc
{"type": "ready", "version": "1.0.0", "mode": "embedded"}
{"type": "speak_started", "id": "utt-42", "text": "..."}
{"type": "speak_ended", "id": "utt-42", "reason": "completed"}   // completed | stopped | interrupted
{"type": "state_changed", "state": "talking"}
{"type": "error", "message": "Unknown state: dancing"}
{"type": "bot_status", "status": "in_call", "name": "Cue"}       // face_bot.py: joining | waiting_admission | in_call
                                                                 // | video_live | left | denied | admission_timeout | ...
```

## Local setup

Requirements: Python 3.12+, Google Chrome (recommended for Meet) or Playwright's Chromium.

```sh
cd /path/to/cue
python3 -m venv .venv                      # or reuse the backend venv
.venv/bin/pip install -r face/requirements.txt
.venv/bin/playwright install chromium       # browser for tests and --browser chromium
```

### Mock demo (no backend)

```sh
.venv/bin/python face/dev_server.py serve
open 'http://127.0.0.1:8765/?mock=1'
```

The mock plays a whole meeting on a loop. Priya and Arjun ask Cue to file an issue; Cue thinks,
answers, files it (`running` → `done`), asks for approval to post in Slack (`needs_approval`, then
waiting), gets approved, has a Linear update fail (`failed`), and is finally interrupted mid-sentence
(`stop`). Cue's voice in the mock is an original formant "babble" synthesised in the browser. It is
real audio sent through the same `speak` path a backend would use, so the mouth sync is real.

Page flags: `?mock=1`, `?loop=0`, `?ws=ws://…`, `?captions=0`, `?mute=1`, `?debug=1` (state,
mouth level and stop latency overlay), `?fps=30`. A browser may block sound until you click; the
page then shows a "Click to turn on Cue's sound" button.

### Drive the face by hand

```sh
.venv/bin/python face/dev_server.py serve
open 'http://127.0.0.1:8765/?ws=ws://127.0.0.1:8765/ws&debug=1'
.venv/bin/python face/dev_server.py send '{"type":"state","state":"thinking"}'
.venv/bin/python face/dev_server.py send '{"type":"action","id":"a1","status":"needs_approval","title":"Post to #eng","tool":"slack"}'
say -o /tmp/hi.wav --file-format=WAVE --data-format=LEI16@24000 "Hi, I'm Cue, the team's AI teammate."   # macOS
.venv/bin/python face/dev_server.py speak /tmp/hi.wav --text "Hi, I'm Cue" --stream-ms 300
.venv/bin/python face/dev_server.py send '{"type":"stop"}'
```

`--stream-ms` splits a 16-bit WAV into `pcm_s16le` chunks sent slightly faster than real time,
the way streaming TTS would.

### Tests

```sh
.venv/bin/pytest face/tests -q            # ~1 min, headless Chromium
.venv/bin/pytest face/tests -q -m slow    # also plays the full mock meeting (~60 s)
```

These cover: contract validation; all five states having distinct poses; the four card statuses;
mouth/audio correlation; stop-to-silence under 200 ms; streamed and out-of-order PCM chunks; late
chunks after `stop`; the captured 1280×720 video and live audio track; the page's own WebSocket
client; and the bot's join flow against `tests/fake_meet.html`. The bot checks include the guest
name, camera and mic on, admission, frames received at 1280×720, events and speech reaching the
"meeting", `stop`, denial, mock mode and clean leave.

## Joining a real Google Meet

Use a **dedicated Google account for Cue**, one that your organisation has authorised to join
meetings as an AI participant. Set its display name to **Cue**, because Meet shows the signed-in
account's name. Never use a personal account, and never commit the browser profile: it holds that
account's session cookies. The default profile lives outside the repo at
`~/.cue-face-bot/chrome-profile` (override with `--profile` or `CUE_FACE_PROFILE`), and
`face/.gitignore` also ignores profile folders in case one is created here.

1. **Sign in once.** A person signs in; the bot never handles the password.

   ```sh
   .venv/bin/python scripts/face_bot.py login
   ```

   This opens a normal Chrome window (not automated) on the bot profile, at accounts.google.com.
   Sign in to Cue's account, then quit Chrome.

2. **Create a meeting** from a different, human account and copy its link.

3. **Join with the mock script** to check camera, mic and admission without a backend:

   ```sh
   .venv/bin/python scripts/face_bot.py join https://meet.google.com/abc-defg-hij --mock
   ```

   Admit **Cue** from the host's window. The log prints
   `Mascot is live: N frames sent at 1280x720, X.Xs after admission`, measured from WebRTC stats.
   This is the 15-second acceptance check.

4. **Join wired to a backend** (or to the dev hub, sending events by hand as above):

   ```sh
   .venv/bin/python face/dev_server.py serve &
   .venv/bin/python scripts/face_bot.py join https://meet.google.com/abc-defg-hij --ws ws://127.0.0.1:8765/ws
   ```

   If the backend socket needs auth, set `CUE_FACE_WS_TOKEN`; it is sent as
   `Authorization: Bearer …` and never logged.

5. **Leave** with Ctrl-C. The bot stops any speech, clicks Leave call, closes the socket and
   browser. A second Ctrl-C exits immediately.

`--guest` joins without the profile, as a guest named `--name` (default `Cue`). This only works
for meetings that admit guests, and the host must let Cue in.

### What the bot handles

- **Admission:** it clicks "Join now" or "Ask to join" and waits up to `--admission-timeout`
  (600 s), reporting `waiting_admission`. If it is denied, nobody answers, or the link is invalid,
  it reports the reason and exits with code 3 (not admitted) or 4 (join failed).
- **Permissions:** Chrome flags auto-grant camera and mic. Meet's camera and mic toggles are turned
  on before joining and checked again after admission. The injected `getUserMedia` returns clones
  of the canvas and speech tracks, so Meet muting or replacing tracks never kills the source.
- **Audio interruption:** `stop` from the backend reaches the page in one `page.evaluate` call and
  silences in about 15 ms. A new `speak` with `interrupt: true` cuts off the current one. The
  AudioContext is kept running even if Chrome tries to suspend it.
- **Frozen frames:** Chromium throttles `requestAnimationFrame` in occluded windows, so a worker
  timer keeps rendering whenever rAF goes quiet.
- **Shutdown:** SIGINT and SIGTERM, the host ending the call, Cue being removed, `--alone-timeout`
  (300 s alone), and `--max-minutes` (240) all lead to the same clean leave. Exit codes are 0 for
  ok, 2 for config, 3 for not admitted, 4 for join failed, and 130 for interrupted.
- **Backend socket drops:** it reconnects with backoff up to 10 s, and the meeting carries on.

### Troubleshooting

- *"No join button appeared"*: the profile is probably signed out, or Meet's UI is in another
  language. The bot matches English labels and launches with `--lang=en-US`, so set the Cue
  account's language to English too.
- *Google says the browser may not be secure*: always sign in with `face_bot.py login` (plain
  Chrome), not inside an automated window.
- *Black or frozen tile*: run with `-v`. The log should show `Mascot is live`. Keep the bot window
  on a real display; `--headless` exists but Meet often blocks headless browsers.

## Using Attendee instead

`index.html` also works as an Attendee voice-agent page. Host this folder over HTTPS, then create
the bot with `"voice_agent_settings": {"url": "https://<host>/index.html?ws=wss://<backend>/face"}`.
The page renders at 1280×720, needs no click, and draws everything on the canvas. Attendee captures
at 15 fps with 16 kHz audio; see the spike for the trade-offs.

## Verification status (2026-10-31)

Verified locally on macOS (Apple Silicon), in Playwright's Chromium and in Google Chrome:

| Check | How | Result |
|---|---|---|
| Five states distinct | Test compares pose parameters; contact sheet reviewed by eye | Pass |
| Mouth synced to audio | Analyser RMS vs. mouth opening, every frame | Correlation above 0.75, opens above 0.6 and closes below 0.15 |
| `stop` within 200 ms | Time from dispatch until the analyser stays silent | Pass (fade is 12 ms; the mock's own probe reads one frame) |
| Card statuses | `running`, `done`, `failed`, `needs_approval`, in-place updates, remove | Pass |
| Mock demo, no backend | Full scripted meeting: every state, status, completion and a barge-in | Pass |
| Camera and mic tracks | Captured stream is 1280×720 video plus live audio | Pass |
| Bot join flow | Against `fake_meet.html`: name, devices, ask to join, admission, denial, leave | Pass |
| Mascot within 15 s of admission | WebRTC outbound stats, then frames received by the far side | First frames at 0.0 s, 1280×720 at 20+ fps |
| Speech reaches the meeting | Level of the received audio track; then `stop` | Pass |
| Ctrl-C to the whole process group | Bot still clicks Leave call, exit 130, no stray browser | Pass |

**Not yet verified:** a real Google Meet join. This needs Cue's dedicated, authorised Google
account to be signed in with `face_bot.py login` by a person, plus a host to admit it. Meet's
labels (`Join now`, `Ask to join`, `Leave call`, `Turn on camera`) are matched as of October 2026
and may change. Also unverified: running Attendee live (see the spike) and Linux or Windows hosts.
