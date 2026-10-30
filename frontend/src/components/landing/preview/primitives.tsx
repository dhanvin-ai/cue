import { CalendarDays, GitBranch, Hash, Mail, SquareKanban, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { CueMark } from "@/components/brand/cue-logo";

export const people = {
  priya: { name: "Priya K.", initials: "PK", tint: "#f6d2b6" },
  arjun: { name: "Arjun Kumar", initials: "AK", tint: "#c4dbf3" },
  sam: { name: "Sam R.", initials: "SR", tint: "#ddd0f5" },
} as const;

export type PersonId = keyof typeof people;

export function PersonAvatar({ id, size = 32 }: { id: PersonId; size?: number }) {
  const person = people[id];
  return (
    <span
      className="grid shrink-0 place-items-center rounded-[10px] font-semibold text-ink/70"
      style={{ width: size, height: size, background: person.tint, fontSize: size * 0.36 }}
    >
      {person.initials}
    </span>
  );
}

export function CueAvatar({ size = 32, online = false }: { size?: number; online?: boolean }) {
  return (
    <span
      className="relative grid shrink-0 place-items-center rounded-[10px] bg-[linear-gradient(160deg,#2a2b26,#0f100d)] shadow-[inset_0_1px_0_rgb(255_255_255/0.14)]"
      style={{ width: size, height: size }}
    >
      <CueMark tone="paper" className="size-[66%]" />
      {online && (
        <span className="absolute -bottom-0.5 -right-0.5 size-[30%] min-h-2.5 min-w-2.5 rounded-full bg-lime ring-2 ring-white" />
      )}
    </span>
  );
}

export const tools: Record<string, { label: string; icon: LucideIcon }> = {
  slack: { label: "Slack", icon: Hash },
  gmail: { label: "Gmail", icon: Mail },
  calendar: { label: "Calendar", icon: CalendarDays },
  github: { label: "GitHub", icon: GitBranch },
  linear: { label: "Linear", icon: SquareKanban },
};

export function ToolGlyph({ tool, className }: { tool: keyof typeof tools; className?: string }) {
  const Icon = tools[tool].icon;
  return <Icon aria-hidden strokeWidth={2} className={className ?? "size-3.5"} />;
}

export function AiBadge() {
  return (
    <span className="rounded-[5px] bg-lime-soft px-1.5 py-[1px] text-[10px] font-semibold uppercase tracking-[0.06em] text-lime-ink">
      AI teammate
    </span>
  );
}

export function RailCard({ title, aside, children }: { title: string; aside?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-line bg-white p-3 shadow-[0_1px_2px_rgb(15_16_13/0.03)]">
      <header className="mb-2 flex items-center justify-between px-1">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.1em] text-muted">{title}</h3>
        {aside}
      </header>
      <div className="flex flex-col gap-1">{children}</div>
    </section>
  );
}
