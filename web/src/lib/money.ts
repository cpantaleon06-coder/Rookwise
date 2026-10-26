// Money in the contract is USD as a decimal string with exactly six decimals
// (docs/api.md, "Conventions"). The web app never turns it into a JavaScript
// number for arithmetic: amounts are parsed into whole micro-USD as BigInt,
// added or compared there, and formatted back to a string for display.

const MONEY_RE = /^([0-9]+)\.([0-9]{6})$/;

export type Micros = bigint;

export const ZERO: Micros = 0n;

/** True when `value` is a contract money string such as "0.015903". */
export function isMoney(value: unknown): value is string {
  return typeof value === "string" && MONEY_RE.test(value);
}

/** Parse a six-decimal money string into whole micro-USD. Throws on anything else. */
export function toMicros(value: string): Micros {
  const match = MONEY_RE.exec(value);
  if (!match) {
    throw new Error(`Not a six-decimal money string: ${JSON.stringify(value)}`);
  }
  return BigInt(match[1]) * 1_000_000n + BigInt(match[2]);
}

/** Parse when valid, otherwise null (for optional or untrusted fields). */
export function toMicrosOrNull(value: unknown): Micros | null {
  return isMoney(value) ? toMicros(value) : null;
}

/** Back to the contract form: "0.015903". Negative values get a leading "-". */
export function microsToString(micros: Micros): string {
  const negative = micros < 0n;
  const abs = negative ? -micros : micros;
  const whole = abs / 1_000_000n;
  const frac = (abs % 1_000_000n).toString().padStart(6, "0");
  return `${negative ? "-" : ""}${whole.toString()}.${frac}`;
}

function groupThousands(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/**
 * Display form: "$0.015903", "$1,234.500000", "-$0.000412". All six decimals
 * are kept so a display never rounds spend under a cap it passed.
 */
export function formatMicros(micros: Micros): string {
  const text = microsToString(micros);
  const negative = text.startsWith("-");
  const [whole, frac] = (negative ? text.slice(1) : text).split(".");
  return `${negative ? "-" : ""}$${groupThousands(whole)}.${frac}`;
}

/** Format a contract money string for display. Invalid input is shown as such, never guessed. */
export function formatUsd(value: string | null | undefined): string {
  if (value === null || value === undefined) return "Not recorded";
  if (!isMoney(value)) return `Invalid amount (${String(value)})`;
  return formatMicros(toMicros(value));
}

export function sumMoney(values: Iterable<string>): Micros {
  let total = ZERO;
  for (const value of values) total += toMicros(value);
  return total;
}

/**
 * Share of `part` in `whole` as a percentage for display (meter widths, the
 * 80 percent threshold). Computed in integers, rounded down to 0.01 percent.
 */
export function percentOf(part: Micros, whole: Micros): number {
  if (whole <= 0n) return part > 0n ? 100 : 0;
  return Number((part * 10_000n) / whole) / 100;
}

/** True when `part` is at least `threshold` percent of `whole`, compared in integers. */
export function atLeastPercent(part: Micros, whole: Micros, threshold: number): boolean {
  if (whole <= 0n) return part > 0n;
  return part * 100n >= whole * BigInt(threshold);
}
