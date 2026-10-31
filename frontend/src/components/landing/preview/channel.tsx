"use client";

import { AnimatePresence, motion } from "motion/react";
import { ArrowUp, Check, Hash, SquareKanban } from "lucide-react";
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Typewriter } from "@/components/ui/typewriter";
import { AiBadge, CueAvatar, PersonAvatar, ToolGlyph, people, type PersonId } from "./primitives";
import type { StepName } from "./scene";

type Register = (id: string) => (el: HTMLElement | null) => void;

const ease = [0.22, 1, 0.36, 1] as const;

const question = "@Cue who shipped the auth refactor? Is v2.3 still blocked?";
const request = "Can you file a ticket for the flaky test and give it to Arjun?";

function Message({
  from,
  time,
  children,
  messageRef,
}: {
  from: PersonId | "cue";
  time: string;
  children: ReactNode;
  messageRef?: (el: HTMLElement | null) => void;
}) {
  return (
    <motion.div
      ref={messageRef}
      layout="position"
      initial={{ opacity: 0, y: 14 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.45, ease }}
      className="flex gap-3"
    >
      {from === "cue" ? <CueAvatar size={34} /> : <PersonAvatar id={from} size={34} />}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[13.5px] font-semibold tracking-[-0.01em] text-ink">
            {from === "cue" ? "Cue" : people[from].name}
          </span>
          {from === "cue" && <AiBadge />}
          <span className="font-mono text-[10.5px] text-faint">{time}</span>
        </div>
        <div className="mt-0.5 text-[13.5px] leading-[1.55] text-ink-soft">{children}</div>
      </div>
    </motion.div>
  );
}

function Mention({ children }: { children: ReactNode }) {
  return <span className="rounded bg-lime-soft px-1 font-medium text-lime-ink">{children}</span>;
}

function Cite({ n }: { n: number }) {
  return (
    <sup className="ml-0.5 inline-grid size-[15px] translate-y-[-1px] place-items-center rounded-[4px] bg-paper-deep font-mono text-[9.5px] font-semibold text-ink-soft ring-1 ring-line">
      {n}
    </sup>
  );
}

const sources = [
  { n: 1, label: "PR #412", tool: "github" as const },
  { n: 2, label: "#418 checks", tool: "github" as const },
  { n: 3, label: "Release sync, Tue", tool: "calendar" as const },
];

function Answer({ at }: { at: (name: StepName) => boolean }) {
  if (!at("answered")) {
    return (
      <div className="flex flex-col gap-1.5">
        <span className="text-shimmer w-fit font-medium">Pulling that up…</span>
        <span className="flex items-center gap-1.5 font-mono text-[10.5px] text-faint">
          <ToolGlyph tool="github" className="size-3" /> Reading GitHub
          <span className="text-line">/</span>
          <ToolGlyph tool="calendar" className="size-3" /> Meeting notes
        </span>
      </div>
    );
  }
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}>
      <p>
        <span className="font-medium text-ink">Arjun</span> shipped it in PR #412, merged 21{" "}
        <span className="whitespace-nowrap">
          Oct<Cite n={1} />.
        </span>{" "}
        v2.3 is still blocked by one check: the login test is flaky and failed again on #418 this{" "}
        <span className="whitespace-nowrap">
          morning<Cite n={2} />.
        </span>{" "}
        In Tuesday&apos;s release sync you agreed to ship once it&apos;s{" "}
        <span className="whitespace-nowrap">
          green<Cite n={3} />.
        </span>
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {sources.map((s, i) => (
          <motion.span
            key={s.n}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.15 + i * 0.1, duration: 0.35, ease }}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-white px-2 py-1 text-[11.5px] text-ink-soft shadow-[0_1px_1px_rgb(15_16_13/0.03)]"
          >
            <span className="font-mono text-[10px] text-faint">{s.n}</span>
            <ToolGlyph tool={s.tool} className="size-3 text-muted" />
            {s.label}
          </motion.span>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-faint">Answered from what everyone in #eng can see.</p>
    </motion.div>
  );
}

