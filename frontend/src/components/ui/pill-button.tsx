import { ArrowRight, LoaderCircle } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";

type PillButtonProps = Omit<ComponentProps<"button">, "children"> & {
  children: ReactNode;
  size?: "sm" | "md" | "lg";
  tone?: "ink" | "ghost";
  arrow?: boolean;
  /** Swaps the arrow for a spinner and disables the button. */
  busy?: boolean;
};

const sizes = {
  sm: "h-9 px-4 text-[13px] gap-1.5",
  md: "h-11 px-5 text-[15px] gap-2",
  lg: "h-13 px-6 text-[16px] gap-2.5",
};

const tones = {
  ink: "bg-ink text-paper shadow-[0_1px_0_rgb(255_255_255/0.12)_inset,0_10px_24px_-10px_rgb(15_16_13/0.6)] enabled:hover:-translate-y-0.5 enabled:hover:bg-[#1c1d19] enabled:hover:shadow-[0_1px_0_rgb(255_255_255/0.12)_inset,0_18px_32px_-12px_rgb(15_16_13/0.55)] disabled:bg-ink/80",
  ghost: "border border-line bg-white/80 text-ink-soft enabled:hover:border-[#d6d6cf] enabled:hover:text-ink enabled:hover:shadow-card",
};

/** Button twin of PillLink, for forms and in-page actions. */
export function PillButton({
  children,
  size = "md",
  tone = "ink",
  arrow = true,
  busy = false,
  disabled,
  className,
  type = "button",
  ...props
}: PillButtonProps) {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={`group relative inline-flex shrink-0 items-center justify-center rounded-full font-medium tracking-[-0.01em] transition-[transform,box-shadow,background-color,border-color,color] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] enabled:active:translate-y-0 enabled:active:scale-[0.98] focus-visible:outline-2 focus-visible:outline-offset-3 focus-visible:outline-ink disabled:cursor-not-allowed ${sizes[size]} ${tones[tone]} ${className ?? ""}`}
    >
      <span>{children}</span>
      {busy ? (
        <LoaderCircle aria-hidden className="size-[1.05em] animate-spin" />
      ) : (
        arrow && (
          <ArrowRight
            aria-hidden
            strokeWidth={2.2}
            className="size-[1.05em] transition-transform duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] group-enabled:group-hover:translate-x-1"
          />
        )
      )}
    </button>
  );
}
