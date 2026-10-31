"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { ArrowUp, Hash } from "lucide-react";
import type { ReactNode } from "react";
import { AiBadge, CueAvatar, PersonAvatar, people, type PersonId } from "@/components/landing/preview/primitives";
import { Typewriter } from "@/components/ui/typewriter";
import { useStory } from "@/lib/use-story";
import { FeatureCard, type StoryCardProps } from "./feature-card";
import { BrandIcon, MockWindow, TypingDots, ease } from "./mock-kit";

const steps = [
  { name: "idle", hold: 700 },
  { name: "typing", hold: 1700 },
  { name: "asked", hold: 500 },
  { name: "thinking", hold: 1500 },
  { name: "answered", hold: 2600 },
  { name: "thanked", hold: 3400 },
] as const;

const question = "@Cue how's the v2.3 launch tracking? Anything at risk?";

function Message({ from, time, children }: { from: PersonId | "cue"; time: string; children: ReactNode }) {
  return (
    <motion.div
      layout="position"
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease }}
      className="flex gap-2.5"
    >
      {from === "cue" ? <CueAvatar size={32} /> : <PersonAvatar id={from} size={32} />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[13px] font-semibold text-ink">{from === "cue" ? "Cue" : people[from].name}</span>
          {from === "cue" && <AiBadge />}
          <span className="text-[10.5px] text-faint">{time}</span>
        </div>
        <div className="mt-0.5 text-[13px] leading-[1.5] text-ink-soft">{children}</div>
      </div>
    </motion.div>
  );
}

function Sidebar({ cueLive }: { cueLive: boolean }) {
  const channels = ["general", "eng", "launch-v2-3", "design"];
  return (
    <aside className="hidden w-[168px] shrink-0 flex-col gap-4 bg-[#2b2233] px-3 py-4 text-[12.5px] text-white/60 sm:flex">
      <span className="px-2 text-[13.5px] font-semibold text-white">yourteam</span>
      <div>
        <span className="px-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-white/35">Channels</span>
        <ul className="mt-1.5 flex flex-col gap-0.5">
          {channels.map((c) => (
            <li
              key={c}
              className={`flex items-center gap-1.5 rounded-md px-2 py-1 ${c === "launch-v2-3" ? "bg-white/12 font-medium text-white" : ""}`}
            >
              <Hash className="size-3 opacity-60" /> {c}
            </li>
          ))}
        </ul>
      </div>
      <div>
        <span className="px-2 text-[10.5px] font-semibold uppercase tracking-[0.08em] text-white/35">Direct messages</span>
        <ul className="mt-1.5 flex flex-col gap-0.5">
          <li className="flex items-center gap-2 rounded-md px-2 py-1">
            <PersonAvatar id="arjun" size={16} /> Arjun Kumar
          </li>
          <li className="flex items-center gap-2 rounded-md px-2 py-1">
            <PersonAvatar id="sam" size={16} /> Sam R.
          </li>
          <li className={`flex items-center gap-2 rounded-md px-2 py-1 transition-colors duration-500 ${cueLive ? "bg-lime/15 text-white" : ""}`}>
            <CueAvatar size={16} online /> Cue
            <span className="rounded bg-lime/20 px-1 text-[9px] font-semibold uppercase text-lime">AI</span>
          </li>
        </ul>
      </div>
    </aside>
  );
}

