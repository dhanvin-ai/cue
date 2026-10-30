import {
  Captions,
  Check,
  CircleX,
  Hand,
  Info,
  MessageSquareText,
  Mic,
  MicOff,
  MonitorUp,
  MoreVertical,
  PhoneOff,
  Shapes,
  Users,
  VideoOff,
  X,
} from "lucide-react";
import type { ReactNode } from "react";
import { AiTag, Brand, CueFace, Face, Waveform, Window, people, type PersonId } from "../kit";
import { camera, mix, prog, wordsShown, wrap } from "../lib";

const START = 96;
const END = 450;

const shots = [
  { f: 96, x: 960, y: 519, s: 0.94 },
  { f: 118, x: 960, y: 519, s: 1 },
  { f: 180, x: 960, y: 519, s: 1 },
  { f: 210, x: 760, y: 430, s: 1.1 },
  { f: 232, x: 760, y: 432, s: 1.1 },
  { f: 256, x: 1150, y: 600, s: 1.36 },
  { f: 326, x: 1170, y: 604, s: 1.42 },
  { f: 350, x: 1000, y: 520, s: 1 },
  { f: 372, x: 1160, y: 500, s: 1.08 },
  { f: 408, x: 1180, y: 505, s: 1.1 },
  { f: 448, x: 960, y: 540, s: 0.92 },
];

type Speaker = PersonId | "cue";

const lines: { who: Speaker; text: string; start: number; end: number; per: number }[] = [
  { who: "sam", text: "Billing v2 is live on staging, and the webhooks look stable.", start: 128, end: 184, per: 3 },
  { who: "priya", text: "Hey Cue, what's blocking our release?", start: 188, end: 240, per: 4.5 },
  {
    who: "cue",
    text: "Two things. PR #418 has a failing webhook test, and the Stripe key rotation Arjun flagged on Tuesday is still open.",
    start: 268,
    end: 340,
    per: 2.8,
  },
  { who: "arjun", text: "I'll take the test fix. Friday at the latest.", start: 364, end: 410, per: 3.2 },
];

/** 0 → 1 → 0 while someone holds the floor. */
const talking = (f: number, who: Speaker) => {
  const line = lines.find((l) => l.who === who && f >= l.start - 4 && f < l.end + 8);
  if (!line) return 0;
  const words = line.text.split(" ").length;
  return prog(f, line.start - 4, 6) * (1 - prog(f, line.start + words * line.per, 8));
};

const cueStatus = (f: number) => {
  if (f < 150) return null;
  if (f < 222) return "Listening";
  if (f < 246) return "Heard “Hey Cue”";
  if (f < 266) return "Checking GitHub · Slack";
  if (f < 334) return "Speaking";
  return "Tracking action items";
};

const TILES_H = 590;
const GAP = 16;

function layout(join: number, chat: number) {
  const W = 1520 - 460 * chat;
  const w = (W - GAP) / 2;
  const h = (TILES_H - GAP) / 2;
  return {
    W,
    priya: { x: 0, y: 0, w, h },
    arjun: { x: w + GAP, y: 0, w, h },
    sam: { x: mix((W - w) / 2, 0, join), y: h + GAP, w, h },
    cue: { x: w + GAP, y: h + GAP, w, h },
  };
}

type Rect = { x: number; y: number; w: number; h: number };

function PersonTile({ id, rect, f, dim }: { id: PersonId; rect: Rect; f: number; dim: number }) {
  const level = talking(f, id);
  return (
    <div
      className="absolute grid place-items-center overflow-hidden rounded-[20px] bg-[#3c4043]"
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        boxShadow: `inset 0 0 0 ${4 * level}px #8ab4f8`,
        filter: `brightness(${mix(1, 0.5, dim)})`,
      }}
    >
      <Face id={id} size={112} />
      <span className="absolute bottom-4 left-5 text-[19px] font-medium text-white">{people[id].name}</span>
      <span
        className="absolute right-4 top-4 grid size-[38px] place-items-center rounded-full"
        style={{ background: level > 0.05 ? "#8ab4f8" : "rgb(0 0 0 / 0.35)" }}
      >
        {level > 0.05 ? (
          <Waveform f={f} level={level} bars={3} color="#062e6f" height={18} width={4} gap={3} />
        ) : (
          <MicOff className="size-[18px] text-white/85" />
        )}
      </span>
    </div>
  );
}

