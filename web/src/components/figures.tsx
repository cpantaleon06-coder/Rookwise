// The one figure the run view still draws in code: a circular progress ring
// for the hold-to-approve control. Theme colors only.

const RING = {
  fg: { track: "stroke-track", arc: "stroke-fg" },
  bg: { track: "stroke-bg/25", arc: "stroke-bg" },
  cost: { track: "stroke-track", arc: "stroke-cost" },
} as const;

/** A circular progress ring, value from 0 to 1. */
export function ProgressRing({
  value,
  size = 89,
  stroke = 8,
  tone = "fg",
  className = "",
}: {
  value: number;
  size?: number;
  stroke?: number;
  tone?: keyof typeof RING;
  className?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={`-rotate-90 ${className}`} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className={RING[tone].track} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={stroke}
        strokeDasharray={c}
        strokeDashoffset={c * (1 - v)}
        className={`hold-ring ${RING[tone].arc}`}
      />
    </svg>
  );
}
