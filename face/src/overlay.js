/* Everything drawn around the mascot: background, "AI teammate" badge, status pill, action cards
 * and captions. All of it is painted on the same canvas, so it reaches the meeting through
 * canvas.captureStream() as well as through a screen-capturing bot such as Attendee. */
(function (g) {
  'use strict';
  const CueFace = g.CueFace;
  const { Spring, clamp, palette: P, roundRect, FONT } = CueFace;
  const TAU = Math.PI * 2;

  const CARD_W = 384;
  const CARD_H = 92;
  const CARD_GAP = 14;
  const CARD_RIGHT = 1112; // stays inside the 4:3 centre crop Meet uses for some tiles
  const CARD_TOP = 150;
  const MAX_CARDS = 4;
  const LINGER = { done: 9, failed: 14 }; // seconds before a finished card leaves

  const STATUS_LABEL = {
    listening: 'Listening',
    thinking: 'Thinking',
    talking: 'Speaking',
    acting: 'Working on it',
    waiting_approval: 'Waiting for approval',
  };

  const CHIP = {
    running: { label: 'Running', fg: P.limeInk, bg: P.limeSoft },
    done: { label: 'Done', fg: P.ink, bg: P.lime },
    failed: { label: 'Failed', fg: P.danger, bg: P.dangerSoft },
    needs_approval: { label: 'Needs approval', fg: P.lime, bg: P.ink },
  };

  function font(size, weight) {
    return (weight || 400) + ' ' + size + 'px ' + FONT;
  }

  class Overlay {
    constructor(options) {
      const opts = options || {};
      this.captionsEnabled = opts.captions !== false;
      this.cards = [];
      this.caption = null;
      this.statusFade = new Spring(1, 120, 20);
      this.status = 'listening';
      this.prevStatus = 'listening';
      this.statusSwap = 1;
      this.background = null;
    }

    /* ---- cards ---- */

    upsertCard(event, t) {
      if (event.remove) {
        const card = this.cards.find((c) => c.id === event.id);
        if (card) card.leaving = t;
        return null;
      }
      let card = this.cards.find((c) => c.id === event.id && card_alive(c));
      const previous = card ? card.status : null;
      if (!card) {
        card = {
          id: event.id,
          born: t,
          leaving: null,
          y: new Spring(CARD_TOP, 170, 22),
          enter: new Spring(0, 140, 16),
          shake: 0,
          statusAt: t,
        };
        this.cards.unshift(card);
        card.enter.set(1);
        // Older cards beyond the limit slide out.
        const alive = this.cards.filter(card_alive);
        for (const old of alive.slice(MAX_CARDS)) old.leaving = t;
      }
      card.title = event.title;
      card.detail = event.detail;
      card.tool = event.tool;
      if (card.status !== event.status) {
        card.status = event.status;
        card.statusAt = t;
        if (event.status === 'failed') card.shake = t;
      }
      return previous;
    }

    get hasCards() {
      return this.cards.some(card_alive);
    }

    /* ---- captions ---- */

    setCaption(event, t) {
      if (!event.text) {
        if (this.caption) this.caption.hideAt = t;
        return;
      }
      const sameSpeaker = this.caption && this.caption.speaker === event.speaker && !this.caption.final && this.caption.hideAt === null;
      this.caption = {
        text: event.text,
        speaker: event.speaker,
        final: event.final,
        shownAt: sameSpeaker ? this.caption.shownAt : t,
        hideAt: null,
        updatedAt: t,
      };
    }

    setStatus(state, t) {
      if (state === this.status) return;
      this.prevStatus = this.status;
      this.status = state;
      this.statusChangedAt = t;
    }

    update(dt, t) {
      for (const card of this.cards) {
        card.enter.update(dt);
        card.y.update(dt);
        const linger = LINGER[card.status];
        if (!card.leaving && linger && t - card.statusAt > linger) card.leaving = t;
      }
      this.cards = this.cards.filter((c) => !c.leaving || t - c.leaving < 0.6);
      let y = CARD_TOP;
      for (const card of this.cards) {
        if (card.leaving) continue;
        card.y.set(y);
        if (card.enter.value < 0.05 && t - card.born < 0.05) card.y.snap(y);
        y += CARD_H + CARD_GAP;
      }
      if (this.caption && this.caption.hideAt === null) {
        const idle = t - this.caption.updatedAt;
        if ((this.caption.final && idle > 4.5) || idle > 9) this.caption.hideAt = t;
      }
      if (this.caption && this.caption.hideAt !== null && t - this.caption.hideAt > 0.5) this.caption = null;
    }

    /* ---- drawing ---- */

    drawBackground(ctx) {
      if (!this.background) this.background = makeBackground();
      ctx.drawImage(this.background, 0, 0);
    }

    drawBadge(ctx) {
      ctx.save();
      ctx.font = font(17, 600);
      const name = 'Cue';
      const tag = 'AI teammate';
      ctx.font = font(17, 600);
      const nameW = ctx.measureText(name).width;
      ctx.font = font(14, 500);
      const tagW = ctx.measureText(tag).width;
      const w = 16 + 26 + 8 + nameW + 12 + tagW + 20 + 16;
      const x = Math.round(CueFace.W / 2 - w / 2);
      const y = 26;
      const h = 42;
      ctx.shadowColor = 'rgba(15,16,13,0.08)';
      ctx.shadowBlur = 16;
      ctx.shadowOffsetY = 4;
      ctx.fillStyle = P.white;
      roundRect(ctx, x, y, w, h, h / 2);
      ctx.fill();
      ctx.shadowColor = 'transparent';
      ctx.strokeStyle = P.inkFaint;
      ctx.lineWidth = 1;
      ctx.stroke();
      CueFace.drawMark(ctx, x + 14, y + 8, 26, P.ink, P.lime);
      ctx.fillStyle = P.ink;
      ctx.font = font(17, 600);
      ctx.textBaseline = 'middle';
      ctx.fillText(name, x + 16 + 26 + 8, y + h / 2 + 1);
      const tx = x + 16 + 26 + 8 + nameW + 12;
      ctx.fillStyle = P.limeSoft;
      roundRect(ctx, tx, y + 9, tagW + 20, h - 18, (h - 18) / 2);
      ctx.fill();
      ctx.fillStyle = P.limeInk;
      ctx.font = font(14, 500);
      ctx.fillText(tag, tx + 10, y + h / 2 + 1);
      ctx.restore();
    }

    drawStatus(ctx, x, t, level) {
      const since = t - (this.statusChangedAt || -10);
      const swap = CueFace.easeOutCubic(since / 0.35);
      const label = STATUS_LABEL[this.status];
      ctx.save();
      ctx.font = font(18, 500);
      const textW = ctx.measureText(label).width;
      const w = 22 + 28 + textW + 22;
      const h = 42;
      const y = 586;
      const px = Math.round(x - w / 2);
      ctx.globalAlpha = 0.35 + 0.65 * swap;
      ctx.translate(0, (1 - swap) * 8);
      ctx.fillStyle = this.status === 'waiting_approval' ? P.ink : P.white;
      ctx.shadowColor = 'rgba(15,16,13,0.08)';
      ctx.shadowBlur = 14;
      ctx.shadowOffsetY = 4;
      roundRect(ctx, px, y, w, h, h / 2);
      ctx.fill();
      ctx.shadowColor = 'transparent';
      if (this.status !== 'waiting_approval') {
        ctx.strokeStyle = P.inkFaint;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
      this._statusIcon(ctx, px + 22 + 10, y + h / 2, t, level);
      ctx.fillStyle = this.status === 'waiting_approval' ? P.paper : P.ink;
      ctx.textBaseline = 'middle';
      ctx.fillText(label, px + 22 + 28, y + h / 2 + 1);
      ctx.restore();
    }

    _statusIcon(ctx, x, y, t, level) {
      ctx.save();
      switch (this.status) {
        case 'listening': {
          const r = 5 + Math.sin(t * 2.2) * 1.2;
          ctx.fillStyle = 'rgba(217,242,92,0.45)';
          ctx.beginPath();
          ctx.arc(x, y, r + 4, 0, TAU);
          ctx.fill();
          ctx.fillStyle = P.limeInk;
          ctx.beginPath();
          ctx.arc(x, y, 5, 0, TAU);
          ctx.fill();
          break;
        }
        case 'thinking':
          for (let i = 0; i < 3; i++) {
            const a = 0.3 + 0.7 * Math.max(0, Math.sin(t * 6 - i * 0.9));
            ctx.fillStyle = 'rgba(15,16,13,' + a.toFixed(3) + ')';
            ctx.beginPath();
            ctx.arc(x - 8 + i * 8, y - a * 2, 3, 0, TAU);
            ctx.fill();
          }
          break;
        case 'talking':
          ctx.fillStyle = P.limeInk;
          for (let i = 0; i < 4; i++) {
            const wobble = 0.35 + 0.65 * Math.abs(Math.sin(t * 9 + i * 1.7));
            const hh = 4 + 14 * clamp(level * 1.4, 0.1, 1) * wobble;
            roundRect(ctx, x - 10 + i * 6, y - hh / 2, 3.5, hh, 1.75);
            ctx.fill();
          }
          break;
        case 'acting':
          ctx.strokeStyle = P.limeInk;
          ctx.lineWidth = 3;
          ctx.lineCap = 'round';
          ctx.beginPath();
          ctx.arc(x, y, 7, t * 6, t * 6 + 4.2);
          ctx.stroke();
          break;
        default: {
          // waiting_approval: a pulsing lime dot on the ink pill
          const p = (t * 0.9) % 1;
          ctx.strokeStyle = 'rgba(217,242,92,' + (1 - p).toFixed(3) + ')';
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(x, y, 5 + p * 7, 0, TAU);
          ctx.stroke();
          ctx.fillStyle = P.lime;
          ctx.beginPath();
          ctx.arc(x, y, 5, 0, TAU);
          ctx.fill();
        }
      }
      ctx.restore();
    }

    drawCards(ctx, t) {
      for (let i = this.cards.length - 1; i >= 0; i--) this._card(ctx, this.cards[i], t);
    }

    _card(ctx, card, t) {
      const enter = clamp(card.enter.value, 0, 1.2);
      const leave = card.leaving ? CueFace.easeInOut((t - card.leaving) / 0.45) : 0;
      const alpha = clamp(enter, 0, 1) * (1 - leave);
      if (alpha <= 0.01) return;
      let x = CARD_RIGHT - CARD_W + (1 - enter) * 60 + leave * 40;
      const y = card.y.value;
      if (card.status === 'failed' && card.shake) {
        const k = t - card.shake;
        if (k < 0.5) x += Math.sin(k * 55) * 7 * (1 - k / 0.5);
      }
      const chip = CHIP[card.status];
      const approval = card.status === 'needs_approval';
      ctx.save();
      ctx.globalAlpha = alpha;

      // Card body
      ctx.shadowColor = 'rgba(15,16,13,0.10)';
      ctx.shadowBlur = 24;
      ctx.shadowOffsetY = 8;
      ctx.fillStyle = P.white;
      roundRect(ctx, x, y, CARD_W, CARD_H, 18);
      ctx.fill();
      ctx.shadowColor = 'transparent';
      if (approval) {
        const pulse = 0.5 + 0.5 * Math.sin(t * 4.2);
        ctx.strokeStyle = 'rgba(91,107,12,' + (0.45 + pulse * 0.45).toFixed(3) + ')';
        ctx.lineWidth = 2.5;
        ctx.stroke();
        ctx.strokeStyle = 'rgba(217,242,92,' + (0.35 * pulse).toFixed(3) + ')';
        ctx.lineWidth = 8;
        roundRect(ctx, x - 4, y - 4, CARD_W + 8, CARD_H + 8, 22);
        ctx.stroke();
      } else {
        ctx.strokeStyle = card.status === 'failed' ? 'rgba(180,35,24,0.35)' : P.inkFaint;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Tool tile
      const tx = x + 16;
      const ty = y + 18;
      ctx.fillStyle = card.status === 'done' ? P.lime : card.status === 'failed' ? P.dangerSoft : P.limeSoft;
      roundRect(ctx, tx, ty, 56, 56, 14);
      ctx.fill();
      this._statusGlyph(ctx, card, tx + 28, ty + 28, t);

      // Text
      const textX = tx + 56 + 14;
      const textW = x + CARD_W - 16 - textX;
      ctx.textBaseline = 'alphabetic';
      ctx.fillStyle = P.ink;
      ctx.font = font(17, 600);
      ctx.fillText(CueFace.ellipsize(ctx, card.title, textW), textX, y + 36);

      // Status chip + tool + detail on the second line
      ctx.font = font(13, 600);
      const chipW = ctx.measureText(chip.label).width + 18;
      const chipX = textX;
      const chipY = y + 50;
      ctx.fillStyle = chip.bg;
      roundRect(ctx, chipX, chipY, chipW, 24, 12);
      ctx.fill();
      ctx.fillStyle = chip.fg;
      ctx.textBaseline = 'middle';
      ctx.fillText(chip.label, chipX + 9, chipY + 12.5);
      const meta = [card.tool ? toolName(card.tool) : '', card.detail].filter(Boolean).join(' · ');
      if (meta) {
        ctx.font = font(14, 400);
        ctx.fillStyle = P.inkMuted;
        ctx.fillText(CueFace.ellipsize(ctx, meta, textW - chipW - 10), chipX + chipW + 10, chipY + 12.5);
      }
      ctx.restore();
    }

    _statusGlyph(ctx, card, x, y, t) {
      const since = t - card.statusAt;
      ctx.save();
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      switch (card.status) {
        case 'running':
          ctx.strokeStyle = 'rgba(91,107,12,0.25)';
          ctx.lineWidth = 4;
          ctx.beginPath();
          ctx.arc(x, y, 13, 0, TAU);
          ctx.stroke();
          ctx.strokeStyle = P.limeInk;
          ctx.beginPath();
          ctx.arc(x, y, 13, t * 5.5, t * 5.5 + 1.6 + Math.sin(t * 3) * 0.6);
          ctx.stroke();
          break;
        case 'done': {
          // The check mark draws itself in.
          const p = CueFace.easeOutCubic(since / 0.45);
          const pts = [[-10, 1], [-3, 8], [11, -8]];
          const l1 = Math.hypot(7, 7);
          const l2 = Math.hypot(14, 16);
          let remaining = p * (l1 + l2);
          ctx.strokeStyle = P.ink;
          ctx.lineWidth = 4.5;
          ctx.beginPath();
          ctx.moveTo(x + pts[0][0], y + pts[0][1]);
          const seg1 = Math.min(1, remaining / l1);
          ctx.lineTo(x + pts[0][0] + 7 * seg1, y + pts[0][1] + 7 * seg1);
          remaining -= l1;
          if (remaining > 0) {
            const seg2 = Math.min(1, remaining / l2);
            ctx.lineTo(x + pts[1][0] + 14 * seg2, y + pts[1][1] - 16 * seg2);
          }
          ctx.stroke();
          break;
        }
        case 'failed': {
          const p = CueFace.easeOutBack(since / 0.4);
          ctx.strokeStyle = P.danger;
          ctx.lineWidth = 4.5;
          const d = 8 * clamp(p, 0, 1.2);
          ctx.beginPath();
          ctx.moveTo(x - d, y - d);
          ctx.lineTo(x + d, y + d);
          ctx.moveTo(x + d, y - d);
          ctx.lineTo(x - d, y + d);
          ctx.stroke();
          break;
        }
        default: {
          // needs_approval: a raised hand reads as "your turn" without words.
          const bob = Math.sin(t * 4.2) * 1.5;
          ctx.translate(x, y + bob);
          ctx.fillStyle = P.ink;
          roundRect(ctx, -9, -4, 18, 16, 6);
          ctx.fill();
          for (let i = 0; i < 4; i++) {
            roundRect(ctx, -9 + i * 4.8, -14 + (i === 0 || i === 3 ? 3 : 0), 3.8, 14, 1.9);
            ctx.fill();
          }
          ctx.save();
          ctx.translate(9, 2);
          ctx.rotate(-0.7);
          roundRect(ctx, 0, -2, 10, 4, 2);
          ctx.fill();
          ctx.restore();
        }
      }
      ctx.restore();
    }

    drawCaption(ctx, t) {
      const c = this.caption;
      if (!c || !this.captionsEnabled) return;
      const appear = CueFace.easeOutCubic((t - c.shownAt) / 0.25);
      const vanish = c.hideAt !== null ? CueFace.easeInOut((t - c.hideAt) / 0.45) : 0;
      const alpha = appear * (1 - vanish);
      if (alpha <= 0.01) return;
      ctx.save();
      ctx.globalAlpha = alpha;
      const maxW = 860;
      ctx.font = font(23, 500);
      const speaker = c.speaker + '  ';
      ctx.font = font(23, 600);
      const speakerW = ctx.measureText(speaker).width;
      ctx.font = font(23, 400);
      const lines = CueFace.wrapText(ctx, c.text, maxW - speakerW, 2);
      const lineH = 32;
      let widest = 0;
      lines.forEach((line, i) => {
        widest = Math.max(widest, ctx.measureText(line).width + (i === 0 ? speakerW : 0));
      });
      const w = Math.min(maxW, widest) + 44;
      const h = lines.length * lineH + 26;
      const x = Math.round(CueFace.W / 2 - w / 2);
      const y = 704 - h + (1 - appear) * 10;
      ctx.fillStyle = 'rgba(15,16,13,0.86)';
      roundRect(ctx, x, y, w, h, 18);
      ctx.fill();
      ctx.textBaseline = 'alphabetic';
      lines.forEach((line, i) => {
        let lx = x + 22;
        const ly = y + 13 + 23 + i * lineH;
        if (i === 0) {
          ctx.font = font(23, 600);
          ctx.fillStyle = c.speaker === 'Cue' ? P.lime : P.limeSoft;
          ctx.fillText(c.speaker, lx, ly);
          lx += speakerW;
        }
        ctx.font = font(23, 400);
        ctx.fillStyle = P.paper;
        ctx.fillText(line, lx, ly);
      });
      ctx.restore();
    }
  }

  function card_alive(card) {
    return !card.leaving;
  }

  function toolName(tool) {
    const names = { github: 'GitHub', slack: 'Slack', linear: 'Linear', gmail: 'Gmail', calendar: 'Calendar', google_calendar: 'Calendar', jira: 'Jira', notion: 'Notion' };
    return names[tool] || tool.charAt(0).toUpperCase() + tool.slice(1);
  }

  function makeBackground() {
    const canvas = document.createElement('canvas');
    canvas.width = CueFace.W;
    canvas.height = CueFace.H;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = P.paper;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // Quiet dot grid, fading toward the edges.
    for (let y = 20; y < canvas.height; y += 28) {
      for (let x = 20; x < canvas.width; x += 28) {
        const dx = (x - 640) / 640;
        const dy = (y - 360) / 360;
        const fade = clamp(1 - Math.sqrt(dx * dx + dy * dy) * 0.75, 0, 1);
        ctx.fillStyle = 'rgba(15,16,13,' + (0.05 * fade + 0.012).toFixed(3) + ')';
        ctx.fillRect(x, y, 1.6, 1.6);
      }
    }
    const vignette = ctx.createRadialGradient(640, 360, 300, 640, 360, 820);
    vignette.addColorStop(0, 'rgba(15,16,13,0)');
    vignette.addColorStop(1, 'rgba(15,16,13,0.05)');
    ctx.fillStyle = vignette;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    return canvas;
  }

  Overlay.STATUS_LABEL = STATUS_LABEL;
  CueFace.Overlay = Overlay;
})(globalThis);
