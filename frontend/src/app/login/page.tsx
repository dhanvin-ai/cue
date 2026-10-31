import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/ui/placeholder-page";

export const metadata: Metadata = { title: "Log in — CUE" };

export default function LoginPage() {
  return (
    <PlaceholderPage eyebrow="Coming soon" title="Log in to CUE">
      <p>Sign in with your Google Workspace account to reach Cue&apos;s desk: your tasks, approvals and what Cue knows.</p>
      <p className="mt-3 text-[13.5px] text-muted">Sign-in isn&apos;t connected yet.</p>
    </PlaceholderPage>
  );
}
