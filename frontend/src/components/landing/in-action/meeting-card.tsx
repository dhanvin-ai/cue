"use client";

import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { Captions, Check, Hand, MessageSquare, Mic, MicOff, PhoneOff, Users, Video } from "lucide-react";
import type { ReactNode } from "react";
import { CueAvatar, PersonAvatar, people, type PersonId } from "@/components/landing/preview/primitives";
import { SpokenWords } from "@/components/ui/typewriter";
import { useStory } from "@/lib/use-story";
import { FeatureCard, type StoryCardProps } from "./feature-card";
import { BrandIcon, MockWindow, Toast, ease } from "./mock-kit";

const steps = [
  { name: "idle", hold: 1000 },
  { name: "joining", hold: 1300 },
  { name: "joined", hold: 1600 },
  { name: "question", hold: 2300 },
  { name: "thinking", hold: 800 },
  { name: "answering", hold: 3800 },
  { name: "chat", hold: 2300 },
  { name: "reply", hold: 1900 },
  { name: "notes", hold: 4400 },
] as const;

type Step = (typeof steps)[number]["name"];

const lines: Partial<Record<Step, { who: PersonId | "cue"; text: string; ms: number }>> = {
  idle: { who: "sam", text: "Design QA is signed off on our side.", ms: 900 },
  question: { who: "priya", text: "Cue, what's blocking our release?", ms: 1300 },
  answering: {
    who: "cue",
    text: "Just one thing. PR 418 has a flaky login test failing on CI. Arjun's fix is in review, so we can ship as soon as it merges.",
    ms: 3300,
  },
  reply: { who: "arjun", text: "I'll merge it right after this call.", ms: 1300 },
};

const tileTint: Record<PersonId, string> = {
  priya: "linear-gradient(160deg,#3a2a22,#1d1714)",
  arjun: "linear-gradient(160deg,#1f2c3a,#13181f)",
  sam: "linear-gradient(160deg,#2c2440,#16131f)",
};

function Waveform({ mode, live }: { mode: "listening" | "speaking"; live: boolean }) {
  const bars = [0.5, 0.8, 0.6, 1, 0.7, 0.9, 0.55, 0.85, 0.65, 0.75];
  return (
    <span className="flex h-7 items-center gap-[3px]">
      {bars.map((h, i) => (
        <motion.span
          key={i}
          className="w-[3px] rounded-full bg-lime"
          style={{ height: `${h * 100}%`, originY: 0.5 }}
          animate={
            !live
              ? { scaleY: mode === "speaking" ? h : 0.18 }
              : mode === "speaking"
                ? { scaleY: [h, 0.25, 0.9, 0.4, h] }
                : { scaleY: [0.12, 0.22, 0.12] }
          }
          transition={{
            duration: mode === "speaking" ? 0.9 + (i % 4) * 0.12 : 1.8,
            repeat: live ? Infinity : 0,
            ease: "easeInOut",
            delay: i * 0.05,
          }}
        />
      ))}
    </span>
  );
}

function PersonTile({ id, speaking, className }: { id: PersonId; speaking: boolean; className?: string }) {
  return (
    <motion.div
      layout
      transition={{ layout: { duration: 0.6, ease } }}
      className={`relative grid place-items-center overflow-hidden rounded-xl transition-shadow duration-300 ${
        speaking ? "shadow-[0_0_0_2px_#8fb8f5]" : ""
      } ${className ?? ""}`}
      style={{ background: tileTint[id] }}
    >
      <motion.span layout="position" className="grid place-items-center rounded-full ring-4 ring-white/5">
        <PersonAvatar id={id} size={48} />
      </motion.span>
      <span className="absolute bottom-2 left-2 flex items-center gap-1 rounded-md bg-black/45 px-1.5 py-[2px] text-[10.5px] font-medium text-white/90">
        {speaking ? <Mic className="size-3 text-[#8fb8f5]" /> : <MicOff className="size-3 text-white/45" />}
        {people[id].name}
      </span>
    </motion.div>
  );
}

