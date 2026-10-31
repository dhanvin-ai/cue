"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useId, useState, useSyncExternalStore, type FormEvent, type ReactNode } from "react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { CalendarCheck, CalendarClock, Globe, Video } from "lucide-react";
import { PillButton } from "@/components/ui/pill-button";
import { PillLink } from "@/components/ui/pill-link";
import { callApi, describeError, formatDateTime, rememberCreated, safeMeetUrl, useTimeZone } from "@/lib/meet-cue/client";
import type { ApiError, CreateSessionBody, CreatedSession } from "@/lib/meet-cue/types";
import { meetCueSession } from "@/lib/routes";
import { ConsentCheckbox, Field, Notice, inputClass, isEmail } from "./fields";

const ease = [0.22, 1, 0.36, 1] as const;

const MIN_LEAD_MS = 10 * 60 * 1000;
const MAX_LEAD_MS = 14 * 24 * 60 * 60 * 1000;

const rise = (delay: number) => ({
  initial: { opacity: 0, y: 20, filter: "blur(6px)" },
  animate: { opacity: 1, y: 0, filter: "blur(0px)" },
  transition: { delay, duration: 0.8, ease },
});

export function MeetCueBooking() {
  return (
    <MotionConfig reducedMotion="user">
      <div className="mx-auto max-w-[1080px]">
        <header className="mx-auto max-w-[720px] text-center">
          <motion.div {...rise(0.05)}>
            <span className="inline-flex items-center gap-2 rounded-full border border-line bg-white/80 px-3.5 py-1.5 text-[12.5px] font-medium text-ink-soft backdrop-blur">
              <Image src="/integrations/google-meet.svg" alt="" width={14} height={14} unoptimized className="size-3.5" />
              Live demo on Google Meet
            </span>
          </motion.div>
          <motion.h1
            {...rise(0.12)}
            className="mt-6 text-balance text-[clamp(2.3rem,6vw,4rem)] font-semibold leading-[1.02] tracking-[-0.05em] text-ink"
          >
            Meet{" "}
            <span className="relative inline-block">
              <motion.span
                aria-hidden
                className="absolute -inset-x-[0.12em] bottom-[0.02em] top-[0.14em] -z-10 origin-left rounded-[0.3em] bg-lime-soft"
                initial={{ scaleX: 0 }}
                animate={{ scaleX: 1 }}
                transition={{ delay: 0.55, duration: 0.8, ease }}
              />
              CUE
            </span>{" "}
            in a real call.
          </motion.h1>
          <motion.p
            {...rise(0.2)}
            className="mx-auto mt-5 max-w-[34rem] text-balance text-[17px] leading-[1.5] text-ink-soft sm:text-[19px]"
          >
            Ask Cue anything about how it works. It joins a Google Meet with you, answers out loud, and sends you a summary
            afterward.
          </motion.p>
        </header>

        <div className="mt-10 grid items-start gap-4 sm:mt-14 md:grid-cols-2 md:gap-5">
          <motion.div {...rise(0.3)}>
            <MeetNowCard />
          </motion.div>
          <motion.div {...rise(0.38)}>
            <ScheduleCard />
          </motion.div>
        </div>
      </div>
    </MotionConfig>
  );
}

function OptionCard({
  icon,
  title,
  description,
  badge,
  children,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="rounded-[28px] border border-line bg-white/85 p-6 shadow-window backdrop-blur sm:p-8"
    >
      <div className="flex items-start justify-between gap-4">
        <span className="grid size-11 place-items-center rounded-2xl bg-lime-soft text-lime-ink ring-1 ring-lime-ink/10">{icon}</span>
        {badge}
      </div>
      <h2 className="mt-5 text-[24px] font-semibold leading-[1.1] tracking-[-0.035em] text-ink sm:text-[26px]">{title}</h2>
      <p className="mt-2 text-[15px] leading-[1.5] text-muted">{description}</p>
      <div className="mt-6">{children}</div>
    </section>
  );
}

type ContactState = { email: string; name: string; consent: boolean };
type ContactErrors = { email?: string; consent?: string };

function validateContact(contact: ContactState): ContactErrors {
  const errors: ContactErrors = {};
  if (!contact.email.trim()) errors.email = "Enter your email so Cue can send the invite.";
  else if (!isEmail(contact.email)) errors.email = "That email doesn't look right.";
  if (!contact.consent) errors.consent = "Please agree before Cue joins a call with you.";
  return errors;
}

