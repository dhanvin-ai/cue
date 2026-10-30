import { Hero } from "@/components/landing/hero";
import { InAction } from "@/components/landing/in-action/in-action";
import { MeetingDemo } from "@/components/landing/meeting-demo";
import { SiteFooter } from "@/components/landing/site-footer";
import { SiteNav } from "@/components/landing/site-nav";
import { WorksWith } from "@/components/landing/works-with";

export default function Home() {
  return (
    <>
      <SiteNav />
      <main className="flex-1">
        <Hero />
        <MeetingDemo />
        <InAction />
        <WorksWith />
      </main>
      <SiteFooter />
    </>
  );
}
