import Link from "next/link";
import { CueLogo } from "@/components/brand/cue-logo";
import { routes } from "@/lib/routes";

export function SiteFooter() {
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-[1320px] flex-col gap-6 px-4 py-10 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-10">
        <div className="flex items-center gap-4">
          <CueLogo />
          <span className="text-[13px] text-muted">Your AI teammate.</span>
        </div>
        <nav aria-label="Footer" className="flex flex-wrap gap-x-6 gap-y-2 text-[14px] text-muted">
          <Link href={routes.product} className="transition-colors hover:text-ink">Product</Link>
          <Link href={routes.pricing} className="transition-colors hover:text-ink">Pricing</Link>
          <Link href={routes.login} className="transition-colors hover:text-ink">Log In</Link>
          <Link href={routes.getStarted} className="transition-colors hover:text-ink">Get Started</Link>
        </nav>
        <p className="text-[12px] text-faint">© 2026 CUE</p>
      </div>
    </footer>
  );
}
