import { Check, CircleAlert, Info } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { CONSENT_TEXT } from "@/lib/meet-cue/types";

export const inputClass =
  "block h-12 w-full min-w-0 rounded-2xl border border-line bg-white px-4 text-[15.5px] tracking-[-0.01em] text-ink shadow-[inset_0_1px_2px_rgb(15_16_13/0.04)] [color-scheme:light] placeholder:text-faint transition-[border-color,box-shadow] duration-200 hover:border-[#d6d6cf] focus:border-ink/40 focus:outline-none focus:ring-4 focus:ring-lime/45 aria-[invalid=true]:border-alert aria-[invalid=true]:focus:ring-alert-line disabled:cursor-not-allowed disabled:bg-paper-deep disabled:text-muted";

type FieldProps = ComponentProps<"input"> & {
  id: string;
  label: string;
  hint?: ReactNode;
  optional?: boolean;
  error?: string;
};

export function Field({ id, label, hint, optional, error, className, ...props }: FieldProps) {
  const describedBy = [error ? `${id}-error` : null, hint ? `${id}-hint` : null].filter(Boolean).join(" ") || undefined;
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 flex items-baseline justify-between gap-2 text-[13.5px] font-medium text-ink-soft">
        {label}
        {optional && <span className="text-[12px] font-normal text-faint">Optional</span>}
      </label>
      <input id={id} aria-invalid={error ? true : undefined} aria-describedby={describedBy} className={inputClass} {...props} />
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-[12.5px] text-alert">
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="mt-1.5 text-[12.5px] text-muted">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

export function ConsentCheckbox({
  id,
  checked,
  onChange,
  error,
  disabled,
}: {
  id: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  error?: string;
  disabled?: boolean;
}) {
  return (
    <div>
      <label
        htmlFor={id}
        className={`flex cursor-pointer gap-3 rounded-2xl border p-3.5 transition-colors duration-200 has-[:focus-visible]:ring-4 has-[:focus-visible]:ring-lime/45 ${
          error ? "border-alert-line bg-alert-wash" : checked ? "border-lime-ink/25 bg-lime-wash" : "border-line bg-paper/70 hover:border-[#d6d6cf]"
        }`}
      >
        <input
          id={id}
          type="checkbox"
          checked={checked}
          disabled={disabled}
          onChange={(event) => onChange(event.target.checked)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : undefined}
          className="peer sr-only"
        />
        <span
          aria-hidden
          className="mt-0.5 grid size-[18px] shrink-0 place-items-center rounded-[6px] border border-[#cfcfc7] bg-white text-ink transition-colors duration-200 peer-checked:border-ink peer-checked:bg-ink peer-checked:text-lime [&>svg]:opacity-0 peer-checked:[&>svg]:opacity-100"
        >
          <Check className="size-3" strokeWidth={3} />
        </span>
        <span className="text-[13px] leading-[1.5] text-ink-soft">
          <span className="font-medium text-ink">I understand and agree. </span>
          {CONSENT_TEXT}
        </span>
      </label>
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-[12.5px] text-alert">
          {error}
        </p>
      )}
    </div>
  );
}

/** Inline status message. `error` is announced to screen readers. */
export function Notice({
  tone = "error",
  title,
  children,
  className,
}: {
  tone?: "error" | "info";
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const Icon = tone === "error" ? CircleAlert : Info;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`flex gap-3 rounded-2xl border p-3.5 text-[13.5px] leading-[1.5] ${
        tone === "error" ? "border-alert-line bg-alert-wash text-alert-ink" : "border-line bg-paper-deep/70 text-ink-soft"
      } ${className ?? ""}`}
    >
      <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${tone === "error" ? "text-alert" : "text-muted"}`} />
      <div className="min-w-0">
        <p className={`font-medium ${tone === "error" ? "text-alert-ink" : "text-ink"}`}>{title}</p>
        {children && <div className="mt-0.5">{children}</div>}
      </div>
    </div>
  );
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const isEmail = (value: string) => EMAIL_RE.test(value.trim());
