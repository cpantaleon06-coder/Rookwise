import type { ButtonHTMLAttributes, ReactNode } from "react";
import { atLeastPercent, formatMicros, formatUsd, percentOf, type Micros } from "../lib/money";

export type Tone = "ok" | "warn" | "danger" | "info" | "audit" | "money" | "neutral";

// docs/DESIGN_DIRECTION.md section 2: teal for what held, amber for what was
// withdrawn or needs a look, Strawberry for failures and actions, violet for
// the auditor, gold for money. Every chip also carries a word.
const DOT: Record<Tone, string> = {
  ok: "bg-teal",
  warn: "bg-amber",
  danger: "bg-berry",
  info: "border-2 border-bone",
  audit: "bg-violet",
  money: "bg-gold",
  neutral: "bg-muted",
};
const CHIP: Record<Tone, string> = {
  ok: "bg-teal-tint text-teal",
  warn: "bg-amber-tint text-amber",
  danger: "bg-berry-tint text-berry",
  info: "bg-raised text-bone",
  audit: "bg-violet-tint text-violet",
  money: "bg-gold-tint text-gold",
  neutral: "border border-line-strong text-muted",
};

/** A dot plus a word. The word carries the meaning. */
export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`label inline-flex max-w-full items-center gap-8 rounded-full px-13 min-h-[34px] ${CHIP[tone]}`}>
      <span aria-hidden="true" className={`size-2 shrink-0 rounded-full ${DOT[tone]}`} />
      <span className="wrap-anywhere">{children}</span>
    </span>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M3 8.5l3.2 3.2L13 4.8" strokeLinecap="square" />
    </svg>
  );
}

function CrossIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true" className="size-4 shrink-0" fill="none" stroke="currentColor" strokeWidth="2.5">
      <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="square" />
    </svg>
  );
}

/** VERIFIED: teal fill, check. WITHDRAWN: amber fill, cross. Ink text on both. */
export function Stamp({ kind, className = "" }: { kind: "verified" | "withdrawn"; className?: string }) {
  const verified = kind === "verified";
  return (
    <span
      className={`label inline-flex shrink-0 items-center gap-8 rounded-full px-13 min-h-[34px] font-black uppercase tracking-wider text-ink ${
        verified ? "bg-teal" : "bg-amber"
      } ${className}`}
    >
      {verified ? <CheckIcon /> : <CrossIcon />}
      {verified ? "Verified" : "Withdrawn"}
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
      className={`card min-w-0 scroll-mt-144 rounded-lg p-21 sm:p-34 ${className}`}
    >
      <div className="mb-21 flex flex-wrap items-baseline justify-between gap-13">
        <h2 id={headingId} className="text-title font-black">
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
    "inline-flex min-h-11 shrink-0 items-center justify-center gap-8 whitespace-nowrap rounded-full px-21 font-extrabold transition-colors duration-[120ms] ease-rw disabled:cursor-not-allowed";
  if (variant === "primary") {
    return `${base} bg-berry text-ink hover:bg-bone disabled:opacity-50 disabled:hover:bg-berry`;
  }
  if (variant === "ghost") {
    return `${base} text-bone hover:bg-raised disabled:text-muted`;
  }
  return `${base} border border-line-strong text-bone hover:bg-raised disabled:border-line disabled:text-muted`;
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
  return <span className="placeholder-box label inline-flex items-center px-8 min-h-[34px]">{children}</span>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`rounded-sm bg-raised ${className}`} />;
}

/**
 * The budget meter: spent solid, reserved hatched, the cap as the end. Gold
 * below 80 percent, Strawberry from 80 percent, on a stop or past the cap.
 * Widths come from integer micro-USD math.
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
  const alert = stopped || over || (c > 0n && atLeastPercent(s, c, 80));
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
        className={`absolute inset-y-0 left-0 transition-[width] duration-200 ease-rw ${alert ? "bg-berry" : "bg-gold"}`}
        style={{ width: `${spentPct}%` }}
      />
      <div
        className="hatched absolute inset-y-0 transition-[width] duration-200 ease-rw"
        style={{ left: `${spentPct}%`, width: `${heldPct}%` }}
      />
      {over && <div className="absolute inset-y-0 right-0 w-1.5 bg-berry" aria-hidden="true" />}
    </div>
  );
}