export function SlackCard({ active, ...card }: StoryCardProps) {
  const reduce = useReducedMotion() ?? false;
  const { at, is, index, cycle } = useStory(steps, active, reduce);
  const beat = at("answered") ? 2 : at("thinking") ? 1 : 0;
  const cueLive = at("thinking") && !at("thanked");

  return (
    <FeatureCard
      {...card}
      tone={{ bg: "#f3effa", accent: "#6a4cc2", pill: "#e5dcf7" }}
      eyebrow={{ label: "Slack", icons: ["/integrations/slack.svg"] }}
      title={{ lead: "A teammate in", accent: "every conversation." }}
      description="Mention @Cue in any channel or DM. It has read the threads, tickets and PRs it was invited to, and answers right in the thread with sources, the way a colleague who read everything would."
      points={["Replies in the thread, with sources", "Only uses what everyone in the channel can see", "Asks before doing anything others will see"]}
      beats={["Mentioned", "Gathers context", "Replies with sources"]}
      beat={beat}
      previewLabel="Illustration: in a Slack-style channel, Priya asks @Cue how the v2.3 launch is tracking, and Cue replies with progress, the one at-risk ticket and its sources."
    >
      <MockWindow title="launch-v2-3" icon={<BrandIcon src="/integrations/slack.svg" size={14} />}>
        <div className="flex h-full">
          <Sidebar cueLive={cueLive} />
          <div className="flex min-w-0 flex-1 flex-col">
            <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
              <Hash className="size-3.5 text-ink" strokeWidth={2.5} />
              <span className="text-[13.5px] font-semibold text-ink">launch-v2-3</span>
              <span className="ml-auto flex items-center -space-x-1.5">
                <span className="rounded-[10px] ring-2 ring-white"><PersonAvatar id="priya" size={20} /></span>
                <span className="rounded-[10px] ring-2 ring-white"><PersonAvatar id="sam" size={20} /></span>
                <span
                  className={`rounded-[10px] ring-2 transition-[scale,box-shadow] duration-400 ${
                    cueLive ? "scale-115 ring-lime" : "ring-white"
                  }`}
                >
                  <CueAvatar size={20} />
                </span>
              </span>
            </header>

            <div className="relative flex-1 overflow-hidden">
              <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 z-10 h-12 bg-gradient-to-b from-white to-transparent" />
              <motion.div
                key={cycle}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="absolute inset-x-0 bottom-0 flex flex-col gap-4 px-4 pb-3"
              >
                <Message from="sam" time="9:41">
                  Design QA on the new onboarding flow is done ✅
                </Message>
                <Message from="arjun" time="9:52">
                  Heads up, I&apos;m moving to billing full-time from Monday. Handing off my open tickets 👋
                </Message>

                <AnimatePresence>
                  {at("asked") && (
                    <Message key="q" from="priya" time="10:14">
                      <span className="rounded bg-lime-soft px-1 font-medium text-lime-ink">@Cue</span> how&apos;s the v2.3 launch tracking? Anything at risk?
                      {at("thanked") && (
                        <motion.span
                          initial={{ scale: 0 }}
                          animate={{ scale: 1 }}
                          transition={{ type: "spring", stiffness: 500, damping: 22 }}
                          className="mt-1.5 flex w-fit items-center gap-1 rounded-full border border-[#ddd3f3] bg-[#f5f1fc] px-2 py-[1px] text-[11px] text-[#5b44a8]"
                        >
                          🙏 <span className="font-medium">1</span>
                        </motion.span>
                      )}
                    </Message>
                  )}

                  {at("answered") && (
                    <Message key="a" from="cue" time="10:14">
                      We&apos;re on track for Thursday. One ticket is at risk:
                      <motion.div
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ delay: 0.15, duration: 0.4, ease }}
                        className="mt-2 rounded-xl border border-line bg-paper/60 p-3"
                      >
                        <div className="flex items-baseline justify-between text-[12px]">
                          <span className="font-semibold text-ink">v2.3 launch</span>
                          <span className="font-mono text-[11px] text-muted">14 of 17 done · Due Thu</span>
                        </div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-line">
                          <motion.div
                            className="h-full rounded-full bg-[#6a4cc2]"
                            initial={{ width: "0%" }}
                            animate={{ width: "82%" }}
                            transition={{ delay: 0.3, duration: 0.9, ease }}
                          />
                        </div>
                        <p className="mt-2.5 text-[12px] leading-snug text-ink-soft">
                          <span className="mr-1 rounded bg-[#fdecea] px-1 py-[1px] font-mono text-[10.5px] font-semibold text-[#c4553a]">LIN-219</span>
                          Export timeout has no owner since Arjun moved to billing.
                        </p>
                      </motion.div>
                      <span className="mt-1.5 block">Want me to ask in #eng who can pick it up?</span>
                      <span className="mt-1.5 flex flex-wrap gap-1.5">
                        {["Linear · v2.3 cycle", "#launch-v2-3 · Arjun, 9:52"].map((s, i) => (
                          <motion.span
                            key={s}
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            transition={{ delay: 0.5 + i * 0.12 }}
                            className="rounded-md border border-line bg-white px-1.5 py-[2px] text-[10.5px] text-muted"
                          >
                            {s}
                          </motion.span>
                        ))}
                      </span>
                    </Message>
                  )}
                </AnimatePresence>

                <div className="h-4 text-[11px] text-muted">
                  <AnimatePresence>
                    {is("thinking") && (
                      <motion.span
                        initial={{ opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        className="flex items-center gap-1.5"
                      >
                        <TypingDots className="text-[#6a4cc2]" />
                        <span>
                          <span className="font-semibold text-ink-soft">Cue</span> is typing…
                        </span>
                      </motion.span>
                    )}
                  </AnimatePresence>
                </div>
              </motion.div>
            </div>

            <div className="border-t border-line px-3 pb-3 pt-2.5">
              <div
                className={`flex items-center gap-2 rounded-xl border px-3 py-2 transition-colors duration-300 ${
                  is("typing") ? "border-ink/25" : "border-line"
                }`}
              >
                <span className="min-w-0 flex-1 truncate text-[12.5px]">
                  {is("typing") ? (
                    <span className="text-ink">
                      <Typewriter key={index} text={question} ms={1400} />
                      <span className="ml-px inline-block h-[1em] w-[1.5px] translate-y-[2px] animate-pulse bg-ink" />
                    </span>
                  ) : (
                    <span className="text-faint">Message #launch-v2-3</span>
                  )}
                </span>
                <span className={`grid size-6 place-items-center rounded-md ${is("typing") ? "bg-ink text-lime" : "bg-paper-deep text-faint"}`}>
                  <ArrowUp className="size-3" strokeWidth={2.5} />
                </span>
              </div>
            </div>
          </div>
        </div>
      </MockWindow>
    </FeatureCard>
  );
}
