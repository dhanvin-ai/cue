"use client";

import { useEffect, useState } from "react";

export type StoryStep = { name: string; hold: number };

/**
 * Plays a list of named steps on a loop, holding each for `hold` ms. The clock
 * only runs while `active`, so off-screen stories pause where they are.
 * Reduced motion jumps straight to the last step and stays there.
 */
export function useStory<const S extends readonly StoryStep[]>(steps: S, active: boolean, reduce: boolean) {
  const [step, setStep] = useState(0);
  const [cycle, setCycle] = useState(0);
  const last = steps.length - 1;

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
  }, [step, active, reduce, steps, last]);

  type Name = S[number]["name"];
  const index = reduce ? last : step;
  const indexOf = (name: Name) => steps.findIndex((s) => s.name === name);

  return {
    index,
    cycle,
    /** True once the story has reached `name` (and stays true until it loops). */
    at: (name: Name) => index >= indexOf(name),
    /** True only while `name` is the current step. */
    is: (name: Name) => index === indexOf(name),
  };
}

export type Story<Name extends string> = {
  index: number;
  cycle: number;
  at: (name: Name) => boolean;
  is: (name: Name) => boolean;
};
