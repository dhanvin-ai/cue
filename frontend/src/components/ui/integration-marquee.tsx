import Image from "next/image";
import type { CSSProperties } from "react";
import { integrations as defaultIntegrations, type Integration } from "@/lib/integrations";

type IntegrationMarqueeProps = {
  items?: Integration[];
  /** Accessible name for the list. */
  label?: string;
  /** Seconds for one full cycle. */
  duration?: number;
  className?: string;
};

function Group({ items, hidden }: { items: Integration[]; hidden?: boolean }) {
  return (
    <ul className="marquee-group" aria-hidden={hidden || undefined} role={hidden ? undefined : "list"}>
      {items.map((item) => {
        const height = item.height ?? 20;
        return (
          <li key={item.name} className="flex shrink-0 items-center gap-[calc(0.5rem*var(--marquee-scale))]">
            <Image
              src={item.logo}
              alt={item.kind === "wordmark" && !hidden ? item.name : ""}
              width={Math.round(height * item.ratio)}
              height={height}
              unoptimized
              // Items start clipped by the marquee, so lazy loading would make them pop in mid-scroll.
              loading="eager"
              draggable={false}
              className={`block select-none ${item.blend ? "mix-blend-multiply" : ""}`}
              style={{ height: `calc(${height}px * var(--marquee-scale))`, width: "auto" }}
            />
            {item.kind === "mark" && (
              <span className="whitespace-nowrap text-[length:calc(14.5px*var(--marquee-scale))] font-medium tracking-[-0.01em] text-ink-soft">
                {item.name}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Infinite right-to-left logo strip. Pure CSS: two identical groups slide by
 * half the track width, so the loop seam is invisible. Pauses on hover for
 * mouse users and becomes a static, wrapped list under reduced motion.
 */
export function IntegrationMarquee({
  items = defaultIntegrations,
  label = "Integrations",
  duration = 40,
  className,
}: IntegrationMarqueeProps) {
  return (
    <div
      role="region"
      aria-label={label}
      className={`marquee ${className ?? ""}`}
      style={{ "--marquee-duration": `${duration}s` } as CSSProperties}
    >
      <div className="marquee-track">
        <Group items={items} />
        <Group items={items} hidden />
      </div>
    </div>
  );
}
