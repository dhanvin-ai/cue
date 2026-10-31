"use client";

import {
  motion,
  useReducedMotion,
  useScroll,
  useSpring,
  useTransform,
  type MotionValue,
} from "motion/react";
import { Check, GitMerge, Mail } from "lucide-react";
import type { ReactNode } from "react";
import { CueMark } from "@/components/brand/cue-logo";

type Pointer = { x: MotionValue<number>; y: MotionValue<number> };

type TileProps = {
  pointer: Pointer;
  /** How strongly the tile reacts to pointer and scroll. Further-back tiles move less. */
  depth: number;
  rotate: number;
  delay: number;
  /** Seconds for one idle bob. */
  bob: number;
  className: string;
  children: ReactNode;
};

function Tile({ pointer, depth, rotate, delay, bob, className, children }: TileProps) {
  const reduce = useReducedMotion();
  const { scrollY } = useScroll();
  const scrollShift = useTransform(scrollY, [0, 700], [0, -140 * depth]);
  const px = useSpring(useTransform(pointer.x, (v) => v * 36 * depth), { stiffness: 60, damping: 18 });
  const py = useSpring(useTransform(pointer.y, (v) => v * 28 * depth), { stiffness: 60, damping: 18 });
  const tiltX = useSpring(useTransform(pointer.y, (v) => v * -14), { stiffness: 80, damping: 20 });
  const tiltY = useSpring(useTransform(pointer.x, (v) => v * 14), { stiffness: 80, damping: 20 });
  const y = useTransform(() => scrollShift.get() + py.get());

  return (
    <motion.div
      aria-hidden
      style={reduce ? undefined : { x: px, y }}
      className={`pointer-events-none absolute ${className}`}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.6, y: 40, filter: "blur(10px)" }}
        animate={{ opacity: 1, scale: 1, y: 0, filter: "blur(0px)" }}
        transition={{ delay, type: "spring", stiffness: 120, damping: 16, mass: 0.9 }}
        style={{ perspective: 800 }}
      >
        <motion.div
          animate={reduce ? undefined : { y: [0, -10, 0], rotate: [rotate, rotate + 2.5, rotate] }}
          transition={{ duration: bob, repeat: Infinity, ease: "easeInOut", delay: delay + 0.6 }}
          style={{ rotate, rotateX: reduce ? 0 : tiltX, rotateY: reduce ? 0 : tiltY, transformStyle: "preserve-3d" }}
        >
          {children}
        </motion.div>
      </motion.div>
    </motion.div>
  );
}

/** Soft, slightly glossy rounded block that every floating object sits on. */
function Block({ className, children, dark = false }: { className?: string; children: ReactNode; dark?: boolean }) {
  return (
    <div
      className={`relative grid place-items-center rounded-[28px] ${
        dark
          ? "bg-[linear-gradient(160deg,#2a2b26_0%,#0f100d_70%)] shadow-[inset_0_1px_0_rgb(255_255_255/0.14),0_2px_4px_rgb(15_16_13/0.1),0_30px_50px_-18px_rgb(15_16_13/0.55)]"
          : "bg-[linear-gradient(160deg,#ffffff_0%,#f1f1eb_100%)] shadow-tile ring-1 ring-black/[0.035]"
      } ${className ?? ""}`}
    >
      <div
        className={`pointer-events-none absolute inset-[5px] rounded-[23px] ${
          dark ? "ring-1 ring-white/5" : "bg-[linear-gradient(180deg,rgb(255_255_255/0.9),rgb(255_255_255/0))] ring-1 ring-black/[0.02]"
        }`}
      />
      <div className="relative">{children}</div>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="flex gap-[3px]">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-[5px] rounded-full bg-muted"
          animate={{ opacity: [0.25, 1, 0.25], y: [0, -2, 0] }}
          transition={{ duration: 1.1, repeat: Infinity, delay: i * 0.16, ease: "easeInOut" }}
        />
      ))}
    </span>
  );
}

function Waveform() {
  const bars = [0.35, 0.7, 1, 0.55, 0.85, 0.4, 0.65];
  return (
    <div className="flex h-9 items-center gap-[4px]">
      {bars.map((h, i) => (
        <motion.span
          key={i}
          className="w-[4px] rounded-full bg-lime"
          style={{ height: `${h * 100}%` }}
          animate={{ scaleY: [1, 0.35, 0.9, 0.5, 1] }}
          transition={{ duration: 1.4 + i * 0.07, repeat: Infinity, ease: "easeInOut", delay: i * 0.09 }}
        />
      ))}
    </div>
  );
}

