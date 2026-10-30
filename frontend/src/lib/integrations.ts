export type Integration = {
  name: string;
  /** Official logo from the vendor or a curated brand library, served from /public/integrations. */
  logo: string;
  /** Intrinsic aspect ratio (width / height) of the logo file, used to reserve space. */
  ratio: number;
  /**
   * "mark" logos sit beside the brand name. "wordmark" logos already spell the
   * name (Zapier), so the name is only given to screen readers.
   */
  kind: "mark" | "wordmark";
  /** Rendered logo height in px; marks default to 20. */
  height?: number;
  /** Raster logos on a white plate blend into the page instead of showing a box. */
  blend?: boolean;
};

export const integrations: Integration[] = [
  { name: "Gmail", logo: "/integrations/gmail.svg", ratio: 512 / 399.42, kind: "mark", height: 17 },
  { name: "Slack", logo: "/integrations/slack.svg", ratio: 1, kind: "mark" },
  { name: "Google Meet", logo: "/integrations/google-meet.svg", ratio: 622 / 512, kind: "mark", height: 18 },
  { name: "Zoom", logo: "/integrations/zoom.svg", ratio: 1, kind: "mark" },
  { name: "Calendly", logo: "/integrations/calendly.svg", ratio: 1, kind: "mark" },
  { name: "Make", logo: "/integrations/make.svg", ratio: 21 / 28, kind: "mark", height: 21 },
  { name: "Zapier", logo: "/integrations/zapier.svg", ratio: 244 / 66, kind: "wordmark", height: 16 },
  { name: "n8n", logo: "/integrations/n8n.svg", ratio: 228 / 120, kind: "mark", height: 15 },
  { name: "viaSocket", logo: "/integrations/viasocket.svg", ratio: 1, kind: "mark" },
  { name: "AiSensy", logo: "/integrations/aisensy.png", ratio: 110 / 57, kind: "mark", height: 17, blend: true },
  { name: "AWS Marketplace", logo: "/integrations/aws.svg", ratio: 304 / 182, kind: "mark", height: 18 },
  { name: "GitHub", logo: "/integrations/github.svg", ratio: 1, kind: "mark" },
  { name: "Notion", logo: "/integrations/notion.svg", ratio: 256 / 268, kind: "mark" },
  { name: "Razorpay", logo: "/integrations/razorpay.png", ratio: 1, kind: "mark", height: 22 },
  { name: "Stripe", logo: "/integrations/stripe.svg", ratio: 1, kind: "mark", height: 18 },
  { name: "Apollo.io", logo: "/integrations/apollo-io.svg", ratio: 1, kind: "mark" },
  { name: "Google Calendar", logo: "/integrations/google-calendar.svg", ratio: 1, kind: "mark" },
];
