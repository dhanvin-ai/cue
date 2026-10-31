// Every link on the marketing site points at one of these, so placeholder
// destinations can be swapped for real flows in one place.
export const routes = {
  home: "/",
  product: "/#product",
  pricing: "/pricing",
  login: "/login",
  // The "Hire your teammate" wizard (Experience Design, Journey 1) will live here.
  getStarted: "/get-started",
} as const;