function CueTile({ status, live }: { status: "listening" | "thinking" | "speaking"; live: boolean }) {
  const speaking = status === "speaking";
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.85 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.9 }}
      transition={{ duration: 0.6, ease, layout: { duration: 0.6, ease } }}
      className={`relative grid place-items-center overflow-hidden rounded-xl bg-[radial-gradient(circle_at_50%_40%,#2b3214,#121410_70%)] transition-shadow duration-300 ${
        speaking ? "shadow-[0_0_0_2px_#d9f25c,0_0_40px_-6px_rgb(217_242_92/0.5)]" : "shadow-[0_0_0_1px_rgb(217_242_92/0.2)]"
      }`}
    >
      <div className="flex flex-col items-center gap-2">
        <motion.span
          className="rounded-[14px] ring-4 ring-lime/15"
          animate={live ? { scale: speaking ? [1, 1.06, 1] : [1, 1.025, 1] } : { scale: 1 }}
          transition={{ duration: speaking ? 0.9 : 2.6, repeat: live ? Infinity : 0, ease: "easeInOut" }}
        >
          <CueAvatar size={48} />
        </motion.span>
        <Waveform mode={speaking ? "speaking" : "listening"} live={live} />
      </div>
      <span className="absolute left-2 top-2 rounded-full bg-black/45 px-2 py-[2px] text-[10px] font-medium text-lime">
        {status === "thinking" ? "Pulling that up…" : speaking ? "Speaking" : "Listening"}
      </span>
      <span className="absolute bottom-2 left-2 flex items-center gap-1.5 rounded-md bg-black/45 px-1.5 py-[2px] text-[10.5px] font-medium text-white/90">
        Cue
        <span className="rounded-[4px] bg-lime px-1 text-[9px] font-semibold uppercase tracking-[0.04em] text-ink">AI teammate</span>
      </span>
    </motion.div>
  );
}

function PrCard() {
  return (
    <div className="mt-1.5 rounded-lg border border-white/10 bg-white/[0.04] p-2">
      <span className="flex items-center gap-1.5 text-[10.5px] text-white/50">
        <BrandIcon src="/integrations/github.svg" size={12} className="invert" />
        yourteam/web · #418
      </span>
      <span className="mt-0.5 block text-[12px] font-semibold text-white">Fix session timeout</span>
      <span className="mt-1 flex items-center gap-1.5 text-[10.5px] text-[#f0a090]">
        <span className="size-1.5 rounded-full bg-[#e5533b]" />1 failing check · login test (flaky)
      </span>
    </div>
  );
}

function ChatMessage({ children }: { children: ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease }}
      className="flex gap-2"
    >
      <CueAvatar size={22} />
      <div className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-[11px] font-semibold text-white">
          Cue <span className="rounded-[4px] bg-lime/20 px-1 text-[8.5px] font-semibold uppercase text-lime">AI</span>
        </span>
        <div className="mt-0.5 text-[11.5px] leading-snug text-white/70">{children}</div>
      </div>
    </motion.div>
  );
}

