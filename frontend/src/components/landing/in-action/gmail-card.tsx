"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Check, Inbox, Pencil, Send, Star } from "lucide-react";
import { useRef, type ReactNode } from "react";
import { CueAvatar, PersonAvatar } from "@/components/landing/preview/primitives";
import { Typewriter } from "@/components/ui/typewriter";
import { useStory } from "@/lib/use-story";
import { FeatureCard, type StoryCardProps } from "./feature-card";
import { BrandIcon, GuideCursor, MockWindow, Toast, ease, usePoint } from "./mock-kit";

const steps = [
  { name: "idle", hold: 800 },
  { name: "arrived", hold: 1400 },
  { name: "opened", hold: 1700 },
  { name: "reading", hold: 1900 },
  { name: "drafting", hold: 3200 },
  { name: "approval", hold: 1500 },
  { name: "approving", hold: 700 },
  { name: "sent", hold: 3400 },
] as const;

const draft =
  "Hi Dana, SSO ships in our v2.3 release this Thursday. Your admins will find it under Settings › Security the same day, and I can send a setup guide ahead of your training. Best, Cue (for Priya)";

const inbox = [
  { from: "GitHub", subject: "[yourteam/web] Review requested on #418", time: "10:41" },
  { from: "Linear", subject: "Weekly cycle summary · v2.3", time: "09:30" },
  { from: "Arjun Kumar", subject: "Billing handoff notes", time: "Tue" },
  { from: "Calendar", subject: "Invitation: v2.3 go / no-go", time: "Mon" },
];

function DanaAvatar({ size = 28 }: { size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full font-semibold text-ink/70"
      style={{ width: size, height: size, background: "#cfe6d6", fontSize: size * 0.36 }}
    >
      DW
    </span>
  );
}

function Mail({ avatar, from, meta, children }: { avatar: ReactNode; from: string; meta: string; children: ReactNode }) {
  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease }}
      className="flex gap-2.5 border-b border-line-soft pb-3"
    >
      {avatar}
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-[12.5px] font-semibold text-ink">{from}</span>
          <span className="truncate text-[10.5px] text-faint">{meta}</span>
        </div>
        <p className="mt-0.5 text-[12px] leading-[1.5] text-ink-soft">{children}</p>
      </div>
    </motion.div>
  );
}

