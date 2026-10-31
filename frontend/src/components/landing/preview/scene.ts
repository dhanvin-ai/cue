"use client";

import { useEffect, useState } from "react";

/**
 * The preview plays one short story on a loop: Priya asks Cue a question in
 * #eng, Cue answers with citations, then turns a follow-up into a plan card
 * that Priya approves. Each step holds for `hold` ms before the next.
 */
export const steps = [
  { name: "idle", hold: 700 },
  { name: "typing-question", hold: 2000 },
  { name: "question-sent", hold: 600 },
  { name: "eyes", hold: 500 },
  { name: "reading", hold: 2200 },
  { name: "answered", hold: 2000 },
  { name: "typing-request", hold: 1900 },
  { name: "request-sent", hold: 700 },
  { name: "plan", hold: 1800 },
  { name: "approving", hold: 700 },
  { name: "done", hold: 4200 },
] as const;

export type StepName = (typeof steps)[number]["name"];

const last = steps.length - 1;

export function useScene(active: boolean, reduce: boolean) {
  const [step, setStep] = useState(0);
  const [cycle, setCycle] = useState(0);

  useEffect(() => {
    if (!active || reduce) return;
    const timer = setTimeout(() => {
      if (step === last) {
        setCycle((c) => c + 1);
        setStep(0);
      } else {
        setStep(step + 1);
      }
    }, steps[step].hold);
    return () => clearTimeout(timer);
  }, [step, active, reduce]);

  // Reduced motion shows the finished story as a still.
  const index = reduce ? last : step;
  return { index, cycle, at: (name: StepName) => index >= steps.findIndex((s) => s.name === name) };
}

/** Which tools and memory items Cue is touching at a given point in the story. */
export function activeSources(at: (name: StepName) => boolean) {
  if (at("done")) return { tools: ["linear"], items: ["task-ticket"] };
  if (at("plan")) return { tools: ["linear"], items: [] };
  if (at("typing-request")) return { tools: ["slack"], items: [] };
  if (at("reading")) return { tools: ["github", "calendar"], items: ["pr-412", "pr-418", "mtg-sync"] };
  if (at("typing-question")) return { tools: ["slack"], items: [] };
  return { tools: [], items: [] };
}