function PlanCard({ at, approveRef }: { at: (name: StepName) => boolean; approveRef: (el: HTMLElement | null) => void }) {
  const done = at("done");
  const pressing = at("approving") && !done;
  return (
    <motion.div
      layout
      className="mt-2 overflow-hidden rounded-xl border border-line bg-white shadow-card"
      transition={{ duration: 0.45, ease }}
    >
      <div className="flex items-center gap-2 border-b border-line-soft bg-paper/70 px-3 py-2">
        <span className="grid size-5 place-items-center rounded-md bg-ink text-lime">
          <SquareKanban className="size-3" />
        </span>
        <span className="text-[12px] font-semibold text-ink">Create Linear issue</span>
        <span className="ml-auto rounded-full bg-white px-2 py-[2px] text-[10px] font-medium text-muted ring-1 ring-line">
          Visible to team
        </span>
      </div>
      <AnimatePresence mode="popLayout" initial={false}>
        {done ? (
          <motion.div
            key="done"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease }}
            className="flex items-center gap-2.5 px-3 py-3"
          >
            <motion.span
              initial={{ scale: 0 }}
              animate={{ scale: [0, 1.2, 1] }}
              transition={{ duration: 0.45 }}
              className="grid size-6 place-items-center rounded-full bg-lime"
            >
              <Check className="size-3.5 text-ink" strokeWidth={3} />
            </motion.span>
            <span className="text-[12.5px] text-ink">
              <span className="font-semibold">Done · LIN-231</span>
              <span className="text-muted"> · Flaky login test on CI → Arjun</span>
            </span>
            <span className="ml-auto text-[11px] font-medium text-muted underline decoration-line underline-offset-2">Undo</span>
          </motion.div>
        ) : (
          <motion.div key="plan" exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.25 }} className="px-3 py-3">
            <dl className="grid grid-cols-[72px_1fr] gap-x-3 gap-y-1.5 text-[12px]">
              <dt className="text-faint">Title</dt>
              <dd className="font-medium text-ink">Flaky login test on CI</dd>
              <dt className="text-faint">Team</dt>
              <dd className="text-ink-soft">Web</dd>
              <dt className="text-faint">Assignee</dt>
              <dd className="flex items-center gap-1.5 text-ink-soft">
                <PersonAvatar id="arjun" size={16} /> Arjun Kumar
              </dd>
              <dt className="text-faint">Linked</dt>
              <dd className="font-mono text-[11.5px] text-ink-soft">PR #418</dd>
            </dl>
            <div className="mt-3 flex gap-1.5">
              <motion.span
                ref={approveRef}
                animate={pressing ? { scale: 0.94, backgroundColor: "#d9f25c", color: "#0f100d" } : { scale: 1 }}
                transition={{ duration: 0.18 }}
                className="rounded-lg bg-ink px-3 py-1.5 text-[12px] font-medium text-paper"
              >
                Approve
              </motion.span>
              <span className="rounded-lg border border-line px-3 py-1.5 text-[12px] font-medium text-ink-soft">Edit</span>
              <span className="rounded-lg px-2 py-1.5 text-[12px] font-medium text-muted">Cancel</span>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

function Composer({ at, index }: { at: (name: StepName) => boolean; index: number }) {
  const typingQuestion = at("typing-question") && !at("question-sent");
  const typingRequest = at("typing-request") && !at("request-sent");
  const typing = typingQuestion || typingRequest;
  return (
    <div className="border-t border-line px-4 pb-4 pt-3">
      <div
        className={`flex items-center gap-2 rounded-xl border bg-white px-3 py-2.5 transition-[border-color,box-shadow] duration-300 ${
          typing ? "border-ink/25 shadow-[0_0_0_4px_rgb(15_16_13/0.04)]" : "border-line"
        }`}
      >
        <span className="min-w-0 flex-1 truncate text-[13px]">
          {typing ? (
            <span className="text-ink">
              <Typewriter key={index} text={typingQuestion ? question : request} ms={1500} />
              <span className="ml-px inline-block h-[1.05em] w-[1.5px] translate-y-[2px] animate-pulse bg-ink" />
            </span>
          ) : (
            <span className="text-faint">Message #eng</span>
          )}
        </span>
        <span
          className={`grid size-7 place-items-center rounded-lg transition-colors duration-300 ${
            typing ? "bg-ink text-lime" : "bg-paper-deep text-faint"
          }`}
        >
          <ArrowUp className="size-3.5" strokeWidth={2.4} />
        </span>
      </div>
    </div>
  );
}

