/* Speech playback. Every utterance runs through its own GainNode into a shared bus:
 *   utterance gain -> bus -> AnalyserNode -> MediaStreamDestination (the meeting microphone)
 *                                        \-> ctx.destination        (standalone page only)
 * The AnalyserNode reads the exact samples the meeting hears, so the mouth follows the real audio. */
(function (g) {
  'use strict';
  const CueFace = g.CueFace;

  const STOP_FADE = 0.012; // seconds; short enough to stay far inside the 200 ms budget, long enough to avoid a click
  const START_LEAD = 0.04; // scheduling headroom for the first chunk of an utterance

  class SpeechEngine {
    constructor(ctx, options) {
      const opts = options || {};
      this.ctx = ctx;
      this.onEvent = opts.onEvent || function () {};
      this.bus = ctx.createGain();
      this.analyser = ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.smoothingTimeConstant = 0;
      this.destination = ctx.createMediaStreamDestination();
      this.bus.connect(this.analyser);
      this.analyser.connect(this.destination);
      if (opts.localOutput) this.analyser.connect(ctx.destination);

      this.time = new Float32Array(this.analyser.fftSize);
      this.freq = new Uint8Array(this.analyser.frequencyBinCount);
      this.queue = []; // utterances waiting to play, in order
      this.active = null;
      this.byId = new Map();
      this.cancelled = new Set();
      this.metrics = { rms: 0, low: 0, high: 0 };
    }

    get stream() {
      return this.destination.stream;
    }

    /* True from the first scheduled chunk until the utterance completes or is stopped, including
     * short gaps while a streamed chunk is still arriving. */
    get speaking() {
      return Boolean(this.active && this.active.started && !this.active.done);
    }

    /* Accepts one normalised `speak` event (one chunk). Chunks with the same id form an utterance. */
    enqueue(event) {
      if (this.cancelled.has(event.id)) return; // late chunk of an utterance that was stopped
      let utt = this.byId.get(event.id);
      if (!utt) {
        if (event.interrupt) this.stop(null, 'interrupted');
        utt = {
          id: event.id,
          text: event.text,
          chunks: new Map(),
          nextSeq: 0,
          autoSeq: 0,
          finalSeq: null,
          scheduledUntil: 0,
          sources: new Set(),
          gain: null,
          started: false,
          done: false,
        };
        this.byId.set(utt.id, utt);
        this.queue.push(utt);
      }
      if (event.text && !utt.text) utt.text = event.text;
      const seq = event.seq === null ? utt.autoSeq : event.seq;
      utt.autoSeq = Math.max(utt.autoSeq, seq + 1);
      if (event.final) utt.finalSeq = seq;
      if (!event.audio && !event.audioUrl) {
        utt.chunks.set(seq, null); // a pure "final" marker with no audio
        this._pump();
        return;
      }
      const pending = { buffer: undefined };
      utt.chunks.set(seq, pending);
      this._decode(event)
        .then((buffer) => {
          pending.buffer = buffer;
          this._pump();
        })
        .catch((error) => {
          pending.buffer = null;
          this.onEvent({ type: 'error', id: utt.id, message: 'Could not decode audio: ' + error.message });
          this._pump();
        });
    }

    /* Stops one utterance (or everything when id is null) within one short fade. */
    stop(id, reason) {
      const why = reason || 'stopped';
      const targets = id ? [this.byId.get(id)].filter(Boolean) : Array.from(this.byId.values());
      if (id && targets.length === 0) this._rememberCancelled(id);
      for (const utt of targets) this._finish(utt, why);
      this._advance();
    }

    /* RMS of whatever is on the bus right now, regardless of utterance bookkeeping. */
    analyserRms() {
      this.analyser.getFloatTimeDomainData(this.time);
      let sum = 0;
      for (let i = 0; i < this.time.length; i++) sum += this.time[i] * this.time[i];
      return Math.sqrt(sum / this.time.length);
    }

    /* Called once per rendered frame: RMS from the time domain, plus low/high band energy that the
     * mascot uses to round or widen the mouth. */
    sample() {
      if (!this.active || this.active.sources.size === 0) {
        this.metrics.rms = 0;
        this.metrics.low = 0;
        this.metrics.high = 0;
        return this.metrics;
      }
      this.metrics.rms = this.analyserRms();
      this.analyser.getByteFrequencyData(this.freq);
      const hz = this.ctx.sampleRate / this.analyser.fftSize;
      this.metrics.low = band(this.freq, hz, 250, 900);
      this.metrics.high = band(this.freq, hz, 1800, 5000);
      return this.metrics;
    }

    async _decode(event) {
      let bytes;
      if (event.audioUrl) {
        const response = await fetch(event.audioUrl);
        if (!response.ok) throw new Error('HTTP ' + response.status);
        bytes = new Uint8Array(await response.arrayBuffer());
      } else {
        bytes = CueFace.base64ToBytes(event.audio);
      }
      if (event.format === 'pcm_s16le') return this._pcm(bytes, event.sampleRate, event.channels);
      // decodeAudioData detaches its input, so hand it a private copy.
      return await this.ctx.decodeAudioData(bytes.slice().buffer);
    }

    _pcm(bytes, sampleRate, channels) {
      const frames = Math.floor(bytes.byteLength / 2 / channels);
      if (frames === 0) throw new Error('empty PCM chunk');
      const view = new DataView(bytes.buffer, bytes.byteOffset, frames * 2 * channels);
      const buffer = this.ctx.createBuffer(channels, frames, sampleRate);
      for (let c = 0; c < channels; c++) {
        const out = buffer.getChannelData(c);
        for (let i = 0; i < frames; i++) out[i] = view.getInt16((i * channels + c) * 2, true) / 32768;
      }
      return buffer;
    }

    _pump() {
      if (!this.active) this._advance();
      const utt = this.active;
      if (!utt || utt.done) return;
      // Schedule every decoded chunk that is next in sequence; wait on gaps.
      while (utt.chunks.has(utt.nextSeq)) {
        const chunk = utt.chunks.get(utt.nextSeq);
        if (chunk && chunk.buffer === undefined) break; // still decoding
        utt.chunks.delete(utt.nextSeq);
        utt.nextSeq += 1;
        if (chunk && chunk.buffer) this._schedule(utt, chunk.buffer);
      }
      this._maybeComplete(utt);
    }

    _schedule(utt, buffer) {
      const ctx = this.ctx;
      if (!utt.gain) {
        utt.gain = ctx.createGain();
        utt.gain.connect(this.bus);
      }
      const now = ctx.currentTime;
      const at = Math.max(utt.scheduledUntil, now + (utt.started ? 0.005 : START_LEAD));
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(utt.gain);
      source.onended = () => {
        utt.sources.delete(source);
        source.disconnect();
        this._maybeComplete(utt);
      };
      source.start(at);
      utt.sources.add(source);
      utt.scheduledUntil = at + buffer.duration;
      if (!utt.started) {
        utt.started = true;
        this.onEvent({ type: 'speak_started', id: utt.id, text: utt.text });
      }
    }

    _maybeComplete(utt) {
      if (utt.done || utt !== this.active) return;
      const allArrived = utt.finalSeq !== null && utt.nextSeq > utt.finalSeq;
      if (allArrived && utt.sources.size === 0) {
        this._finish(utt, 'completed');
        this._advance();
      }
    }

    _finish(utt, reason) {
      if (utt.done) return;
      utt.done = true;
      this.byId.delete(utt.id);
      this.queue = this.queue.filter((u) => u !== utt);
      if (reason !== 'completed') this._rememberCancelled(utt.id);
      const now = this.ctx.currentTime;
      if (utt.gain) {
        const gain = utt.gain.gain;
        gain.cancelScheduledValues(now);
        gain.setValueAtTime(gain.value, now);
        gain.linearRampToValueAtTime(0, now + STOP_FADE);
      }
      for (const source of utt.sources) {
        source.onended = null;
        try {
          source.stop(now + STOP_FADE + 0.002);
        } catch (_) {
          /* already stopped */
        }
      }
      const sources = Array.from(utt.sources);
      const gainNode = utt.gain;
      utt.sources.clear();
      setTimeout(() => {
        for (const s of sources) s.disconnect();
        if (gainNode) gainNode.disconnect();
      }, 60);
      if (this.active === utt) this.active = null;
      if (utt.started || reason !== 'completed') {
        this.onEvent({ type: 'speak_ended', id: utt.id, reason });
      }
    }

    _advance() {
      if (this.active && !this.active.done) return;
      this.active = this.queue.find((u) => !u.done) || null;
      if (this.active) this._pump();
    }

    _rememberCancelled(id) {
      this.cancelled.add(id);
      if (this.cancelled.size > 256) this.cancelled.delete(this.cancelled.values().next().value);
    }
  }

  function band(freq, hz, lo, hi) {
    const a = Math.max(1, Math.floor(lo / hz));
    const b = Math.min(freq.length - 1, Math.ceil(hi / hz));
    let sum = 0;
    for (let i = a; i <= b; i++) sum += freq[i];
    return sum / ((b - a + 1) * 255);
  }

  CueFace.SpeechEngine = SpeechEngine;
})(globalThis);