export function GmailCard({ active, ...card }: StoryCardProps) {
  const reduce = useReducedMotion() ?? false;
  const { at, is, cycle } = useStory(steps, active, reduce);
  const beat = at("approval") ? 3 : at("drafting") ? 2 : at("reading") ? 1 : 0;

  const stage = useRef<HTMLDivElement>(null);
  const approve = useRef<HTMLButtonElement>(null);
  const point = usePoint(stage, approve, at("approval") && !at("sent"));
  const sent = at("sent");

  const checks = ["Thread · 2 messages", "Linear · SSO is in v2.3", "Release calendar · ships Thu"];

  return (
    <FeatureCard
      {...card}
      tone={{ bg: "#fbf0ea", accent: "#bf4f2b", pill: "#f6ddd1" }}
      eyebrow={{ label: "Gmail", icons: ["/integrations/gmail.svg"] }}
      title={{ lead: "Your inbox", accent: "has a teammate." }}
      description="CC cue@yourteam.com on any thread. Cue reads the history, checks the facts across your tools and drafts the reply. Anything that leaves the company waits for your approval."
      points={["Drafts in context, from its own address", "External emails always need your approval", "Every send is logged for audit"]}
      beats={["CC'd", "Reads the thread", "Drafts a reply", "You approve"]}
      beat={beat}
      previewLabel="Illustration: Cue's inbox, where Priya CCs Cue on a customer email about SSO. Cue reads the thread, checks the release date, drafts a reply, and sends it only after Priya approves."
    >
      <MockWindow title="Inbox · cue@yourteam.com" icon={<BrandIcon src="/integrations/gmail.svg" size={14} />}>
        <div ref={stage} key={cycle} className="relative flex h-full">
          {/* Folder rail */}
          <aside className="hidden w-[52px] shrink-0 flex-col items-center gap-3 border-r border-line bg-paper/60 py-4 text-muted lg:flex">
            <span className="relative grid size-8 place-items-center rounded-lg bg-[#fde8e3] text-[#bf4f2b]">
              <Inbox className="size-4" />
              <AnimatePresence>
                {at("arrived") && !at("opened") && (
                  <motion.span
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    exit={{ scale: 0 }}
                    className="absolute -right-1 -top-1 grid size-4 place-items-center rounded-full bg-[#bf4f2b] text-[9px] font-semibold text-white"
                  >
                    1
                  </motion.span>
                )}
              </AnimatePresence>
            </span>
            <Star className="size-4" />
            <Send className="size-4" />
            <Pencil className="size-4" />
          </aside>

          {/* Message list */}
          <div className="hidden w-[40%] shrink-0 flex-col border-r border-line md:flex">
            <AnimatePresence initial={false}>
              {at("arrived") && (
                <motion.div
                  key="new"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  transition={{ duration: 0.5, ease }}
                  className="overflow-hidden"
                >
                  <div
                    className={`border-b border-line px-3 py-2.5 transition-colors duration-500 ${
                      at("opened") ? "bg-[#fdf3ee] shadow-[inset_3px_0_0_#bf4f2b]" : "bg-lime-wash"
                    }`}
                  >
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-[12px] font-semibold text-ink">Priya K., Dana W.</span>
                      <span className="text-[10px] text-faint">10:52</span>
                    </div>
                    <p className="truncate text-[11.5px] font-semibold text-ink">Re: SSO rollout timeline</p>
                    <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted">
                      <span className="rounded bg-ink px-1 text-[9px] font-semibold text-lime">cc: you</span>
                      <span className="truncate">Looping in Cue, who can…</span>
                    </p>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            {inbox.map((m) => (
              <motion.div layout="position" key={m.subject} className="border-b border-line-soft px-3 py-2.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-[12px] text-ink-soft">{m.from}</span>
                  <span className="text-[10px] text-faint">{m.time}</span>
                </div>
                <p className="truncate text-[11.5px] text-muted">{m.subject}</p>
              </motion.div>
            ))}
          </div>

          {/* Thread */}
          <div className="relative flex min-w-0 flex-1 flex-col">
            <AnimatePresence mode="wait">
              {!at("opened") ? (
                <motion.div
                  key="empty"
                  exit={{ opacity: 0 }}
                  className="grid flex-1 place-items-center p-6 text-center text-[12px] text-faint"
                >
                  <span>
                    <Inbox className="mx-auto mb-2 size-6 text-line" />
                    Threads Cue is copied on show up here.
                  </span>
                </motion.div>
              ) : (
                <motion.div
                  key="thread"
                  initial={{ opacity: 0, x: 12 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ duration: 0.45, ease }}
                  className="flex min-h-0 flex-1 flex-col"
                >
                  <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                    <span className="truncate text-[13.5px] font-semibold tracking-[-0.01em] text-ink">Re: SSO rollout timeline</span>
                    <span className="shrink-0 rounded-full bg-[#fdebe4] px-1.5 py-[1px] text-[10px] font-medium text-[#bf4f2b]">External</span>
                  </div>
                  <div className="relative flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-hidden px-4 pb-3 pt-3">
                    <Mail avatar={<DanaAvatar />} from="Dana Whitfield" meta="dana@fieldstone.co">
                      Hi Priya, can you confirm when SSO will be live for our workspace? We&apos;d like to book admin training.
                    </Mail>
                    <Mail avatar={<PersonAvatar id="priya" size={28} />} from="Priya K." meta="to Dana · cc Cue">
                      Looping in Cue, who can confirm the date. Cue, can you draft a reply?
                    </Mail>

                    <AnimatePresence>
                      {at("reading") && !at("drafting") && (
                        <motion.div
                          key="reading"
                          initial={{ opacity: 0, y: 8 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, height: 0 }}
                          className="flex flex-col gap-1.5 rounded-xl bg-paper p-2.5"
                        >
                          <span className="flex items-center gap-2 text-[11.5px] font-medium text-ink">
                            <CueAvatar size={18} />
                            <span className="text-shimmer">Reading the thread and checking the facts…</span>
                          </span>
                          {checks.map((c, i) => (
                            <motion.span
                              key={c}
                              initial={{ opacity: 0, x: -6 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ delay: 0.3 + i * 0.4, duration: 0.35 }}
                              className="flex items-center gap-1.5 pl-6 text-[11px] text-muted"
                            >
                              <Check className="size-3 text-[#6b8a12]" strokeWidth={3} /> {c}
                            </motion.span>
                          ))}
                        </motion.div>
                      )}

                      {at("drafting") && (
                        <motion.div
                          key="draft"
                          layout
                          initial={{ opacity: 0, y: 10 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.45, ease }}
                          className={`overflow-hidden rounded-xl border ${sent ? "border-line-soft bg-white" : "border-line bg-white shadow-card"}`}
                        >
                          <div className="flex items-center gap-2 border-b border-line-soft px-3 py-2 text-[11px] text-muted">
                            <CueAvatar size={18} />
                            <span className="font-semibold text-ink">Cue</span>
                            <span className="truncate">to dana@fieldstone.co · cc Priya</span>
                            <span
                              className={`ml-auto shrink-0 rounded-full px-1.5 py-[1px] text-[10px] font-medium ${
                                sent ? "bg-lime text-ink" : "bg-paper-deep text-muted"
                              }`}
                            >
                              {sent ? "Sent" : "Draft"}
                            </span>
                          </div>
                          <p className="px-3 py-2.5 text-[12px] leading-[1.55] text-ink-soft">
                            {at("approval") ? draft : <Typewriter text={draft} ms={2700} />}
                            {is("drafting") && <span className="ml-px inline-block h-[1em] w-[1.5px] translate-y-[2px] animate-pulse bg-ink" />}
                          </p>
                          <AnimatePresence>
                            {at("approval") && !sent && (
                              <motion.div
                                initial={{ opacity: 0, height: 0 }}
                                animate={{ opacity: 1, height: "auto" }}
                                exit={{ opacity: 0, height: 0 }}
                                transition={{ duration: 0.35, ease }}
                                className="overflow-hidden"
                              >
                                <div className="flex flex-wrap items-center gap-2 border-t border-[#f3d9cd] bg-[#fdf3ee] px-3 py-2">
                                  <span className="mr-auto text-[11px] font-medium text-[#9a3d1f]">
                                    Leaves the company · needs Priya&apos;s OK
                                  </span>
                                  <motion.button
                                    ref={approve}
                                    type="button"
                                    tabIndex={-1}
                                    animate={is("approving") ? { scale: 0.94, backgroundColor: "#d9f25c", color: "#0f100d" } : { scale: 1 }}
                                    className="rounded-lg bg-ink px-2.5 py-1 text-[11px] font-medium text-paper"
                                  >
                                    Approve &amp; send
                                  </motion.button>
                                  <span className="rounded-lg border border-line bg-white px-2.5 py-1 text-[11px] font-medium text-ink-soft">Edit</span>
                                </div>
                              </motion.div>
                            )}
                          </AnimatePresence>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>

          <Toast show={is("arrived")} className="right-3 top-3">
            <BrandIcon src="/integrations/gmail.svg" size={13} /> Priya cc&apos;d you · Re: SSO rollout timeline
          </Toast>
          <Toast show={sent} className="right-3 top-3">
            <Check className="size-3.5 text-lime" strokeWidth={3} /> Sent from cue@yourteam.com · approved by Priya
          </Toast>
          <GuideCursor point={point} show={at("approval") && !sent} pressing={is("approving")} name="Priya" color="#f0b48a" />
        </div>
      </MockWindow>
    </FeatureCard>
  );
}
