"use client";

import { motion } from "motion/react";
import { CalendarDays, GitBranch, Hash, Mail, SquareKanban, Video, type LucideIcon } from "lucide-react";

const surfaces: { label: string; detail: string; icon: LucideIcon }[] = [
  { label: "Slack", detail: "Mentions, DMs, approvals", icon: Hash },
  { label: "Email", detail: "Its own inbox", icon: Mail },
  { label: "Calendar", detail: "Invites and briefs", icon: CalendarDays },
  { label: "Meet & Zoom", detail: "Joins by voice", icon: Video },
  { label: "GitHub", detail: "PRs, reviews, issues", icon: GitBranch },
  { label: "Linear", detail: "Tickets and cycles", icon: SquareKanban },
];

export function WorksWith() {
  return (
    <section className="relative mx-auto max-w-[1180px] px-4 pb-24 pt-24 sm:px-6 sm:pb-32 sm:pt-32">
      <motion.p
        initial={{ opacity: 0, y: 12 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, amount: 0.6 }}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
        className="text-center text-[12px] font-medium uppercase tracking-[0.22em] text-ink-soft sm:text-[13px]"
      >
        Works where your team already works
      </motion.p>
      <ul className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {surfaces.map((s, i) => (
          <motion.li
            key={s.label}
            initial={{ opacity: 0, y: 18 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true, amount: 0.4 }}
            transition={{ delay: i * 0.07, duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
            className="group flex flex-col items-center gap-2.5 rounded-2xl px-3 py-5 text-center transition-[background-color,box-shadow] duration-300 hover:bg-white hover:shadow-card"
          >
            <span className="grid size-11 place-items-center rounded-xl border border-line bg-white text-ink shadow-[0_1px_2px_rgb(15_16_13/0.04)] transition-[transform,background-color,border-color] duration-300 group-hover:-translate-y-0.5 group-hover:border-lime group-hover:bg-lime">
              <s.icon className="size-[18px]" strokeWidth={2} />
            </span>
            <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink">{s.label}</span>
            <span className="text-[12.5px] text-muted">{s.detail}</span>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}
