import type { NextRequest } from "next/server";
import {
  SESSION_COOKIE_MAX_AGE,
  backendUrl,
  forward,
  isUuid,
  json,
  notConfigured,
  passThrough,
  sessionCookieName,
  visitorIp,
} from "@/lib/meet-cue/proxy";

/** Creates a demo session. The bearer token goes into an httpOnly cookie, never the response body. */
export async function POST(request: NextRequest) {
  const base = backendUrl();
  if (!base) return notConfigured();

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ error: "invalid", message: "The request body must be JSON." }, 400);
  }
  if (typeof body !== "object" || body === null || Array.isArray(body)) {
    return json({ error: "invalid", message: "The request body must be a JSON object." }, 400);
  }

  // Creating a session can involve Google Calendar and Meet calls, so allow it more time.
  const upstream = await forward(base, "/demo/sessions", {
    method: "POST",
    body,
    visitorIp: visitorIp(request),
    timeoutMs: 30_000,
  });
  if (!upstream.ok) return upstream.response;
  if (upstream.status !== 201) return passThrough(upstream);

  const { token, ...session } = (upstream.data ?? {}) as Record<string, unknown>;
  const id = session.session_id;
  if (typeof token !== "string" || !token || typeof id !== "string" || !isUuid(id)) {
    return json({ error: "upstream_error", message: "The demo service sent an unexpected response." }, 502);
  }

  const response = json(session, 201);
  response.cookies.set(sessionCookieName(id), token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_COOKIE_MAX_AGE,
  });
  return response;
}
