"use client";

import { motion, useInView, useReducedMotion, useScroll, useSpring, useTransform } from "motion/react";
import { Search } from "lucide-react";
import { useRef } from "react";
import { ActivityRail } from "./preview/activity-rail";
import { Channel } from "./preview/channel";
import { Connectors, useConnectorRegistry, type Link } from "./preview/connectors";
import { ProfileRail, ProfileStrip } from "./preview/profile-rail";
import { activeSources, useScene } from "./preview/scene";

export function ProductPreview() {
  const reduce = useReducedMotion() ?? false;
  const frameRef = useRef<HTMLDivElement>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const inView = useInView(frameRef, { amount: 0.25 });
  const { index, cycle, at } = useScene(inView, reduce);
  const { nodes, register } = useConnectorRegistry();

  // The window starts tipped back and settles flat as it scrolls into view.
  const { scrollYProgress } = useScroll({ target: frameRef, offset: ["start end", "start 0.2"] });
  const progress = useSpring(scrollYProgress, { stiffness: 90, damping: 24, mass: 0.4 });
  const rotateX = useTransform(progress, [0, 1], [24, 0]);
  const scale = useTransform(progress, [0, 1], [0.9, 1]);
  const y = useTransform(progress, [0, 1], [40, 0]);

  const { tools: liveTools, items: hotItems } = activeSources(at);
  const ticket = at("done") ? "done" : at("plan") ? "waiting" : "none";

  let links: Link[] = [];
  if (at("reading") && !at("typing-request")) {
    links = ["pr-412", "pr-418", "mtg-sync"].map((from) => ({ from, to: "cue-answer" }));
  } else if (at("done")) {
    links = [{ from: "cue-plan", to: "task-ticket" }];
  }

  return (
    <div id="product" className="relative z-10 mx-auto -mt-4 max-w-[1320px] scroll-mt-24 px-3 sm:px-6 lg:px-10">
      <motion.div
        initial={{ opacity: 0, y: 60 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 1.05, duration: 1.1, ease: [0.22, 1, 0.36, 1] }}
        style={{ perspective: 1600 }}
      >
        <motion.div
          ref={frameRef}
          style={reduce ? undefined : { rotateX, scale, y, transformOrigin: "50% 0%" }}
          className="rounded-[30px] border border-white/90 bg-white/55 p-1.5 shadow-window ring-1 ring-black/[0.05] backdrop-blur-sm sm:rounded-[36px] sm:p-2.5"
        >
          <div className="overflow-hidden rounded-[24px] border border-line bg-white sm:rounded-[28px]">
            {/* Window chrome */}
            <div className="flex h-11 items-center gap-3 border-b border-line bg-paper/70 px-4 sm:h-12 sm:px-5">
              <div className="flex gap-1.5">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="size-2.5 rounded-full bg-line" />
                ))}
              </div>
              <span className="text-[12px] font-medium text-muted">
                <span className="text-ink">Cue&apos;s desk</span>
                <span className="hidden sm:inline"> · yourteam</span>
              </span>
              <span className="ml-auto hidden items-center gap-2 rounded-lg border border-line bg-white px-2.5 py-1.5 text-[12px] text-faint sm:flex sm:w-56">
                <Search className="size-3.5" />
                Ask Cue anything
                <kbd className="ml-auto rounded border border-line px-1 font-mono text-[10px] text-faint">⌘K</kbd>
              </span>
            </div>

            <ProfileStrip liveTools={liveTools} />

            <div
              ref={bodyRef}
              className="relative grid h-[520px] grid-cols-1 sm:h-[560px] md:grid-cols-[minmax(0,1fr)_290px] lg:h-[620px] lg:grid-cols-[250px_minmax(0,1fr)_300px]"
            >
              <div className="hidden lg:block">
                <ProfileRail liveTools={liveTools} />
              </div>
              <div className="min-w-0">
                <Channel at={at} index={index} cycle={cycle} register={register} />
              </div>
              <div className="hidden md:block">
                <ActivityRail hotItems={hotItems} ticket={ticket} register={register} />
              </div>
              <Connectors container={bodyRef} nodes={nodes} links={links} revision={`${cycle}:${index}`} />
            </div>
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