function ContactFields({
  prefix,
  contact,
  errors,
  disabled,
  onChange,
}: {
  prefix: string;
  contact: ContactState;
  errors: ContactErrors;
  disabled: boolean;
  onChange: (patch: Partial<ContactState>) => void;
}) {
  return (
    <>
      <Field
        id={`${prefix}-email`}
        label="Work email"
        type="email"
        autoComplete="email"
        inputMode="email"
        placeholder="you@company.com"
        required
        value={contact.email}
        disabled={disabled}
        error={errors.email}
        hint="We'll send the Google Calendar invite here."
        onChange={(event) => onChange({ email: event.target.value })}
      />
      <Field
        id={`${prefix}-name`}
        label="Your name"
        optional
        autoComplete="name"
        placeholder="So Cue knows what to call you"
        maxLength={80}
        value={contact.name}
        disabled={disabled}
        onChange={(event) => onChange({ name: event.target.value })}
      />
      <ConsentCheckbox
        id={`${prefix}-consent`}
        checked={contact.consent}
        disabled={disabled}
        error={errors.consent}
        onChange={(consent) => onChange({ consent })}
      />
    </>
  );
}

function ErrorNotice({ error }: { error: ApiError }) {
  const copy = describeError(error);
  return (
    <Notice title={copy.title}>
      {copy.detail && copy.detail !== copy.title ? <p>{copy.detail}</p> : null}
    </Notice>
  );
}

function payload(contact: ContactState, extra: Pick<CreateSessionBody, "mode" | "start_at" | "timezone">): CreateSessionBody {
  return {
    ...extra,
    email: contact.email.trim(),
    name: contact.name.trim() || null,
    consent: true,
  };
}

const browserTimeZone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

/* ------------------------------------------------------------------ */

function MeetNowCard() {
  const router = useRouter();
  const prefix = useId();
  const [contact, setContact] = useState<ContactState>({ email: "", name: "", consent: false });
  const [errors, setErrors] = useState<ContactErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<ApiError | null>(null);

  const update = (patch: Partial<ContactState>) => {
    setContact((current) => ({ ...current, ...patch }));
    setErrors((current) => ({
      ...current,
      ...("email" in patch ? { email: undefined } : {}),
      ...("consent" in patch ? { consent: undefined } : {}),
    }));
  };

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const found = validateContact(contact);
    setErrors(found);
    if (found.email || found.consent) return;

    setSubmitting(true);
    setApiError(null);
    const result = await callApi<CreatedSession>("/api/meet-cue/sessions", {
      method: "POST",
      body: payload(contact, { mode: "now", start_at: null, timezone: browserTimeZone() }),
    });
    if (!result.ok) {
      setApiError(result.error);
      setSubmitting(false);
      return;
    }
    rememberCreated(result.data.session_id);
    // Stay in the "submitting" state until the session page takes over.
    router.push(meetCueSession(result.data.session_id));
  }

  return (
    <OptionCard
      icon={<Video className="size-5" strokeWidth={2} />}
      title="Meet CUE now"
      description="We'll open a Google Meet and Cue will join you in under a minute."
      badge={
        <span className="inline-flex items-center gap-1.5 rounded-full bg-ink px-2.5 py-1 text-[11.5px] font-medium text-paper">
          <span className="relative flex size-1.5">
            <span className="absolute inset-0 animate-ping rounded-full bg-lime opacity-70 motion-reduce:hidden" />
            <span className="relative size-1.5 rounded-full bg-lime" />
          </span>
          Instant
        </span>
      }
    >
      <form noValidate onSubmit={submit} className="flex flex-col gap-4">
        <ContactFields prefix={`now${prefix}`} contact={contact} errors={errors} disabled={submitting} onChange={update} />
        {apiError && <ErrorNotice error={apiError} />}
        <div className="flex flex-col gap-3 pt-1 sm:flex-row sm:items-center">
          <PillButton type="submit" size="lg" busy={submitting} className="w-full sm:w-auto">
            {submitting ? "Starting meeting" : "Start meeting"}
          </PillButton>
          <p aria-live="polite" className="text-center text-[13px] text-muted sm:text-left">
            {submitting ? <span className="text-shimmer">Setting up your Google Meet…</span> : "Opens on the next screen."}
          </p>
        </div>
      </form>
    </OptionCard>
  );
}

/* ------------------------------------------------------------------ */

