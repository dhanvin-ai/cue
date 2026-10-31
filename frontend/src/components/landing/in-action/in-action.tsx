"use client";

import { MotionConfig, motion, motionValue, useMotionValueEvent, useScroll } from "motion/react";
import { useCallback, useEffect, useRef, useState, type ComponentType } from "react";
import type { StoryCardProps } from "./feature-card";
import { CalendarCard } from "./calendar-card";
import { GmailCard } from "./gmail-card";
import { MeetingCard } from "./meeting-card";
import { SlackCard } from "./slack-card";

const cards: ComponentType<StoryCardProps>[] = [SlackCard, CalendarCard, MeetingCard, GmailCard];

/** Matches FeatureCard's sticky offset: each card rests a little lower than the one before. */
const stickTop = (i: number) => 88 + i * 18;

const clamp = (v: number) => Math.min(1, Math.max(0, v));

const ease = [0.22, 1, 0.36, 1] as const;

export function InAction() {
  const refs = useRef<(HTMLElement | null)[]>([]);
  const [active, setActive] = useState(-1);
  const [covers] = useState(() => cards.map(() => motionValue(0)));
  const [enters] = useState(() => cards.map(() => motionValue(1)));
  const { scrollY } = useScroll();

  // One pass over every card per scroll frame: pick the frontmost card to play,
  // and feed the stack and parallax progress straight into motion values.
  const measure = useCallback(() => {
    const vh = window.innerHeight;
    const stacked = window.matchMedia("(min-width: 1024px)").matches;
    const rects = refs.current.map((el) => el?.getBoundingClientRect() ?? null);

    let front = -1;
    rects.forEach((r, i) => {
      if (r && r.top <= vh * 0.6 && r.bottom >= vh * 0.3) front = i;
    });
    setActive(front);

    rects.forEach((r, i) => {
      if (!r) return;
      enters[i].set(clamp((vh - r.top) / (vh - stickTop(i))));
      const next = rects[i + 1];
      covers[i].set(stacked && next ? clamp((vh - next.top) / (vh - stickTop(i + 1))) : 0);
    });
  }, [covers, enters]);

  useMotionValueEvent(scrollY, "change", measure);
  useEffect(() => {
    // First read waits a frame so the cards have laid out.
    const frame = requestAnimationFrame(measure);
    window.addEventListener("resize", measure);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
    };
  }, [measure]);

  return (
    <MotionConfig reducedMotion="user">
      <section id="in-action" aria-labelledby="in-action-title" className="relative mx-auto max-w-[1180px] scroll-mt-24 px-3 pt-28 sm:px-6 sm:pt-36">
        <header className="mx-auto max-w-[720px] px-2 text-center">
          <motion.span
            initial={{ opacity: 0, y: 10 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.8 }}
            transition={{ duration: 0.6, ease }}
            className="inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-3.5 py-1.5 text-[12.5px] font-medium text-ink-soft"
          >
            <span className="size-1.5 rounded-full bg-lime ring-2 ring-lime/30" />
            Cue in action
          </motion.span>
          <motion.h2
            id="in-action-title"
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.8 }}
            transition={{ duration: 0.8, ease, delay: 0.05 }}
            className="mt-5 text-balance text-[clamp(2.25rem,5.6vw,4rem)] font-semibold leading-[1] tracking-[-0.05em] text-ink"
          >
            Meet Cue{" "}
            <span className="relative inline-block">
              <motion.span
                aria-hidden
                className="absolute -inset-x-[0.12em] bottom-[0.02em] top-[0.14em] -z-10 origin-left rounded-[0.3em] bg-lime-soft"
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true, amount: 0.8 }}
                transition={{ duration: 0.8, ease, delay: 0.45 }}
              />
              in action.
            </span>
          </motion.h2>
          <motion.p
            initial={{ opacity: 0, y: 16 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.8 }}
            transition={{ duration: 0.8, ease, delay: 0.12 }}
            className="mx-auto mt-5 max-w-[34rem] text-balance text-[17px] leading-[1.5] text-ink-soft sm:text-[19px]"
          >
            Four places your team already works. One teammate showing up in all of them, with the same memory and the same
            manners.
          </motion.p>
          <p className="mt-4 text-[12px] text-faint">Previews are illustrations with sample data.</p>
        </header>

        <div className="mt-14 flex flex-col gap-5 sm:mt-16 sm:gap-8 lg:gap-16">
          {cards.map((Card, i) => (
            <Card
              key={i}
              index={i}
              active={active === i}
              cover={covers[i]}
              enter={enters[i]}
              cardRef={(el) => {
                refs.current[i] = el;
              }}
            />
          ))}
          {/* Lets the finished stack rest on screen briefly before the section scrolls away. */}
          <div aria-hidden className="hidden h-[12vh] lg:block" />
        </div>
      </section>
    </MotionConfig>
  );
}
