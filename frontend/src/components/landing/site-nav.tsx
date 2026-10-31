"use client";

import Link from "next/link";
import { useState } from "react";
import { AnimatePresence, motion, useMotionValueEvent, useScroll } from "motion/react";
import { ArrowRight, Menu, X } from "lucide-react";
import { CueLogo, CueMark } from "@/components/brand/cue-logo";
import { PillLink } from "@/components/ui/pill-link";
import { routes } from "@/lib/routes";

const links = [
  { label: "Product", href: routes.product },
  { label: "Pricing", href: routes.pricing },
  { label: "Log In", href: routes.login },
];

const ease = [0.22, 1, 0.36, 1] as const;

export function SiteNav() {
  const { scrollY } = useScroll();
  const [docked, setDocked] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useMotionValueEvent(scrollY, "change", (y) => setDocked(y > 160));

  return (
    <>
      {/* Full-width bar: always on mobile, at the top of the page on desktop. */}
      <motion.header
        initial={{ opacity: 0, y: -12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease }}
        className={`fixed inset-x-0 top-0 z-50 border-b transition-[background-color,backdrop-filter,border-color] duration-500 ${
          docked || menuOpen
            ? "border-line/70 bg-paper/80 backdrop-blur-xl"
            : "border-transparent bg-paper/0"
        } ${docked && !menuOpen ? "md:pointer-events-none md:border-transparent md:bg-paper/0 md:backdrop-blur-none" : ""}`}
      >
        <nav
          aria-label="Main"
          className={`mx-auto flex h-16 max-w-[1320px] items-center justify-between px-4 transition-[opacity,translate] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] sm:px-6 md:h-20 lg:px-10 ${
            docked ? "md:-translate-y-4 md:opacity-0" : ""
          }`}
        >
          <Link href={routes.home} aria-label="CUE home" className="rounded-md focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ink">
            <CueLogo />
          </Link>

          <div className="hidden items-center gap-1 md:flex">
            {links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                className="group relative rounded-full px-4 py-2 text-[15px] text-muted transition-colors duration-300 hover:text-ink focus-visible:outline-2 focus-visible:outline-ink"
              >
                {link.label}
                <span className="absolute inset-x-4 bottom-1.5 h-px origin-left scale-x-0 bg-ink/40 transition-transform duration-300 ease-out group-hover:scale-x-100" />
              </Link>
            ))}
            <PillLink href={routes.getStarted} size="md" className="ml-4">
              Get Started
            </PillLink>
          </div>

          <div className="flex items-center gap-2 md:hidden">
            <PillLink href={routes.getStarted} size="sm">
              Get Started
            </PillLink>
            <button
              type="button"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
              aria-controls="mobile-menu"
              onClick={() => setMenuOpen((open) => !open)}
              className="grid size-9 place-items-center rounded-full border border-line bg-white/70 text-ink transition-colors hover:bg-white"
            >
              {menuOpen ? <X className="size-4" /> : <Menu className="size-4" />}
            </button>
          </div>
        </nav>

        <AnimatePresence>
          {menuOpen && (
            <motion.div
              id="mobile-menu"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.35, ease }}
              className="overflow-hidden md:hidden"
            >
              <ul className="flex flex-col gap-1 px-4 pb-5 sm:px-6">
                {links.map((link, i) => (
                  <motion.li
                    key={link.label}
                    initial={{ opacity: 0, y: -6 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ delay: 0.05 * i + 0.05, duration: 0.3, ease }}
                  >
                    <Link
                      href={link.href}
                      onClick={() => setMenuOpen(false)}
                      className="flex items-center justify-between rounded-2xl px-3 py-3 text-[17px] font-medium tracking-[-0.02em] text-ink hover:bg-paper-deep"
                    >
                      {link.label}
                      <ArrowRight className="size-4 text-faint" />
                    </Link>
                  </motion.li>
                ))}
              </ul>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.header>

      {/* Floating pill that takes over on desktop once the hero scrolls away. */}
      <AnimatePresence>
        {docked && (
          <motion.nav
            aria-label="Main (compact)"
            initial={{ opacity: 0, y: -24, scale: 0.94, x: "-50%" }}
            animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
            exit={{ opacity: 0, y: -24, scale: 0.94, x: "-50%" }}
            transition={{ type: "spring", stiffness: 380, damping: 32 }}
            className="fixed left-1/2 top-5 z-50 hidden items-center gap-1 whitespace-nowrap rounded-full bg-ink/95 p-1.5 pl-3 text-[15px] shadow-[0_1px_0_rgb(255_255_255/0.1)_inset,0_20px_40px_-12px_rgb(15_16_13/0.45)] backdrop-blur-xl md:flex"
          >
            <Link href={routes.home} aria-label="CUE home" className="mr-2 grid size-8 place-items-center rounded-full">
              <CueMark tone="paper" className="size-6" />
            </Link>
            {links.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                className="rounded-full px-4 py-2 text-paper/60 transition-colors duration-300 hover:bg-white/8 hover:text-paper"
              >
                {link.label}
              </Link>
            ))}
            <Link
              href={routes.getStarted}
              className="group ml-1 inline-flex items-center gap-1.5 rounded-full bg-white/6 px-4 py-2 font-medium text-lime transition-colors duration-300 hover:bg-lime hover:text-ink"
            >
              Get Started
              <ArrowRight className="size-4 transition-transform duration-300 group-hover:translate-x-0.5" />
            </Link>
          </motion.nav>
        )}
      </AnimatePresence>
    </>
  );
}