export function FloatingTiles({ pointer }: { pointer: Pointer }) {
  return (
    <div className="pointer-events-none absolute inset-0 -z-0 mx-auto max-w-[1440px]">
      {/* Someone @mentions Cue in a channel. */}
      <Tile
        pointer={pointer}
        depth={0.9}
        rotate={-8}
        delay={0.35}
        bob={6}
        className="left-[1%] top-0 origin-top-left scale-[0.6] sm:left-[3%] sm:scale-[0.72] lg:scale-[0.85] xl:left-[6%] xl:top-[14%] xl:scale-100 2xl:left-[10%] 2xl:top-[18%]"
      >
        <Block className="h-[104px] w-[132px]">
          <div className="flex flex-col items-start gap-2">
            <span className="rounded-full bg-lime-soft px-2 py-[3px] font-mono text-[11px] font-medium text-lime-ink">@cue</span>
            <span className="flex items-center gap-2 rounded-2xl rounded-tl-md bg-white px-3 py-2 shadow-card ring-1 ring-black/[0.04]">
              <TypingDots />
            </span>
          </div>
        </Block>
      </Tile>

      {/* Cue speaking in a meeting. */}
      <Tile
        pointer={pointer}
        depth={1.1}
        rotate={9}
        delay={0.5}
        bob={7}
        className="right-[1%] top-0 origin-top-right scale-[0.6] sm:right-[3%] sm:scale-[0.72] lg:scale-[0.85] xl:right-[7%] xl:top-[13%] xl:scale-100 2xl:right-[10%] 2xl:top-[17%]"
      >
        <Block dark className="size-[112px]">
          <Waveform />
        </Block>
      </Tile>

      {/* A merged PR Cue remembers. */}
      <Tile
        pointer={pointer}
        depth={0.6}
        rotate={-6}
        delay={0.65}
        bob={8}
        className="hidden md:block md:left-[1%] md:top-[50%] md:scale-[0.7] lg:left-[3%] lg:scale-[0.85] xl:left-[13%] xl:top-[52%] xl:scale-100 2xl:left-[17%]"
      >
        <Block className="h-[100px] w-[124px]">
          <div className="flex flex-col items-center gap-1.5">
            <GitMerge className="size-7 text-ink" strokeWidth={2.2} />
            <span className="font-mono text-[13px] font-medium tracking-tight text-ink">#412</span>
          </div>
        </Block>
      </Tile>

      {/* A task Cue followed through on. */}
      <Tile
        pointer={pointer}
        depth={0.75}
        rotate={7}
        delay={0.8}
        bob={6.5}
        className="hidden md:block md:right-[1%] md:top-[52%] md:scale-[0.7] lg:right-[3%] lg:scale-[0.85] xl:right-[14%] xl:top-[55%] xl:scale-100 2xl:right-[18%]"
      >
        <Block className="size-[96px]">
          <motion.div
            className="grid size-11 place-items-center rounded-full bg-lime shadow-[inset_0_-2px_0_rgb(0_0_0/0.08)]"
            initial={{ scale: 0 }}
            animate={{ scale: [0, 1.15, 1] }}
            transition={{ delay: 1.4, duration: 0.6, ease: "easeOut" }}
          >
            <Check className="size-6 text-ink" strokeWidth={3} />
          </motion.div>
        </Block>
      </Tile>

      {/* Cue's own inbox. */}
      <Tile
        pointer={pointer}
        depth={1.3}
        rotate={-12}
        delay={0.95}
        bob={7.5}
        className="hidden lg:block lg:-left-[1%] lg:top-[76%] xl:left-[2%]"
      >
        <Block className="h-[108px] w-[124px]">
          <div className="relative">
            <Mail className="size-10 text-ink" strokeWidth={1.8} />
            <span className="absolute -right-1.5 -top-1.5 size-3.5 rounded-full bg-lime ring-[3px] ring-white" />
          </div>
        </Block>
      </Tile>

      {/* An upcoming meeting with Cue on the invite. */}
      <Tile
        pointer={pointer}
        depth={1.2}
        rotate={8}
        delay={1.1}
        bob={6.8}
        className="hidden lg:block lg:-right-[1%] lg:top-[74%] xl:right-[2%]"
      >
        <Block className="h-[112px] w-[148px]">
          <div className="flex w-[118px] flex-col gap-2">
            <div className="flex items-baseline justify-between">
              <span className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted">Thu</span>
              <span className="font-mono text-[11px] text-muted">09:30</span>
            </div>
            <span className="text-[14px] font-semibold leading-none tracking-[-0.02em] text-ink">Standup</span>
            <div className="flex -space-x-1.5">
              {["#f6c9a8", "#b9d4f0", "#d8c8f3"].map((c) => (
                <span key={c} className="size-5 rounded-full ring-2 ring-white" style={{ background: c }} />
              ))}
              <span className="grid size-5 place-items-center rounded-full bg-ink ring-2 ring-white">
                <CueMark tone="paper" className="size-3.5" />
              </span>
            </div>
          </div>
        </Block>
      </Tile>
    </div>
  );
}
