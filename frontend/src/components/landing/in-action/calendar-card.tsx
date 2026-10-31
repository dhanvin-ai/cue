"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { useRef } from "react";
import { CueAvatar, PersonAvatar } from "@/components/landing/preview/primitives";
import { useStory } from "@/lib/use-story";
import { FeatureCard, type StoryCardProps } from "./feature-card";
import { BrandIcon, GuideCursor, MockWindow, Toast, ease, usePoint } from "./mock-kit";

const steps = [
  { name: "idle", hold: 700 },
  { name: "spotted", hold: 1300 },
  { name: "brief", hold: 1300 },
  { name: "items", hold: 2300 },
  { name: "request", hold: 1600 },
  { name: "proposed", hold: 1700 },
  { name: "approving", hold: 700 },
  { name: "booked", hold: 3400 },
] as const;

const days = [
  { label: "Mon", date: 26, narrow: false },
  { label: "Tue", date: 27, narrow: false },
  { label: "Wed", date: 28, narrow: true },
  { label: "Thu", date: 29, narrow: true },
  { label: "Fri", date: 30, narrow: true },
];

const firstHour = 9;
const hours = 8;

type CalEvent = { id: string; day: number; start: number; end: number; title: string; tint: string; ink: string };

const events: CalEvent[] = [
  { id: "s1", day: 0, start: 9.5, end: 10, title: "Standup", tint: "#eef0e6", ink: "#4d5340" },
  { id: "cust", day: 0, start: 14, end: 15, title: "Customer call", tint: "#fdeee6", ink: "#9a4a25" },
  { id: "design", day: 1, start: 10, end: 11, title: "Design review", tint: "#efe9fb", ink: "#5b44a8" },
  { id: "s2", day: 2, start: 9.5, end: 10, title: "Standup", tint: "#eef0e6", ink: "#4d5340" },
  { id: "1on1", day: 2, start: 13, end: 13.5, title: "1:1 Priya / Sam", tint: "#e8f1fb", ink: "#2f5f99" },
  { id: "gonogo", day: 3, start: 11, end: 12, title: "v2.3 go / no-go", tint: "#dcebfb", ink: "#1f4f8a" },
  { id: "pricing", day: 3, start: 14, end: 15, title: "Pricing review", tint: "#fdeee6", ink: "#9a4a25" },
  { id: "retro", day: 4, start: 10, end: 10.5, title: "Retro", tint: "#efe9fb", ink: "#5b44a8" },
];

const now = 10.75; // Thursday, 10:45
const today = 3;

const pos = (start: number, end: number) => ({
  top: `${((start - firstHour) / hours) * 100}%`,
  height: `${((end - start) / hours) * 100}%`,
});

const actionItems = [
  { who: "arjun" as const, text: "Merge the #418 fix", state: "Open" },
  { who: "sam" as const, text: "Release notes draft", state: "Done" },
  { who: "priya" as const, text: "Confirm launch email", state: "Open" },
];

