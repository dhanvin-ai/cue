import Link from "next/link";
import { ArrowRight } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

type PillLinkProps = Omit<ComponentProps<typeof Link>, "children"> & {
  children: ReactNode;
  size?: "sm" | "md" | "lg";
  /** Show the lime "presence" dot before the label. */
  dot?: boolean;
  arrow?: boolean;
};

const sizes = {
  sm: "h-9 px-4 text-[13px] gap-1.5",
  md: "h-11 px-5 text-[15px] gap-2",
  lg: "h-14 px-7 text-[17px] gap-2.5",
};

export function PillLink({
  children,
  size = "md",
  dot = false,
  arrow = true,
  className,
  ...props
}: PillLinkProps) {
  return (
    <Link
      {...props}
      className={`group relative inline-flex shrink-0 items-center justify-center rounded-full bg-ink font-medium tracking-[-0.01em] text-paper shadow-[0_1px_0_rgb(255_255_255/0.12)_inset,0_10px_24px_-10px_rgb(15_16_13/0.6)] transition-[transform,box-shadow,background-color] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] hover:-translate-y-0.5 hover:bg-[#1c1d19] hover:shadow-[0_1px_0_rgb(255_255_255/0.12)_inset,0_18px_32px_-12px_rgb(15_16_13/0.55)] active:translate-y-0 active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-ink ${sizes[size]} ${className ?? ""}`}
    >
      {dot && (
        <span className="relative mr-1 flex size-2">
          <span className="absolute inset-0 animate-ping rounded-full bg-lime opacity-60 motion-reduce:hidden" />
          <span className="relative size-2 rounded-full bg-lime" />
        </span>
      )}
      <span>{children}</span>
      {arrow && (
        <ArrowRight
          aria-hidden
          strokeWidth={2.2}
          className="size-[1.05em] transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:translate-x-1"
        />
      )}
    </Link>
  );
}
