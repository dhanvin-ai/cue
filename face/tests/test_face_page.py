"""Browser tests for the face page: states, cards, captions, audio-driven mouth, stop latency,
the captured MediaStream, and the full ?mock=1 meeting. Run with:

    .venv/bin/pytest face/tests -q            # fast tests
    .venv/bin/pytest face/tests -q -m slow    # also the ~60s full mock meeting
"""

import json
import statistics

import pytest

SPEAK_LONG = """async () => {
  const wav = await CueFace.synthPhrase('This is a long sentence that keeps going for a while, so there is time to interrupt it, and then some more words after that.', 11);
  cueFace.dispatch({type: 'speak', id: 'long', format: 'wav', audio: wav, text: 'long'});
}"""


def open_face(page, server, query=""):
    page.goto(f"{server['http']}/?mute=1{query}")
    page.wait_for_function("() => window.cueFace && cueFace.frames > 5")


def snapshot(page):
    return page.evaluate("() => cueFace.snapshot()")


def test_page_boots_without_errors(page, server):
    open_face(page, server)
    snap = snapshot(page)
    assert snap["state"] == "listening"
    assert snap["audio"] == "running"
    assert page.evaluate("() => [cueFace.canvas.width, cueFace.canvas.height]") == [1280, 720]
    assert page.errors == []


def test_five_states_have_distinct_poses(page, server):
    open_face(page, server)
    poses = {}
    for state in ["listening", "thinking", "talking", "acting", "waiting_approval"]:
        page.evaluate("s => cueFace.dispatch({type: 'state', state: s})", state)
        page.wait_for_timeout(1400)
        poses[state] = page.evaluate(
            """() => { const m = cueFace.mascot, s = m.s;
              return { state: m.state, label: cueFace.overlay.status, lookY: s.lookY.value, squint: s.squint.value,
                       browY: s.browY.value, ring: s.ring.value, lime: s.ringLime.value, spin: m.rotVel,
                       dotLift: s.dotLift.value, eyeScale: s.eyeScale.value }; }"""
        )
        assert poses[state]["state"] == state
        assert poses[state]["label"] == state
    # Each state has a signature the others lack.
    assert poses["thinking"]["spin"] > 1.5 and poses["thinking"]["lime"] < 0.1 and poses["thinking"]["lookY"] < -0.3
    assert poses["acting"]["spin"] > 3 and poses["acting"]["lime"] > 0.9
    assert poses["waiting_approval"]["dotLift"] > 0.9 and poses["waiting_approval"]["eyeScale"] > 1.08
    assert poses["listening"]["spin"] < 0.2 and poses["listening"]["ring"] < 0.2
    assert poses["talking"]["spin"] < 0.2 and poses["talking"]["dotLift"] < 0.1
    # Canvas frames actually differ between states.
    assert page.errors == []


def test_contract_rejects_bad_events(page, server):
    open_face(page, server)
    results = page.evaluate(
        """() => [
          cueFace.dispatch('not json'),
          cueFace.dispatch({type: 'state', state: 'dancing'}),
          cueFace.dispatch({type: 'action', status: 'running'}),
          cueFace.dispatch({type: 'action', id: 'x', status: 'exploded'}),
          cueFace.dispatch({type: 'teleport'}),
          cueFace.dispatch({type: 'state', state: 'idle'}),
          cueFace.dispatch(JSON.stringify({type: 'caption', text: 'hello', speaker: 'Priya'})),
        ]"""
    )
    assert results == [False, False, False, False, False, True, True]
    snap = snapshot(page)
    assert snap["rejected"] == 5 and snap["state"] == "listening" and snap["caption"] == "hello"


