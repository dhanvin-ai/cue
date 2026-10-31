// Shapes shared by the Meet CUE pages and the /api/meet-cue route handlers.
// They mirror the demo backend's contract (POST /demo/sessions and friends).

export type DemoMode = "now" | "scheduled";

export type SessionStatus =
  | "scheduled"
  | "creating"
  | "bot_starting"
  | "bot_joining"
  | "bot_waiting"
  | "bot_in_call"
  | "live"
  | "ended"
  | "failed"
  | "cancelled";

export const TERMINAL_STATUSES: readonly SessionStatus[] = ["ended", "failed", "cancelled"];
export const IN_CALL_STATUSES: readonly SessionStatus[] = ["bot_in_call", "live"];

export const isTerminal = (status: SessionStatus) => TERMINAL_STATUSES.includes(status);
export const isInCall = (status: SessionStatus) => IN_CALL_STATUSES.includes(status);

export type CreateSessionBody = {
  mode: DemoMode;
  email: string;
  name: string | null;
  start_at: string | null;
  timezone: string;
  consent: true;
};

/** What the browser gets back from POST /api/meet-cue/sessions (the token stays in a cookie). */
export type CreatedSession = {
  session_id: string;
  mode: DemoMode;
  status: SessionStatus;
  meet_url: string | null;
  start_at: string;
  end_at: string;
};

export type DemoSession = {
  session_id: string;
  mode: DemoMode;
  status: SessionStatus;
  meet_url: string | null;
  start_at: string;
  end_at: string;
  error: string | null;
  bot: { status: string | null; detail: string | null };
  voice: { available: boolean; detail: string | null };
  summary_ready: boolean;
};

export type DemoSummary = {
  status: "pending" | "ready" | "unavailable";
  summary: string | null;
  highlights: { speaker: string; text: string }[];
  duration_seconds: number | null;
  detail: string | null;
};

/** Error body from the backend or from our own route handlers. */
export type ApiError = {
  /** HTTP status; 0 when the request never got a response. */
  status: number;
  error: string;
  message?: string;
  retry_after?: number;
  missing?: string[];
};

/** The disclosure every visitor agrees to before Cue joins a call. */
export const CONSENT_TEXT =
  "Cue is an AI teammate. The call is transcribed and processed by AI to answer you and to produce a summary. Transcripts are deleted after 7 days. Don't share confidential information.";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (value: string) => UUID_RE.test(value);
