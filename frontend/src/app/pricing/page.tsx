import type { Metadata } from "next";
import { PlaceholderPage } from "@/components/ui/placeholder-page";

export const metadata: Metadata = { title: "Pricing — CUE" };

export default function PricingPage() {
  return (
    <PlaceholderPage eyebrow="Coming soon" title="Priced like a teammate">
      <p>One flat monthly price per teammate, with meeting hours included. No per-seat fees for the people working with it.</p>
      <p className="mt-3 text-[13.5px] text-muted">Plans will be published here.</p>
    </PlaceholderPage>
  );
}
