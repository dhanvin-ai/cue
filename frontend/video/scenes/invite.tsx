import { Check, ChevronLeft, ChevronRight, Video } from "lucide-react";
import { Brand, CueFace, Status, Window } from "../kit";
import { camera, mix, prog } from "../lib";

const START = 0;
const END = 114;

const days = [
  ["Mon", 26],
  ["Tue", 27],
  ["Wed", 28],
  ["Thu", 29],
  ["Fri", 30],
] as const;

const HOUR = 104;
const GRID_TOP = 164;
const GUTTER = 76;
const COL = 196;

type Slot = { d: number; from: number; to: number; title: string; tone: "lime" | "grey"; zoom?: boolean };

/** Cue's existing week, so the new invite lands in a real-looking calendar. */
const week: Slot[] = [
  ...days.map((_, d): Slot => ({ d, from: 9.5, to: 9.85, title: "Standup", tone: "lime" })),
  { d: 1, from: 13, to: 14, title: "Design review", tone: "grey" },
  { d: 2, from: 11.5, to: 12.5, title: "Fieldstone weekly", tone: "grey", zoom: true },
  { d: 3, from: 14, to: 14.75, title: "Billing handoff", tone: "grey" },
  { d: 4, from: 13, to: 13.75, title: "Retro", tone: "grey" },
];

const prep = [
  { icon: "google-calendar", title: "Last release sync · Oct 23", detail: "Decided: ship behind the billing_v2 flag", at: 48 },
  { icon: "slack", title: "#launch-billing", detail: "38 new messages since Tuesday", at: 56 },
  { icon: "github", title: "PR #418 · Webhook retries", detail: "2 of 14 checks failing", at: 64 },
  { icon: "gmail", title: "Dana at Fieldstone", detail: "Asked us to confirm the launch date", at: 72 },
];

const shots = [
  { f: 0, x: 960, y: 519, s: 1 },
  { f: 12, x: 960, y: 519, s: 1 },
  { f: 34, x: 1330, y: 330, s: 1.28 },
  { f: 44, x: 1330, y: 336, s: 1.28 },
  { f: 64, x: 1370, y: 680, s: 1.2 },
  { f: 90, x: 1380, y: 690, s: 1.18 },
  { f: 114, x: 1500, y: 420, s: 2.7 },
];

function at(hour: number) {
  return GRID_TOP + (hour - 9) * HOUR;
}