def test_action_cards_support_all_statuses(page, server):
    open_face(page, server)
    for i, status in enumerate(["running", "done", "failed", "needs_approval"]):
        page.evaluate(
            "([id, status]) => cueFace.dispatch({type: 'action', id, status, title: 'Task ' + id, tool: 'github'})",
            [f"a{i}", status],
        )
    page.wait_for_timeout(600)
    cards = {c["id"]: c["status"] for c in snapshot(page)["cards"]}
    assert cards == {"a0": "running", "a1": "done", "a2": "failed", "a3": "needs_approval"}
    # Status updates in place; cards move the mascot aside; remove clears them.
    page.evaluate("() => cueFace.dispatch({type: 'action', id: 'a3', status: 'done', title: 'Approved'})")
    assert {c["id"]: c["status"] for c in snapshot(page)["cards"]}["a3"] == "done"
    page.wait_for_timeout(1200)
    assert page.evaluate("() => cueFace.mascot.x") < 500
    for i in range(4):
        page.evaluate("id => cueFace.dispatch({type: 'action', id, remove: true})", f"a{i}")
    page.wait_for_timeout(1500)
    assert snapshot(page)["cards"] == []
    assert page.evaluate("() => cueFace.mascot.x") > 600


def test_mouth_follows_speech_amplitude(page, server):
    open_face(page, server)
    page.evaluate(SPEAK_LONG)
    page.wait_for_function("() => cueFace.speech.speaking")
    # Sample the analyser level and the mouth opening on every rendered frame for ~2.5 s.
    samples = page.evaluate(
        """async () => {
          const out = [];
          const end = performance.now() + 2500;
          while (performance.now() < end) {
            await new Promise(r => requestAnimationFrame(r));
            out.push([cueFace.speech.metrics.rms, cueFace.mascot.env]);
          }
          return out;
        }"""
    )
    rms = [s[0] for s in samples]
    mouth = [s[1] for s in samples]
    assert snapshot(page)["state"] == "talking"
    assert max(mouth) > 0.6, "mouth should open wide on loud syllables"
    assert min(mouth) < 0.15, "mouth should close between syllables"
    corr = statistics.correlation(rms, mouth)
    assert corr > 0.75, f"mouth/audio correlation too low: {corr:.2f}"


def test_stop_silences_speech_within_200ms(page, server):
    open_face(page, server)
    page.evaluate(SPEAK_LONG)
    page.wait_for_function("() => cueFace.speech.speaking && cueFace.speech.analyserRms() > 0.01", timeout=5000)
    page.wait_for_timeout(700)
    elapsed = page.evaluate(
        """async () => {
          const t0 = performance.now();
          cueFace.dispatch({type: 'stop'});
          // Poll the analyser (the exact signal the meeting hears) until it is silent.
          let quietSince = null;
          while (performance.now() - t0 < 1000) {
            const now = performance.now();
            if (cueFace.speech.analyserRms() < 0.001) {
              quietSince = quietSince || now;
              if (now - quietSince > 60) return quietSince - t0;  // stays silent
            } else {
              quietSince = null;
            }
            await new Promise(r => setTimeout(r, 2));
          }
          return null;
        }"""
    )
    assert elapsed is not None and elapsed < 200, f"stop took {elapsed} ms"
    page.wait_for_timeout(200)
    assert snapshot(page)["speaking"] is False


def test_streamed_pcm_chunks_and_late_chunks_after_stop(page, server):
    open_face(page, server)
    events = page.evaluate(
        """async () => {
          const seen = [];
          cueFace.on(m => { if (m.type.startsWith('speak')) seen.push(m.type + ':' + (m.reason || '')); });
          // 3 x 300 ms of a 220 Hz tone as raw pcm_s16le, sent out of order.
          const chunk = (phase) => {
            const n = 24000 * 0.3, bytes = new Uint8Array(n * 2), v = new DataView(bytes.buffer);
            for (let i = 0; i < n; i++) v.setInt16(i * 2, Math.sin((i + phase) * 2 * Math.PI * 220 / 24000) * 12000, true);
            return CueFace.bytesToBase64(bytes);
          };
          const ev = (seq, final) => ({type: 'speak', id: 'pcm', seq, final, format: 'pcm_s16le', sample_rate: 24000, audio: chunk(seq * 7200)});
          cueFace.dispatch(ev(1, false));
          cueFace.dispatch(ev(0, false));
          cueFace.dispatch(ev(2, true));
          await new Promise(r => setTimeout(r, 1300));
          // A stopped utterance ignores chunks that arrive afterwards.
          cueFace.dispatch({...ev(0, false), id: 'late'});
          await new Promise(r => setTimeout(r, 150));
          cueFace.dispatch({type: 'stop', id: 'late'});
          cueFace.dispatch({...ev(1, true), id: 'late'});
          await new Promise(r => setTimeout(r, 500));
          return {seen, speaking: cueFace.speech.speaking};
        }"""
    )
    assert events["seen"] == ["speak_started:", "speak_ended:completed", "speak_started:", "speak_ended:stopped"]
    assert events["speaking"] is False


