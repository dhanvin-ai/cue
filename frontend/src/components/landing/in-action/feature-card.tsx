"use client";

import Image from "next/image";
import { motion, useReducedMotion, useTransform, type MotionValue } from "motion/react";
import type { CSSProperties, ReactNode, Ref } from "react";
import { Check } from "lucide-react";

export type CardTone = {
  /** Card background. */
  bg: string;
  /** Headline accent and progress colour. */
  accent: string;
  /** Eyebrow pill background. */
  pill: string;
};

export type FeatureCardProps = {
  index: number;
  tone: CardTone;
  eyebrow: { label: string; icons: string[] };
  title: { lead: string; accent: string };
  description: string;
  points: string[];
  /** Short labels for the story's beats, shown as a progress row under the copy. */
  beats: string[];
  /** Which beat the preview is currently showing. */
  beat: number;
  /** 0 → 1 as the next card slides over this one (desktop stack). */
  cover: MotionValue<number>;
  /** 0 → 1 as this card travels from the bottom of the viewport to its resting place. */
  enter: MotionValue<number>;
  cardRef: Ref<HTMLElement>;
  /** Plain-language description of the illustration, for screen readers. */
  previewLabel: string;
  /** Gives the preview more room; used for the lead card. */
  featured?: boolean;
  children: ReactNode;
};

/** What the section hands each story card. */
export type StoryCardProps = Pick<FeatureCardProps, "index" | "cover" | "enter" | "cardRef"> & {
  /** Only the frontmost card on screen plays its story. */
  active: boolean;
};

const ease = [0.22, 1, 0.36, 1] as const;

const copy = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.1 } },
};

const item = {
  hidden: { opacity: 0, y: 18 },
  show: { opacity: 1, y: 0, transition: { duration: 0.7, ease } },
};

export function FeatureCard({
  index,
  tone,
  eyebrow,
  title,
  description,
  points,
  beats,
  beat,
  cover,
  enter,
  cardRef,
  previewLabel,
  featured = false,
  children,
}: FeatureCardProps) {
  const reduce = useReducedMotion();
  const scale = useTransform(cover, [0, 1], [1, 0.94]);
  const shade = useTransform(cover, [0, 1], [0, 0.07]);
  const previewY = useTransform(enter, [0, 1], [56, 0]);

  return (
    <motion.article
      ref={cardRef}
      initial={reduce ? false : { opacity: 0, y: 48 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{ duration: 0.9, ease }}
      style={{ "--stick": `${88 + index * 18}px` } as CSSProperties}
      className="lg:sticky lg:top-[var(--stick)]"
    >
      <motion.div
        style={reduce ? { background: tone.bg } : { background: tone.bg, scale, transformOrigin: "50% 0%" }}
        className={`relative grid gap-8 overflow-hidden rounded-[32px] p-5 shadow-[0_1px_0_rgb(255_255_255/0.7)_inset,0_30px_60px_-30px_rgb(15_16_13/0.25)] ring-1 ring-black/[0.04] sm:rounded-[40px] sm:p-8 lg:h-[min(640px,calc(100svh-150px))] lg:gap-12 lg:p-12 ${
          featured
            ? "lg:grid-cols-[minmax(0,0.78fr)_minmax(0,1.4fr)]"
            : "lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.2fr)]"
        }`}
      >
        <motion.div
          variants={copy}
          initial={reduce ? false : "hidden"}
          whileInView="show"
          viewport={{ once: true, amount: 0.3 }}
          className="flex min-w-0 flex-col px-1 pt-2 sm:px-0 lg:justify-between lg:pt-0"
        >
          <div>
            <motion.span
              variants={item}
              className="inline-flex items-center gap-2 rounded-full py-1.5 pl-2 pr-3.5 text-[12.5px] font-semibold uppercase tracking-[0.12em] text-ink"
              style={{ background: tone.pill }}
            >
              <span className="flex -space-x-1">
                {eyebrow.icons.map((src) => (
                  <span key={src} className="grid size-6 place-items-center rounded-full bg-white shadow-[0_1px_2px_rgb(15_16_13/0.1)]">
                    <Image src={src} alt="" width={14} height={14} unoptimized className="size-3.5" />
                  </span>
                ))}
              </span>
              {eyebrow.label}
            </motion.span>

            <motion.h3
              variants={item}
              className="mt-5 text-balance text-[34px] font-semibold leading-[1.02] tracking-[-0.045em] text-ink sm:text-[42px] lg:mt-6 lg:text-[48px]"
            >
              {title.lead} <span style={{ color: tone.accent }}>{title.accent}</span>
            </motion.h3>

            <motion.p variants={item} className="mt-4 max-w-[30rem] text-[16px] leading-[1.55] text-ink-soft sm:text-[17px] lg:mt-5">
              {description}
            </motion.p>
          </div>

          <div className="mt-7 lg:mt-0">
            <motion.ul variants={item} className="flex flex-col gap-2.5">
              {points.map((point) => (
                <li key={point} className="flex items-start gap-2.5 text-[14.5px] text-ink-soft">
                  <span className="mt-[2px] grid size-[18px] shrink-0 place-items-center rounded-full bg-ink">
                    <Check className="size-2.5 text-lime" strokeWidth={3.5} />
                  </span>
                  {point}
                </li>
              ))}
            </motion.ul>

            <motion.ol variants={item} aria-hidden className="mt-7 flex gap-1.5">
              {beats.map((label, i) => (
                <li key={label} className="min-w-0 flex-1">
                  <span className="block h-[3px] overflow-hidden rounded-full bg-black/[0.07]">
                    <motion.span
                      className="block h-full origin-left rounded-full"
                      style={{ background: tone.accent }}
                      initial={false}
                      animate={{ scaleX: i <= beat ? 1 : 0, opacity: i < beat ? 0.4 : 1 }}
                      transition={{ duration: i === beat ? 0.6 : 0.3, ease }}
                    />
                  </span>
                  <span
                    className={`mt-2 block truncate text-[11.5px] font-medium transition-colors duration-500 ${
                      i === beat ? "text-ink" : "text-faint"
                    }`}
                  >
                    {label}
                  </span>
                </li>
              ))}
            </motion.ol>
          </div>
        </motion.div>

        <motion.figure
          role="img"
          aria-label={previewLabel}
          style={reduce ? undefined : { y: previewY }}
          className="relative h-[460px] min-w-0 sm:h-[500px] lg:h-full"
        >
          <div aria-hidden className="h-full">
            {children}
          </div>
        </motion.figure>

        {/* Dims the card a touch as the next one slides over it. */}
        <motion.div aria-hidden style={{ opacity: shade }} className="pointer-events-none absolute inset-0 bg-ink" />
      </motion.div>
    </motion.article>
  );
}