export function InviteScene({ f }: { f: number }) {
  if (f < START || f > END) return null;

  const rise = prog(f, 0, 22);
  const card = prog(f, 12, 18);
  const accepted = f >= 32;
  const press = f >= 29 && f < 33;
  const ready = prog(f, 84, 14);
  const through = prog(f, 94, 16);

  return (
    <div className="absolute inset-0" style={{ ...camera(f, shots), opacity: 1 - through, filter: `blur(${through * 10}px)` }}>
      <Window
        style={{ opacity: rise, translate: `0 ${mix(50, 0, rise)}px` }}
        bar={
          <>
            <span className="flex items-center gap-3 text-[20px] font-medium">
              <Brand name="google-calendar" size={26} />
              Cue&rsquo;s calendar
            </span>
            <span className="ml-auto flex items-center gap-3 text-[18px] text-muted">
              cue@yourteam.com
              <CueFace size={30} />
            </span>
          </>
        }
      >
        {/* Week grid */}
        <div className="absolute inset-y-0 left-0 w-[1080px]">
          <div className="flex h-[84px] items-center gap-5 px-8">
            <span className="text-[30px] font-semibold tracking-[-0.03em] text-ink">October 2026</span>
            <span className="flex gap-1 text-muted">
              <ChevronLeft className="size-7" />
              <ChevronRight className="size-7" />
            </span>
            <span className="ml-auto rounded-full border border-line px-4 py-1.5 text-[17px] font-medium text-ink-soft">Week</span>
          </div>
          <div className="absolute left-0 right-6 top-[84px] flex h-[70px]" style={{ paddingLeft: GUTTER }}>
            {days.map(([name, date], i) => (
              <div key={name} className="flex flex-col items-center justify-center" style={{ width: COL }}>
                <span className="text-[15px] font-medium uppercase tracking-[0.08em] text-muted">{name}</span>
                <span
                  className={`mt-1 grid size-[40px] place-items-center rounded-full text-[22px] font-semibold ${i === 3 ? "bg-[#0b57d0] text-white" : "text-ink"}`}
                >
                  {date}
                </span>
              </div>
            ))}
          </div>
          {Array.from({ length: 7 }, (_, h) => (
            <div key={h} className="absolute left-0 right-6 flex items-start" style={{ top: at(9 + h) }}>
              <span className="-mt-[10px] w-[64px] pr-3 text-right text-[14px] text-faint">{`${((8 + h) % 12) + 1} ${h < 3 ? "AM" : "PM"}`}</span>
              <span className="ml-3 h-px flex-1 bg-line-soft" />
            </div>
          ))}
          {days.map((_, i) => (
            <span key={i} className="absolute w-px bg-line-soft" style={{ left: GUTTER + i * COL, top: GRID_TOP, height: 6 * HOUR }} />
          ))}

          {week.map((e) => (
            <div
              key={`${e.d}-${e.title}`}
              className={`absolute flex items-start gap-2 overflow-hidden rounded-[10px] px-3 py-1.5 text-[15px] font-semibold ${
                e.tone === "lime" ? "bg-lime-wash text-lime-ink" : "bg-paper-deep text-ink-soft"
              }`}
              style={{ left: GUTTER + e.d * COL + 4, width: COL - 8, top: at(e.from) + 2, height: (e.to - e.from) * HOUR - 4 }}
            >
              {e.zoom && <Brand name="zoom" size={18} style={{ marginTop: 2 }} />}
              {e.title}
            </div>
          ))}

          {/* Now line: Thursday, 10:12 */}
          <div className="absolute flex items-center" style={{ left: GUTTER + 3 * COL - 6, width: COL + 6, top: at(10.2) - 6 }}>
            <span className="size-3 rounded-full bg-[#ea4335]" />
            <span className="h-[2px] flex-1 bg-[#ea4335]" />
          </div>

          {/* The new invite */}
          <div
            className={`absolute rounded-[12px] px-3.5 py-2 ${accepted ? "bg-[#d3e3fd] text-[#041e49]" : "border-2 border-dashed border-[#0b57d0]/50 bg-white text-[#0b57d0]"}`}
            style={{
              left: GUTTER + 3 * COL + 4,
              width: COL - 8,
              top: at(11) + 2,
              height: 0.75 * HOUR - 4,
              opacity: prog(f, 16, 12),
              scale: `${mix(0.9, 1, prog(f, 16, 16))}`,
              boxShadow: accepted ? "inset 4px 0 0 #0b57d0" : undefined,
            }}
          >
            <span className="flex items-center gap-1.5 text-[16px] font-semibold">
              <Brand name="google-meet" size={18} />
              Release sync
            </span>
            <span className="text-[13px] opacity-75">11:00 – 11:45 AM</span>
          </div>
        </div>

        {/* Side panel: the invite, then Cue's prep */}
        <div className="absolute inset-y-0 right-0 w-[480px] border-l border-line bg-paper">
          <div
            className="absolute left-7 top-6 w-[424px] rounded-[22px] border border-line bg-white p-6 shadow-[0_18px_40px_-24px_rgb(15_16_13/0.35)]"
            style={{ opacity: card, translate: `0 ${mix(-24, 0, card)}px`, height: 300 }}
          >
            <span className="flex items-center gap-2.5 text-[16px] text-muted">
              <Brand name="google-meet" size={22} />
              Invitation from Priya K.
            </span>
            <p className="mt-3 text-[32px] font-semibold tracking-[-0.03em] text-ink">Release sync</p>
            <p className="mt-1 text-[18px] text-ink-soft">Thu, Oct 29 · 11:00 – 11:45 AM</p>
            <p className="text-[16px] text-muted">Priya, Arjun, Sam, Cue</p>
            <div className="mt-4 flex gap-2">
              {["Yes", "No", "Maybe"].map((label) => {
                const going = label === "Yes" && accepted;
                return (
                  <span
                    key={label}
                    className={`flex h-[40px] items-center gap-1.5 rounded-full border px-4 text-[16px] font-medium ${
                      going ? "border-[#0b57d0] bg-[#0b57d0] text-white" : "border-line text-ink-soft"
                    }`}
                    style={{ scale: label === "Yes" && press ? "0.92" : "1" }}
                  >
                    {going && <Check className="size-4" strokeWidth={3} />}
                    {going ? "Going" : label}
                  </span>
                );
              })}
            </div>
            <span className="absolute inset-x-6 bottom-5 flex h-[44px] items-center justify-center gap-2 rounded-full bg-[#0b57d0] text-[17px] font-semibold text-white">
              <Video className="size-5" />
              Join with Google Meet
            </span>
          </div>

          <div
            className="absolute left-7 top-[346px] w-[424px] rounded-[22px] border border-line bg-white p-5"
            style={{ opacity: prog(f, 38, 16), translate: `0 ${mix(30, 0, prog(f, 38, 18))}px`, height: 448 }}
          >
            <div className="flex items-center gap-3">
              <CueFace size={38} round={false} />
              <div className="leading-tight">
                <p className="text-[19px] font-semibold text-ink">Prepping for Release sync</p>
                <p className="text-[15px] text-muted">Reading what changed since last time</p>
              </div>
            </div>
            <div className="mt-4 flex flex-col gap-1">
              {prep.map((row) => {
                const shown = prog(f, row.at, 12);
                const state = f >= row.at + 12 ? 1 : f >= row.at ? 0.5 : 0;
                return (
                  <div
                    key={row.title}
                    className="flex h-[66px] items-center gap-3.5 rounded-[14px] px-2"
                    style={{ opacity: mix(0.25, 1, shown), background: state === 0.5 ? "var(--color-paper)" : undefined }}
                  >
                    <span className="grid size-[42px] place-items-center rounded-[12px] border border-line bg-white">
                      <Brand name={row.icon} size={24} />
                    </span>
                    <span className="min-w-0 flex-1 leading-tight">
                      <span className="block text-[17px] font-semibold text-ink">{row.title}</span>
                      <span className="block truncate text-[14.5px] text-muted">{row.detail}</span>
                    </span>
                    <Status f={f} p={state} size={26} />
                  </div>
                );
              })}
            </div>
            <div
              className="absolute inset-x-5 bottom-5 flex h-[48px] items-center gap-2.5 rounded-[14px] bg-lime-soft px-4 text-[16px] font-semibold text-lime-ink"
              style={{ opacity: ready, translate: `0 ${mix(12, 0, ready)}px` }}
            >
              <span className="size-2.5 rounded-full bg-lime-ink" />
              Brief ready · 2 blockers, 1 past decision
            </div>
          </div>
        </div>
      </Window>
    </div>
  );
}
