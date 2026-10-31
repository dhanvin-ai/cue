// Server-side helpers for the /api/meet-cue route handlers. They forward
// requests to the demo backend and keep its secrets (the demo key and each
// session's bearer token) out of the browser. Only import from route handlers.

import { NextResponse, type NextRequest } from "next/server";
import { isUuid } from "./types";

export { isUuid };

/** The httpOnly cookie holding a session's bearer token. */
export const sessionCookieName = (id: string) => `cue_demo_${id.toLowerCase()}`;

export const SESSION_COOKIE_MAX_AGE = 60 * 60 * 24 * 3;

/** JSON response that no browser, CDN or Next cache may store. */
export function json(body: unknown, status = 200, headers?: Record<string, string>) {
  const response = NextResponse.json(body, { status });
  response.headers.set("Cache-Control", "no-store");
  for (const [key, value] of Object.entries(headers ?? {})) response.headers.set(key, value);
  return response;
}

/** Base URL of the demo backend, read per request so it can change without a rebuild. */
export function backendUrl(): string | null {
  const raw = process.env.CUE_DEMO_API_URL?.trim();
  return raw ? raw.replace(/\/+$/, "") : null;
}

export const notConfigured = () =>
  json({ error: "not_configured", message: "Live demos aren't configured on this server." }, 503);

export const notFound = () => json({ error: "not_found" }, 404);

export const invalidId = () => json({ error: "invalid", message: "That isn't a valid demo session id." }, 400);

/** First hop of X-Forwarded-For, else X-Real-IP, else "unknown". */
export function visitorIp(request: NextRequest) {
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return forwarded || request.headers.get("x-real-ip")?.trim() || "unknown";
}

type ForwardOptions = {
  method: "GET" | "POST";
  token?: string;
  body?: unknown;
  visitorIp?: string;
  timeoutMs?: number;
};

export type Upstream =
  | { ok: true; status: number; data: unknown; retryAfter: string | null }
  | { ok: false; response: NextResponse };

/** Calls the backend and parses its JSON, turning network failures into clean 502/504 responses. */
export async function forward(base: string, path: string, options: ForwardOptions): Promise<Upstream> {
  const headers: Record<string, string> = { Accept: "application/json" };
  const key = process.env.CUE_DEMO_API_KEY?.trim();
  if (key) headers["X-Demo-Key"] = key;
  if (options.token) headers.Authorization = `Bearer ${options.token}`;
  if (options.visitorIp) headers["X-Visitor-IP"] = options.visitorIp;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let upstream: Response;
  try {
    upstream = await fetch(`${base}${path}`, {
      method: options.method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(options.timeoutMs ?? 15_000),
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    return {
      ok: false,
      response: timedOut
        ? json({ error: "upstream_timeout", message: "The demo service took too long to respond. Try again in a moment." }, 504)
        : json({ error: "upstream_unreachable", message: "We couldn't reach the demo service. Try again in a moment." }, 502),
    };
  }

  let data: unknown;
  try {
    data = await upstream.json();
  } catch {
    return {
      ok: false,
      response: json(
        { error: "upstream_error", message: "The demo service sent an unexpected response." },
        upstream.ok ? 502 : upstream.status,
      ),
    };
  }

  return { ok: true, status: upstream.status, data, retryAfter: upstream.headers.get("retry-after") };
}

/** Passes the backend's status code and JSON body through unchanged. */
export function passThrough(upstream: Extract<Upstream, { ok: true }>) {
  return json(upstream.data, upstream.status, upstream.retryAfter ? { "Retry-After": upstream.retryAfter } : undefined);
}

/**
 * Shared shape of the three per-session handlers: check config and id, read
 * the session cookie, then forward with its token.
 */
export async function forwardForSession(
  request: NextRequest,
  id: string,
  method: "GET" | "POST",
  suffix = "",
) {
  const base = backendUrl();
  if (!base) return notConfigured();
  if (!isUuid(id)) return invalidId();

  const token = request.cookies.get(sessionCookieName(id))?.value;
  if (!token) return notFound();

  const upstream = await forward(base, `/demo/sessions/${id.toLowerCase()}${suffix}`, {
    method,
    token,
    timeoutMs: method === "POST" ? 20_000 : 10_000,
  });
  return upstream.ok ? passThrough(upstream) : upstream.response;
}
