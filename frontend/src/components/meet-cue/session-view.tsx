"use client";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import {
  ArrowRight,
  ArrowUpRight,
  CalendarClock,
  CalendarX,
  Check,
  CircleAlert,
  Clock,
  MicOff,
  RefreshCw,
} from "lucide-react";
import { PillButton } from "@/components/ui/pill-button";
import { PillLink } from "@/components/ui/pill-link";
import {
  callApi,
  claimAutoRedirect,
  describeError,
  formatDateTime,
  formatDuration,
  readCreated,
  safeMeetUrl,
  useNow,
  useTimeZone,
} from "@/lib/meet-cue/client";
import { isInCall, isTerminal, isUuid, type ApiError, type DemoSession, type DemoSummary } from "@/lib/meet-cue/types";
import { routes } from "@/lib/routes";
import { Notice } from "./fields";

const ease = [0.22, 1, 0.36, 1] as const;

const POLL_MS = 2_000;
/** A scheduled session far from its start time doesn't need 2 s polling. */
const IDLE_POLL_MS = 15_000;
const SLOW_JOIN_MS = 60_000;
const REDIRECT_MS = 3_000;

/** Errors after which polling can't succeed, so we stop and explain. */
const isFatal = (error: ApiError) =>
  error.status === 400 || error.status === 401 || error.status === 403 || error.status === 404 || error.error === "not_configured";

export function SessionView({ id }: { id: string }) {
  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto max-w-[640px]">
        {isUuid(id) ? (
          <SessionTracker id={id} />
        ) : (
          <ProblemState error={{ status: 404, error: "not_found" }} />
        )}
      </div>
    </MotionConfig>
  );
}

/** Suspense fallback while the route params resolve. */
export function SessionLoading() {
  return (
    <div className="mx-auto max-w-[640px]">
      <LoadingState />
    </div>
  );
}

function SessionTracker({ id }: { id: string }) {
  const [session, setSession] = useState<DemoSession | null>(null);
  const [fatal, setFatal] = useState<ApiError | null>(null);
  const [transient, setTransient] = useState<ApiError | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  // When Cue reached the call for a "now" demo: when to send the visitor to Meet.
  const [redirectAt, setRedirectAt] = useState<number | null>(null);
  const [redirectCancelled, setRedirectCancelled] = useState(false);
  // Reference point for the "taking longer than usual" fallback.
  const [joinClockStart, setJoinClockStart] = useState<number | null>(null);
  const redirectClaimed = useRef(false);
  const navigated = useRef(false);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    let failures = 0;

    async function poll() {
      const result = await callApi<DemoSession>(`/api/meet-cue/sessions/${id}`);
      if (stopped) return;

      if (!result.ok) {
        if (isFatal(result.error)) {
          setFatal(result.error);
          return;
        }
        failures += 1;
        setTransient(result.error);
        timer = window.setTimeout(poll, Math.min(POLL_MS * 2 ** (failures - 1), 15_000));
        return;
      }

      failures = 0;
      const data = result.data;
      setSession(data);
      setTransient(null);
      setFatal(null);
      setJoinClockStart((current) => current ?? joinReference(id, data));

      if (
        !redirectClaimed.current &&
        data.mode === "now" &&
        isInCall(data.status) &&
        safeMeetUrl(data.meet_url)
      ) {
        redirectClaimed.current = true;
        if (claimAutoRedirect(id)) setRedirectAt(Date.now() + REDIRECT_MS);
      }

      if (isTerminal(data.status)) return;
      const startsIn = Date.parse(data.start_at) - Date.now();
      const delay = data.status === "scheduled" && startsIn > 2 * 60_000 ? IDLE_POLL_MS : POLL_MS;
      timer = window.setTimeout(poll, delay);
    }

    poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [id, refreshKey]);

  const meetUrl = safeMeetUrl(session?.meet_url);
  const counting = redirectAt !== null && !redirectCancelled;
  const waiting = session !== null && !isTerminal(session.status) && !isInCall(session.status) && session.status !== "scheduled";
  const now = useNow(counting ? 200 : 1_000, counting || waiting);

  useEffect(() => {
    if (!counting || !meetUrl || navigated.current || now < redirectAt) return;
    navigated.current = true;
    window.location.assign(meetUrl);
  }, [counting, meetUrl, now, redirectAt]);

  if (fatal) return <ProblemState error={fatal} />;
  if (!session) {
    return transient ? <ProblemState error={transient} retrying /> : <LoadingState />;
  }

  const slow = waiting && joinClockStart !== null && now - joinClockStart > SLOW_JOIN_MS;
  const secondsLeft = counting ? Math.max(0, Math.ceil((redirectAt - now) / 1000)) : null;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={phase(session)}
        initial={{ opacity: 0, y: 14 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -8 }}
        transition={{ duration: 0.5, ease }}
      >
        {session.status === "scheduled" ? (
          <ScheduledState
            id={id}
            session={session}
            onCancelled={() => {
              setSession({ ...session, status: "cancelled" });
              setRefreshKey((key) => key + 1);
            }}
          />
        ) : session.status === "ended" ? (
          <EndedState id={id} />
        ) : session.status === "failed" ? (
          <FailedState session={session} />
        ) : session.status === "cancelled" ? (
          <CancelledState />
        ) : (
          <LiveState
            session={session}
            meetUrl={meetUrl}
            slow={slow}
            secondsLeft={secondsLeft}
            onCancelRedirect={() => setRedirectCancelled(true)}
            reconnecting={transient !== null}
          />
        )}
      </motion.div>
    </AnimatePresence>
  );
}

