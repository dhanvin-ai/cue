// Every link on the marketing site points at one of these, so placeholder
// destinations can be swapped for real flows in one place.
export const routes = {
  home: "/",
  product: "/#product",
  pricing: "/pricing",
  login: "/login",
  // The "Hire your teammate" wizard (Experience Design, Journey 1) will live here.
  getStarted: "/get-started",
  // Live demo: meet Cue in a Google Meet now, or book a time.
  meetCue: "/meet-cue",
} as const;

/** A visitor's demo session page (status, join link, summary). */
export const meetCueSession = (id: string) => `${routes.meetCue}/session/${id}`;
