import { Check } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Img, staticFile } from "remotion";
import { CueMark } from "@/components/brand/cue-logo";
import { frame as stage } from "./lib";

export const people = {
  priya: { name: "Priya K.", initials: "P", tint: "#f6d2b6" },
  arjun: { name: "Arjun Kumar", initials: "A", tint: "#c4dbf3" },
  sam: { name: "Sam R.", initials: "S", tint: "#ddd0f5" },
  dana: { name: "Dana Whitfield", initials: "D", tint: "#f3c9c9" },
  marcus: { name: "Marcus Lee", initials: "M", tint: "#cfe8d4" },
} as const;

export type PersonId = keyof typeof people;

export function Brand({ name, size = 28, style }: { name: string; size?: number; style?: CSSProperties }) {
  return <Img src={staticFile(`integrations/${name}.svg`)} style={{ width: size, height: size, objectFit: "contain", ...style }} />;
}

/** Desktop window on the shared stage. `bar` content sits beside the window controls. */
export function Window({
  dark = false,
  bar,
  style,
  children,
}: {
  dark?: boolean;
  bar: ReactNode;
  style?: CSSProperties;
  children: ReactNode;
}) {
  return (
    <div
      className={`absolute flex flex-col overflow-hidden rounded-[30px] ring-1 ${dark ? "bg-[#202124] ring-white/10" : "bg-white ring-black/[0.06]"}`}
      style={{
        left: stage.x,
        top: stage.y,
        width: stage.w,
        height: stage.h,
        boxShadow: "0 2px 4px rgb(15 16 13 / 0.04), 0 40px 90px -30px rgb(15 16 13 / 0.35), 0 90px 160px -60px rgb(15 16 13 / 0.25)",
        ...style,
      }}
    >
      <div
        className={`flex shrink-0 items-center gap-5 border-b px-6 ${dark ? "border-white/[0.06] bg-[#17181a] text-white/75" : "border-line bg-paper text-ink-soft"}`}
        style={{ height: stage.bar }}
      >
        <div className="flex gap-2">
          {["#ff5f57", "#febc2e", "#28c840"].map((c) => (
            <span key={c} className="size-[14px] rounded-full" style={{ background: dark ? "rgb(255 255 255 / 0.16)" : c, opacity: dark ? 1 : 0.9 }} />
          ))}
        </div>
        {bar}
      </div>
      <div className="relative min-h-0 flex-1">{children}</div>
    </div>
  );
}

/** Round, camera-off participant avatar, the way meeting apps show it. */
export function Face({ id, size = 120 }: { id: PersonId; size?: number }) {
  const p = people[id];
  return (
    <span
      className="grid shrink-0 place-items-center rounded-full font-semibold text-ink/75"
      style={{ width: size, height: size, background: p.tint, fontSize: size * 0.42 }}
    >
      {p.initials}
    </span>
  );
}

export function CueFace({ size = 120, ring = 0, round = true }: { size?: number; ring?: number; round?: boolean }) {
  return (
    <span
      className="relative grid shrink-0 place-items-center bg-[linear-gradient(160deg,#2c2d27,#0f100d)]"
      style={{
        width: size,
        height: size,
        borderRadius: round ? "50%" : size * 0.3,
        boxShadow: `inset 0 1px 0 rgb(255 255 255 / 0.14), 0 0 0 ${ring * size * 0.07}px rgb(217 242 92 / ${0.9 * ring})`,
      }}
    >
      <CueMark tone="paper" className="size-[62%]" />
    </span>
  );
}

export function AiTag({ size = 15, className }: { size?: number; className?: string }) {
  return (
    <span
      className={`rounded-[6px] bg-lime px-[0.5em] py-[0.12em] font-semibold uppercase tracking-[0.06em] text-ink ${className ?? ""}`}
      style={{ fontSize: size }}
    >
      AI teammate
    </span>
  );
}

/** Speaking bars. `level` 0 is a flat idle line, 1 is full speech. */
export function Waveform({
  f,
  level,
  bars = 5,
  color = "#d9f25c",
  height = 30,
  width = 6,
  gap = 4,
}: {
  f: number;
  level: number;
  bars?: number;
  color?: string;
  height?: number;
  width?: number;
  gap?: number;
}) {
  return (
    <span className="flex items-center" style={{ gap, height }}>
      {Array.from({ length: bars }, (_, i) => {
        const n = Math.abs(Math.sin(f * 0.43 + i * 1.9)) * 0.6 + Math.abs(Math.sin(f * 0.17 + i * 0.7)) * 0.4;
        return (
          <span
            key={i}
            style={{ width, height: Math.max(width, height * (0.2 + 0.8 * n * level)), borderRadius: width, background: color }}
          />
        );
      })}
    </span>
  );
}

/** A check that pops in when `p` reaches 1, with a spinner before it. */
export function Status({ f, p, size = 30 }: { f: number; p: number; size?: number }) {
  if (p >= 1)
    return (
      <span className="grid place-items-center rounded-full bg-lime text-ink" style={{ width: size, height: size }}>
        <Check strokeWidth={3} style={{ width: size * 0.56, height: size * 0.56 }} />
      </span>
    );
  return (
    <span
      className="rounded-full border-[3px] border-line border-t-ink-soft"
      style={{ width: size, height: size, transform: `rotate(${f * 22}deg)`, opacity: p > 0 ? 1 : 0 }}
    />
  );
}