function CueTile({ rect, f, join }: { rect: Rect; f: number; join: number }) {
  const level = talking(f, "cue");
  const status = cueStatus(f);
  const heard = prog(f, 222, 10) * (1 - prog(f, 336, 12));
  return (
    <div
      className="absolute grid place-items-center overflow-hidden rounded-[20px] bg-[#2b2c28]"
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.w,
        height: rect.h,
        opacity: join,
        scale: `${mix(0.86, 1, join)}`,
        boxShadow: `inset 0 0 0 ${4 * Math.max(level, heard)}px #d9f25c`,
      }}
    >
      <div className="flex flex-col items-center gap-4">
        <CueFace size={112} ring={Math.max(level, heard * 0.6) * (0.75 + 0.25 * Math.sin(f / 4))} />
        <span style={{ opacity: level > 0.05 ? 1 : 0.5 }}>
          <Waveform f={f} level={level} bars={9} height={30} width={6} gap={5} color={level > 0.05 ? "#d9f25c" : "#6b6d63"} />
        </span>
      </div>
      {status && (
        <span
          key={status}
          className="absolute left-4 top-4 flex h-[38px] items-center gap-2 rounded-full bg-black/45 px-4 text-[17px] font-medium text-white"
        >
          <span className="size-2.5 rounded-full bg-lime" />
          {status}
        </span>
      )}
      <span className="absolute bottom-4 left-5 flex items-center gap-2.5 text-[19px] font-medium text-white">
        Cue
        <AiTag size={13} />
      </span>
      <span
        className="absolute right-4 top-4 grid size-[38px] place-items-center rounded-full"
        style={{ background: level > 0.05 ? "#d9f25c" : "rgb(0 0 0 / 0.35)" }}
      >
        {level > 0.05 ? (
          <Waveform f={f} level={level} bars={3} color="#0f100d" height={18} width={4} gap={3} />
        ) : (
          <Mic className="size-[18px] text-white/85" />
        )}
      </span>
    </div>
  );
}

