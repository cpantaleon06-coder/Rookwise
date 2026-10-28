import type { ButtonHTMLAttributes, ReactNode } from "react";
import { atLeastPercent, formatMicros, formatUsd, percentOf, type Micros } from "../lib/money";

export type Tone = "ok" | "warn" | "danger" | "info" | "audit" | "money" | "neutral";

// docs/DESIGN_DIRECTION.md section 2: muted marks only where they carry a
// meaning (supported, withdrawn, auditor, cost), always next to a word and a
// symbol, never as the only signal.
const MARK: Record<Tone, { cls: string; symbol: string }> = {
  ok: { cls: "text-supported", symbol: "✓" },
  warn: { cls: "text-withdrawn", symbol: "!" },
  danger: { cls: "text-withdrawn", symbol: "✕" },
  info: { cls: "text-fg", symbol: "○" },
  audit: { cls: "text-auditor", symbol: "◇" },
  money: { cls: "text-cost", symbol: "$" },
  neutral: { cls: "text-muted", symbol: "·" },
};

/** A small caps word with a symbol before it. The word carries the meaning. */
export function Chip({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  const m = MARK[tone];
  return (
    <span className={`label inline-flex max-w-full items-baseline gap-8 ${m.cls}`}>
      <span aria-hidden="true" className="ui font-semibold">
        {m.symbol}
      </span>
      <span className="wrap-anywhere">{children}</span>
    </span>
  );
}

/** The verdict of the evidence check on a claim: a word and a symbol in its color, framed by a hairline. */
export function Stamp({ kind, className = "" }: { kind: "verified" | "withdrawn"; className?: string }) {
  const verified = kind === "verified";
  return (
    <span
      className={`label inline-flex shrink-0 items-center gap-8 rounded-sm border border-current px-8 ${
        verified ? "text-supported" : "text-withdrawn"
      } ${className}`}
    >
      <span aria-hidden="true">{verified ? "✓" : "✕"}</span>
      {verified ? "Verified" : "Withdrawn"}
    </span>
  );
}

export function Label({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`label text-muted ${className}`}>{children}</span>;
}

/** A section of the document: a hairline above, a serif heading, no box. */
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
    <section id={id} aria-labelledby={headingId} className={`min-w-0 scroll-mt-144 border-t border-rule pt-21 ${className}`}>
      <div className="mb-13 flex flex-wrap items-baseline justify-between gap-13">
        <h2 id={headingId} className="text-title">
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

/** Flat rectangular actions; secondary and ghost read as underlined text. */
export function buttonClass(variant: "primary" | "secondary" | "ghost" = "secondary"): string {
  const base =
    "ui inline-flex min-h-11 shrink-0 items-center justify-center gap-8 rounded-sm px-21 font-semibold transition-colors duration-150 ease-rw disabled:cursor-not-allowed";
  if (variant === "primary") {
    return `${base} bg-fg text-bg hover:bg-muted disabled:opacity-50`;
  }
  if (variant === "ghost") {
    return `${base} px-8 text-fg underline decoration-1 underline-offset-4 hover:decoration-2 disabled:text-muted`;
  }
  return `${base} border border-rule-strong text-fg hover:border-fg disabled:border-rule disabled:text-muted`;
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
  return <span className="placeholder-box label inline-flex items-center px-8">{children}</span>;
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`rounded-sm bg-subtle ${className}`} />;
}

/**
 * The budget meter: spent solid, reserved hatched, the cap as the end. Ochre
 * below 80 percent, the withdrawn mark from 80 percent, on a stop or past the
 * cap. Widths come from integer micro-USD math and ease as the replay spends.
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
      className={`meter-track relative h-2 w-full overflow-hidden rounded-sm bg-track ${stale ? "outline outline-1 outline-dashed outline-rule-strong" : ""}`}
    >
      <div
        className={`absolute inset-y-0 left-0 transition-[width] duration-300 ease-rw ${alert ? "bg-withdrawn" : "bg-cost"}`}
        style={{ width: `${spentPct}%` }}
      />
      <div
        className="hatched absolute inset-y-0 transition-[width] duration-300 ease-rw"
        style={{ left: `${spentPct}%`, width: `${heldPct}%` }}
      />
      {over && <div className="absolute inset-y-0 right-0 w-1.5 bg-withdrawn" aria-hidden="true" />}
    </div>
  );
}
