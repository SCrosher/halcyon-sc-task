import { useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Check, Copy } from "./icons";

export function cx(...xs: (string | false | null | undefined)[]) {
  return xs.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" };

export function Button({ variant = "secondary", className, ...p }: ButtonProps) {
  return (
    <button
      {...p}
      className={cx(
        "inline-flex h-9 items-center justify-center gap-2 rounded-full px-4 text-[13px] font-medium transition-colors duration-150 disabled:opacity-40",
        variant === "primary" && "bg-ink text-canvas hover:bg-ink-soft",
        variant === "secondary" && "border border-line-strong bg-surface text-ink hover:border-ink/30",
        variant === "ghost" && "text-muted hover:bg-sunken hover:text-ink",
        className,
      )}
    />
  );
}

export function IconButton({ className, label, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      aria-label={label}
      title={label}
      {...p}
      className={cx(
        "inline-flex size-9 items-center justify-center rounded-full text-[18px] text-muted transition-colors duration-150 hover:bg-sunken hover:text-ink disabled:opacity-40",
        className,
      )}
    />
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  description?: ReactNode;
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-6">
      <span>
        <span className="block text-[14px] text-ink">{label}</span>
        {description && <span className="mt-1 block text-[12.5px] leading-relaxed text-muted">{description}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        onClick={() => onChange(!checked)}
        className={cx(
          "relative mt-0.5 h-6 w-10 shrink-0 rounded-full transition-colors duration-200",
          checked ? "bg-ink" : "bg-line-strong",
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 left-0.5 size-5 rounded-full bg-surface shadow-sm transition-transform duration-200",
            checked && "translate-x-4",
          )}
        />
      </button>
    </label>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-[12.5px] font-medium text-ink-soft">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-[12px] leading-relaxed text-muted">{hint}</span>}
    </label>
  );
}

export const inputClass =
  "h-11 w-full rounded-xl border border-line bg-surface px-3.5 text-[14px] text-ink placeholder:text-faint transition-colors duration-150 hover:border-line-strong focus:border-ink/40 focus:outline-none";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx(
        "inline-block size-3.5 animate-spin rounded-full border-[1.5px] border-current border-r-transparent",
        className,
      )}
      aria-hidden
    />
  );
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <IconButton
      label={label}
      className="size-7 text-[14px]"
      onClick={async (e) => {
        e.preventDefault();
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1200);
        } catch {
          /* clipboard blocked */
        }
      }}
    >
      {done ? <Check className="text-ok" /> : <Copy />}
    </IconButton>
  );
}