export function Channel({
  at,
  index,
  cycle,
  register,
}: {
  at: (name: StepName) => boolean;
  index: number;
  cycle: number;
  register: Register;
}) {
  const panelRef = useRef<HTMLDivElement>(null);
  const approveEl = useRef<HTMLElement | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);

  const showCursor = at("plan") && !at("done");

  // Glide Priya's cursor onto the Approve button once the plan card has settled.
  useLayoutEffect(() => {
    if (!showCursor) return;
    const timer = setTimeout(() => {
      const panel = panelRef.current?.getBoundingClientRect();
      const button = approveEl.current?.getBoundingClientRect();
      if (!panel || !button) return;
      setCursor({ x: button.left - panel.left + button.width * 0.55, y: button.top - panel.top + button.height * 0.6 });
    }, 450);
    return () => clearTimeout(timer);
  }, [showCursor, cycle]);

  return (
    <div ref={panelRef} className="relative flex h-full min-w-0 flex-col bg-white">
      <header className="flex items-center gap-2 border-b border-line px-5 py-3">
        <Hash className="size-4 text-ink" strokeWidth={2.4} />
        <span className="text-[14px] font-semibold tracking-[-0.02em] text-ink">eng</span>
        <span className="rounded-md bg-paper-deep px-1.5 py-[1px] text-[10.5px] font-medium text-muted">Slack</span>
        <span className="ml-auto flex items-center gap-2 text-[11.5px] text-muted">
          <span className="flex -space-x-1.5">
            <span className="rounded-[10px] ring-2 ring-white"><PersonAvatar id="priya" size={20} /></span>
            <span className="rounded-[10px] ring-2 ring-white"><PersonAvatar id="arjun" size={20} /></span>
            <span className="rounded-[10px] ring-2 ring-white"><CueAvatar size={20} /></span>
          </span>
          <span className="hidden sm:inline">14 members</span>
        </span>
      </header>

      <div className="relative flex-1 overflow-hidden">
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-0 z-10 h-16 bg-gradient-to-b from-white to-transparent" />
        <AnimatePresence mode="wait">
          <motion.div
            key={cycle}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.35 } }}
            className="absolute inset-x-0 bottom-0 flex flex-col gap-5 px-4 pb-4 sm:px-5"
          >
            <Message from="arjun" time="10:02">
              Re-ran CI on #418, the login test failed again. Third time this week 🙃
            </Message>

            <AnimatePresence>
              {at("question-sent") && (
                <Message key="q" from="priya" time="10:14">
                  <Mention>@Cue</Mention> who shipped the auth refactor? Is v2.3 still blocked?
                  {at("eyes") && (
                    <motion.span
                      initial={{ scale: 0, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      transition={{ type: "spring", stiffness: 500, damping: 22 }}
                      className="mt-1.5 flex w-fit items-center gap-1 rounded-full border border-[#dfe9a8] bg-lime-wash px-2 py-[2px] text-[11px] text-lime-ink"
                    >
                      👀 <span className="font-mono">1</span>
                    </motion.span>
                  )}
                </Message>
              )}

              {at("reading") && (
                <Message key="a" from="cue" time="10:14" messageRef={register("cue-answer")}>
                  <Answer at={at} />
                </Message>
              )}

              {at("request-sent") && (
                <Message key="r" from="priya" time="10:15">
                  {request}
                </Message>
              )}

              {at("plan") && (
                <Message key="p" from="cue" time="10:15" messageRef={register("cue-plan")}>
                  On it. The team will see this, so I need your OK first.
                  <PlanCard
                    at={at}
                    approveRef={(el) => {
                      approveEl.current = el;
                    }}
                  />
                </Message>
              )}
            </AnimatePresence>
          </motion.div>
        </AnimatePresence>
      </div>

      <Composer at={at} index={index} />

      {/* Priya's cursor, so the approval reads as a person's tap. */}
      <AnimatePresence>
        {showCursor && cursor && (
          <motion.div
            aria-hidden
            className="pointer-events-none absolute left-0 top-0 z-20"
            initial={{ x: cursor.x + 140, y: cursor.y + 90, opacity: 0 }}
            animate={{ x: cursor.x, y: cursor.y, opacity: 1, scale: at("approving") ? 0.86 : 1 }}
            exit={{ opacity: 0, transition: { duration: 0.2 } }}
            transition={{ type: "spring", stiffness: 70, damping: 16 }}
          >
            <svg width="18" height="20" viewBox="0 0 18 20" className="drop-shadow-[0_2px_3px_rgb(15_16_13/0.3)]">
              <path d="M1.5 1.5 L16 9.2 L9.4 10.6 L6.2 17.6 Z" fill="#0f100d" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
            </svg>
            <span className="ml-3 mt-0.5 block w-fit rounded-md rounded-tl-sm bg-[#e9a97a] px-1.5 py-[1px] text-[10.5px] font-semibold text-ink">
              Priya
            </span>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