function Notes() {
  const actions = [
    { who: "arjun" as const, text: "Merge the #418 fix", due: "Today", confirmed: true },
    { who: "sam" as const, text: "Publish release notes", due: "Fri", confirmed: true },
    { who: "priya" as const, text: "Send the launch email", due: "Thu", confirmed: false },
  ];
  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: 20 }}
      transition={{ duration: 0.6, ease }}
      className="absolute inset-2 z-20 flex flex-col overflow-hidden rounded-xl bg-white p-4 shadow-[0_30px_60px_-20px_rgb(0_0_0/0.6)] sm:inset-3 sm:p-5"
    >
      <div className="flex items-center gap-2">
        <CueAvatar size={26} />
        <div className="min-w-0">
          <p className="text-[13.5px] font-semibold tracking-[-0.02em] text-ink">Notes · v2.3 go / no-go</p>
          <p className="truncate text-[11px] text-muted">Sent to #eng and all attendees · 4 min after the call</p>
        </div>
      </div>
      <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Decision</p>
      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.3 }}
        className="mt-1 rounded-lg bg-lime-wash px-2.5 py-2 text-[12.5px] font-medium text-ink"
      >
        Ship v2.3 on Thursday once #418 is green.
      </motion.p>
      <p className="mt-4 text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">Action items</p>
      <ul className="mt-1.5 flex flex-col gap-1">
        {actions.map((a, i) => (
          <motion.li
            key={a.text}
            initial={{ opacity: 0, x: -8 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.45 + i * 0.15, duration: 0.4, ease }}
            className="flex items-center gap-2 rounded-lg px-1.5 py-1.5 text-[12px]"
          >
            <PersonAvatar id={a.who} size={20} />
            <span className="min-w-0 flex-1 truncate text-ink">{a.text}</span>
            <span className="font-mono text-[10.5px] text-muted">{a.due}</span>
            <span
              className={`flex items-center gap-1 rounded-full px-1.5 py-[1px] text-[10px] font-medium ${
                a.confirmed ? "bg-lime text-ink" : "bg-paper-deep text-muted"
              }`}
            >
              {a.confirmed && <Check className="size-2.5" strokeWidth={3.5} />}
              {a.confirmed ? "Confirmed" : "Asked in Slack"}
            </span>
          </motion.li>
        ))}
      </ul>
      <p className="mt-auto pt-3 text-[10.5px] text-faint">Owners come from people confirming, not from Cue guessing.</p>
    </motion.div>
  );
}