function Caption({ f, width }: { f: number; width: number }) {
  const line = lines.find((l) => f >= l.start && f < l.end);
  if (!line) return null;
  // Like live captions: the newest two lines, older ones scrolled away.
  const shown = wrap(line.text.split(" ").slice(0, wordsShown(f, line.start, line.text, line.per)), 64).slice(-2);
  const fade = prog(f, line.start, 6) * (1 - prog(f, line.end - 6, 6));
  return (
    <div
      className="absolute left-1/2 top-[606px] flex -translate-x-1/2 items-start gap-4 rounded-[16px] bg-black/55 px-5 py-3.5"
      style={{ width: Math.min(960, width), opacity: fade }}
    >
      {line.who === "cue" ? <CueFace size={44} /> : <Face id={line.who} size={44} />}
      <div className="min-w-0 flex-1">
        <p className="text-[16px] font-semibold text-white/60">{line.who === "cue" ? "Cue" : people[line.who].name}</p>
        <div className="h-[76px] text-[26px] leading-[38px] text-white">
          {shown.map((l) => (
            <p key={l} className="whitespace-nowrap">
              {l}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

function ControlBar({ f, count, chat }: { f: number; count: number; chat: boolean }) {
  const ending = f >= 404 && f < 414;
  const round = "grid size-[56px] place-items-center rounded-full bg-[#3c4043] text-white";
  return (
    <div className="absolute inset-x-0 bottom-0 flex h-[88px] items-center px-8 text-white">
      <span className="w-[360px] text-[19px] text-white/85">
        11:04 AM <span className="mx-2 text-white/30">|</span> Release sync
      </span>
      <div className="flex flex-1 items-center justify-center gap-3">
        <span className={round}>
          <Mic className="size-6" />
        </span>
        <span className={round}>
          <VideoOff className="size-6" />
        </span>
        <span className="grid size-[56px] place-items-center rounded-full bg-[#8ab4f8] text-[#062e6f]">
          <Captions className="size-6" />
        </span>
        <span className={round}>
          <Hand className="size-6" />
        </span>
        <span className={round}>
          <MonitorUp className="size-6" />
        </span>
        <span className={round}>
          <MoreVertical className="size-6" />
        </span>
        <span
          className="grid h-[56px] w-[80px] place-items-center rounded-full bg-[#ea4335]"
          style={{ scale: ending ? "0.9" : "1", boxShadow: ending ? "0 0 0 8px rgb(234 67 53 / 0.3)" : undefined }}
        >
          <PhoneOff className="size-6" />
        </span>
      </div>
      <div className="flex w-[360px] items-center justify-end gap-6 text-white/85">
        <Info className="size-7" />
        <span className="relative">
          <Users className="size-7" />
          <span className="absolute -right-3 -top-2.5 grid size-[22px] place-items-center rounded-full bg-[#8ab4f8] text-[13px] font-bold text-[#062e6f]">
            {count}
          </span>
        </span>
        <span className={chat ? "grid size-11 place-items-center rounded-full bg-[#8ab4f8]/25 text-[#8ab4f8]" : ""}>
          <MessageSquareText className="size-7" />
        </span>
        <Shapes className="size-7" />
      </div>
    </div>
  );
}

function Message({ f, at, time, children }: { f: number; at: number; time: string; children: ReactNode }) {
  const p = prog(f, at, 14);
  if (p <= 0) return null;
  return (
    <div style={{ opacity: p, translate: `0 ${mix(18, 0, p)}px` }}>
      <p className="flex items-center gap-2 text-[15px] text-[#5f6368]">
        <span className="font-semibold text-[#202124]">Cue</span>
        <AiTag size={11} />
        <span>{time}</span>
      </p>
      <div className="mt-1.5 text-[17px] leading-[1.45] text-[#202124]">{children}</div>
    </div>
  );
}

function ChatPanel({ f, open }: { f: number; open: number }) {
  const item = (who: PersonId, text: string, due: string, at: number) => {
    const done = f >= at;
    return (
      <div className="flex items-center gap-3 rounded-[12px] bg-[#f1f3f4] px-3 py-2.5">
        <span className={`grid size-6 place-items-center rounded-[7px] ${done ? "bg-lime text-ink" : "border-2 border-[#c4c7c5]"}`}>
          {done && <Check className="size-4" strokeWidth={3} />}
        </span>
        <Face id={who} size={28} />
        <span className="flex-1 text-[16px] font-medium text-[#202124]">{text}</span>
        <span className="text-[14px] text-[#5f6368]">{due}</span>
      </div>
    );
  };
  return (
    <div
      className="absolute right-5 top-5 flex h-[700px] w-[440px] flex-col rounded-[22px] bg-white px-6 py-5"
      style={{ opacity: open, translate: `${mix(480, 0, open)}px 0` }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[22px] font-medium text-[#202124]">In-call messages</span>
        <X className="size-6 text-[#5f6368]" />
      </div>
      <p className="mt-3 rounded-[12px] bg-[#f1f3f4] px-4 py-2.5 text-[14px] text-[#5f6368]">
        Messages are visible to people in the call
      </p>
      <div className="mt-5 flex flex-col gap-5">
        <Message f={f} at={346} time="11:04 AM">
          Two blockers for the v2.4 release:
          <span className="mt-2 flex items-center gap-3 rounded-[14px] border border-[#e0e3e7] p-3">
            <Brand name="github" size={30} />
            <span className="flex-1 leading-tight">
              <span className="block text-[16px] font-semibold">PR #418 · Webhook retries</span>
              <span className="flex items-center gap-1.5 text-[14px] text-[#c5221f]">
                <CircleX className="size-4" /> 2 of 14 checks failing
              </span>
            </span>
          </span>
          <span className="mt-2 flex items-center gap-3 rounded-[14px] border border-[#e0e3e7] p-3">
            <Brand name="slack" size={30} />
            <span className="flex-1 leading-tight">
              <span className="block text-[16px] font-semibold">Stripe key rotation</span>
              <span className="block text-[14px] text-[#5f6368]">Open since Tue · #launch-billing</span>
            </span>
          </span>
        </Message>
        <Message f={f} at={366} time="11:04 AM">
          From the Oct 23 sync: we agreed to ship billing v2 behind the <span className="font-mono text-[15px]">billing_v2</span> flag.
        </Message>
        <Message f={f} at={386} time="11:05 AM">
          Tracking action items
          <span className="mt-2 flex flex-col gap-2">
            {item("arjun", "Fix webhook test", "Fri", 398)}
            {item("sam", "Rotate Stripe key", "Today", 406)}
          </span>
        </Message>
      </div>
    </div>
  );
}

/** What Cue pulls in to answer Priya. Screen-space cards layered over the zoomed call. */
function Retrieval({ f }: { f: number }) {
  const out = prog(f, 326, 16);
  if (f < 240 || out >= 1) return null;
  const card = (at: number) => {
    const p = prog(f, at, 18);
    return { opacity: p * (1 - out), translate: `${mix(-60, 0, p) - out * 80 + (f - at) * 0.12}px ${mix(20, 0, p)}px` };
  };
  const used = (at: number) => (
    <span
      className="flex items-center gap-1.5 rounded-full bg-lime-soft px-3 py-1 text-[14px] font-semibold text-lime-ink"
      style={{ opacity: prog(f, at, 8) }}
    >
      <Check className="size-4" strokeWidth={3} /> In the answer
    </span>
  );
  return (
    <div className="absolute inset-0">
      <p
        className="absolute left-[100px] top-[244px] flex items-center gap-2.5 rounded-full bg-white py-2 pl-3.5 pr-5 text-[18px] font-semibold text-ink shadow-[0_12px_30px_-12px_rgb(15_16_13/0.5)]"
        style={{ opacity: prog(f, 240, 12) * (1 - out) }}
      >
        <span className="size-2.5 rounded-full bg-lime ring-4 ring-lime/30" />
        Cue is pulling context
      </p>
      <div className="absolute left-[100px] top-[300px] w-[540px] rounded-[24px] bg-white p-5 shadow-[0_30px_60px_-24px_rgb(15_16_13/0.5)]" style={card(244)}>
        <div className="flex items-center gap-3">
          <Brand name="github" size={30} />
          <span className="text-[16px] text-muted">yourteam/billing · Pull request</span>
          <span className="ml-auto">{used(268)}</span>
        </div>
        <p className="mt-3 text-[22px] font-semibold tracking-[-0.02em] text-ink">#418 Webhook retries for billing v2</p>
        <div className="mt-3 flex items-center gap-2.5 rounded-[12px] bg-[#fdecea] px-3.5 py-2.5 text-[16px] text-[#a50e0e]">
          <CircleX className="size-5" />
          <span className="font-mono text-[14.5px]">payment-webhook.test.ts</span>
          <span className="ml-auto font-medium">failing</span>
        </div>
      </div>
      <div className="absolute left-[100px] top-[510px] w-[540px] rounded-[24px] bg-white p-5 shadow-[0_30px_60px_-24px_rgb(15_16_13/0.5)]" style={card(254)}>
        <div className="flex items-center gap-3">
          <Brand name="slack" size={30} />
          <span className="text-[16px] text-muted">#launch-billing · Tuesday</span>
          <span className="ml-auto">{used(274)}</span>
        </div>
        <div className="mt-3 flex gap-3">
          <Face id="arjun" size={40} />
          <p className="text-[18px] leading-[1.4] text-ink-soft">
            <span className="font-semibold text-ink">Arjun Kumar</span> Stripe key rotation is still pending. Sam needs to rotate it before
            we ship.
          </p>
        </div>
      </div>
    </div>
  );
}

export function MeetScene({ f }: { f: number }) {
  if (f < START || f > END) return null;

  const enter = prog(f, 98, 20);
  const join = prog(f, 124, 22);
  const chat = prog(f, 332, 22);
  const ended = prog(f, 414, 12);
  const recede = prog(f, 420, 28);
  const L = layout(join, chat);
  const toast = prog(f, 122, 12) * (1 - prog(f, 166, 12));
  // While Cue is on the spot, the rest of the room steps back.
  const dim = prog(f, 236, 14) * (1 - prog(f, 330, 14));

  return (
    <>
      <div className="absolute inset-0" style={camera(f, shots)}>
        <Window
          dark
          style={{
            opacity: enter * (1 - recede),
            scale: `${mix(0.96, 1, enter) * mix(1, 0.9, recede)}`,
            filter: `blur(${recede * 8}px)`,
          }}
          bar={
            <>
              <span className="flex items-center gap-3 text-[20px] font-medium">
                <Brand name="google-meet" size={26} />
                Release sync
              </span>
              <span className="ml-auto text-[17px] text-white/45">Google Meet</span>
            </>
          }
        >
          <div className="absolute left-5 top-5" style={{ width: L.W, height: TILES_H, opacity: 1 - ended }}>
            <PersonTile id="priya" rect={L.priya} f={f} dim={dim} />
            <PersonTile id="arjun" rect={L.arjun} f={f} dim={dim} />
            <PersonTile id="sam" rect={L.sam} f={f} dim={dim} />
            {join > 0 && <CueTile rect={L.cue} f={f} join={join} />}
            <span
              className="absolute left-1/2 flex -translate-x-1/2 items-center gap-3 rounded-full bg-[#202124]/90 py-2 pl-2 pr-5 text-[18px] text-white shadow-lg ring-1 ring-white/10"
              style={{ opacity: toast, top: mix(4, 16, toast) }}
            >
              <CueFace size={34} />
              <span>
                <span className="font-semibold">Cue</span> joined · AI teammate
              </span>
            </span>
          </div>
          <div className="absolute left-5" style={{ width: L.W, opacity: 1 - ended }}>
            <Caption f={f} width={L.W} />
          </div>
          {chat > 0 && <ChatPanel f={f} open={chat * (1 - ended)} />}
          <div
            className="absolute inset-x-0 top-0 grid h-[730px] place-items-center"
            style={{ opacity: ended }}
          >
            <div className="text-center">
              <p className="text-[40px] font-semibold tracking-[-0.03em] text-white">Call ended · 24 min</p>
              <p className="mt-3 flex items-center justify-center gap-2.5 text-[20px] text-white/60">
                <span className="size-2.5 rounded-full bg-lime" />
                Cue is writing up the notes
              </p>
            </div>
          </div>
          <ControlBar f={f} count={join > 0.5 ? 4 : 3} chat={chat > 0.5} />
        </Window>
      </div>
      <Retrieval f={f} />
    </>
  );
}
