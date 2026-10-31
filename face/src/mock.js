/* ?mock=1: a scripted meeting that needs no backend. It behaves like a fake backend: every step is
 * a contract event passed to FaceApp.dispatch(), and Cue's "voice" is real audio (an original
 * formant babble synthesised here) sent as base64 WAV `speak` chunks, so the mouth, captions,
 * stop handling and cards all run through the production code path. */
(function (g) {
  'use strict';
  const CueFace = g.CueFace;

  const VOWELS = {
    a: [780, 1240, 2550],
    e: [480, 1900, 2600],
    i: [310, 2250, 3000],
    o: [500, 880, 2450],
    u: [360, 820, 2300],
  };
  const VOWEL_KEYS = Object.keys(VOWELS);
  const RATE = 24000;

  /* Deterministic PRNG so every run of the demo sounds the same. */
  function rng(seed) {
    let s = seed >>> 0 || 1;
    return function () {
      s ^= s << 13;
      s ^= s >>> 17;
      s ^= s << 5;
      return ((s >>> 0) % 100000) / 100000;
    };
  }

  /* Render one phrase of babble that follows the rhythm of `text` (syllables, word gaps, commas). */
  async function synthPhrase(text, seed) {
    const rand = rng(seed);
    const plan = [];
    let t = 0.06;
    const words = text.split(/\s+/).filter(Boolean);
    for (const word of words) {
      const letters = word.replace(/[^a-z]/gi, '');
      const syllables = Math.max(1, Math.round((letters.match(/[aeiouy]+/gi) || []).length * 0.9));
      for (let i = 0; i < syllables; i++) {
        const dur = 0.1 + rand() * 0.09;
        plan.push({ start: t, dur, vowel: VOWEL_KEYS[Math.floor(rand() * VOWEL_KEYS.length)], stress: i === 0 ? 1 : 0.75, consonant: rand() < 0.55 });
        t += dur + 0.012;
      }
      t += /[,;:]$/.test(word) ? 0.22 : /[.!?]$/.test(word) ? 0.3 : 0.045;
    }
    const length = t + 0.12;
    const question = /\?\s*$/.test(text);
    const ctx = new OfflineAudioContext(1, Math.ceil(length * RATE), RATE);

    const out = ctx.createGain();
    out.gain.value = 0.9;
    const lowpass = ctx.createBiquadFilter();
    lowpass.type = 'lowpass';
    lowpass.frequency.value = 4800;
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.ratio.value = 4;
    lowpass.connect(comp).connect(out).connect(ctx.destination);

    // Voiced source: a band-limited sawtooth with gentle vibrato and a falling (or rising) contour.
    const osc = ctx.createOscillator();
    osc.type = 'sawtooth';
    const f0 = 205;
    osc.frequency.setValueAtTime(f0 * 1.04, 0);
    osc.frequency.linearRampToValueAtTime(question ? f0 * 1.22 : f0 * 0.86, length);
    const vib = ctx.createOscillator();
    vib.frequency.value = 5.2;
    const vibDepth = ctx.createGain();
    vibDepth.gain.value = 3.5;
    vib.connect(vibDepth).connect(osc.frequency);

    const voice = ctx.createGain();
    voice.gain.value = 0;
    osc.connect(voice);
    const formants = [0, 1, 2].map((i) => {
      const bp = ctx.createBiquadFilter();
      bp.type = 'bandpass';
      bp.Q.value = [7, 10, 12][i];
      const gain = ctx.createGain();
      gain.gain.value = [1.0, 0.55, 0.25][i];
      voice.connect(bp).connect(gain).connect(lowpass);
      return bp;
    });

    // Unvoiced source for consonant bursts.
    const noiseBuf = ctx.createBuffer(1, Math.ceil(length * RATE), RATE);
    const nd = noiseBuf.getChannelData(0);
    for (let i = 0; i < nd.length; i++) nd[i] = rand() * 2 - 1;
    const noise = ctx.createBufferSource();
    noise.buffer = noiseBuf;
    const hp = ctx.createBiquadFilter();
    hp.type = 'highpass';
    hp.frequency.value = 3200;
    const hiss = ctx.createGain();
    hiss.gain.value = 0;
    noise.connect(hp).connect(hiss).connect(lowpass);

    for (const s of plan) {
      const [f1, f2, f3] = VOWELS[s.vowel];
      formants[0].frequency.setTargetAtTime(f1, s.start, 0.02);
      formants[1].frequency.setTargetAtTime(f2, s.start, 0.02);
      formants[2].frequency.setTargetAtTime(f3, s.start, 0.02);
      const peak = 0.55 * s.stress;
      voice.gain.setTargetAtTime(peak, s.start + 0.01, 0.018);
      voice.gain.setTargetAtTime(peak * 0.7, s.start + s.dur * 0.55, 0.03);
      voice.gain.setTargetAtTime(0.0, s.start + s.dur, 0.018);
      if (s.consonant) {
        hiss.gain.setTargetAtTime(0.12, s.start - 0.01, 0.006);
        hiss.gain.setTargetAtTime(0, s.start + 0.025, 0.008);
      }
    }
    osc.start(0);
    vib.start(0);
    noise.start(0);
    const buffer = await ctx.startRendering();
    return encodeWav(buffer);
  }

  function encodeWav(buffer) {
    const data = buffer.getChannelData(0);
    const bytes = new Uint8Array(44 + data.length * 2);
    const view = new DataView(bytes.buffer);
    const str = (o, s) => {
      for (let i = 0; i < s.length; i++) view.setUint8(o + i, s.charCodeAt(i));
    };
    str(0, 'RIFF');
    view.setUint32(4, 36 + data.length * 2, true);
    str(8, 'WAVE');
    str(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, buffer.sampleRate, true);
    view.setUint32(28, buffer.sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    str(36, 'data');
    view.setUint32(40, data.length * 2, true);
    for (let i = 0; i < data.length; i++) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, data[i])) * 0x7fff, true);
    return CueFace.bytesToBase64(bytes);
  }

  const LINES = {
    ack: 'Sure. I will open an issue in cue api, and assign it to Arjun.',
    approval: 'Posting in a channel needs approval. I sent the request to Priya.',
    failed: 'Linear did not accept the update, the connection expired. I will ask an admin to reconnect it.',
    long: 'One more thing. The staging deploy from yesterday also changed the session timeout, so the two might be related, and I can pull the deploy diff if that helps.',
  };

  class MockMeeting {
    constructor(app, options) {
      this.app = app;
      this.loop = !options || options.loop !== false;
      this.audio = null;
      this.running = false;
      this.counter = 0;
    }

    async prepare() {
      if (this.audio) return;
      const entries = Object.entries(LINES);
      const audio = {};
      let seed = 7;
      for (const [key, text] of entries) {
        // Split into sentences so each utterance streams as several chunks, like real TTS.
        const sentences = text.match(/[^.?!]+[.?!]?/g).map((s) => s.trim()).filter(Boolean);
        audio[key] = { text, chunks: [] };
        for (const sentence of sentences) audio[key].chunks.push(await synthPhrase(sentence, seed++));
      }
      this.audio = audio;
    }

    async run() {
      await this.prepare();
      this.running = true;
      do {
        await this.scene();
      } while (this.running && this.loop);
    }

    stop() {
      this.running = false;
    }

    send(event) {
      if (this.running) this.app.dispatch(event);
    }

    sleep(seconds) {
      return new Promise((resolve) => setTimeout(resolve, seconds * 1000));
    }

    /* Streams an utterance chunk by chunk and resolves when playback ends (or is stopped). */
    speak(key, options) {
      const line = this.audio[key];
      const id = 'mock-' + key + '-' + ++this.counter;
      const done = new Promise((resolve) => {
        const off = this.app.on((msg) => {
          if (msg.type === 'speak_ended' && msg.id === id) {
            off();
            resolve(msg.reason);
          }
        });
      });
      line.chunks.forEach((chunk, seq) => {
        setTimeout(() => {
          this.send({ type: 'speak', id, seq, final: seq === line.chunks.length - 1, format: 'wav', audio: chunk, text: seq === 0 ? line.text : undefined, interrupt: options && options.interrupt });
        }, seq * 350);
      });
      return { id, done };
    }

    async scene() {
      const say = (speaker, text) => this.send({ type: 'caption', speaker, text, final: true });
      this.send({ type: 'state', state: 'listening' });
      await this.sleep(1.2);
      say('Priya', 'Login timeouts on staging are back since this morning.');
      await this.sleep(3.4);
      say('Priya', 'Cue, can you open an issue for it and assign Arjun?');
      await this.sleep(2.6);

      this.send({ type: 'state', state: 'thinking' });
      await this.sleep(2.2);
      this.send({ type: 'state', state: 'talking' });
      await this.speak('ack').done;

      this.send({ type: 'state', state: 'acting' });
      this.send({ type: 'action', id: 'gh-issue', tool: 'github', title: 'Create GitHub issue', detail: 'cue/api · Login timeouts on staging', status: 'running' });
      await this.sleep(2.8);
      this.send({ type: 'action', id: 'gh-issue', tool: 'github', title: 'Created cue/api#142', detail: 'Assigned to Arjun', status: 'done' });
      this.send({ type: 'state', state: 'listening' });
      await this.sleep(2.2);

      say('Arjun', 'Thanks. Can you also post it in #eng-standup?');
      await this.sleep(2.6);
      this.send({ type: 'state', state: 'thinking' });
      await this.sleep(1.6);
      this.send({ type: 'action', id: 'slack-post', tool: 'slack', title: 'Post to #eng-standup', detail: 'Waiting for Priya', status: 'needs_approval' });
      await this.speak('approval').done;
      this.send({ type: 'state', state: 'waiting_approval' });
      await this.sleep(5);

      say('Priya', 'Approved.');
      this.send({ type: 'state', state: 'acting' });
      this.send({ type: 'action', id: 'slack-post', tool: 'slack', title: 'Post to #eng-standup', detail: 'Approved by Priya', status: 'running' });
      await this.sleep(2.2);
      this.send({ type: 'action', id: 'slack-post', tool: 'slack', title: 'Posted to #eng-standup', detail: 'Linked cue/api#142', status: 'done' });
      this.send({ type: 'action', id: 'linear-link', tool: 'linear', title: 'Link Linear ticket ENG-88', detail: 'Add cue/api#142', status: 'running' });
      await this.sleep(2.6);
      this.send({ type: 'action', id: 'linear-link', tool: 'linear', title: 'Link Linear ticket ENG-88', detail: 'Connection expired', status: 'failed' });
      await this.sleep(1.2);
      await this.speak('failed').done;
      this.send({ type: 'state', state: 'listening' });
      await this.sleep(2);

      // Barge-in: a person talks over Cue and the backend sends `stop`.
      const long = this.speak('long');
      await this.sleep(3.2);
      say('Priya', 'Sorry, one sec, quick question...');
      this.send({ type: 'stop', id: long.id });
      this.send({ type: 'state', state: 'listening' });
      await long.done;
      await this.sleep(5);

      for (const id of ['gh-issue', 'slack-post', 'linear-link']) this.send({ type: 'action', id, remove: true });
      this.send({ type: 'caption', text: '' });
      await this.sleep(2.5);
    }
  }

  CueFace.MockMeeting = MockMeeting;
  CueFace.synthPhrase = synthPhrase;
})(globalThis);
