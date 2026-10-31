"use client";

import { AnimatePresence, motion } from "motion/react";
import { Check, GitMerge, GitPullRequest, Video } from "lucide-react";
import type { ReactNode } from "react";
import { CueAvatar, PersonAvatar, RailCard, type PersonId } from "./primitives";

type Register = (id: string) => (el: HTMLElement | null) => void;

function Row({
  id,
  hot,
  register,
  children,
}: {
  id?: string;
  hot?: boolean;
  register: Register;
  children: ReactNode;
}) {
  return (
    <div
      ref={id ? register(id) : undefined}
      className={`relative flex items-center gap-2.5 rounded-xl px-2 py-[7px] transition-[background-color,box-shadow] duration-500 ${
        hot ? "bg-lime-wash shadow-[inset_0_0_0_1px_var(--color-lime)]" : ""
      }`}
    >
      {children}
      <AnimatePresence>
        {hot && (
          <motion.span
            initial={{ opacity: 0, scale: 0.8 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.8 }}
            className="absolute -top-1.5 right-2 rounded-full bg-lime px-1.5 py-[1px] text-[9px] font-semibold uppercase tracking-[0.08em] text-ink"
          >
            Reading
          </motion.span>
        )}
      </AnimatePresence>
    </div>
  );
}

function Lines({ title, meta }: { title: ReactNode; meta: ReactNode }) {
  return (
    <span className="min-w-0 flex-1">
      <span className="block truncate text-[12.5px] font-medium leading-tight text-ink">{title}</span>
      <span className="block truncate text-[11px] leading-tight text-muted">{meta}</span>
    </span>
  );
}

function Speaking() {
  return (
    <span className="flex h-3 items-center gap-[2px]">
      {[0.5, 1, 0.7, 0.9].map((h, i) => (
        <motion.span
          key={i}
          className="w-[2px] rounded-full bg-lime-ink"
          style={{ height: `${h * 100}%` }}
          animate={{ scaleY: [1, 0.3, 1] }}
          transition={{ duration: 0.9 + i * 0.1, repeat: Infinity, ease: "easeInOut" }}
        />
      ))}
    </span>
  );
}

const prs: { id: string; number: number; title: string; who: PersonId; state: "merged" | "failing" | "open"; when: string }[] = [
  { id: "pr-412", number: 412, title: "Refactor session handling to JWT", who: "arjun", state: "merged", when: "merged 21 Oct" },
  { id: "pr-418", number: 418, title: "Fix session timeout", who: "arjun", state: "failing", when: "checks failing · 2d" },
  { id: "pr-421", number: 421, title: "Stream CSV exports", who: "sam", state: "open", when: "review requested" },
];

export function ActivityRail({
  hotItems,
  ticket,
  register,
}: {
  hotItems: string[];
  /** Where the ticket Cue was asked to file currently stands. */
  ticket: "none" | "waiting" | "done";
  register: Register;
}) {
  return (
    <aside className="flex h-full flex-col gap-3 overflow-hidden border-l border-line bg-paper/60 p-4">
      <RailCard
        title="Meetings"
        aside={<span className="font-mono text-[10.5px] text-faint">Today</span>}
      >
        <Row register={register}>
          <span className="grid size-7 place-items-center rounded-lg bg-ink text-lime">
            <Video className="size-3.5" />
          </span>
          <Lines title="v2.3 go / no-go" meta="11:00 · Cue joins, answers when asked" />
          <Speaking />
        </Row>
        <Row register={register}>
          <span className="grid size-7 place-items-center rounded-lg border border-line bg-paper font-mono text-[10px] text-ink-soft">14</span>
          <Lines title="Pricing review" meta="14:00 · Notes only" />
        </Row>
        <Row id="mtg-sync" hot={hotItems.includes("mtg-sync")} register={register}>
          <span className="grid size-7 place-items-center rounded-lg border border-line bg-paper font-mono text-[10px] text-ink-soft">Tu</span>
          <Lines title="Release sync" meta="Notes · 3 decisions, 4 actions" />
        </Row>
      </RailCard>

      <RailCard title="GitHub" aside={<span className="font-mono text-[10.5px] text-faint">api · web</span>}>
        {prs.map((pr) => (
          <Row key={pr.id} id={pr.id} hot={hotItems.includes(pr.id)} register={register}>
            <span
              className={`grid size-7 place-items-center rounded-lg border ${
                pr.state === "merged"
                  ? "border-[#d9d0f2] bg-[#f3effc] text-[#6c4fc4]"
                  : pr.state === "failing"
                    ? "border-[#f3d4cc] bg-[#fdf1ee] text-[#c4553a]"
                    : "border-line bg-paper text-ink-soft"
              }`}
            >
              {pr.state === "merged" ? <GitMerge className="size-3.5" /> : <GitPullRequest className="size-3.5" />}
            </span>
            <Lines
              title={
                <>
                  <span className="font-mono text-muted">#{pr.number}</span> {pr.title}
                </>
              }
              meta={pr.when}
            />
            <PersonAvatar id={pr.who} size={20} />
          </Row>
        ))}
      </RailCard>

      <RailCard title="Cue's tasks" aside={<CueAvatar size={18} />}>
        <AnimatePresence initial={false}>
          {ticket !== "none" && (
            <motion.div
              key="ticket"
              layout
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            >
              <Row id="task-ticket" hot={false} register={register}>
                <motion.span
                  layout
                  className={`grid size-7 place-items-center rounded-lg ${
                    ticket === "done" ? "bg-lime text-ink" : "border border-dashed border-faint text-faint"
                  }`}
                >
                  {ticket === "done" ? <Check className="size-3.5" strokeWidth={3} /> : <span className="size-1.5 rounded-full bg-faint" />}
                </motion.span>
                <Lines
                  title="Flaky login test on CI"
                  meta={ticket === "done" ? "Done · LIN-231 · assigned to Arjun" : "Waiting for Priya's OK"}
                />
              </Row>
            </motion.div>
          )}
        </AnimatePresence>
        <Row register={register}>
          <span className="relative grid size-7 place-items-center rounded-lg border border-line bg-paper">
            <svg viewBox="0 0 20 20" className="size-4 -rotate-90">
              <circle cx="10" cy="10" r="7" fill="none" stroke="var(--color-line)" strokeWidth="2.5" />
              <motion.circle
                cx="10"
                cy="10"
                r="7"
                fill="none"
                stroke="var(--color-ink)"
                strokeWidth="2.5"
                strokeLinecap="round"
                initial={{ pathLength: 0.2 }}
                animate={{ pathLength: 0.62 }}
                transition={{ duration: 2.4, ease: "easeOut" }}
              />
            </svg>
          </span>
          <Lines title="Compile v2.3 release notes" meta="Due Thu · Working" />
        </Row>
        <Row register={register}>
          <span className="grid size-7 place-items-center rounded-lg border border-line bg-paper font-mono text-[10px] text-ink-soft">Fr</span>
          <Lines title="Remind #eng: release notes" meta="Fri 16:00 · Scheduled" />
        </Row>
      </RailCard>
    </aside>
  );
}
