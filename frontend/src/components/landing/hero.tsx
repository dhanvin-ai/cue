"use client";

import Link from "next/link";
import type { PointerEvent } from "react";
import { motion, useMotionValue, useReducedMotion, useScroll, useTransform } from "motion/react";
import { ArrowRight } from "lucide-react";
import { IntegrationMarquee } from "@/components/ui/integration-marquee";
import { PillLink } from "@/components/ui/pill-link";
import { routes } from "@/lib/routes";
import { FloatingTiles } from "./floating-tiles";
import { ProductPreview } from "./product-preview";

const ease = [0.22, 1, 0.36, 1] as const;

const rise = (delay: number) => ({
  initial: { opacity: 0, y: 24, filter: "blur(8px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { delay, duration: 0.9, ease },
});

function Word({ children, delay }: { children: string; delay: number }) {
  return (
    <span className="inline-block overflow-hidden pb-[0.12em] align-bottom">
      <motion.span
        className="inline-block"
        initial={{ y: "105%", opacity: 0, filter: "blur(10px)" }}
        animate={{ y: "0%", opacity: 1, filter: "blur(0px)" }}
        transition={{ delay, duration: 1, ease }}
      >
        {children}
      </motion.span>
    </span>
  );
}

export function Hero() {
  const reduce = useReducedMotion();
  const pointerX = useMotionValue(0);
  const pointerY = useMotionValue(0);

  const { scrollY } = useScroll();
  const copyY = useTransform(scrollY, [0, 600], [0, -70]);
  const copyOpacity = useTransform(scrollY, [0, 480], [1, 0]);

  function trackPointer(event: PointerEvent<HTMLElement>) {
    if (event.pointerType !== "mouse") return;
    const rect = event.currentTarget.getBoundingClientRect();
    pointerX.set((event.clientX - rect.left) / rect.width - 0.5);
    pointerY.set((event.clientY - rect.top) / rect.height - 0.5);
  }

  return (
    <section
      onPointerMove={trackPointer}
      onPointerLeave={() => {
        pointerX.set(0);
        pointerY.set(0);
      }}
      className="relative isolate overflow-x-clip pt-28 sm:pt-32 md:pt-40"
    >
      <div aria-hidden className="hero-grid absolute inset-x-0 top-0 -z-10 h-[1100px]" />
      <div
        aria-hidden
        className="absolute left-1/2 top-[520px] -z-10 h-[620px] w-[1100px] max-w-[160vw] -translate-x-1/2 rounded-[100%] bg-[radial-gradient(closest-side,rgb(217_242_92/0.22),transparent)] blur-2xl"
      />

      <div className="relative h-[560px] sm:h-[600px] md:h-[640px]">
        <FloatingTiles pointer={{ x: pointerX, y: pointerY }} />

        <motion.div
          style={reduce ? undefined : { y: copyY, opacity: copyOpacity }}
          className="relative z-10 mx-auto flex max-w-[1000px] flex-col items-center px-4 pt-[88px] text-center sm:px-6 sm:pt-24 lg:pt-12 xl:pt-10"
        >
          <motion.div {...rise(0.1)}>
            <Link
              href={routes.getStarted}
              className="group inline-flex items-center gap-2.5 rounded-full border border-line bg-white/80 p-1 pr-4 text-[13px] text-ink-soft shadow-[0_1px_2px_rgb(15_16_13/0.04)] backdrop-blur transition-[border-color,box-shadow] duration-300 hover:border-[#d6d6cf] hover:shadow-card sm:text-[14px]"
            >
              <span className="rounded-full bg-lime px-3 py-1 font-medium text-ink">Beta</span>
              <span>
                <span className="hidden sm:inline">Now onboarding our first design-partner teams</span>
                <span className="sm:hidden">Onboarding design partners</span>
              </span>
              <ArrowRight className="size-3.5 text-muted transition-transform duration-300 group-hover:translate-x-0.5 group-hover:text-ink" />
            </Link>
          </motion.div>

          <h1 className="mt-7 text-[clamp(2.4rem,7vw,5.25rem)] font-semibold leading-[0.98] tracking-[-0.055em] text-ink sm:mt-9">
            <span className="block">
              <Word delay={0.2}>Meet</Word> <Word delay={0.28}>your</Word> <Word delay={0.36}>newest</Word>
            </span>
            <span className="relative inline-block">
              <motion.span
                aria-hidden
                className="absolute -inset-x-[0.14em] bottom-[0.02em] top-[0.12em] -z-10 origin-left rounded-[0.32em] bg-lime-soft"
                initial={{ scaleX: 0, opacity: 0 }}
                animate={{ scaleX: 1, opacity: 1 }}
                transition={{ delay: 0.95, duration: 0.8, ease }}
              />
              <Word delay={0.46}>teammate.</Word>
            </span>
          </h1>

          <motion.p
            {...rise(0.7)}
            className="mt-6 max-w-[34rem] text-balance text-[17px] leading-[1.5] tracking-[-0.01em] text-ink-soft sm:mt-7 sm:text-[21px]"
          >
            One teammate. Every conversation, meeting, and project.{" "}
            <span className="text-ink">Always in the loop.</span>
          </motion.p>

          <motion.div {...rise(0.85)} className="mt-9 flex flex-col items-center gap-4 sm:mt-10">
            <PillLink href={routes.meetCue} size="lg" dot>
              Meet CUE
            </PillLink>
            <IntegrationMarquee label="Works with" className="mt-4 w-[min(980px,100vw-2rem)]" />
          </motion.div>
        </motion.div>
      </div>

      <ProductPreview />
    </section>
  );
}
