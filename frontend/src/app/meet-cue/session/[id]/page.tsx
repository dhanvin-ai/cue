import type { Metadata } from "next";
import { Suspense } from "react";
import { MeetCueShell } from "@/components/meet-cue/page-shell";
import { SessionLoading, SessionView } from "@/components/meet-cue/session-view";
import { routes } from "@/lib/routes";

export const metadata: Metadata = {
  title: "Your demo — CUE",
  robots: { index: false, follow: false },
};

// With Cache Components, params are runtime data: the shell is prerendered and
// the session id is read inside a Suspense boundary. Everything session-specific
// is fetched in the browser through /api/meet-cue, which holds the token cookie.
export default function MeetCueSessionPage({ params }: PageProps<"/meet-cue/session/[id]">) {
  return (
    <MeetCueShell back={{ href: routes.meetCue, label: "Meet CUE" }}>
      <Suspense fallback={<SessionLoading />}>{params.then(({ id }) => <SessionView id={id} />)}</Suspense>
    </MeetCueShell>
  );
}
