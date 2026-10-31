/* FaceApp wires the pieces together: one 1280x720 canvas, one AudioContext, the speech engine,
 * the mascot and the overlay. dispatch() is the single entry point for the WebSocket contract;
 * the standalone page, the mock meeting and face_bot.py all feed events through it. */
(function (g) {
  'use strict';
  const CueFace = g.CueFace;

  class FaceApp {
    constructor(options) {
      const opts = options || {};
      this.fps = opts.fps || 30;
      // 'worker' (default) or 'timer'. Blob-URL workers crash the renderer inside Google Meet, so the
      // bot uses a main-thread timer; it launches Chrome with background throttling disabled.
      this.watchdog = opts.watchdog || 'worker';
      this.listeners = new Set();
      if (opts.onEmit) this.listeners.add(opts.onEmit);
      this.canvas = opts.canvas || document.createElement('canvas');
      this.canvas.width = CueFace.W;
      this.canvas.height = CueFace.H;
      this.ctx = this.canvas.getContext('2d', { alpha: false });
      this.audio = opts.audioContext || new AudioContext({ latencyHint: 'interactive' });
      this.speech = new CueFace.SpeechEngine(this.audio, {
        localOutput: Boolean(opts.localAudio),
        onEvent: (event) => this._onSpeech(event),
      });
      this.mascot = new CueFace.Mascot();
      this.overlay = new CueFace.Overlay({ captions: opts.captions !== false });
      this.baseState = 'listening';
      this.displayState = 'listening';
      this.clock = 0;
      this.last = null;
      this.lastDraw = -1;
      this.frames = 0;
      this.running = false;
      this.stats = { events: 0, rejected: 0, lastError: null };
      this.videoStream = null;
      this.stopProbe = null;
      this.lastStopMs = null;
      this.captionsForSpeech = new Map(); // utterance id -> text, shown when its audio starts
    }

    start() {
      if (this.running) return this;
      this.running = true;
      this._render(0);
      this._schedule();
      return this;
    }

    stopLoop() {
      this.running = false;
      if (this._worker) this._worker.terminate();
      if (this._timer) clearInterval(this._timer);
      this._worker = null;
      this._timer = null;
    }

    /* A MediaStream carrying the canvas video and the speech audio: the bot's camera and mic. */
    mediaStream() {
      if (!this.videoStream) this.videoStream = this.canvas.captureStream(this.fps);
      return new MediaStream([...this.videoStream.getVideoTracks(), ...this.speech.stream.getAudioTracks()]);
    }

    /* Subscribe to outbound messages (speak_started, speak_ended, state_changed, error). */
    on(listener) {
      this.listeners.add(listener);
      return () => this.listeners.delete(listener);
    }

    _emit(message) {
      for (const listener of this.listeners) {
        try {
          listener(message);
        } catch (error) {
          console.error('[cue-face] listener failed', error);
        }
      }
    }

    resumeAudio() {
      if (this.audio.state !== 'running') return this.audio.resume();
      return Promise.resolve();
    }

    /* Apply one contract event. Returns true when accepted, false when rejected. */
    dispatch(raw) {
      let event;
      try {
        event = CueFace.normalizeEvent(raw);
      } catch (error) {
        this.stats.rejected += 1;
        this.stats.lastError = error.message;
        this._emit({ type: 'error', message: error.message });
        return false;
      }
      this.stats.events += 1;
      const t = this.clock;
      switch (event.type) {
        case 'state':
          this.baseState = event.state;
          break;
        case 'speak':
          this.resumeAudio();
          if (event.caption !== false && event.text && this.overlay.captionsEnabled) this.captionsForSpeech.set(event.id, event.text);
          this.speech.enqueue(event);
          break;
        case 'stop':
          if (this.speech.speaking) this.stopProbe = performance.now();
          this.speech.stop(event.id, 'stopped');
          break;
        case 'action': {
          const previous = this.overlay.upsertCard(event, t);
          if (!event.remove && previous !== event.status) {
            if (event.status === 'done') this.mascot.react('joy', t);
            if (event.status === 'failed') this.mascot.react('oops', t);
          }
          break;
        }
        case 'caption':
          this.overlay.setCaption(event, t);
          break;
      }
      this._syncState();
      return true;
    }

    _onSpeech(event) {
      if (event.type === 'speak_started') {
        const text = this.captionsForSpeech.get(event.id);
        if (text) this.overlay.setCaption({ text, speaker: 'Cue', final: true }, this.clock);
      }
      if (event.type === 'speak_ended') {
        this.captionsForSpeech.delete(event.id);
        // The backend's "talking" state belongs to the utterance that just finished.
        if (this.baseState === 'talking' && !this.speech.speaking) this.baseState = 'listening';
      }
      this._syncState();
      this._emit(event);
    }

    _syncState() {
      // Real speech always shows as talking; otherwise show what the backend last asked for.
      const next = this.speech.speaking ? 'talking' : this.baseState;
      if (next !== this.displayState) {
        this.displayState = next;
        this._emit({ type: 'state_changed', state: next });
      }
      this.mascot.setState(next, this.clock);
      this.overlay.setStatus(next, this.clock);
    }

    _schedule() {
      // rAF gives the smoothest frames, but Chromium throttles it for hidden or occluded windows
      // even when visibilityState says "visible". A worker timer (not throttled) acts as a
      // watchdog and renders whenever rAF has gone quiet, so the camera feed never freezes.
      const raf = (now) => {
        if (!this.running) return;
        this.lastRaf = performance.now();
        this._tick(now);
        requestAnimationFrame(raf);
      };
      requestAnimationFrame(raf);
      const period = Math.round(1000 / this.fps);
      const check = () => {
        const now = performance.now();
        if (this.running && now - (this.lastRaf || 0) > period * 2.5) this._tick(now);
      };
      if (this.watchdog === 'timer') {
        this._timer = setInterval(check, period);
        return;
      }
      const src = 'setInterval(function(){postMessage(0)},' + period + ')';
      try {
        this._worker = new Worker(URL.createObjectURL(new Blob([src], { type: 'text/javascript' })));
        this._worker.onmessage = check;
      } catch (_) {
        this._worker = null; // CSP may forbid blob workers on some hosts; rAF alone still works
      }
    }

    _tick(now) {
      if (this.last === null) this.last = now;
      const elapsed = (now - this.last) / 1000;
      // Cap at the stream frame rate: smoother capture and half the CPU of 60 fps.
      if (elapsed < 1 / (this.fps + 2)) return;
      this.last = now;
      this._render(Math.min(elapsed, 0.1));
    }

    _render(dt) {
      this.clock += dt;
      const t = this.clock;
      const metrics = this.speech.sample();
      if (this.stopProbe !== null && this.speech.analyserRms() < 0.001) {
        // Frame-granular upper bound on how long `stop` took to reach silence.
        this.lastStopMs = Math.round(performance.now() - this.stopProbe);
        this.stopProbe = null;
      }
      this.mascot.setLayout(this.overlay.hasCards);
      this.mascot.update(dt, t, metrics, this.speech.speaking);
      this.overlay.update(dt, t);
      const ctx = this.ctx;
      this.overlay.drawBackground(ctx);
      this.mascot.draw(ctx, t);
      this.overlay.drawCards(ctx, t);
      this.overlay.drawBadge(ctx);
      this.overlay.drawStatus(ctx, this.mascot.x, t, this.mascot.env);
      this.overlay.drawCaption(ctx, t);
      this.frames += 1;
    }

    snapshot() {
      return {
        state: this.displayState,
        baseState: this.baseState,
        speaking: this.speech.speaking,
        mouth: Number(this.mascot.env.toFixed(3)),
        rms: Number(this.speech.metrics.rms.toFixed(4)),
        cards: this.overlay.cards.filter((c) => !c.leaving).map((c) => ({ id: c.id, status: c.status, title: c.title })),
        caption: this.overlay.caption ? this.overlay.caption.text : null,
        frames: this.frames,
        audio: this.audio.state,
        events: this.stats.events,
        rejected: this.stats.rejected,
        lastStopMs: this.lastStopMs,
      };
    }

    async loadFont(source) {
      if (typeof FontFace === 'undefined' || !source) return false;
      try {
        const face = new FontFace('Geist', source, { weight: '100 900', style: 'normal' });
        await face.load();
        document.fonts.add(face);
        return true;
      } catch (_) {
        return false; // system fallback font is fine
      }
    }
  }

  CueFace.FaceApp = FaceApp;
})(globalThis);
