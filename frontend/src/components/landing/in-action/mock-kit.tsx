"use client";

import Image from "next/image";
import { AnimatePresence, motion } from "motion/react";
import { useLayoutEffect, useState, type ReactNode, type RefObject } from "react";

export const ease = [0.22, 1, 0.36, 1] as const;

export function BrandIcon({ src, size = 16, className }: { src: string; size?: number; className?: string }) {
  return <Image src={src} alt="" width={size} height={size} unoptimized className={className} style={{ width: size, height: size }} />;
}

/** App window the mockups sit in. Deliberately generic chrome, not any vendor's. */
export function MockWindow({
  title,
  icon,
  aside,
  dark = false,
  children,
}: {
  title: ReactNode;
  icon?: ReactNode;
  aside?: ReactNode;
  dark?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className={`relative flex h-full flex-col overflow-hidden rounded-[22px] shadow-[0_1px_2px_rgb(15_16_13/0.06),0_24px_50px_-24px_rgb(15_16_13/0.35)] ring-1 sm:rounded-[26px] ${
        dark ? "bg-[#111214] ring-white/10" : "bg-white ring-black/[0.06]"
      }`}
    >
      <div
        className={`flex h-10 shrink-0 items-center gap-3 border-b px-4 ${
          dark ? "border-white/[0.07] bg-[#17181b]" : "border-line bg-paper/70"
        }`}
      >
        <div className="flex gap-1.5">
          {[0, 1, 2].map((i) => (
            <span key={i} className={`size-2.5 rounded-full ${dark ? "bg-white/15" : "bg-line"}`} />
          ))}
        </div>
        <span className={`flex min-w-0 items-center gap-2 truncate text-[12px] font-medium ${dark ? "text-white/70" : "text-muted"}`}>
          {icon}
          {title}
        </span>
        {aside && <span className="ml-auto flex shrink-0 items-center gap-2">{aside}</span>}
      </div>
      <div className="relative min-h-0 flex-1">{children}</div>
    </div>
  );
}

/** Where `target` sits inside `container`, re-measured whenever `when` turns true. */
export function usePoint(
  container: RefObject<HTMLElement | null>,
  target: RefObject<HTMLElement | null>,
  when: boolean,
  delay = 400,
) {
  const [point, setPoint] = useState<{ x: number; y: number } | null>(null);
  useLayoutEffect(() => {
    if (!when) return;
    const timer = setTimeout(() => {
      const box = container.current?.getBoundingClientRect();
      const el = target.current?.getBoundingClientRect();
      if (!box || !el) return;
      setPoint({ x: el.left - box.left + el.width * 0.55, y: el.top - box.top + el.height * 0.6 });
    }, delay);
    return () => clearTimeout(timer);
  }, [container, target, when, delay]);
  return point;
}

/** A teammate's labelled cursor gliding onto something and tapping it. */
export function GuideCursor({
  point,
  show,
  pressing,
  name,
  color,
}: {
  point: { x: number; y: number } | null;
  show: boolean;
  pressing: boolean;
  name: string;
  color: string;
}) {
  return (
    <AnimatePresence>
      {show && point && (
        <motion.div
          aria-hidden
          className="pointer-events-none absolute left-0 top-0 z-30 flex items-start"
          initial={{ x: point.x + 120, y: point.y + 80, opacity: 0 }}
          animate={{ x: point.x, y: point.y, opacity: 1, scale: pressing ? 0.86 : 1 }}
          exit={{ opacity: 0, transition: { duration: 0.2 } }}
          transition={{ type: "spring", stiffness: 70, damping: 16 }}
        >
          <svg width="18" height="20" viewBox="0 0 18 20" className="drop-shadow-[0_2px_3px_rgb(15_16_13/0.3)]">
            <path d="M1.5 1.5 L16 9.2 L9.4 10.6 L6.2 17.6 Z" fill="#0f100d" stroke="#fff" strokeWidth="1.5" strokeLinejoin="round" />
          </svg>
          <span className="-ml-0.5 mt-3.5 block w-fit rounded-md rounded-tl-sm px-1.5 py-[1px] text-[10.5px] font-semibold text-ink" style={{ background: color }}>
            {name}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export function Toast({ show, children, dark = false, className }: { show: boolean; children: ReactNode; dark?: boolean; className?: string }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div
          initial={{ opacity: 0, y: -10, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -6, transition: { duration: 0.2 } }}
          transition={{ duration: 0.4, ease }}
          className={`pointer-events-none absolute z-20 flex items-center gap-2 rounded-xl px-3 py-2 text-[12px] font-medium shadow-[0_12px_28px_-12px_rgb(15_16_13/0.45)] ${
            dark ? "bg-white text-ink" : "bg-ink text-paper"
          } ${className ?? ""}`}
        >
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Three bouncing dots, used for "Cue is typing". */
export function TypingDots({ className }: { className?: string }) {
  return (
    <span className={`flex gap-[3px] ${className ?? ""}`}>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="size-[5px] rounded-full bg-current"
          animate={{ opacity: [0.3, 1, 0.3], y: [0, -2, 0] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.15, ease: "easeInOut" }}
        />
      ))}
    </span>
  );
}