export function MeetingCard({ active, ...card }: StoryCardProps) {
  const reduce = useReducedMotion() ?? false;
  const { at, is, index, cycle } = useStory(steps, active, reduce);
  const live = active && !reduce;

  const current = steps[index].name;
  const line = lines[current];
  const cueIn = at("joining");
  const cueStatus = is("thinking") ? "thinking" : is("answering") ? "speaking" : "listening";
  const beat = at("notes") ? 4 : at("chat") ? 3 : at("thinking") ? 2 : at("joined") ? 1 : 0;

  return (
    <FeatureCard
      {...card}
      featured
      tone={{ bg: "#f2f7d9", accent: "#55640a", pill: "#e3efa6" }}
      eyebrow={{ label: "Google Meet & Zoom", icons: ["/integrations/google-meet.svg", "/integrations/zoom.svg"] }}
      title={{ lead: "Not just taking notes.", accent: "Part of the meeting." }}
      description="Invite Cue like any colleague. It joins as a clearly labelled AI participant, answers out loud when someone asks, drops the link in chat, and sends decisions with owners when the call ends."
      points={["Speaks only when someone addresses it", "Announces itself and that it's recording", "Notes with confirmed owners within 5 minutes"]}
      beats={["Joins", "Listens", "Answers", "Shares", "Notes"]}
      beat={beat}
      previewLabel="Illustration: a video meeting where Cue joins as a labelled AI participant, answers Priya's question about the release out loud with captions, posts the blocking pull request in the meeting chat, and then shares notes with decisions and action items."
    >
      <MockWindow
        dark
        title="v2.3 go / no-go"
        icon={
          <span className="flex items-center gap-1">
            <BrandIcon src="/integrations/google-meet.svg" size={14} />
            <BrandIcon src="/integrations/zoom.svg" size={14} />
          </span>
        }
        aside={
          <>
            <span className="flex items-center gap-1.5 rounded-full bg-[#e5533b]/15 px-2 py-[2px] text-[10px] font-semibold text-[#ff8a75]">
              <span className="size-1.5 animate-pulse rounded-full bg-[#ff6b52] motion-reduce:animate-none" /> REC
            </span>
            <span className="font-mono text-[11px] text-white/50">11:02</span>
          </>
        }
      >
        <div key={cycle} className="flex h-full flex-col">
          <div className="relative flex min-h-0 flex-1">
            {/* Participant tiles */}
            <div className="relative min-w-0 flex-1 p-2 pb-[60px]">
              <div className="grid h-full grid-cols-2 grid-rows-2 gap-2">
                <PersonTile id="priya" speaking={is("question")} />
                <PersonTile id="arjun" speaking={is("reply")} />
                <PersonTile id="sam" speaking={is("idle")} className={cueIn ? "" : "col-span-2"} />
                <AnimatePresence>{cueIn && <CueTile key="cue" status={cueStatus} live={live} />}</AnimatePresence>
              </div>

              {/* Live captions */}
              <AnimatePresence mode="wait">
                {line && (
                  <motion.div
                    key={current}
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: 4, transition: { duration: 0.2 } }}
                    transition={{ duration: 0.3, ease }}
                    className="absolute inset-x-3 bottom-2 z-10 mx-auto line-clamp-2 h-[48px] max-w-[480px] rounded-xl bg-white/[0.06] px-3 py-1.5 text-[12px] leading-snug sm:text-[12.5px]"
                  >
                    <span className={`mr-1.5 font-semibold ${line.who === "cue" ? "text-lime" : "text-[#8fb8f5]"}`}>
                      {line.who === "cue" ? "Cue" : people[line.who].name.split(" ")[0]}
                    </span>
                    <SpokenWords key={`${cycle}-${current}`} text={line.text} ms={reduce ? 1 : line.ms} className="text-white/60" />
                  </motion.div>
                )}
              </AnimatePresence>

              <Toast show={is("joining")} className="left-1/2 top-3 -translate-x-1/2 whitespace-nowrap" dark>
                <CueAvatar size={16} /> Cue (AI teammate) is joining
              </Toast>

              {/* On phones the chat column is hidden, so Cue's link pops over the call instead. */}
              <AnimatePresence>
                {at("chat") && !at("notes") && (
                  <motion.div
                    initial={{ opacity: 0, y: -8 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }}
                    className="absolute inset-x-3 top-3 z-10 rounded-xl bg-[#1d1e22] p-2.5 shadow-[0_16px_32px_-12px_rgb(0_0_0/0.8)] ring-1 ring-white/10 md:hidden"
                  >
                    <ChatMessage>
                      The blocker, for reference:
                      <PrCard />
                    </ChatMessage>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>

            {/* In-call chat */}
            <aside className="hidden w-[220px] shrink-0 flex-col border-l border-white/[0.07] bg-[#16171a] md:flex">
              <div className="flex items-center justify-between px-3 py-2.5">
                <span className="text-[11.5px] font-semibold text-white/80">In-call messages</span>
                <MessageSquare className="size-3.5 text-white/40" />
              </div>
              <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-hidden px-3">
                <AnimatePresence>
                  {at("joined") && (
                    <motion.p
                      key="sys"
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="text-center text-[10px] text-white/35"
                    >
                      Cue (AI teammate) joined · recording for notes
                    </motion.p>
                  )}
                  {at("joined") && (
                    <ChatMessage key="hello">
                      Hi all, I&apos;m Cue, the team&apos;s AI teammate. I&apos;m transcribing for notes. Say &ldquo;Cue, stop
                      recording&rdquo; anytime.
                    </ChatMessage>
                  )}
                  {at("chat") && (
                    <ChatMessage key="pr">
                      The blocker, for reference:
                      <PrCard />
                      <span className="mt-1 block">Arjun&apos;s fix is in review.</span>
                    </ChatMessage>
                  )}
                </AnimatePresence>
              </div>
              <div className="m-2.5 rounded-lg bg-white/[0.06] px-2.5 py-2 text-[11px] text-white/35">Send a message</div>
            </aside>

            <AnimatePresence>{at("notes") && <Notes key="notes" />}</AnimatePresence>
          </div>

          {/* Call controls */}
          <div className="flex h-12 shrink-0 items-center justify-center gap-2 border-t border-white/[0.07] bg-[#141518]">
            {[Mic, Video, Captions, Hand, MessageSquare, Users].map((Icon, i) => (
              <span
                key={i}
                className={`grid size-8 place-items-center rounded-full ${
                  i === 2 || i === 4 ? "bg-white/90 text-ink" : "bg-white/[0.08] text-white/70"
                } ${i === 3 || i === 5 ? "hidden sm:grid" : ""}`}
              >
                <Icon className="size-3.5" />
              </span>
            ))}
            <span className="ml-1 grid h-8 w-12 place-items-center rounded-full bg-[#e5533b] text-white">
              <PhoneOff className="size-3.5" />
            </span>
          </div>
        </div>
      </MockWindow>
    </FeatureCard>
  );
}