function Panel({ at }: { at: (name: (typeof steps)[number]["name"]) => boolean }) {
  const scheduling = at("request");
  return (
    <AnimatePresence mode="wait" initial={false}>
      {!scheduling ? (
        <motion.div
          key="brief"
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -12 }}
          transition={{ duration: 0.45, ease }}
          className="flex h-full flex-col gap-3 p-3.5"
        >
          <div className="flex items-center gap-2">
            <CueAvatar size={22} />
            <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Brief · in 15 min</span>
          </div>
          <div>
            <p className="text-[14px] font-semibold tracking-[-0.02em] text-ink">v2.3 go / no-go</p>
            <p className="text-[11.5px] text-muted">Thu 11:00 · 4 attendees</p>
            <div className="mt-2 flex -space-x-1">
              {(["priya", "arjun", "sam"] as const).map((p) => (
                <span key={p} className="rounded-[9px] ring-2 ring-white"><PersonAvatar id={p} size={20} /></span>
              ))}
              <span className="rounded-[9px] ring-2 ring-white"><CueAvatar size={20} /></span>
            </div>
          </div>
          <div className="rounded-xl bg-paper p-2.5 text-[11.5px] leading-snug text-ink-soft">
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Since last sync</p>
            <p>PR #418 still failing on CI</p>
            <p>LIN-219 has no owner</p>
          </div>
          <div>
            <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Open action items</p>
            <ul className="flex flex-col gap-1">
              {actionItems.map((a, i) => (
                <motion.li
                  key={a.text}
                  initial={{ opacity: 0, y: 6 }}
                  animate={at("items") ? { opacity: 1, y: 0 } : { opacity: 0, y: 6 }}
                  transition={{ delay: i * 0.25, duration: 0.4, ease }}
                  className={`flex items-center gap-2 rounded-lg px-1.5 py-1 text-[11.5px] ${a.state === "Open" ? "bg-[#eaf3fd]" : ""}`}
                >
                  <PersonAvatar id={a.who} size={16} />
                  <span className={`min-w-0 flex-1 truncate ${a.state === "Done" ? "text-faint line-through" : "text-ink"}`}>{a.text}</span>
                  <span className={`text-[10px] font-medium ${a.state === "Done" ? "text-faint" : "text-[#1f4f8a]"}`}>{a.state}</span>
                </motion.li>
              ))}
            </ul>
          </div>
        </motion.div>
      ) : (
        <motion.div
          key="schedule"
          initial={{ opacity: 0, x: 16 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.45, ease }}
          className="flex h-full flex-col gap-3 p-3.5"
        >
          <div className="flex gap-2">
            <PersonAvatar id="priya" size={22} />
            <p className="rounded-xl rounded-tl-sm bg-paper px-2.5 py-2 text-[11.5px] leading-snug text-ink">
              Find 30 min with Arjun and Sam about the billing handoff this week.
              <span className="mt-1 block text-[10px] text-faint">via Slack</span>
            </p>
          </div>
          <AnimatePresence>
            {at("proposed") && (
              <motion.div
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, ease }}
                className="flex gap-2"
              >
                <CueAvatar size={22} />
                <div className="min-w-0 flex-1 text-[11.5px] leading-snug text-ink-soft">
                  Everyone&apos;s free <span className="font-semibold text-ink">Fri 2:00–2:30</span>. Send the invite?
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function CalendarCard({ active, ...card }: StoryCardProps) {
  const reduce = useReducedMotion() ?? false;
  const { at, is, cycle } = useStory(steps, active, reduce);
  const beat = at("request") ? 2 : at("brief") ? 1 : 0;

  const stage = useRef<HTMLDivElement>(null);
  const approve = useRef<HTMLButtonElement>(null);
  const point = usePoint(stage, approve, at("proposed") && !at("booked"));

  const highlight = at("spotted") && !at("request");
  const booked = at("booked");

  return (
    <FeatureCard
      {...card}
      tone={{ bg: "#edf4fc", accent: "#2b67b0", pill: "#d9e8f8" }}
      eyebrow={{ label: "Calendar", icons: ["/integrations/google-calendar.svg"] }}
      title={{ lead: "Always", accent: "one step ahead." }}
      description="Cue keeps its own calendar, and yours if you share it. Before you meet, it sends a brief. When you ask for time with someone, it finds the slot and waits for your OK before anyone gets an invite."
      points={["A brief 15 minutes before every meeting", "Open action items from the last time you met", "Invites go out only after you approve"]}
      beats={["Spots the meeting", "Prepares a brief", "Schedules on approval"]}
      beat={beat}
      previewLabel="Illustration: a weekly calendar where Cue highlights an upcoming meeting, opens a brief with open action items, then proposes a Friday slot that Priya approves."
    >
      <MockWindow
        title="Week of Oct 26"
        icon={<BrandIcon src="/integrations/google-calendar.svg" size={14} />}
        aside={
          <span className="flex items-center gap-1 text-faint">
            <ChevronLeft className="size-3.5" />
            <ChevronRight className="size-3.5" />
          </span>
        }
      >
        <div ref={stage} className="relative flex h-full">
          <div key={cycle} className="flex min-w-0 flex-1 flex-col">
            {/* Day headers */}
            <div className="flex border-b border-line pl-9">
              {days.map((d, i) => (
                <div key={d.label} className={`flex-1 py-2 text-center ${d.narrow ? "" : "hidden sm:block"}`}>
                  <span className="block text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">{d.label}</span>
                  <span
                    className={`mx-auto mt-0.5 grid size-6 place-items-center rounded-full text-[12.5px] font-semibold ${
                      i === today ? "bg-[#2b67b0] text-white" : "text-ink"
                    }`}
                  >
                    {d.date}
                  </span>
                </div>
              ))}
            </div>

            {/* Grid */}
            <div className="relative flex min-h-0 flex-1">
              <div className="relative w-9 shrink-0">
                {Array.from({ length: hours }, (_, h) => (
                  <span
                    key={h}
                    className="absolute right-1.5 -translate-y-1/2 text-[9.5px] text-faint"
                    style={{ top: `${(h / hours) * 100}%` }}
                  >
                    {h === 0 ? "" : `${((firstHour + h - 1) % 12) + 1}${firstHour + h >= 12 ? "p" : "a"}`}
                  </span>
                ))}
              </div>
              <div className="relative flex flex-1">
                {Array.from({ length: hours }, (_, h) => (
                  <span key={h} className="absolute inset-x-0 border-t border-line-soft" style={{ top: `${(h / hours) * 100}%` }} />
                ))}
                {days.map((d, di) => (
                  <div key={d.label} className={`relative flex-1 border-l border-line-soft ${d.narrow ? "" : "hidden sm:block"}`}>
                    {events
                      .filter((e) => e.day === di)
                      .map((e) => {
                        const target = e.id === "gonogo";
                        return (
                          <motion.div
                            key={e.id}
                            className="absolute inset-x-1 overflow-hidden rounded-md px-1.5 py-1"
                            style={{ ...pos(e.start, e.end), background: e.tint, color: e.ink }}
                            animate={{
                              boxShadow: target && highlight ? "0 0 0 2px #d9f25c, 0 8px 20px -8px rgba(15,16,13,0.35)" : "0 0 0 0px rgba(0,0,0,0)",
                              scale: target && highlight ? 1.04 : 1,
                              opacity: highlight && !target ? 0.55 : 1,
                            }}
                            transition={{ duration: 0.45, ease }}
                          >
                            <span className="line-clamp-2 break-words text-[10px] font-semibold leading-[1.15]">{e.title}</span>
                            {e.end - e.start >= 1 && !(target && highlight) && (
                              <span className="block text-[9px] opacity-70">
                                {e.start > 12 ? e.start - 12 : e.start}:00
                              </span>
                            )}
                            {target && highlight && (
                              <motion.span
                                initial={{ opacity: 0, y: 4 }}
                                animate={{ opacity: 1, y: 0 }}
                                className="absolute bottom-1 left-1.5 flex items-center gap-1 rounded-full bg-ink px-1.5 py-[1px] text-[9px] font-medium text-lime"
                              >
                                <CueAvatar size={10} /> Briefing
                              </motion.span>
                            )}
                          </motion.div>
                        );
                      })}

                    {di === 4 && at("proposed") && (
                      <motion.div
                        initial={{ opacity: 0, scale: 0.9 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ duration: 0.4, ease }}
                        className={`absolute inset-x-1 rounded-md px-1.5 py-1 transition-colors duration-500 ${
                          booked ? "bg-lime text-ink" : "border-[1.5px] border-dashed border-[#2b67b0] bg-white/70 text-[#1f4f8a]"
                        }`}
                        style={pos(14, 14.75)}
                      >
                        <span className="flex items-start gap-1 text-[10px] font-semibold leading-[1.15]">
                          {booked && <Check className="size-3 shrink-0" strokeWidth={3} />}
                          <span className="line-clamp-2">Billing handoff</span>
                        </span>
                        <span className="block truncate text-[9px] opacity-70">{booked ? "Invite sent" : "Proposed"}</span>
                      </motion.div>
                    )}

                    {di === today && (
                      <div className="pointer-events-none absolute inset-x-0 z-10" style={{ top: pos(now, now).top }}>
                        <span className="absolute -left-1 -top-1 size-2 rounded-full bg-[#e5533b]" />
                        <span className="block h-[1.5px] bg-[#e5533b]" />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Cue's side panel: a sheet on phones, a column on larger screens */}
          <AnimatePresence>
            {at("brief") && (
              <motion.aside
                initial={{ opacity: 0, x: 40 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: 40 }}
                transition={{ duration: 0.5, ease }}
                className="absolute inset-x-2 bottom-2 z-20 flex h-[56%] flex-col overflow-hidden rounded-2xl border border-line bg-white shadow-[0_20px_40px_-16px_rgb(15_16_13/0.35)] sm:static sm:inset-auto sm:h-auto sm:w-[232px] sm:shrink-0 sm:rounded-none sm:border-0 sm:border-l sm:shadow-none"
              >
                <div className="min-h-0 flex-1 overflow-hidden">
                  <Panel at={at} />
                </div>
                <AnimatePresence>
                  {at("proposed") && (
                    <motion.div
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      transition={{ duration: 0.4, ease }}
                      className="m-3 mt-0 rounded-xl border border-line bg-white p-2.5 shadow-card"
                    >
                      <p className="text-[11.5px] font-semibold text-ink">Send invite · Billing handoff</p>
                      <p className="text-[10.5px] text-muted">Fri 2:00–2:30 · Arjun, Sam</p>
                      {booked ? (
                        <p className="mt-2 flex items-center gap-1.5 text-[11.5px] font-semibold text-ink">
                          <span className="grid size-4 place-items-center rounded-full bg-lime"><Check className="size-2.5" strokeWidth={3.5} /></span>
                          Invite sent
                        </p>
                      ) : (
                        <motion.button
                          ref={approve}
                          type="button"
                          tabIndex={-1}
                          animate={is("approving") ? { scale: 0.94, backgroundColor: "#d9f25c", color: "#0f100d" } : { scale: 1 }}
                          className="mt-2 w-full rounded-lg bg-ink py-1.5 text-[11.5px] font-medium text-paper"
                        >
                          Approve
                        </motion.button>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </motion.aside>
            )}
          </AnimatePresence>

          <GuideCursor point={point} show={at("proposed") && !booked} pressing={is("approving")} name="Priya" color="#f0b48a" />
          <Toast show={booked} className="left-1/2 top-3 -translate-x-1/2 whitespace-nowrap">
            <Check className="size-3.5 text-lime" strokeWidth={3} /> Invite sent from Cue&apos;s calendar
          </Toast>
        </div>
      </MockWindow>
    </FeatureCard>
  );
}
