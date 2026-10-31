/* Starts the face in one of two modes:
 *  - page mode: face/index.html in a normal browser, or as Attendee's voice_agent_settings.url.
 *    Query params: ?mock=1  ?ws=wss://...  ?captions=0  ?debug=1  ?mute=1  ?fps=60
 *  - embedded mode: scripts/face_bot.py injects these files into Google Meet with
 *    globalThis.__CUE_FACE_EMBED__ set. The canvas and speech audio replace getUserMedia, so Meet
 *    sends the mascot as Cue's camera and the speech as Cue's microphone. */
(function (g) {
  'use strict';
  const CueFace = g.CueFace;

  function bootEmbedded(config) {
    if (CueFace.app) return CueFace.app;
    const canvas = document.createElement('canvas');
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.cssText = 'position:fixed;left:-20000px;top:0;width:1280px;height:720px;pointer-events:none;';
    const emit = (message) => {
      const binding = g[config.emitBinding || '__cueFaceEmit'];
      if (typeof binding === 'function') binding(JSON.stringify(message)).catch(() => {});
    };
    const app = new CueFace.FaceApp({ canvas, localAudio: false, captions: config.captions !== false, fps: config.fps || 30, watchdog: 'timer', onEmit: emit });
    CueFace.app = app;
    const attach = () => (document.body || document.documentElement).appendChild(canvas);
    if (document.documentElement) attach();
    else document.addEventListener('readystatechange', attach, { once: true });
    if (config.font) app.loadFont('url(' + config.font + ')');
    app.start();

    // Keep the AudioContext running; Chrome may suspend it until the page has media activity.
    const keepAlive = () => {
      if (app.audio.state === 'suspended') app.audio.resume().catch(() => {});
    };
    setInterval(keepAlive, 1000);

    installMediaOverride(app);
    trackPeerConnections();
    if (config.captureAudio) CueFace.onRemoteAudio = listenToMeeting(app, emit);
    if (config.mock) new CueFace.MockMeeting(app).run();
    emit({ type: 'ready', version: CueFace.version, mode: 'embedded' });
    return app;
  }

  function installMediaOverride(app) {
    const md = navigator.mediaDevices;
    if (!md || md.__cueFace) return;
    const stream = app.mediaStream();
    const video = stream.getVideoTracks()[0];
    const audio = stream.getAudioTracks()[0];
    // Flat cartoon art stays sharp at low bitrates, so ask WebRTC to keep the resolution and trade
    // frame rate or quality instead; otherwise it starts at 320x180 and takes ~20 s to ramp up.
    video.contentHint = 'detail';
    audio.contentHint = 'speech';
    const quiet = (track) => {
      // Meet tunes capture with applyConstraints; the canvas and Web Audio tracks ignore it.
      track.applyConstraints = () => Promise.resolve();
      return track;
    };
    md.getUserMedia = async function (constraints) {
      const c = constraints || {};
      const out = new MediaStream();
      // Clones, so Meet can stop() its tracks when muting without killing our sources.
      if (c.video) out.addTrack(quiet(video.clone()));
      if (c.audio) out.addTrack(quiet(audio.clone()));
      app.resumeAudio();
      return out;
    };
    md.__cueFace = true;
  }

  /* Records the page's peer connections so face_bot.py can confirm, from WebRTC stats, that the
   * mascot video and speech audio are actually leaving the browser. */
  function trackPeerConnections() {
    const Native = g.RTCPeerConnection;
    if (!Native || Native.__cueTracked) return;
    const live = new Set();
    class TrackedPeerConnection extends Native {
      constructor(...args) {
        super(...args);
        live.add(this);
        // Remote audio is what other participants say; Meet never sends Cue's own voice back.
        this.addEventListener('track', (event) => {
          if (event.track.kind === 'audio' && CueFace.onRemoteAudio) CueFace.onRemoteAudio(event.track);
        });
        this.addEventListener('connectionstatechange', () => {
          if (this.connectionState === 'closed') live.delete(this);
        });
      }
    }
    TrackedPeerConnection.__cueTracked = true;
    CueFace.NativeRTCPeerConnection = Native;
    g.RTCPeerConnection = TrackedPeerConnection;
    CueFace.outboundStats = async function outboundStats() {
      const out = { peerConnections: live.size, videoFramesSent: 0, frameWidth: 0, frameHeight: 0, framesPerSecond: 0, audioPacketsSent: 0 };
      for (const pc of live) {
        let report;
        try {
          report = await pc.getStats();
        } catch (_) {
          continue;
        }
        report.forEach((s) => {
          if (s.type !== 'outbound-rtp') return;
          if (s.kind === 'video') {
            out.videoFramesSent += s.framesSent || 0;
            out.frameWidth = Math.max(out.frameWidth, s.frameWidth || 0);
            out.frameHeight = Math.max(out.frameHeight, s.frameHeight || 0);
            out.framesPerSecond = Math.max(out.framesPerSecond, s.framesPerSecond || 0);
          } else if (s.kind === 'audio') {
            out.audioPacketsSent += s.packetsSent || 0;
          }
        });
      }
      return out;
    };
  }

  /* Mixes every remote audio track, downsamples to 16 kHz mono PCM16 and emits ~200 ms chunks as
   * {type: 'audio_in'} for the backend's speech-to-text. A ScriptProcessorNode is used because
   * AudioWorklet modules need a blob or remote URL, and blob-URL workers crash the Meet tab. */
  function listenToMeeting(app, emit) {
    const ctx = app.audio;
    const mix = ctx.createGain();
    const processor = ctx.createScriptProcessor(4096, 1, 1);
    const sink = ctx.createGain();
    sink.gain.value = 0;
    mix.connect(processor);
    processor.connect(sink);
    sink.connect(ctx.destination);
    const ratio = ctx.sampleRate / 16000;
    let chunks = [];
    let length = 0;
    let seq = 0;
    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const n = Math.floor(input.length / ratio);
      const out = new Int16Array(n);
      for (let i = 0; i < n; i++) {
        const a = Math.floor(i * ratio);
        const b = Math.max(a + 1, Math.floor((i + 1) * ratio));
        let sum = 0;
        for (let j = a; j < b; j++) sum += input[j];
        out[i] = Math.max(-1, Math.min(1, sum / (b - a))) * 32767;
      }
      chunks.push(out);
      length += n;
      if (length >= 3200) {
        const joined = new Int16Array(length);
        let offset = 0;
        for (const c of chunks) {
          joined.set(c, offset);
          offset += c.length;
        }
        chunks = [];
        length = 0;
        emit({ type: 'audio_in', seq: seq++, sample_rate: 16000, pcm: CueFace.bytesToBase64(new Uint8Array(joined.buffer)) });
      }
    };
    const seen = new Set();
    return function addTrack(track) {
      if (seen.has(track.id)) return;
      seen.add(track.id);
      const stream = new MediaStream([track]);
      // Chrome only feeds remote WebRTC audio into Web Audio once a media element consumes it.
      const element = new Audio();
      element.muted = true;
      element.srcObject = stream;
      element.play().catch(() => {});
      const source = ctx.createMediaStreamSource(stream);
      source.connect(mix);
      track.addEventListener('ended', () => source.disconnect());
    };
  }

  function bootPage() {
    const params = new URLSearchParams(location.search);
    const canvas = document.getElementById('face');
    const app = new CueFace.FaceApp({
      canvas,
      localAudio: params.get('mute') !== '1',
      captions: params.get('captions') !== '0',
      fps: Number(params.get('fps')) || 60,
    });
    CueFace.app = app;
    g.cueFace = app;

    const fontReady = Promise.race([app.loadFont('url(assets/geist-latin.woff2)'), new Promise((r) => setTimeout(r, 1500))]);
    fontReady.then(() => app.start());

    const unlock = document.getElementById('unlock');
    const refreshUnlock = () => {
      unlock.hidden = app.audio.state === 'running' || params.get('mute') === '1';
    };
    unlock.addEventListener('click', () => app.resumeAudio().then(refreshUnlock));
    app.audio.addEventListener('statechange', refreshUnlock);
    app.resumeAudio().catch(() => {}).finally(refreshUnlock);

    if (params.get('mock') === '1') {
      const mock = new CueFace.MockMeeting(app, { loop: params.get('loop') !== '0' });
      g.cueMock = mock;
      mock.run();
    }
    const ws = params.get('ws');
    if (ws) connect(app, ws);
    if (params.get('debug') === '1') debugHud(app);
  }

  /* WebSocket client with capped exponential backoff. Inbound frames are contract events;
   * outbound frames are speak_started / speak_ended / state_changed / error / ready. */
  function connect(app, url) {
    let delay = 500;
    let socket = null;
    const send = (message) => {
      if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify(message));
    };
    app.on(send);
    const open = () => {
      socket = new WebSocket(url);
      CueFace.socket = socket;
      socket.onopen = () => {
        delay = 500;
        send({ type: 'ready', version: CueFace.version, mode: 'page' });
      };
      socket.onmessage = (message) => {
        if (typeof message.data === 'string') app.dispatch(message.data);
      };
      socket.onclose = () => {
        setTimeout(open, delay);
        delay = Math.min(delay * 2, 8000);
      };
    };
    open();
  }

  function debugHud(app) {
    const pre = document.createElement('pre');
    pre.id = 'debug';
    document.body.appendChild(pre);
    setInterval(() => {
      const s = app.snapshot();
      s.socket = CueFace.socket ? ['connecting', 'open', 'closing', 'closed'][CueFace.socket.readyState] : 'none';
      pre.textContent = JSON.stringify(s, null, 1);
    }, 250);
  }

  CueFace.bootEmbedded = bootEmbedded;
  if (g.__CUE_FACE_EMBED__) bootEmbedded(g.__CUE_FACE_EMBED__);
  else if (typeof document !== 'undefined' && document.getElementById('face')) bootPage();
})(globalThis);