const pad = (n: number) => String(n).padStart(2, "0");
const localDate = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** "2026-11-02T14:30:00-07:00": local wall time with the browser's UTC offset. */
function toOffsetIso(d: Date) {
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const abs = Math.abs(offset);
  return `${localDate(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}:00${sign}${pad(Math.floor(abs / 60))}:${pad(abs % 60)}`;
}

function parseLocal(date: string, time: string) {
  const [y, m, d] = date.split("-").map(Number);
  const [hh, mm] = time.split(":").map(Number);
  if (![y, m, d, hh, mm].every(Number.isFinite)) return null;
  const value = new Date(y, m - 1, d, hh, mm, 0, 0);
  return Number.isNaN(value.getTime()) ? null : value;
}

const noopSubscribe = () => () => {};

/** Bookable date range for the native date input, computed in the browser's timezone. */
function useDateBounds() {
  const min = useSyncExternalStore(noopSubscribe, () => localDate(new Date()), () => undefined);
  const max = useSyncExternalStore(noopSubscribe, () => localDate(new Date(Date.now() + MAX_LEAD_MS)), () => undefined);
  return { min, max };
}

function useTimeZoneLabel(timeZone: string | null) {
  return useSyncExternalStore(
    noopSubscribe,
    () => {
      if (!timeZone) return null;
      const short = new Intl.DateTimeFormat(undefined, { timeZone, timeZoneName: "short" })
        .formatToParts(new Date())
        .find((part) => part.type === "timeZoneName")?.value;
      return short ? `${timeZone.replaceAll("_", " ")} (${short})` : timeZone.replaceAll("_", " ");
    },
    () => null,
  );
}

type SlotErrors = { date?: string; time?: string };

function ScheduleCard() {
  const prefix = useId();
  const timeZone = useTimeZone();
  const tzLabel = useTimeZoneLabel(timeZone);
  const bounds = useDateBounds();
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [contact, setContact] = useState<ContactState>({ email: "", name: "", consent: false });
  const [errors, setErrors] = useState<ContactErrors & SlotErrors>({});
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [booked, setBooked] = useState<{ session: CreatedSession; email: string } | null>(null);

  const update = (patch: Partial<ContactState>) => {
    setContact((current) => ({ ...current, ...patch }));
    setErrors((current) => ({
      ...current,
      ...("email" in patch ? { email: undefined } : {}),
      ...("consent" in patch ? { consent: undefined } : {}),
    }));
  };

  function validateSlot(): { errors: SlotErrors; start: Date | null } {
    if (!date) return { errors: { date: "Pick a day." }, start: null };
    if (!time) return { errors: { time: "Pick a time." }, start: null };
    const start = parseLocal(date, time);
    if (!start) return { errors: { time: "That time doesn't look right." }, start: null };
    const lead = start.getTime() - Date.now();
    if (lead < MIN_LEAD_MS) return { errors: { time: "Pick a time at least 10 minutes from now." }, start: null };
    if (lead > MAX_LEAD_MS) return { errors: { date: "Pick a time within the next 14 days." }, start: null };
    return { errors: {}, start };
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    const slot = validateSlot();
    const found = { ...slot.errors, ...validateContact(contact) };
    setErrors(found);
    if (!slot.start || found.email || found.consent) return;

    setSubmitting(true);
    setApiError(null);
    const result = await callApi<CreatedSession>("/api/meet-cue/sessions", {
      method: "POST",
      body: payload(contact, { mode: "scheduled", start_at: toOffsetIso(slot.start), timezone: timeZone ?? browserTimeZone() }),
    });
    setSubmitting(false);
    if (!result.ok) {
      setApiError(result.error);
      return;
    }
    rememberCreated(result.data.session_id);
    setBooked({ session: result.data, email: contact.email.trim() });
  }

  function reset() {
    setBooked(null);
    setDate("");
    setTime("");
    setApiError(null);
    setErrors({});
  }

  const dateTimeInput = `${inputClass} appearance-none [&::-webkit-date-and-time-value]:text-left [&::-webkit-calendar-picker-indicator]:opacity-50 [&::-webkit-calendar-picker-indicator]:transition-opacity hover:[&::-webkit-calendar-picker-indicator]:opacity-90`;

  return (
    <OptionCard
      icon={<CalendarClock className="size-5" strokeWidth={2} />}
      title="Schedule a demo"
      description="Pick a time in the next two weeks. Cue sends a calendar invite and shows up on time."
    >
      <AnimatePresence mode="wait" initial={false}>
        {booked ? (
          <motion.div
            key="booked"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.45, ease }}
          >
            <Booked session={booked.session} email={booked.email} timeZone={timeZone} onReset={reset} />
          </motion.div>
        ) : (
          <motion.form
            key="form"
            noValidate
            onSubmit={submit}
            className="flex flex-col gap-4"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.45, ease }}
          >
            <fieldset className="min-w-0" disabled={submitting}>
              <legend className="sr-only">Date and time</legend>
              <div className="grid grid-cols-[1.25fr_1fr] gap-3">
                <div className="min-w-0">
                  <label htmlFor={`sched${prefix}-date`} className="mb-1.5 block text-[13.5px] font-medium text-ink-soft">
                    Day
                  </label>
                  <input
                    id={`sched${prefix}-date`}
                    type="date"
                    required
                    min={bounds.min}
                    max={bounds.max}
                    value={date}
                    onChange={(event) => {
                      setDate(event.target.value);
                      setErrors((current) => ({ ...current, date: undefined, time: undefined }));
                    }}
                    aria-invalid={errors.date ? true : undefined}
                    aria-describedby={`sched${prefix}-slot-help`}
                    className={dateTimeInput}
                  />
                </div>
                <div className="min-w-0">
                  <label htmlFor={`sched${prefix}-time`} className="mb-1.5 block text-[13.5px] font-medium text-ink-soft">
                    Time
                  </label>
                  <input
                    id={`sched${prefix}-time`}
                    type="time"
                    required
                    step={300}
                    value={time}
                    onChange={(event) => {
                      setTime(event.target.value);
                      setErrors((current) => ({ ...current, date: undefined, time: undefined }));
                    }}
                    aria-invalid={errors.time ? true : undefined}
                    aria-describedby={`sched${prefix}-slot-help`}
                    className={dateTimeInput}
                  />
                </div>
              </div>
              <p id={`sched${prefix}-slot-help`} className={`mt-1.5 text-[12.5px] ${errors.date || errors.time ? "text-alert" : "text-muted"}`}>
                {errors.date || errors.time || (
                  <span className="inline-flex items-center gap-1.5">
                    <Globe aria-hidden className="size-3.5 shrink-0" />
                    {tzLabel ? <>Times are in {tzLabel}</> : "Times are in your local timezone"}
                  </span>
                )}
              </p>
            </fieldset>

            <ContactFields prefix={`sched${prefix}`} contact={contact} errors={errors} disabled={submitting} onChange={update} />
            {apiError && <ErrorNotice error={apiError} />}
            <div className="pt-1">
              <PillButton type="submit" size="lg" busy={submitting} className="w-full sm:w-auto">
                {submitting ? "Scheduling" : "Schedule"}
              </PillButton>
            </div>
          </motion.form>
        )}
      </AnimatePresence>
    </OptionCard>
  );
}