/** For "now" demos, when the visitor pressed Start; for scheduled ones, the start time. */
function joinReference(id: string, session: DemoSession) {
  const start = Date.parse(session.start_at);
  if (session.mode === "now") return readCreated(id) ?? (Number.isNaN(start) ? Date.now() : start);
  return Number.isNaN(start) ? Date.now() : start;
}

function phase(session: DemoSession) {
  if (session.status === "scheduled" || session.status === "ended" || session.status === "failed" || session.status === "cancelled") {
    return session.status;
  }
  return "live";
}

/* ------------------------------------------------------------------ */
/* Shared pieces                                                       */

function StateHeader({ eyebrow, title, children }: { eyebrow: ReactNode; title: ReactNode; children?: ReactNode }) {
  return (
    <header className="text-center">
      <span className="inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-3.5 py-1.5 text-[12.5px] font-medium text-ink-soft backdrop-blur">
        {eyebrow}
      </span>
      <h1 className="mt-5 text-balance text-[clamp(2rem,5.4vw,3.1rem)] font-semibold leading-[1.04] tracking-[-0.05em] text-ink">
        {title}
      </h1>
      {children && (
        <p className="mx-auto mt-4 max-w-[30rem] text-balance text-[16px] leading-[1.5] text-ink-soft sm:text-[17px]">{children}</p>
      )}
    </header>
  );
}

function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={`mt-8 rounded-[28px] border border-line bg-white/85 p-5 shadow-window backdrop-blur sm:mt-10 sm:p-8 ${className ?? ""}`}>
      {children}
    </div>
  );
}

function LiveDot({ tone = "lime" }: { tone?: "lime" | "muted" }) {
  return (
    <span className="relative flex size-2">
      {tone === "lime" && <span className="absolute inset-0 animate-ping rounded-full bg-lime opacity-70 motion-reduce:hidden" />}
      <span className={`relative size-2 rounded-full ${tone === "lime" ? "bg-lime ring-2 ring-lime/30" : "bg-faint"}`} />
    </span>
  );
}

const pillBase =
  "group relative inline-flex shrink-0 items-center justify-center rounded-full font-medium tracking-[-0.01em] transition-[transform,box-shadow,background-color] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-ink";

