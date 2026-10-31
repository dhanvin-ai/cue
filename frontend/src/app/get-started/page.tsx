import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/ui/placeholder-page";

export const metadata: Metadata = { title: "Hire your teammate — CUE" };

export default function GetStartedPage() {
  return (
    <PlaceholderPage eyebrow="Coming next" title="Hire your teammate">
      <p>
        This is where you&apos;ll bring CUE onto your team: give it a name and a desk, invite it to Slack, share your
        repos and tracker, and let it catch up on your history.
      </p>
      <p className="mt-3 text-[13.5px] text-muted">The hiring flow is the next thing we&apos;re building.</p>
    </PlaceholderPage>
  );
}
