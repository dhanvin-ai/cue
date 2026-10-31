"use client";

import Image from "next/image";
import { MotionConfig, motion } from "motion/react";
import { Play, X } from "lucide-react";
import { useEffect, useRef, useState, type MouseEvent } from "react";

const ease = [0.22, 1, 0.36, 1] as const;

const video = {
  poster: "/video/cue-meeting-demo-poster.jpg",
  webm: "/video/cue-meeting-demo.webm",
  mp4: "/video/cue-meeting-demo.mp4",
  length: "0:20",
};

const inView = (delay = 0, y = 18) => ({
  initial: { opacity: 0, y },
  whileInView: { opacity: 1, y: 0 },
  viewport: { once: true, amount: 0.6 },
  transition: { duration: 0.8, ease, delay },
});

/** Rendered demo film (see /video) behind a poster frame; plays in a modal on click. */
export function MeetingDemo() {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);

  // The modal owns the screen while it's up, so the page behind it shouldn't scroll.
  useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    const before = root.style.overflow;
    root.style.overflow = "hidden";
    return () => {
      root.style.overflow = before;
    };
  }, [open]);

  const play = () => {
    dialog.current?.showModal();
    setOpen(true);
  };

  // Clicks that land on the dialog itself are on the backdrop around the video.
  const dismiss = (event: MouseEvent<HTMLDialogElement>) => {
    if (event.target === event.currentTarget) dialog.current?.close();
  };

  return (
    <MotionConfig reducedMotion="user">
      <section id="demo" aria-labelledby="demo-title" className="relative mx-auto max-w-[1240px] scroll-mt-24 px-3 pt-24 sm:px-6 sm:pt-32">
        <header className="mx-auto max-w-[780px] px-2 text-center">
          <motion.span
            {...inView(0, 10)}
            className="inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-3.5 py-1.5 text-[12.5px] font-medium text-ink-soft"
          >
            <span className="size-1.5 rounded-full bg-lime ring-2 ring-lime/30" />
            In the meeting
          </motion.span>
          <motion.h2
            id="demo-title"
            {...inView(0.05, 20)}
            className="mt-5 text-balance text-[clamp(2.1rem,5.2vw,3.75rem)] font-semibold leading-[1.02] tracking-[-0.05em] text-ink"
          >
            Not another bot in your meeting.{" "}
            <span className="relative inline-block">
              <motion.span
                aria-hidden
                className="absolute -inset-x-[0.12em] bottom-[0.02em] top-[0.14em] -z-10 origin-left rounded-[0.3em] bg-lime-soft"
                initial={{ scaleX: 0 }}
                whileInView={{ scaleX: 1 }}
                viewport={{ once: true, amount: 0.8 }}
                transition={{ duration: 0.8, ease, delay: 0.45 }}
              />
              Another teammate.
            </span>
          </motion.h2>
          <motion.p
            {...inView(0.12, 16)}
            className="mx-auto mt-5 max-w-[36rem] text-balance text-[17px] leading-[1.5] text-ink-soft sm:text-[19px]"
          >
            CUE joins the conversation, remembers what matters, answers in real time, and follows through after everyone leaves.
          </motion.p>
        </header>

        <motion.div
          initial={{ opacity: 0, y: 48, scale: 0.97 }}
          whileInView={{ opacity: 1, y: 0, scale: 1 }}
          viewport={{ once: true, amount: 0.25 }}
          transition={{ duration: 1, ease }}
          className="mt-12 sm:mt-14"
        >
          <button
            type="button"
            onClick={play}
            aria-haspopup="dialog"
            aria-label={`Play the CUE meeting demo, ${video.length}`}
            className="group relative block aspect-video w-full overflow-hidden rounded-[22px] bg-paper-deep shadow-window ring-1 ring-black/[0.06] outline-none focus-visible:ring-4 focus-visible:ring-lime sm:rounded-[32px]"
          >
            <Image
              src={video.poster}
              alt=""
              fill
              sizes="(min-width: 1240px) 1192px, calc(100vw - 24px)"
              className="object-cover transition-transform duration-[900ms] ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:scale-[1.025]"
            />
            <span aria-hidden className="absolute inset-0 bg-[radial-gradient(circle_at_center,rgb(15_16_13/0.28),rgb(15_16_13/0.06)_55%)] transition-opacity duration-500 group-hover:opacity-70" />

            <span aria-hidden className="absolute left-1/2 top-1/2 grid -translate-x-1/2 -translate-y-1/2 place-items-center">
              <span className="demo-pulse absolute size-full rounded-full bg-white/50" />
              <span className="demo-pulse absolute size-full rounded-full bg-white/40 [animation-delay:1.2s]" />
              <span className="relative grid size-[68px] place-items-center rounded-full bg-white/90 text-ink shadow-[0_18px_40px_-12px_rgb(15_16_13/0.5)] ring-1 ring-white/60 backdrop-blur-md transition-transform duration-500 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:scale-110 group-active:scale-95 sm:size-[104px]">
                <Play className="ml-1 size-6 fill-ink sm:size-9" strokeWidth={1.5} />
              </span>
            </span>

            <span
              aria-hidden
              className="absolute bottom-3 left-3 flex items-center gap-2 rounded-full bg-ink/85 py-1.5 pl-2 pr-3.5 text-[12px] font-medium text-paper backdrop-blur sm:bottom-6 sm:left-6 sm:text-[13.5px]"
            >
              <span className="grid size-5 place-items-center rounded-full bg-lime text-ink sm:size-6">
                <Play className="ml-px size-2.5 fill-ink sm:size-3" strokeWidth={2} />
              </span>
              Watch the demo · {video.length}
            </span>
            <span
              aria-hidden
              className="absolute bottom-3 right-3 hidden items-center gap-2 rounded-full bg-white/90 px-3.5 py-1.5 text-[13px] font-medium text-ink-soft backdrop-blur sm:bottom-6 sm:right-6 sm:flex"
            >
              <Image src="/integrations/google-meet.svg" alt="" width={16} height={16} unoptimized />
              Google Meet
              <span className="text-faint">·</span>
              <Image src="/integrations/zoom.svg" alt="" width={16} height={16} unoptimized />
              Zoom
            </span>
          </button>
        </motion.div>
        <p className="mt-4 text-center text-[12px] text-faint">Illustrative demo with sample data. No real meetings were joined.</p>

        <dialog
          ref={dialog}
          aria-label="CUE meeting demo"
          onClose={() => setOpen(false)}
          onClick={dismiss}
          className="demo-dialog m-auto max-h-none max-w-none overflow-visible bg-transparent p-0 backdrop:bg-[rgb(15_16_13/0.84)] backdrop:backdrop-blur-sm"
        >
          <div className="relative w-[min(1280px,calc(100vw-2rem),calc((100svh-7rem)*16/9))]">
            {open && (
              <video
                autoPlay
                controls
                muted
                playsInline
                preload="auto"
                poster={video.poster}
                className="block aspect-video w-full rounded-[16px] bg-ink shadow-[0_40px_120px_-30px_rgb(0_0_0/0.7)] sm:rounded-[24px]"
              >
                <source src={video.webm} type="video/webm" />
                <source src={video.mp4} type="video/mp4" />
              </video>
            )}
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              aria-label="Close video"
              className="absolute -top-12 right-0 grid size-10 place-items-center rounded-full bg-white/10 text-white ring-1 ring-white/20 transition hover:bg-white/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-lime"
            >
              <X className="size-5" />
            </button>
          </div>
        </dialog>
      </section>
    </MotionConfig>
  );
}
