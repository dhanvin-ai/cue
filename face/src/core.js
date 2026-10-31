/* Cue face: shared constants, motion helpers, and the WebSocket event contract.
 * Every face script is a classic script that attaches to globalThis.CueFace, so the same
 * files run in the standalone page and when face_bot.py injects them into Google Meet. */
(function (g) {
  'use strict';
  const CueFace = (g.CueFace = g.CueFace || {});

  CueFace.version = '1.0.0';
  CueFace.W = 1280;
  CueFace.H = 720;
  CueFace.FONT = '"Geist", "Geist Fallback", ui-sans-serif, system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif';

  CueFace.palette = {
    paper: '#fafaf7',
    ink: '#0f100d',
    lime: '#d9f25c',
    limeSoft: '#edf8b0',
    limeInk: '#5b6b0c',
    white: '#ffffff',
    inkMuted: 'rgba(15,16,13,0.58)',
    inkFaint: 'rgba(15,16,13,0.10)',
    headTop: '#2b2d25',
    headBottom: '#0f100d',
    danger: '#b42318',
    dangerSoft: '#fde7e4',
  };

  CueFace.STATES = ['listening', 'thinking', 'talking', 'acting', 'waiting_approval'];
  CueFace.ACTION_STATUSES = ['running', 'done', 'failed', 'needs_approval'];

  const STATE_ALIASES = {
    idle: 'listening',
    listen: 'listening',
    think: 'thinking',
    speaking: 'talking',
    talk: 'talking',
    act: 'acting',
    working: 'acting',
    approval: 'waiting_approval',
    waiting: 'waiting_approval',
    awaiting_approval: 'waiting_approval',
    waiting_for_approval: 'waiting_approval',
  };

  const STATUS_ALIASES = {
    pending: 'running',
    in_progress: 'running',
    success: 'done',
    succeeded: 'done',
    completed: 'done',
    error: 'failed',
    approval: 'needs_approval',
    awaiting_approval: 'needs_approval',
    waiting_approval: 'needs_approval',
  };

  function text(value, max) {
    if (value === undefined || value === null) return '';
    const s = String(value).replace(/\s+/g, ' ').trim();
    return max && s.length > max ? s.slice(0, max - 1) + '…' : s;
  }

  function contractError(message) {
    const error = new Error(message);
    error.name = 'ContractError';
    return error;
  }

  /* Validate and normalise one inbound event. Throws ContractError for events the face cannot
   * act on; unknown fields are ignored so the backend can add metadata freely. */
  CueFace.normalizeEvent = function normalizeEvent(raw) {
    let event = raw;
    if (typeof raw === 'string') {
      try {
        event = JSON.parse(raw);
      } catch (_) {
        throw contractError('Event is not valid JSON');
      }
    }
    if (!event || typeof event !== 'object' || Array.isArray(event)) throw contractError('Event must be an object');
    const type = String(event.type || '').toLowerCase();

    if (type === 'state') {
      const requested = String(event.state || '').toLowerCase();
      const state = STATE_ALIASES[requested] || requested;
      if (!CueFace.STATES.includes(state)) throw contractError('Unknown state: ' + requested);
      return { type, state };
    }

    if (type === 'speak') {
      const hasAudio = typeof event.audio === 'string' && event.audio.length > 0;
      const hasUrl = typeof event.audio_url === 'string' && event.audio_url.length > 0;
      const final = event.final === undefined ? true : Boolean(event.final);
      if (!hasAudio && !hasUrl && !final) throw contractError('speak needs audio or audio_url');
      const format = String(event.format || (hasUrl ? 'auto' : 'wav')).toLowerCase();
      const sampleRate = Number(event.sample_rate || 24000);
      const channels = Number(event.channels || 1);
      if (format === 'pcm_s16le' && (!(sampleRate >= 8000 && sampleRate <= 96000) || !(channels >= 1 && channels <= 2))) {
        throw contractError('pcm_s16le needs a valid sample_rate and channels');
      }
      return {
        type,
        id: text(event.id || event.utterance_id || 'utterance', 120),
        audio: hasAudio ? event.audio : null,
        audioUrl: hasUrl ? event.audio_url : null,
        format,
        sampleRate,
        channels,
        seq: Number.isInteger(event.seq) ? event.seq : null,
        final,
        interrupt: Boolean(event.interrupt),
        text: text(event.text, 600),
        caption: event.caption === undefined ? null : Boolean(event.caption),
      };
    }

    if (type === 'stop') {
      return { type, id: event.id ? text(event.id, 120) : null };
    }

    if (type === 'action') {
      const id = text(event.id, 120);
      if (!id) throw contractError('action needs an id');
      if (event.remove === true) return { type, id, remove: true };
      const requested = String(event.status || 'running').toLowerCase();
      const status = STATUS_ALIASES[requested] || requested;
      if (!CueFace.ACTION_STATUSES.includes(status)) throw contractError('Unknown action status: ' + requested);
      return {
        type,
        id,
        remove: false,
        status,
        title: text(event.title || event.name || 'Action', 80),
        detail: text(event.detail || event.description || '', 120),
        tool: text(event.tool || event.provider || '', 24).toLowerCase(),
      };
    }

    if (type === 'caption') {
      return {
        type,
        text: text(event.text, 400),
        speaker: text(event.speaker || 'Cue', 40),
        final: event.final === undefined ? true : Boolean(event.final),
      };
    }

    throw contractError('Unknown event type: ' + (type || '(missing)'));
  };

  /* Damped spring used for every animated value. Integrated with semi-implicit Euler at a fixed
   * sub-step so motion stays identical at 30 and 60 fps and never explodes on a long frame. */
  class Spring {
    constructor(value, stiffness, damping) {
      this.value = value;
      this.target = value;
      this.velocity = 0;
      this.stiffness = stiffness || 170;
      this.damping = damping || 26;
    }
    set(target) {
      this.target = target;
      return this;
    }
    snap(value) {
      this.value = this.target = value;
      this.velocity = 0;
      return this;
    }
    update(dt) {
      let remaining = Math.min(dt, 0.1);
      while (remaining > 1e-6) {
        const h = Math.min(remaining, 1 / 240);
        const force = this.stiffness * (this.target - this.value) - this.damping * this.velocity;
        this.velocity += force * h;
        this.value += this.velocity * h;
        remaining -= h;
      }
      return this.value;
    }
  }
  CueFace.Spring = Spring;

  /* Smooth 1D value noise for organic drift (head sway, eye wander). */
  function hash(n) {
    const s = Math.sin(n * 127.1 + 311.7) * 43758.5453;
    return s - Math.floor(s);
  }
  CueFace.noise = function noise(x, seed) {
    const i = Math.floor(x);
    const f = x - i;
    const u = f * f * (3 - 2 * f);
    const o = (seed || 0) * 17.13;
    return (hash(i + o) * (1 - u) + hash(i + 1 + o) * u) * 2 - 1;
  };

  CueFace.clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  CueFace.lerp = (a, b, t) => a + (b - a) * t;
  CueFace.easeOutCubic = (t) => 1 - Math.pow(1 - CueFace.clamp(t, 0, 1), 3);
  CueFace.easeInOut = (t) => {
    const x = CueFace.clamp(t, 0, 1);
    return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  };
  CueFace.easeOutBack = (t) => {
    const x = CueFace.clamp(t, 0, 1);
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
  };

  CueFace.roundRect = function roundRect(ctx, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
  };

  /* Draws the CUE mark: the open "C" stroke with the lime dot in its mouth (32x32 source box). */
  CueFace.drawMark = function drawMark(ctx, x, y, size, ink, dot) {
    const s = size / 32;
    ctx.save();
    ctx.translate(x, y);
    ctx.scale(s, s);
    ctx.lineCap = 'round';
    ctx.lineWidth = 4.2;
    ctx.strokeStyle = ink;
    ctx.beginPath();
    ctx.arc(16, 16, 10, -0.75, 0.75, true);
    ctx.stroke();
    ctx.fillStyle = dot;
    ctx.beginPath();
    ctx.arc(24.2, 16, 3.4, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
  };

  /* Wraps text to at most maxLines lines, keeping the end of the text (newest words). */
  CueFace.wrapText = function wrapText(ctx, value, maxWidth, maxLines) {
    const words = String(value).split(' ').filter(Boolean);
    const lines = [];
    let line = '';
    for (const word of words) {
      const next = line ? line + ' ' + word : word;
      if (ctx.measureText(next).width <= maxWidth || !line) {
        line = next;
      } else {
        lines.push(line);
        line = word;
      }
    }
    if (line) lines.push(line);
    return lines.slice(-maxLines);
  };

  CueFace.ellipsize = function ellipsize(ctx, value, maxWidth) {
    if (ctx.measureText(value).width <= maxWidth) return value;
    let s = value;
    while (s.length > 1 && ctx.measureText(s + '…').width > maxWidth) s = s.slice(0, -1);
    return s.trimEnd() + '…';
  };

  CueFace.base64ToBytes = function base64ToBytes(b64) {
    const clean = b64.includes(',') && b64.startsWith('data:') ? b64.slice(b64.indexOf(',') + 1) : b64;
    const bin = atob(clean);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return bytes;
  };

  CueFace.bytesToBase64 = function bytesToBase64(bytes) {
    let bin = '';
    const step = 0x8000;
    for (let i = 0; i < bytes.length; i += step) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + step));
    return btoa(bin);
  };
})(globalThis);