/** The Google Meet link, as a normal same-tab link, plus a new-tab alternative. */
function JoinMeet({ meetUrl, emphasis = "primary" }: { meetUrl: string; emphasis?: "primary" | "secondary" }) {
  return (
    <div className="flex flex-col items-stretch gap-3 sm:flex-row sm:items-center">
      <a
        href={meetUrl}
        className={`${pillBase} h-14 gap-2.5 px-7 text-[17px] hover:-translate-y-0.5 active:translate-y-0 active:scale-[0.98] ${
          emphasis === "primary"
            ? "bg-ink text-paper shadow-[0_1px_0_rgb(255_255_255/0.12)_inset,0_10px_24px_-10px_rgb(15_16_13/0.6)] hover:bg-[#1c1d19] hover:shadow-[0_1px_0_rgb(255_255_255/0.12)_inset,0_18px_32px_-12px_rgb(15_16_13/0.55)]"
            : "border border-line bg-white text-ink hover:border-[#d6d6cf] hover:shadow-card"
        }`}
      >
        <span className="grid size-7 place-items-center rounded-full bg-white">
          <Image src="/integrations/google-meet.svg" alt="" width={16} height={16} unoptimized className="size-4" />
        </span>
        Join Google Meet
        <ArrowRight aria-hidden strokeWidth={2.2} className="size-[1.05em] transition-transform duration-300 group-hover:translate-x-1" />
      </a>
      <a
        href={meetUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center justify-center gap-1 rounded-full px-3 py-2 text-[14px] text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-ink"
      >
        Open in new tab
        <ArrowUpRight aria-hidden className="size-4" />
      </a>
    </div>
  );
}

function BackToBooking({ label = "Back to Meet CUE" }: { label?: string }) {
  return (
    <PillLink href={routes.meetCue} size="md">
      {label}
    </PillLink>
  );
}

/* ------------------------------------------------------------------ */
/* States                                                              */

function LoadingState() {
  return (
    <div role="status" aria-label="Loading your demo">
      <header className="flex flex-col items-center text-center">
        <span className="h-8 w-40 animate-pulse rounded-full bg-paper-deep" />
        <span className="mt-5 h-11 w-[min(420px,80%)] animate-pulse rounded-2xl bg-paper-deep" />
        <span className="mt-4 h-5 w-[min(320px,70%)] animate-pulse rounded-full bg-paper-deep" />
      </header>
      <Panel>
        <p className="text-shimmer text-center text-[14px] font-medium">Loading your demo…</p>
        <div className="mt-6 space-y-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3">
              <span className="size-7 shrink-0 animate-pulse rounded-full bg-paper-deep" />
              <span className="h-4 animate-pulse rounded-full bg-paper-deep" style={{ width: `${70 - i * 10}%` }} />
            </div>
          ))}
        </div>
      </Panel>
    </div>
  );
}

function ProblemState({ error, retrying = false }: { error: ApiError; retrying?: boolean }) {
  const copy = describeError(error);
  const notConfigured = error.error === "not_configured";
  return (
    <div>
      <StateHeader
        eyebrow={
          <>
            <CircleAlert aria-hidden className="size-3.5 text-alert" />
            {notConfigured ? "Demos paused" : retrying ? "Connection problem" : "Demo not found"}
          </>
        }
        title={notConfigured ? "Live demos aren't available right now" : retrying ? "We're having trouble reaching Cue" : copy.title}
      >
        {notConfigured
          ? "We're not running live demos on this server at the moment. Watch the recorded demo on the home page instead."
          : retrying
            ? "Retrying automatically. Your demo isn't affected; keep this tab open."
            : copy.detail}
      </StateHeader>
      <Panel className="flex flex-col items-center gap-4 text-center">
        {retrying ? (
          <p aria-live="polite" className="inline-flex items-center gap-2 text-[14px] text-muted">
            <RefreshCw aria-hidden className="size-4 animate-spin [animation-duration:2s]" />
            {copy.title}
          </p>
        ) : notConfigured && error.message ? (
          <p className="text-[14px] text-muted">{error.message}</p>
        ) : null}
        <div className="flex flex-col items-center gap-2 sm:flex-row">
          {notConfigured ? (
            <PillLink href={`${routes.home}#demo`} size="md">
              Watch the demo
            </PillLink>
          ) : (
            <BackToBooking label="Book a new demo" />
          )}
        </div>
      </Panel>
    </div>
  );
}

