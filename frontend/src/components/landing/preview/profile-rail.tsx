"use client";

import { motion } from "motion/react";
import { AiBadge, CueAvatar, ToolGlyph, tools } from "./primitives";

const connections: { tool: keyof typeof tools; detail: string }[] = [
  { tool: "slack", detail: "#eng, #product, #standup" },
  { tool: "gmail", detail: "cue@yourteam.com" },
  { tool: "calendar", detail: "6 meetings this week" },
  { tool: "github", detail: "api, web" },
  { tool: "linear", detail: "Web, API" },
];

const record = [
  { label: "Started", value: "Oct 2" },
  { label: "Tasks done", value: "214" },
  { label: "Meetings", value: "38" },
];

function ConnectionRow({ tool, detail, live }: { tool: keyof typeof tools; detail: string; live: boolean }) {
  return (
    <div
      className={`relative flex items-center gap-2.5 rounded-xl px-2 py-2 transition-colors duration-500 ${
        live ? "bg-lime-wash" : "bg-transparent"
      }`}
    >
      <span
        className={`grid size-7 place-items-center rounded-lg border transition-colors duration-500 ${
          live ? "border-lime bg-lime text-ink" : "border-line bg-paper text-ink-soft"
        }`}
      >
        <ToolGlyph tool={tool} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[12.5px] font-medium leading-tight text-ink">{tools[tool].label}</span>
        <span className="block truncate text-[11px] leading-tight text-muted">{detail}</span>
      </span>
      <span className="relative flex size-2">
        {live && (
          <motion.span
            className="absolute inset-0 rounded-full bg-lime"
            initial={{ scale: 1, opacity: 0.8 }}
            animate={{ scale: 2.6, opacity: 0 }}
            transition={{ duration: 1.1, repeat: Infinity, ease: "easeOut" }}
          />
        )}
        <span className={`relative size-2 rounded-full ${live ? "bg-[#9bbd12]" : "bg-[#c7d98a]"}`} />
      </span>
    </div>
  );
}

/** Cue's profile card, as an admin would see it on Cue's desk (large screens). */
export function ProfileRail({ liveTools }: { liveTools: string[] }) {
  return (
    <aside className="flex h-full flex-col gap-3 border-r border-line bg-paper/60 p-4">
      <div className="rounded-2xl border border-line bg-white p-4 shadow-[0_1px_2px_rgb(15_16_13/0.03)]">
        <div className="flex items-start justify-between">
          <CueAvatar size={52} online />
          <span className="inline-flex items-center gap-1.5 rounded-full bg-paper px-2 py-1 text-[10.5px] font-medium text-ink-soft ring-1 ring-line">
            <span className="size-1.5 rounded-full bg-[#9bbd12]" />
            Available
          </span>
        </div>
        <div className="mt-3 flex items-center gap-2">
          <span className="text-[17px] font-semibold tracking-[-0.03em] text-ink">Cue</span>
          <AiBadge />
        </div>
        <p className="mt-0.5 text-[12.5px] text-muted">Engineering teammate</p>
        <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-line-soft pt-3">
          {record.map((item) => (
            <div key={item.label}>
              <dt className="text-[10px] uppercase tracking-[0.08em] text-faint">{item.label}</dt>
              <dd className="mt-0.5 font-mono text-[13px] font-medium text-ink">{item.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="flex-1 rounded-2xl border border-line bg-white p-2 shadow-[0_1px_2px_rgb(15_16_13/0.03)]">
        <h3 className="px-2 pb-1 pt-1.5 text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">Access</h3>
        {connections.map((c) => (
          <ConnectionRow key={c.tool} {...c} live={liveTools.includes(c.tool)} />
        ))}
      </div>

      <p className="px-1 text-[11px] leading-snug text-faint">
        Reads only what it&apos;s invited to. Asks before anything others can see.
      </p>
    </aside>
  );
}

/** Compact identity strip shown above the conversation on smaller screens. */
export function ProfileStrip({ liveTools }: { liveTools: string[] }) {
  return (
    <div className="flex items-center gap-3 border-b border-line bg-paper/60 px-4 py-3 lg:hidden">
      <CueAvatar size={38} online />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-semibold tracking-[-0.03em] text-ink">Cue</span>
          <AiBadge />
        </div>
        <p className="truncate text-[11.5px] text-muted">cue@yourteam.com · Engineering teammate</p>
      </div>
      <div className="hidden gap-1 sm:flex">
        {connections.map((c) => (
          <span
            key={c.tool}
            title={tools[c.tool].label}
            className={`grid size-7 place-items-center rounded-lg border transition-colors duration-500 ${
              liveTools.includes(c.tool) ? "border-lime bg-lime text-ink" : "border-line bg-white text-ink-soft"
            }`}
          >
            <ToolGlyph tool={c.tool} />
          </span>
        ))}
      </div>
    </div>
  );
}
