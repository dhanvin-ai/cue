import { Check } from "lucide-react";
import { AbsoluteFill, useCurrentFrame } from "remotion";
import { CueMark } from "@/components/brand/cue-logo";
import { chapters, DURATION, prog } from "./lib";
import { InviteScene } from "./scenes/invite";
import { MeetScene } from "./scenes/meet";
import { RecapScene } from "./scenes/recap";
import { ZoomScene } from "./scenes/zoom";

function Backdrop({ f }: { f: number }) {
  return (
    <AbsoluteFill className="bg-paper">
      <AbsoluteFill
        style={{
          backgroundImage:
            "linear-gradient(to bottom, rgb(15 16 13 / 0.05) 1px, transparent 1px), linear-gradient(to right, rgb(15 16 13 / 0.035) 1px, transparent 1px)",
          backgroundSize: "100% 96px, 96px 100%",
          // Drifts slower than the windows, so the stage reads as having depth.
          backgroundPosition: `${-f * 0.5}px ${-f * 0.25}px`,
          maskImage: "radial-gradient(ellipse 80% 70% at 50% 45%, black 35%, transparent 85%)",
        }}
      />
    </AbsoluteFill>
  );
}

function Progress({ f }: { f: number }) {
  const current = chapters.findLastIndex((c) => f >= c.at);
  const hide = prog(f, 566, 14);
  return (
    <div
      className="absolute inset-x-0 bottom-[30px] flex justify-center"
      style={{ opacity: prog(f, 4, 16) * (1 - hide), translate: `0 ${hide * 16}px` }}
    >
      <div className="flex items-center gap-1 rounded-full bg-white/90 p-1.5 shadow-[0_10px_30px_-12px_rgb(15_16_13/0.3)] ring-1 ring-black/[0.06]">
        {chapters.map((c, i) => {
          const end = chapters[i + 1]?.at ?? DURATION;
          const active = i === current;
          const done = i < current;
          return (
            <span
              key={c.label}
              className={`relative flex h-[42px] items-center gap-2 overflow-hidden rounded-full px-4 text-[17px] font-medium ${
                active ? "bg-ink text-paper" : done ? "text-ink-soft" : "text-faint"
              }`}
            >
              {done ? (
                <Check className="size-4 text-lime-ink" strokeWidth={3} />
              ) : (
                <span className={`font-mono text-[14px] ${active ? "text-lime" : ""}`}>{String(i + 1).padStart(2, "0")}</span>
              )}
              {c.label}
              {active && (
                <span
                  className="absolute bottom-0 left-0 h-[3px] bg-lime"
                  style={{ width: `${Math.min(1, (f - c.at) / (end - c.at)) * 100}%` }}
                />
              )}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function Corners({ f }: { f: number }) {
  const show = prog(f, 0, 16);
  return (
    <>
      <span className="absolute left-[56px] top-[24px] flex items-center gap-2.5" style={{ opacity: show }}>
        <CueMark className="size-[38px]" />
        <span className="text-[30px] font-semibold tracking-[-0.04em] text-ink">cue</span>
      </span>
      <span className="absolute right-[56px] top-[34px] text-[17px] text-muted" style={{ opacity: show }}>
        Illustrative demo · sample data
      </span>
    </>
  );
}

/** `poster` drops the progress strip so the landing page can lay its own controls over the still. */
export function CueMeetingDemo({ sans, mono, poster = false }: { sans: string; mono: string; poster?: boolean }) {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill
      className="overflow-hidden font-sans text-ink antialiased"
      style={{ ["--font-geist-sans" as string]: sans, ["--font-geist-mono" as string]: mono }}
    >
      <Backdrop f={f} />
      {/* Under the scenes, so windows pass over the corner marks as the camera moves. */}
      <Corners f={f} />
      <InviteScene f={f} />
      <MeetScene f={f} />
      <RecapScene f={f} />
      <ZoomScene f={f} />
      {!poster && <Progress f={f} />}
    </AbsoluteFill>
  );
}
