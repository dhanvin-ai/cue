type CueMarkProps = {
  className?: string;
  /** Colour of the open "C" stroke. */
  tone?: "ink" | "paper";
};

/** The CUE mark: an open "C" with a lime presence dot sitting in its mouth. */
export function CueMark({ className, tone = "ink" }: CueMarkProps) {
  const stroke = tone === "ink" ? "var(--color-ink)" : "var(--color-paper)";
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden className={className}>
      <path
        d="M23.3 9.2A10 10 0 1 0 23.3 22.8"
        stroke={stroke}
        strokeWidth="4.2"
        strokeLinecap="round"
      />
      <circle cx="24.2" cy="16" r="3.4" fill="var(--color-lime)" />
    </svg>
  );
}

export function CueLogo({ className }: { className?: string }) {
  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`}>
      <CueMark className="size-7" />
      <span className="text-[22px] font-semibold tracking-[-0.04em] text-ink">cue</span>
    </span>
  );
}
