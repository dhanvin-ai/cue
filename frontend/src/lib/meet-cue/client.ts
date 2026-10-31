"use client";

import { useEffect, useState, useSyncExternalStore } from "react";
import type { ApiError } from "./types";

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: ApiError };

/** Calls our own /api/meet-cue route handlers (never the backend directly). */
export async function callApi<T>(path: string, init?: { method?: "GET" | "POST"; body?: unknown }): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(path, {
      method: init?.method ?? "GET",
      headers: init?.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      cache: "no-store",
    });
  } catch {
    return { ok: false, error: { status: 0, error: "network" } };
  }

  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // Handled below: an OK response without JSON is still an error for us.
  }

  if (response.ok && data !== null) return { ok: true, data: data as T };

  const body = (data ?? {}) as Partial<ApiError>;
  return {
    ok: false,
    error: {
      status: response.status,
      error: typeof body.error === "string" ? body.error : "unknown",
      message: typeof body.message === "string" ? body.message : undefined,
      retry_after: typeof body.retry_after === "number" ? body.retry_after : undefined,
      missing: Array.isArray(body.missing) ? body.missing : undefined,
    },
  };
}

/** "4 min", "45 s", "2 h" */
export function formatWait(seconds: number) {
  const s = Math.max(1, Math.ceil(seconds));
  if (s < 60) return `${s} s`;
  if (s < 3600) return `${Math.ceil(s / 60)} min`;
  const hours = Math.round((s / 3600) * 10) / 10;
  return `${hours} h`;
}

export function formatDuration(seconds: number) {
  const s = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(s / 60);
  const rest = s % 60;
  if (minutes === 0) return `${rest} s`;
  if (minutes < 60) return rest ? `${minutes} min ${rest} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

/** Visitor-facing copy for an API error; `detail` carries the backend's own message when there is one. */
export function describeError(error: ApiError): { title: string; detail?: string } {
  const message = error.message?.trim() || undefined;
  switch (error.error) {
    case "rate_limited": {
      const wait = error.retry_after ? ` Try again in about ${formatWait(error.retry_after)}.` : " Try again a little later.";
      return { title: `You've reached the demo limit for now.${wait}`, detail: message };
    }
    case "slot_unavailable":
      return { title: "Cue is in another demo at that time, pick another slot.", detail: message };
    case "not_configured":
      return { title: "Live demos aren't available right now.", detail: message };
    case "google_error":
      return { title: "Google Calendar didn't cooperate. Please try again.", detail: message };
    case "not_found":
      return {
        title: "We can't find this demo.",
        detail: "Demo links only work in the browser you booked from, for up to 3 days.",
      };
    case "network":
      return { title: "You appear to be offline.", detail: "Check your connection and try again." };
    case "invalid":
      return { title: message ?? "Some details don't look right. Check the form and try again." };
    default:
      return { title: message ?? "Something went wrong on our side. Please try again." };
  }
}

const noopSubscribe = () => () => {};

/** The browser's IANA timezone, or null while server-rendering. */
export function useTimeZone() {
  return useSyncExternalStore(
    noopSubscribe,
    () => Intl.DateTimeFormat().resolvedOptions().timeZone,
    () => null,
  );
}

/** Wall-clock time that re-renders every `intervalMs` while `active`. */
export function useNow(intervalMs: number, active = true) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const tick = () => setNow(Date.now());
    const id = window.setInterval(tick, intervalMs);
    const first = window.setTimeout(tick, 0);
    return () => {
      window.clearInterval(id);
      window.clearTimeout(first);
    };
  }, [intervalMs, active]);
  return now;
}

export function formatDateTime(iso: string, timeZone: string | null) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const options: Intl.DateTimeFormatOptions = {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  };
  if (timeZone) options.timeZone = timeZone;
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

/** Only https links are rendered as join targets. */
export function safeMeetUrl(url: string | null | undefined) {
  if (!url) return null;
  try {
    return new URL(url).protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

const createdKey = (id: string) => `cue-demo:${id}:created`;
const redirectedKey = (id: string) => `cue-demo:${id}:redirected`;

function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function rememberCreated(id: string) {
  try {
    storage()?.setItem(createdKey(id), String(Date.now()));
  } catch {}
}

export function readCreated(id: string) {
  try {
    const value = Number(storage()?.getItem(createdKey(id)));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

/** True the first time it's called for a session in this tab; false afterwards. */
export function claimAutoRedirect(id: string) {
  try {
    const store = storage();
    if (!store) return true;
    if (store.getItem(redirectedKey(id))) return false;
    store.setItem(redirectedKey(id), "1");
    return true;
  } catch {
    return true;
  }
}