function Booked({
  session,
  email,
  timeZone,
  onReset,
}: {
  session: CreatedSession;
  email: string;
  timeZone: string | null;
  onReset: () => void;
}) {
  const meetUrl = safeMeetUrl(session.meet_url);
  return (
    <div role="status" className="flex flex-col gap-5">
      <div className="rounded-[22px] border border-lime-ink/15 bg-lime-wash p-5">
        <div className="flex items-center gap-2 text-[13px] font-medium text-lime-ink">
          <CalendarCheck aria-hidden className="size-4" />
          You&apos;re booked
        </div>
        <p className="mt-2 text-[22px] font-semibold leading-[1.15] tracking-[-0.03em] text-ink">
          {formatDateTime(session.start_at, timeZone)}
        </p>
        <p className="mt-3 text-[14.5px] leading-[1.5] text-ink-soft">
          Check your inbox for the Google Calendar invite from Cue. We sent it to{" "}
          <span className="font-medium text-ink">{email}</span>.
        </p>
        {meetUrl && (
          <p className="mt-2 truncate text-[13px] text-muted">
            Meet link:{" "}
            <a href={meetUrl} target="_blank" rel="noopener noreferrer" className="text-ink underline decoration-line underline-offset-4 hover:decoration-ink">
              {meetUrl.replace(/^https:\/\//, "")}
            </a>
          </p>
        )}
      </div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <PillLink href={meetCueSession(session.session_id)} size="md" className="w-full sm:w-auto">
          View your demo
        </PillLink>
        <button
          type="button"
          onClick={onReset}
          className="rounded-full px-4 py-2 text-[14px] text-muted transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-ink"
        >
          Book another time
        </button>
      </div>
    </div>
  );
}
