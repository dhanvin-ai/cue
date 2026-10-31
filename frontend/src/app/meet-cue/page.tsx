import type { Metadata } from "next";
import { MeetCueBooking } from "@/components/meet-cue/booking";
import { MeetCueShell } from "@/components/meet-cue/page-shell";

export const metadata: Metadata = {
  title: "Meet CUE — Live demo",
  description: "Meet CUE in a real Google Meet: start a call now or schedule a demo, and get a summary afterward.",
};

export default function MeetCuePage() {
  return (
    <MeetCueShell>
      <MeetCueBooking />
    </MeetCueShell>
  );
}
