// Figures drawn in code: the dot-matrix rook and circular progress rings.
// Theme colors only, no raster images.

import { useMemo } from "react";
import { rookDots } from "../lib/halftone";
import { ROOK_HEIGHT, ROOK_WIDTH } from "./mark";

/** The rook as a halftone figure: dots sized by depth, a Strawberry core in the slit. */
export function DotRook({ className = "" }: { className?: string }) {
  const dots = useMemo(() => rookDots(), []);
  return (
    <svg viewBox={`-1 -1 ${ROOK_WIDTH + 2} ${ROOK_HEIGHT + 2}`} className={className} aria-hidden="true">
      {dots.map((d) => (
        <circle
          key={`${d.x}:${d.y}`}
          cx={d.x}
          cy={d.y}
          r={d.r}
          className={d.core ? "fill-strawberry" : "fill-fg"}
          opacity={d.core ? 1 : 0.45 + d.r}
        />
      ))}
    </svg>
  );
}

const RING = {
  fg: { track: "stroke-track", arc: "stroke-fg" },
  bg: { track: "stroke-bg/25", arc: "stroke-bg" },
  cost: { track: "stroke-track", arc: "stroke-cost" },
  supported: { track: "stroke-track", arc: "stroke-supported" },
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
