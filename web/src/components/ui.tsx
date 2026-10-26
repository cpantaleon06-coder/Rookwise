import type { ButtonHTMLAttributes, ReactNode } from "react";
import { atLeastPercent, formatMicros, formatUsd, percentOf, type Micros } from "../lib/money";

export type Tone = "ok" | "warn" | "danger" | "info" | "neutral";

const DOT: Record<Tone, string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
  info: "bg-info",
  neutral: "bg-ink",
};
const TEXT: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
  info: "text-info",
  neutral: "text-ink",
};
const TINT: Record<Tone, string> = {
  ok: "bg-ok-tint",
  warn: "bg-warn-tint",
  danger: "bg-danger-tint",
  info: "bg-info-tint",
  neutral: "bg-raised",
};

/** P8: a dot plus an uppercase word. The word carries the meaning. */
export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`label inline-flex max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 ${TINT[tone]} ${TEXT[tone]}`}
    >
      <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${DOT[tone]}`} />
      <span className="wrap-anywhere">{children}</span>
    </span>
  );
}

export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`label text-muted ${className}`}>{children}</span>;
}

export function Panel({
  id,
  title,
  aside,
  children,
  className = "",
}: {
  id?: string;
  title: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={headingId}
      className={`min-w-0 scroll-mt-52 rounded-[16px] border border-line bg-surface p-4 sm:p-6 ${className}`}
    >
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={headingId} className="text-xl/7 font-semibold sm:text-2xl/8">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

type ButtonProps = {
  variant?: "primary" | "secondary" | "ghost";
  children: ReactNode;
  className?: string;
} & ButtonHTMLAttributes<HTMLButtonElement>;

export function buttonClass(variant: "primary" | "secondary" | "ghost" = "secondary"): string {
  const base =
    "inline-flex min-h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-full px-5 text-sm font-medium transition-colors duration-[120ms] ease-rw disabled:cursor-not-allowed";
  if (variant === "primary") {
    return `${base} bg-primary text-on-primary hover:opacity-90 disabled:opacity-50`;
  }
  if (variant === "ghost") {
    return `${base} text-ink hover:bg-raised disabled:text-muted`;
  }
  return `${base} border border-line-strong text-ink hover:bg-raised disabled:border-line disabled:text-muted`;
}

export function Button({ variant = "secondary", children, className = "", ...rest }: ButtonProps) {
  return (
    <button type="button" className={`${buttonClass(variant)} ${className}`} {...rest}>
      {children}
    </button>
  );
}

/** A money string from the files, shown with all six decimals. */
export function Usd({ value, className = "" }: { value: string | null | undefined; className?: string }) {
  return <span className={`num ${className}`}>{formatUsd(value)}</span>;
}

/** A value that does not exist yet: dashed box, never a zero. */
export function Placeholder({ children }: { children: ReactNode }) {
  return <span className="placeholder-box label inline-block px-2 py-1">{children}</span>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`rounded-[6px] bg-raised ${className}`} />;
}

/**
 * The budget meter (web/DESIGN.md 3.2.1): spent solid, reserved hatched, the
 * cap as the end. Neutral below 80 percent, warn from 80 percent, danger on a
 * stop or past the cap. Widths come from integer micro-USD math.
 */
export function Meter({
  spent,
  held,
  cap,
  stopped,
  stale = false,
}: {
  spent: Micros | null;
  held: Micros | null;
  cap: Micros | null;
  stopped: boolean;
  stale?: boolean;
}) {
  const s = spent ?? 0n;
  const h = held ?? 0n;
  const c = cap ?? 0n;
  const over = c > 0n && s > c;
  const tone: Tone = stopped || over ? "danger" : c > 0n && atLeastPercent(s, c, 80) ? "warn" : "neutral";
  const spentPct = Math.min(100, percentOf(s, c));
  const heldPct = Math.max(0, Math.min(100 - spentPct, percentOf(h, c)));
  const valueText =
    spent === null || cap === null
      ? "Not started"
      : `Spent ${formatMicros(s)} of ${formatMicros(c)} cap, ${formatMicros(h)} reserved`;
  return (
    <div
      role="meter"
      aria-label="Budget"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={spent === null ? 0 : Math.min(100, spentPct)}
      aria-valuetext={valueText}
      className={`meter-track relative h-2.5 w-full overflow-hidden rounded-full bg-track ${stale ? "outline outline-1 outline-dashed outline-line-strong" : ""}`}
    >
      <div
        className={`absolute inset-y-0 left-0 transition-[width] duration-200 ease-rw ${DOT[tone]}`}
        style={{ width: `${spentPct}%` }}
      />
      <div
        className="hatched absolute inset-y-0 transition-[width] duration-200 ease-rw"
        style={{ left: `${spentPct}%`, width: `${heldPct}%` }}
      />
      {over && <div className="absolute inset-y-0 right-0 w-1.5 bg-danger" aria-hidden="true" />}
    </div>
  );
}