const STEPS = ["Meeting created", "Cue is starting", "Cue is joining the call", "Cue is in the call"] as const;

/** Index of the step in progress; STEPS.length when every step is done. */
function activeStep(status: DemoSession["status"]) {
  switch (status) {
    case "creating":
      return 0;
    case "bot_starting":
      return 1;
    case "bot_joining":
    case "bot_waiting":
      return 2;
    default:
      return STEPS.length;
  }
}

function StepList({ session }: { session: DemoSession }) {
  const active = activeStep(session.status);
  const detail =
    session.bot.detail?.trim() ||
    (session.status === "bot_waiting" ? "Cue is in the waiting room. Admit “Cue” from Google Meet." : null);
  return (
    <ol className="relative flex flex-col">
      {STEPS.map((label, i) => {
        const state = i < active ? "done" : i === active ? "active" : "pending";
        const last = i === STEPS.length - 1;
        return (
          <li key={label} className="relative flex gap-3.5 pb-5 last:pb-0" aria-current={state === "active" ? "step" : undefined}>
            {!last && (
              <span
                aria-hidden
                className={`absolute left-[13px] top-8 bottom-1 w-px ${i < active ? "bg-lime-ink/30" : "bg-line"}`}
              />
            )}
            <span
              className={`relative grid size-7 shrink-0 place-items-center rounded-full transition-colors duration-500 ${
                state === "done"
                  ? "bg-lime text-ink"
                  : state === "active"
                    ? "bg-ink text-lime"
                    : "border border-line bg-white text-faint"
              }`}
            >
              {state === "done" ? (
                <Check aria-hidden className="size-3.5" strokeWidth={3} />
              ) : state === "active" ? (
                <>
                  <span className="absolute inset-0 animate-ping rounded-full bg-ink/15 motion-reduce:hidden" />
                  <span className="size-2 rounded-full bg-lime" />
                </>
              ) : (
                <span className="text-[11px] font-medium">{i + 1}</span>
              )}
            </span>
            <div className="min-w-0 pt-[3px]">
              <p
                className={`text-[15px] tracking-[-0.01em] ${
                  state === "pending" ? "text-faint" : state === "active" ? "font-medium text-ink" : "text-ink-soft"
                }`}
              >
                {label}
                <span className="sr-only">{state === "done" ? " (done)" : state === "active" ? " (in progress)" : ""}</span>
              </p>
              {state === "active" && detail && <p className="mt-0.5 text-[13px] text-muted">{detail}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function LiveState({
  session,
  meetUrl,
  slow,
  secondsLeft,
  onCancelRedirect,
  reconnecting,
}: {
  session: DemoSession;
  meetUrl: string | null;
  slow: boolean;
  secondsLeft: number | null;
  onCancelRedirect: () => void;
  reconnecting: boolean;
}) {
  const inCall = isInCall(session.status);
  return (
    <div>
      <StateHeader
        eyebrow={
          <>
            <LiveDot />
            {inCall ? "Cue is in the call" : "Live demo"}
          </>
        }
        title={inCall ? "Cue is ready for you" : "Cue is on its way"}
      >
        {inCall
          ? "Join the Google Meet and say hello. Ask Cue anything about how it works."
          : meetUrl
            ? "Your Google Meet is ready. Join whenever you like; Cue will appear as soon as it connects."
            : "We're setting up a Google Meet for you. This usually takes a few seconds."}
      </StateHeader>

      <Panel>
        <AnimatePresence initial={false}>
          {secondsLeft !== null && meetUrl && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.35, ease }}
              className="overflow-hidden"
            >
              <div
                role="status"
                aria-live="polite"
                className="mb-6 flex items-center justify-between gap-3 rounded-2xl bg-ink px-4 py-3.5 text-paper"
              >
                <span className="flex items-center gap-3 text-[14.5px]">
                  <span className="grid size-8 shrink-0 place-items-center rounded-full bg-lime text-[15px] font-semibold tabular-nums text-ink">
                    {secondsLeft}
                  </span>
                  Taking you to Google Meet…
                </span>
                <button
                  type="button"
                  onClick={onCancelRedirect}
                  className="rounded-full px-3 py-1.5 text-[13.5px] font-medium text-paper/70 transition-colors hover:bg-white/10 hover:text-paper focus-visible:outline-2 focus-visible:outline-lime"
                >
                  Cancel
                </button>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        {meetUrl ? (
          <JoinMeet meetUrl={meetUrl} />
        ) : (
          <div className="flex h-14 items-center gap-3 rounded-full border border-dashed border-line px-5 text-[14.5px]">
            <span className="size-2 shrink-0 animate-pulse rounded-full bg-faint" />
            <span className="text-shimmer">Creating your Google Meet link…</span>
          </div>
        )}

        <div className="mt-7 border-t border-line-soft pt-6">
          <StepList session={session} />
        </div>

        <div className="mt-6 flex flex-col gap-3 empty:hidden">
          {slow && (
            <Notice tone="info" title="Cue is taking longer than usual to join.">
              You can join now; Cue will appear as soon as it connects.
            </Notice>
          )}
          {!session.voice.available && (
            <VoiceNotice detail={session.voice.detail} />
          )}
        </div>

        {reconnecting && (
          <p aria-live="polite" className="mt-5 inline-flex items-center gap-2 text-[12.5px] text-muted">
            <RefreshCw aria-hidden className="size-3.5 animate-spin [animation-duration:2s]" />
            Reconnecting…
          </p>
        )}
      </Panel>

      <p className="mt-5 text-center text-[12.5px] text-faint">
        Keep this tab open until you&apos;ve joined. It updates on its own.
      </p>
    </div>
  );
}

function VoiceNotice({ detail }: { detail: string | null }) {
  return (
    <div role="status" className="flex gap-3 rounded-2xl border border-line bg-paper-deep/70 p-3.5 text-[13.5px] leading-[1.5] text-ink-soft">
      <MicOff aria-hidden className="mt-0.5 size-4 shrink-0 text-muted" />
      <p>
        <span className="font-medium text-ink">Cue can see the meeting but can&apos;t talk yet: </span>
        {detail?.trim() || "its voice isn't set up on this server."}
      </p>
    </div>
  );
}

function ScheduledState({ id, session, onCancelled }: { id: string; session: DemoSession; onCancelled: () => void }) {
  const timeZone = useTimeZone();
  const meetUrl = safeMeetUrl(session.meet_url);
  return (
    <div>
      <StateHeader
        eyebrow={
          <>
            <CalendarClock aria-hidden className="size-3.5 text-lime-ink" />
            Scheduled
          </>
        }
        title="You're booked"
      >
        Check your inbox for the Google Calendar invite from Cue.
      </StateHeader>
      <Panel>
        <div className="rounded-[22px] border border-lime-ink/15 bg-lime-wash p-5">
          <p className="flex items-center gap-2 text-[13px] font-medium text-lime-ink">
            <Clock aria-hidden className="size-4" />
            Your demo
          </p>
          <p className="mt-2 text-[22px] font-semibold leading-[1.15] tracking-[-0.03em] text-ink sm:text-[26px]">
            {formatDateTime(session.start_at, timeZone)}
          </p>
          {timeZone && <p className="mt-1 text-[13px] text-muted">Shown in {timeZone.replaceAll("_", " ")}</p>}
        </div>

        {meetUrl && (
          <div className="mt-6">
            <p className="mb-3 text-[13.5px] text-muted">The Meet link works now, but Cue will join at the scheduled time.</p>
            <JoinMeet meetUrl={meetUrl} emphasis="secondary" />
          </div>
        )}

        <div className="mt-7 border-t border-line-soft pt-6">
          <CancelControl id={id} onCancelled={onCancelled} />
        </div>
      </Panel>
      <p className="mt-5 text-center text-[12.5px] text-faint">This page updates on its own when Cue starts joining.</p>
    </div>
  );
}

function CancelControl({ id, onCancelled }: { id: string; onCancelled: () => void }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  async function cancel() {
    setBusy(true);
    setError(null);
    const result = await callApi<{ status: string }>(`/api/meet-cue/sessions/${id}/cancel`, { method: "POST" });
    setBusy(false);
    if (!result.ok) {
      setError(result.error);
      return;
    }
    onCancelled();
  }

  const copy = error ? describeError(error) : null;

  return (
    <div className="flex flex-col gap-3">
      {confirming ? (
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[14.5px] text-ink">Cancel this demo? Cue will remove the calendar invite.</p>
          <div className="flex items-center gap-2">
            <PillButton size="sm" arrow={false} busy={busy} onClick={cancel}>
              {busy ? "Cancelling" : "Yes, cancel"}
            </PillButton>
            <PillButton size="sm" tone="ghost" arrow={false} disabled={busy} onClick={() => setConfirming(false)}>
              Keep it
            </PillButton>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[14px] text-muted">Can&apos;t make it?</p>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="inline-flex items-center gap-1.5 self-start rounded-full py-1 text-[14px] font-medium text-ink-soft underline decoration-line underline-offset-4 transition-colors hover:text-ink hover:decoration-ink focus-visible:outline-2 focus-visible:outline-ink sm:self-auto"
          >
            <CalendarX aria-hidden className="size-4" />
            Cancel demo
          </button>
        </div>
      )}
      {copy && (
        <Notice title={copy.title}>{copy.detail && copy.detail !== copy.title ? <p>{copy.detail}</p> : null}</Notice>
      )}
    </div>
  );
}

function FailedState({ session }: { session: DemoSession }) {
  return (
    <div>
      <StateHeader
        eyebrow={
          <>
            <CircleAlert aria-hidden className="size-3.5 text-alert" />
            Demo didn&apos;t start
          </>
        }
        title="Cue couldn't make it to this call"
      >
        Sorry about that. Starting a new demo usually fixes it.
      </StateHeader>
      <Panel className="flex flex-col gap-5">
        <Notice title="What went wrong">
          <p>{session.error?.trim() || "Cue wasn't able to join the meeting."}</p>
        </Notice>
        <div className="flex flex-col items-start gap-2 sm:flex-row sm:items-center">
          <BackToBooking label="Try again" />
        </div>
      </Panel>
    </div>
  );
}

function CancelledState() {
  return (
    <div>
      <StateHeader
        eyebrow={
          <>
            <CalendarX aria-hidden className="size-3.5 text-muted" />
            Cancelled
          </>
        }
        title="This demo was cancelled"
      >
        No problem. You can start a demo right now or pick another time.
      </StateHeader>
      <Panel className="flex justify-center">
        <BackToBooking label="Book a new demo" />
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/* After the call                                                      */

function EndedState({ id }: { id: string }) {
  const [summary, setSummary] = useState<DemoSummary | null>(null);
  const [error, setError] = useState<ApiError | null>(null);

  useEffect(() => {
    let stopped = false;
    let timer: number | undefined;
    let failures = 0;

    async function poll() {
      const result = await callApi<DemoSummary>(`/api/meet-cue/sessions/${id}/summary`);
      if (stopped) return;
      if (!result.ok) {
        if (isFatal(result.error) || failures >= 5) {
          setError(result.error);
          return;
        }
        failures += 1;
        timer = window.setTimeout(poll, POLL_MS * 2 ** failures);
        return;
      }
      failures = 0;
      setSummary(result.data);
      setError(null);
      if (result.data.status === "pending") timer = window.setTimeout(poll, POLL_MS);
    }

    poll();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  const duration = summary?.duration_seconds;

  return (
    <div>
      <StateHeader
        eyebrow={
          <>
            <LiveDot tone="muted" />
            Call ended
          </>
        }
        title="Thanks for meeting Cue"
      >
        Here&apos;s what Cue took away from your conversation.
      </StateHeader>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-muted">Summary</h2>
          {typeof duration === "number" && (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-paper-deep px-3 py-1 text-[12.5px] font-medium text-ink-soft">
              <Clock aria-hidden className="size-3.5" />
              {formatDuration(duration)}
            </span>
          )}
        </div>

        <div className="mt-4" aria-live="polite">
          {error ? (
            <Notice title="We couldn't load the summary.">
              <p>{describeError(error).title}</p>
            </Notice>
          ) : !summary || summary.status === "pending" ? (
            <div role="status">
              <p className="text-shimmer text-[15px] font-medium">Cue is writing up the summary…</p>
              <div className="mt-4 space-y-2.5">
                <span className="block h-3.5 w-full animate-pulse rounded-full bg-paper-deep" />
                <span className="block h-3.5 w-[92%] animate-pulse rounded-full bg-paper-deep" />
                <span className="block h-3.5 w-[64%] animate-pulse rounded-full bg-paper-deep" />
              </div>
            </div>
          ) : summary.status === "unavailable" ? (
            <div>
              <p className="text-[15.5px] leading-[1.55] text-ink">A summary isn&apos;t available for this call.</p>
              {summary.detail && <p className="mt-1.5 text-[14px] text-muted">{summary.detail}</p>}
            </div>
          ) : (
            <SummaryBody summary={summary} />
          )}
        </div>
      </Panel>

      <div className="mt-8 flex flex-col items-center gap-3 text-center">
        <p className="text-[15px] text-ink-soft">Want Cue on your team?</p>
        <PillLink href={routes.getStarted} size="md" dot>
          Hire your teammate
        </PillLink>
        <Link href={routes.meetCue} className="mt-1 text-[13.5px] text-muted transition-colors hover:text-ink">
          Or book another demo
        </Link>
      </div>
      <p className="mt-6 text-center text-[12px] text-faint">Transcripts are deleted after 7 days.</p>
    </div>
  );
}

function SummaryBody({ summary }: { summary: DemoSummary }) {
  return (
    <div>
      {summary.summary ? (
        <p className="text-[16px] leading-[1.6] text-ink">{summary.summary}</p>
      ) : (
        <p className="text-[15px] text-muted">No written summary for this call.</p>
      )}
      {summary.highlights.length > 0 && (
        <div className="mt-7">
          <h3 className="text-[13px] font-medium uppercase tracking-[0.08em] text-muted">Highlights</h3>
          <ul className="mt-3 flex flex-col gap-2.5">
            {summary.highlights.map((highlight, i) => (
              <motion.li
                key={i}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.06 * i, duration: 0.45, ease }}
                className="rounded-2xl border border-line-soft bg-paper/80 px-4 py-3"
              >
                <p className="text-[12px] font-medium text-lime-ink">{highlight.speaker}</p>
                <p className="mt-0.5 text-[14.5px] leading-[1.5] text-ink-soft">{highlight.text}</p>
              </motion.li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
