import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import type { ReactNode } from "react";
import { CueLogo } from "@/components/brand/cue-logo";
import { routes } from "@/lib/routes";

/** Stand-in for routes the landing page links to but that aren't built yet. */
export function PlaceholderPage({
  eyebrow,
  title,
  children,
}: {
  eyebrow: string;
  title: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="relative isolate flex min-h-screen flex-col">
      <div aria-hidden className="hero-grid absolute inset-0 -z-10" />
      <header className="mx-auto flex h-16 w-full max-w-[1320px] items-center justify-between px-4 sm:px-6 md:h-20 lg:px-10">
        <Link href={routes.home} aria-label="CUE home">
          <CueLogo />
        </Link>
        <Link
          href={routes.home}
          className="group inline-flex items-center gap-1.5 text-[14px] text-muted transition-colors hover:text-ink"
        >
          <ArrowLeft className="size-4 transition-transform group-hover:-translate-x-0.5" />
          Back to home
        </Link>
      </header>
      <main className="flex flex-1 items-center justify-center px-4 pb-24">
        <div className="w-full max-w-[520px] rounded-[28px] border border-line bg-white/80 p-8 text-center shadow-window backdrop-blur sm:p-10">
          <span className="inline-flex rounded-full bg-lime-soft px-3 py-1 text-[12px] font-medium text-lime-ink">
            {eyebrow}
          </span>
          <h1 className="mt-5 text-[34px] font-semibold leading-[1.05] tracking-[-0.045em] text-ink sm:text-[40px]">
            {title}
          </h1>
          <div className="mt-4 text-[15.5px] leading-relaxed text-ink-soft">{children}</div>
        </div>
      </main>
    </div>
  );
}
