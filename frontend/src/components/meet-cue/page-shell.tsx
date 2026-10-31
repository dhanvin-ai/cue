import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { CueLogo } from "@/components/brand/cue-logo";
import { SiteFooter } from "@/components/landing/site-footer";
import { routes } from "@/lib/routes";

/** Frame for the Meet CUE pages: logo bar, the hero's ruled grid and lime glow, footer. */
export function MeetCueShell({
  children,
  back = { href: routes.home, label: "Back to home" },
}: {
  children: ReactNode;
  back?: { href: string; label: string };
}) {
  return (
    <>
      <div className="relative isolate flex flex-1 flex-col overflow-x-clip">
        <div aria-hidden className="hero-grid absolute inset-x-0 top-0 -z-10 h-[900px]" />
        <div
          aria-hidden
          className="absolute left-1/2 top-[260px] -z-10 h-[520px] w-[1000px] max-w-[160vw] -translate-x-1/2 rounded-[100%] bg-[radial-gradient(closest-side,rgb(217_242_92/0.2),transparent)] blur-2xl"
        />
        <header className="mx-auto flex h-16 w-full max-w-[1320px] items-center justify-between px-4 sm:px-6 md:h-20 lg:px-10">
          <Link
            href={routes.home}
            aria-label="CUE home"
            className="rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ink"
          >
            <CueLogo />
          </Link>
          <Link
            href={back.href}
            className="group inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[14px] text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-ink"
          >
            <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
            {back.label}
          </Link>
        </header>
        <main className="flex-1 px-4 pb-20 pt-6 sm:px-6 sm:pb-28 sm:pt-10">{children}</main>
      </div>
      <SiteFooter />
    </>
  );
}

/** Small rounded label used above headings across the site. */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-3.5 py-1.5 text-[12.5px] font-medium text-ink-soft backdrop-blur">
      <span className="size-1.5 rounded-full bg-lime ring-2 ring-lime/30" />
      {children}
    </span>
  );
}

/** White card on paper, matching the placeholder pages. */
export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-[28px] border border-line bg-white/85 shadow-window backdrop-blur ${className ?? ""}`}>
      {children}
    </div>
  );
}
