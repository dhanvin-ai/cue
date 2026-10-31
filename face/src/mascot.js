/* The Cue mascot: an ink "pebble" head inside the open C of the CUE mark, with the lime dot in the
 * C's mouth. Every feature is a spring, so state changes blend instead of snapping, and a few
 * procedural layers (breathing, blinks, saccades, nods) keep it alive between events. */
(function (g) {
  'use strict';
  const CueFace = g.CueFace;
  const { Spring, noise, clamp, lerp, palette: P } = CueFace;
  const TAU = Math.PI * 2;

  const HEAD_W = 300;
  const HEAD_H = 272;
  const RING_R = 226;
  const GAP = 0.5; // half-angle of the C's opening, radians
  const BASE_Y = 318;

  /* Per-state expression targets. lookX/lookY are eye directions in -1..1. */
  const POSES = {
    listening: { smile: 0.34, mouthWidth: 0.5, eyeScale: 1, squint: 0.06, browY: 0, browTilt: 0, browAsym: 0, ring: 0.1, ringLime: 0, spin: 0, ringAngle: 0, dotLift: 0, dotSize: 1, glow: 0.35, mouthShift: 0 },
    thinking: { smile: -0.02, mouthWidth: 0.3, eyeScale: 0.96, squint: 0.28, browY: 0.25, browTilt: 0, browAsym: 0.55, ring: 0.62, ringLime: 0, spin: 2.1, ringAngle: 0, dotLift: 0, dotSize: 0.9, glow: 0.25, mouthShift: 0.45 },
    talking: { smile: 0.22, mouthWidth: 0.55, eyeScale: 1.03, squint: 0.04, browY: 0.12, browTilt: 0, browAsym: 0, ring: 0.14, ringLime: 0, spin: 0, ringAngle: 0, dotLift: 0, dotSize: 1, glow: 0.55, mouthShift: 0 },
    acting: { smile: 0.06, mouthWidth: 0.42, eyeScale: 0.98, squint: 0.36, browY: -0.25, browTilt: -0.22, browAsym: 0, ring: 0.9, ringLime: 1, spin: 4.2, ringAngle: 0, dotLift: 0, dotSize: 0.85, glow: 0.45, mouthShift: 0.12 },
    waiting_approval: { smile: 0.2, mouthWidth: 0.16, eyeScale: 1.13, squint: 0, browY: 0.55, browTilt: 0.42, browAsym: 0, ring: 0.26, ringLime: 0, spin: 0, ringAngle: -0.62, dotLift: 1, dotSize: 1.28, glow: 0.6, mouthShift: 0, open: 0.16 },
  };

  class Mascot {
    constructor() {
      const S = (v, k, d) => new Spring(v, k, d);
      this.state = 'listening';
      this.stateSince = 0;
      this.s = {
        x: S(CueFace.W / 2, 42, 13),
        bob: S(0, 150, 13),
        tilt: S(0, 70, 12),
        squash: S(1, 260, 15),
        lookX: S(0, 210, 22),
        lookY: S(0, 210, 22),
        eyeScale: S(1, 170, 15),
        squint: S(0, 140, 19),
        joy: S(0, 120, 16),
        browY: S(0, 170, 15),
        browTilt: S(0, 150, 16),
        browAsym: S(0, 150, 16),
        smile: S(0.34, 150, 17),
        mouthWidth: S(0.5, 190, 19),
        mouthShift: S(0, 120, 17),
        mouthRest: S(0, 260, 26),
        ring: S(0.1, 70, 14),
        ringLime: S(0, 60, 14),
        dotLift: S(0, 90, 11),
        dotSize: S(1, 160, 12),
        glow: S(0.35, 40, 12),
      };
      this.rot = 0;
      this.rotVel = 0;
      this.spinTarget = 0;
      this.ringAngle = 0;
      this.env = 0; // audio envelope 0..1
      this.peak = 0.05;
      this.bright = 0;
      this.shape = 0.5; // 0 round (oo) .. 1 wide (ee)
      this.blink = 0;
      this.nextBlink = 1.5;
      this.blinkStart = -1;
      this.doubleBlink = false;
      this.nextSaccade = 0.6;
      this.gaze = { x: 0, y: 0 };
      this.nextNod = 4;
      this.reaction = null;
      this.cardsVisible = false;
      this.prevEnv = 0;
      this.apply('listening', 0);
    }

    setState(state, t) {
      if (state === this.state) return;
      this.state = state;
      this.stateSince = t;
      this.apply(state, t);
      this.nextSaccade = t + 0.05;
      // A small physical cue sells each transition.
      if (state === 'thinking') this.s.bob.velocity -= 40;
      if (state === 'waiting_approval') this.s.bob.velocity -= 90;
      if (state === 'acting') this.s.squash.velocity += 0.5;
      if (state === 'talking') this.s.browY.velocity += 3;
    }

    apply(state) {
      const pose = POSES[state];
      for (const key of ['smile', 'mouthWidth', 'eyeScale', 'squint', 'browY', 'browTilt', 'browAsym', 'ring', 'ringLime', 'dotLift', 'dotSize', 'glow', 'mouthShift']) {
        this.s[key].set(pose[key]);
      }
      this.spinTarget = pose.spin;
      this.ringAngle = pose.ringAngle;
    }

    /* Short emotional beats layered over the current state: 'joy' after an action succeeds,
     * 'oops' after one fails. */
    react(kind, t) {
      this.reaction = { kind, until: t + (kind === 'joy' ? 1.3 : 1.5), start: t };
      if (kind === 'joy') {
        this.s.bob.velocity -= 120;
        this.s.squash.velocity -= 0.9;
      } else if (kind === 'oops') {
        this.s.tilt.velocity += 1.6;
      }
    }

    setLayout(cardsVisible) {
      this.cardsVisible = cardsVisible;
      this.s.x.set(cardsVisible ? 430 : CueFace.W / 2);
    }

    get x() {
      return this.s.x.value;
    }

    /* metrics: { rms, low, high } sampled from the AnalyserNode this frame. */
    update(dt, t, metrics, speaking) {
      const s = this.s;
      this._audio(dt, metrics, speaking);
      this._blink(t);
      this._gaze(t);
      this._idle(dt, t);
      this._reaction(t);
      for (const key in s) s[key].update(dt);
      this._ring(dt);
    }

    _audio(dt, m, speaking) {
      // Adaptive normalisation: track a slowly decaying peak so quiet and loud TTS both read well.
      const rms = speaking ? m.rms : 0;
      this.peak = Math.max(rms, this.peak * Math.exp(-dt / 2.5), 0.035);
      const gate = 0.012;
      const level = clamp((rms - gate) / (this.peak * 0.8 - gate), 0, 1);
      const shaped = Math.pow(level, 0.75);
      // Fast attack, slower release: lips snap open on a syllable and relax between them.
      const tau = shaped > this.env ? 0.016 : 0.075;
      this.prevEnv = this.env;
      this.env += (shaped - this.env) * (1 - Math.exp(-dt / tau));
      if (this.env < 0.002) this.env = 0;
      // Spectral balance drives mouth shape: more highs = wider "ee", more lows = rounder "oo".
      const total = m.low + m.high + 1e-4;
      const wide = clamp((m.high / total - 0.18) * 2.4, 0, 1);
      this.shape += ((speaking ? wide : 0.5) - this.shape) * (1 - Math.exp(-dt / 0.06));
      this.bright += ((speaking ? this.env : 0) - this.bright) * (1 - Math.exp(-dt / 0.12));
      // Brows pop on syllable onsets.
      if (speaking && this.env - this.prevEnv > 0.18) this.s.browY.velocity += 2.2;
    }

    _blink(t) {
      if (this.blinkStart < 0 && t >= this.nextBlink) {
        this.blinkStart = t;
        this.doubleBlink = Math.random() < 0.18;
      }
      if (this.blinkStart >= 0) {
        const d = this.doubleBlink ? 0.36 : 0.17;
        const p = (t - this.blinkStart) / d;
        if (p >= 1) {
          this.blinkStart = -1;
          this.blink = 0;
          const base = this.state === 'thinking' ? 4.2 : this.state === 'acting' ? 3.6 : 2.8;
          this.nextBlink = t + base * (0.55 + Math.random() * 0.9);
        } else {
          const local = this.doubleBlink ? (p < 0.5 ? p * 2 : (p - 0.5) * 2) : p;
          // Close quickly, open a little slower.
          this.blink = local < 0.38 ? local / 0.38 : 1 - (local - 0.38) / 0.62;
          this.blink = CueFace.easeInOut(this.blink);
        }
      }
    }

    _gaze(t) {
      if (t < this.nextSaccade) return;
      const r = Math.random;
      let x = 0;
      let y = 0;
      let hold = 1.2 + r() * 2.2;
      switch (this.state) {
        case 'thinking':
          x = 0.5 + (r() - 0.5) * 0.35;
          y = -0.6 + (r() - 0.5) * 0.2;
          hold = 0.8 + r() * 1.2;
          break;
        case 'talking':
          x = (r() - 0.5) * 0.18;
          y = (r() - 0.5) * 0.12;
          hold = 0.5 + r() * 1.1;
          break;
        case 'acting':
          x = this.cardsVisible ? 0.62 + (r() - 0.5) * 0.12 : 0.15;
          y = this.cardsVisible ? -0.05 + r() * 0.3 : 0.35;
          hold = 0.6 + r() * 0.9;
          break;
        case 'waiting_approval': {
          const lookAtCard = this.cardsVisible && this.gaze.x < 0.3 && r() < 0.45;
          x = lookAtCard ? 0.6 : (r() - 0.5) * 0.1;
          y = lookAtCard ? 0.05 : -0.05;
          hold = lookAtCard ? 0.7 : 1.4 + r();
          break;
        }
        default:
          if (r() < 0.45) {
            x = 0;
            y = 0;
          } else {
            x = (r() - 0.5) * 0.8;
            y = (r() - 0.5) * 0.4;
          }
      }
      this.gaze = { x, y };
      this.s.lookX.set(x);
      this.s.lookY.set(y);
      this.nextSaccade = t + hold;
      // Big gaze shifts usually come with a blink.
      if (Math.abs(x - this.s.lookX.value) > 0.45 && this.blinkStart < 0 && Math.random() < 0.5) this.nextBlink = t;
    }

    _idle(dt, t) {
      const s = this.s;
      const state = this.state;
      const breathe = Math.sin(t * 1.7) * 0.012;
      let bob = Math.sin(t * 1.15) * 5 + noise(t * 0.4, 3) * 3;
      let tilt = noise(t * 0.22, 1) * 0.035;
      let squash = 1 + breathe;

      if (state === 'listening' && t >= this.nextNod) {
        s.bob.velocity += 70; // an "mm-hm" nod
        s.tilt.velocity += (Math.random() - 0.5) * 0.4;
        this.nextNod = t + 5 + Math.random() * 5;
      }
      if (state === 'thinking') tilt += 0.07;
      if (state === 'talking') {
        bob -= this.env * 7;
        squash += this.env * 0.018;
        tilt += noise(t * 0.9, 7) * 0.025;
      }
      if (state === 'acting') {
        tilt += this.cardsVisible ? 0.05 : 0;
        bob += Math.sin(t * 3.2) * 1.5;
      }
      if (state === 'waiting_approval') {
        tilt = 0.08 + Math.sin(t * 1.4) * 0.035;
        bob = Math.sin(t * 2.1) * 6;
      }
      s.bob.set(bob);
      s.tilt.set(tilt);
      s.squash.set(squash);
      s.mouthRest.set(POSES[state].open || 0);
    }

    _reaction(t) {
      const r = this.reaction;
      if (!r) return;
      if (t > r.until) {
        this.reaction = null;
        this.s.joy.set(0);
        this.apply(this.state);
        return;
      }
      if (r.kind === 'joy') {
        this.s.joy.set(1);
        this.s.smile.set(0.6);
        this.s.browY.set(0.35);
      } else {
        const k = t - r.start;
        this.s.browTilt.set(0.5);
        this.s.browY.set(0.15);
        this.s.smile.set(-0.35);
        this.s.mouthWidth.set(0.3);
        this.s.tilt.set(Math.sin(k * 18) * 0.05 * Math.max(0, 1 - k * 1.6));
      }
    }

    _ring(dt) {
      if (this.spinTarget > 0) {
        this.rotVel += (this.spinTarget - this.rotVel) * (1 - Math.exp(-dt * 3));
        this.rot += this.rotVel * dt;
      } else {
        // Glide forward to the nearest resting angle instead of reversing.
        const base = this.ringAngle;
        const target = base + TAU * Math.ceil((this.rot - base - 0.15) / TAU);
        const k = 26;
        const c = 2 * Math.sqrt(k) * 0.95;
        this.rotVel += (k * (target - this.rot) - c * this.rotVel) * dt;
        this.rot += this.rotVel * dt;
      }
    }

    draw(ctx, t) {
      const s = this.s;
      const cx = s.x.value;
      const cy = BASE_Y + s.bob.value;

      this._glow(ctx, cx, BASE_Y, t);
      this._shadow(ctx, cx, s.bob.value);

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(s.tilt.value);
      const sq = s.squash.value;
      ctx.scale(1 / Math.sqrt(sq), sq);

      this._ringDraw(ctx, t);
      this._head(ctx);
      this._eyes(ctx);
      this._brows(ctx);
      this._mouth(ctx);
      this._dot(ctx, t);
      ctx.restore();
    }

    _glow(ctx, cx, cy, t) {
      const strength = clamp(this.s.glow.value + this.bright * 0.5, 0, 1.2);
      const r = 330 + this.bright * 40 + Math.sin(t * 1.3) * 6;
      const grad = ctx.createRadialGradient(cx, cy, 40, cx, cy, r);
      grad.addColorStop(0, 'rgba(237,248,176,' + (0.85 * strength).toFixed(3) + ')');
      grad.addColorStop(0.55, 'rgba(237,248,176,' + (0.28 * strength).toFixed(3) + ')');
      grad.addColorStop(1, 'rgba(237,248,176,0)');
      ctx.fillStyle = grad;
      ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
    }

    _shadow(ctx, cx, bob) {
      const lift = clamp(-bob / 30, -0.5, 1);
      const w = 150 * (1 - lift * 0.12);
      ctx.save();
      ctx.translate(cx, BASE_Y + RING_R + 26);
      ctx.scale(1, 0.16);
      const grad = ctx.createRadialGradient(0, 0, 0, 0, 0, w);
      grad.addColorStop(0, 'rgba(15,16,13,' + (0.16 * (1 - lift * 0.3)).toFixed(3) + ')');
      grad.addColorStop(1, 'rgba(15,16,13,0)');
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(0, 0, w, 0, TAU);
      ctx.fill();
      ctx.restore();
    }

    _ringDraw(ctx, t) {
      const s = this.s;
      const emphasis = s.ring.value;
      const lime = clamp(s.ringLime.value, 0, 1);
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineWidth = 11;
      ctx.strokeStyle = 'rgba(15,16,13,' + clamp(0.08 + emphasis * 0.72 * (1 - lime), 0, 1).toFixed(3) + ')';
      ctx.beginPath();
      ctx.arc(0, 0, RING_R, this.rot + GAP, this.rot + TAU - GAP);
      ctx.stroke();
      if (lime > 0.01) {
        // Acting: a lime sweep chases around the C like a progress spinner.
        const len = 1.5 + Math.sin(t * 2.4) * 0.6;
        const head = this.rot + TAU - GAP;
        ctx.strokeStyle = 'rgba(15,16,13,' + (0.1 * lime).toFixed(3) + ')';
        ctx.beginPath();
        ctx.arc(0, 0, RING_R, this.rot + GAP, head);
        ctx.stroke();
        ctx.globalAlpha = lime;
        ctx.strokeStyle = P.limeInk;
        ctx.lineWidth = 12;
        ctx.beginPath();
        ctx.arc(0, 0, RING_R, head - len, head);
        ctx.stroke();
        ctx.strokeStyle = P.lime;
        ctx.lineWidth = 6;
        ctx.stroke();
      }
      ctx.restore();
    }

    _head(ctx) {
      const a = HEAD_W / 2;
      const b = HEAD_H / 2;
      squircle(ctx, a, b, 4.2);
      const grad = ctx.createLinearGradient(0, -b, 0, b);
      grad.addColorStop(0, P.headTop);
      grad.addColorStop(0.55, '#16170f');
      grad.addColorStop(1, P.headBottom);
      ctx.save();
      ctx.shadowColor = 'rgba(15,16,13,0.28)';
      ctx.shadowBlur = 36;
      ctx.shadowOffsetY = 18;
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.restore();
      // Soft top highlight and a faint lime rim light underneath.
      ctx.save();
      squircle(ctx, a, b, 4.2);
      ctx.clip();
      const hi = ctx.createRadialGradient(-a * 0.35, -b * 0.85, 10, -a * 0.35, -b * 0.85, a * 1.1);
      hi.addColorStop(0, 'rgba(255,255,255,0.10)');
      hi.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = hi;
      ctx.fillRect(-a, -b, a * 2, b * 2);
      const rim = ctx.createLinearGradient(0, b * 0.55, 0, b);
      rim.addColorStop(0, 'rgba(217,242,92,0)');
      rim.addColorStop(1, 'rgba(217,242,92,0.10)');
      ctx.fillStyle = rim;
      ctx.fillRect(-a, b * 0.5, a * 2, b * 0.5);
      ctx.restore();
    }

    _eyes(ctx) {
      const s = this.s;
      const lx = s.lookX.value;
      const ly = s.lookY.value;
      const joy = clamp(s.joy.value, 0, 1);
      for (const side of [-1, 1]) {
        const persp = 1 + lx * side * 0.07;
        const ex = side * 60 * (1 - Math.abs(lx) * 0.06) + lx * 24;
        const ey = -20 + ly * 17;
        const w = 46 * s.eyeScale.value * persp;
        const squint = clamp(s.squint.value, 0, 0.9);
        const open = clamp((1 - this.blink) * (1 - squint * 0.5), 0.04, 1.2);
        const fullH = 68 * s.eyeScale.value * persp;
        const h = Math.max(6, fullH * open);
        // Squinting raises the lower lid: keep the top edge, lift the bottom.
        const cy = ey - (fullH - h) * 0.18 + squint * 6;
        ctx.save();
        ctx.globalAlpha = 1 - joy;
        ctx.shadowColor = 'rgba(237,248,176,0.45)';
        ctx.shadowBlur = 16;
        ctx.fillStyle = P.paper;
        CueFace.roundRect(ctx, ex - w / 2, cy - h / 2, w, h, Math.min(w, h) / 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        // A subtle cool inner shade gives the eye some depth.
        const shade = ctx.createLinearGradient(0, cy - h / 2, 0, cy + h / 2);
        shade.addColorStop(0, 'rgba(15,16,13,0)');
        shade.addColorStop(1, 'rgba(91,107,12,0.16)');
        ctx.fillStyle = shade;
        ctx.fill();
        // Catch-light.
        if (h > 24) {
          ctx.fillStyle = 'rgba(15,16,13,0.13)';
          ctx.beginPath();
          ctx.arc(ex + w * 0.18 + lx * 3, cy - h * 0.2 + ly * 2, w * 0.13, 0, TAU);
          ctx.fill();
        }
        ctx.restore();
        if (joy > 0.01) {
          // Happy eyes: upturned arcs.
          ctx.save();
          ctx.globalAlpha = joy;
          ctx.strokeStyle = P.paper;
          ctx.lineCap = 'round';
          ctx.lineWidth = 10;
          ctx.beginPath();
          ctx.arc(ex, ey + 12, 22, Math.PI * 1.12, Math.PI * 1.88);
          ctx.stroke();
          ctx.restore();
        }
      }
    }

    _brows(ctx) {
      const s = this.s;
      ctx.save();
      ctx.strokeStyle = 'rgba(250,250,247,0.62)';
      ctx.lineCap = 'round';
      ctx.lineWidth = 7;
      for (const side of [-1, 1]) {
        const raise = s.browY.value + (side < 0 ? s.browAsym.value : -s.browAsym.value * 0.3);
        const bx = side * 60 + s.lookX.value * 18;
        const by = -82 - raise * 15 + s.lookY.value * 8 + s.squint.value * 8;
        const ang = side * s.browTilt.value * 0.42;
        ctx.save();
        ctx.translate(bx, by);
        ctx.rotate(-ang);
        ctx.beginPath();
        ctx.moveTo(-16, 2);
        ctx.quadraticCurveTo(0, -4, 16, 2);
        ctx.stroke();
        ctx.restore();
      }
      ctx.restore();
    }

    _mouth(ctx) {
      const s = this.s;
      // The audio envelope drives the mouth directly (no spring lag); the spring only carries poses.
      const open = clamp(Math.max(this.env, s.mouthRest.value), 0, 1);
      const smile = s.smile.value;
      const shape = this.state === 'talking' ? this.shape : 0.5;
      // Wide "ee" sounds stretch the mouth; round "oo" sounds narrow it and drop the jaw.
      const w = 36 + s.mouthWidth.value * 56 + open * lerp(8, 34, shape);
      const h = open * lerp(62, 40, shape);
      const mx = s.mouthShift.value * 22 + s.lookX.value * 10;
      const my = 66 + s.lookY.value * 5;
      ctx.save();
      ctx.translate(mx, my);
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      const curve = smile * 20;
      if (h > 1.5) {
        // D-shaped open mouth: the upper lip keeps the smile line, the jaw drops below it.
        const lip = curve * 0.45 - h * 0.08;
        const mouth = new Path2D();
        mouth.moveTo(-w / 2, 0);
        mouth.bezierCurveTo(-w / 4, lip, w / 4, lip, w / 2, 0);
        mouth.bezierCurveTo(w / 2, h * 0.95 + curve * 0.3, -w / 2, h * 0.95 + curve * 0.3, -w / 2, 0);
        mouth.closePath();
        ctx.fillStyle = '#070805';
        ctx.fill(mouth);
        if (h > 8) {
          ctx.save();
          ctx.clip(mouth);
          ctx.fillStyle = P.limeInk;
          ctx.beginPath();
          ctx.ellipse(0, h * 0.78 + curve * 0.25, w * 0.26, h * 0.22, 0, 0, TAU);
          ctx.fill();
          ctx.restore();
        }
        ctx.strokeStyle = P.lime;
        ctx.lineWidth = 6.5;
        ctx.stroke(mouth);
      } else {
        ctx.strokeStyle = P.lime;
        ctx.lineWidth = 7.5;
        ctx.beginPath();
        ctx.moveTo(-w / 2, 0);
        ctx.quadraticCurveTo(0, curve, w / 2, 0);
        ctx.stroke();
      }
      ctx.restore();
    }

    _dot(ctx, t) {
      const s = this.s;
      const lift = s.dotLift.value;
      const angle = this.rot;
      const pulse = this.state === 'waiting_approval' ? 1 + Math.sin(t * 4.2) * 0.07 : 1 + Math.sin(t * 1.7) * 0.03;
      const r = 21 * s.dotSize.value * pulse * (1 + this.bright * 0.32);
      const dx = Math.cos(angle) * RING_R;
      const dy = Math.sin(angle) * RING_R - lift * 10;
      if (lift > 0.05) {
        // Approval: ripples radiate from the dot like a raised hand.
        for (let i = 0; i < 2; i++) {
          const p = ((t * 0.7 + i * 0.5) % 1 + 1) % 1;
          ctx.strokeStyle = 'rgba(91,107,12,' + ((1 - p) * 0.45 * lift).toFixed(3) + ')';
          ctx.lineWidth = 3;
          ctx.beginPath();
          ctx.arc(dx, dy, r + p * 46, 0, TAU);
          ctx.stroke();
        }
      }
      ctx.save();
      ctx.shadowColor = 'rgba(91,107,12,0.35)';
      ctx.shadowBlur = 12 + this.bright * 18;
      ctx.fillStyle = P.lime;
      ctx.beginPath();
      ctx.arc(dx, dy, r, 0, TAU);
      ctx.fill();
      ctx.restore();
      ctx.strokeStyle = 'rgba(91,107,12,0.45)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  function squircle(ctx, a, b, n) {
    ctx.beginPath();
    const steps = 72;
    for (let i = 0; i <= steps; i++) {
      const th = (i / steps) * TAU;
      const c = Math.cos(th);
      const s = Math.sin(th);
      const x = a * Math.sign(c) * Math.pow(Math.abs(c), 2 / n);
      const y = b * Math.sign(s) * Math.pow(Math.abs(s), 2 / n);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  Mascot.POSES = POSES;
  CueFace.Mascot = Mascot;
})(globalThis);