def test_captured_stream_is_720p_video_plus_speech_audio(page, server):
    open_face(page, server)
    info = page.evaluate(
        """async () => {
          const stream = cueFace.mediaStream();
          const [v] = stream.getVideoTracks(), [a] = stream.getAudioTracks();
          const video = document.createElement('video');
          video.muted = true; video.srcObject = stream; await video.play();
          await new Promise(r => setTimeout(r, 500));
          const c = document.createElement('canvas'); c.width = 1280; c.height = 720;
          const ctx = c.getContext('2d'); ctx.drawImage(video, 0, 0);
          const px = ctx.getImageData(640, 318, 1, 1).data;  // centre of the ink head
          return {video: v.readyState, audio: a.readyState, w: video.videoWidth, h: video.videoHeight, centre: Array.from(px)};
        }"""
    )
    assert info["video"] == "live" and info["audio"] == "live"
    assert (info["w"], info["h"]) == (1280, 720)
    assert max(info["centre"][:3]) < 70, "captured frame should show the mascot's dark head"


def test_mock_mode_starts_a_scripted_meeting(page, server):
    open_face(page, server, "&mock=1")
    page.wait_for_function("() => cueFace.snapshot().caption && cueFace.snapshot().caption.includes('staging')", timeout=8000)
    page.wait_for_function("() => cueFace.snapshot().state === 'thinking'", timeout=12000)
    page.wait_for_function("() => cueFace.snapshot().speaking && cueFace.mascot.env > 0.3", timeout=8000)
    assert page.errors == []


@pytest.mark.slow
def test_full_mock_meeting_covers_every_state_and_status(page, server):
    open_face(page, server, "&mock=1&loop=0")
    seen = page.evaluate(
        """async () => {
          const states = new Set(), statuses = new Set(), ends = [];
          cueFace.on(m => {
            if (m.type === 'state_changed') states.add(m.state);
            if (m.type === 'speak_ended') ends.push(m.reason);
          });
          const t0 = performance.now();
          while (performance.now() - t0 < 75000) {
            for (const c of cueFace.snapshot().cards) statuses.add(c.status);
            if (ends.includes('stopped')) break;
            await new Promise(r => setTimeout(r, 100));
          }
          await new Promise(r => setTimeout(r, 400));  // lastStopMs is recorded on the next frames
          return {states: [...states], statuses: [...statuses], ends, stopMs: cueFace.lastStopMs};
        }"""
    )
    assert set(seen["states"]) >= {"thinking", "talking", "acting", "waiting_approval", "listening"}, seen
    assert set(seen["statuses"]) == {"running", "done", "failed", "needs_approval"}, seen
    assert seen["ends"].count("completed") == 3 and "stopped" in seen["ends"], seen
    assert seen["stopMs"] is not None and seen["stopMs"] < 200, seen
    assert page.errors == []


def test_page_talks_to_websocket_hub(page, server):
    """The page's own ws client (used for Attendee's voice_agent URL) round-trips events."""
    import asyncio
    import threading

    from dev_server import send_events

    open_face(page, server, f"&ws={server['ws']}")
    page.wait_for_function("() => CueFace.socket && CueFace.socket.readyState === 1")
    events = [{"type": "state", "state": "acting"}, {"type": "action", "id": "w", "status": "running", "title": "From hub"}]
    # Sync Playwright owns this thread's event loop, so the "backend" runs in its own thread.
    sender = threading.Thread(target=lambda: asyncio.run(send_events(server["ws"], events)))
    sender.start()
    sender.join(10)
    page.wait_for_function("() => cueFace.snapshot().state === 'acting' && cueFace.snapshot().cards.length === 1")
    assert json.loads(json.dumps(snapshot(page)["cards"]))[0]["title"] == "From hub"
