// Shapes drawn in code: the dot-matrix rook, the mirrored arcs, the team
// rings, the progress ring and the safeguard glyphs. Three hues only, no
// raster images and no icon pack.

import { useMemo } from "react";
import { rookDots } from "../lib/halftone";
import { ROOK_HEIGHT, ROOK_PATHS, ROOK_WIDTH } from "./mark";

/** The rook as a halftone figure: bone dots sized by depth, a Strawberry core in the slit. */
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
          className={d.core ? "fill-berry" : "fill-bone"}
          opacity={d.core ? 1 : 0.55 + d.r}
        />
      ))}
    </svg>
  );
}

/** Two arcs mirrored about the vertical axis, crossing behind the hero object. */
export function MirroredArcs({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 987 610" preserveAspectRatio="none" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="arc-berry" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#ff5c8d" stopOpacity="0" />
          <stop offset="0.5" stopColor="#ff5c8d" stopOpacity="0.8" />
          <stop offset="1" stopColor="#ff5c8d" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="arc-bone" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#eae4d3" stopOpacity="0" />
          <stop offset="0.5" stopColor="#eae4d3" stopOpacity="0.38" />
          <stop offset="1" stopColor="#eae4d3" stopOpacity="0" />
        </linearGradient>
      </defs>
      <g fill="none" vectorEffect="non-scaling-stroke">
        <path d="M0 560 Q493.5 -144 987 377" stroke="url(#arc-berry)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <path d="M987 560 Q493.5 -144 0 377" stroke="url(#arc-berry)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        <path d="M0 610 Q493.5 55 987 466" stroke="url(#arc-bone)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        <path d="M987 610 Q493.5 55 0 466" stroke="url(#arc-bone)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      </g>
    </svg>
  );
}

export type NodeTone = "lit" | "active" | "dim" | "alert";

const FILL: Record<NodeTone, string> = {
  lit: "fill-bone stroke-bone",
  active: "fill-berry stroke-berry",
  dim: "fill-none stroke-line-strong",
  alert: "fill-none stroke-berry",
};

export interface RingNode {
  tone: NodeTone;
  /** Drawn as a square instead of a circle (a second operator model). */
  square?: boolean;
}

function around(i: number, n: number, radius: number, start = -90): [number, number] {
  const a = ((start + (360 * i) / Math.max(n, 1)) * Math.PI) / 180;
  return [305 + radius * Math.cos(a), 305 + radius * Math.sin(a)];
}

/**
 * The team as concentric rings: the director at the center, managers on the
 * first ring, operators as dots on the second, the auditor on a dashed outer
 * ring. With `lights`, operator dots carry the .light class and light up in
 * sequence once their parent has .is-playing.
 */
export function TeamRings({
  director,
  managers,
  operators,
  auditor,
  lights = false,
  compact = false,
  className = "",
}: {
  director: NodeTone;
  managers: RingNode[];
  operators: RingNode[];
  auditor: NodeTone | null;
  lights?: boolean;
  /** Bigger nodes and thicker lines, for the small diagram in the run strip. */
  compact?: boolean;
  className?: string;
}) {
  const k = compact ? 2.6 : 1;
  return (
    <svg viewBox="0 0 610 610" className={className} aria-hidden="true">
      <g fill="none" className={compact ? "stroke-line-strong" : "stroke-line"} strokeWidth={compact ? 8 : 1}>
        <circle cx="305" cy="305" r="144" />
        <circle cx="305" cy="305" r="233" />
        {auditor && <circle cx="305" cy="305" r="289" strokeDasharray={compact ? "13 21" : "3 8"} className="stroke-line-strong" />}
      </g>
      <circle cx="305" cy="305" r="55" strokeWidth="2" className={director === "lit" ? "fill-ink stroke-bone" : `fill-ink ${FILL[director]}`} />
      <g transform={`translate(${305 - ROOK_WIDTH * 0.9} ${305 - ROOK_HEIGHT * 0.9}) scale(1.8)`} className="fill-bone" fillRule="evenodd">
        {ROOK_PATHS.map((d) => (
          <path key={d} d={d} />
        ))}
      </g>
      {managers.map((m, i) => {
        const [x, y] = around(i, managers.length, 144);
        return <circle key={i} cx={x} cy={y} r={17 * k} strokeWidth={3 * k} className={FILL[m.tone]} />;
      })}
      {operators.map((o, i) => {
        const [x, y] = around(i, operators.length, 233);
        const cls = `${FILL[o.tone]} ${lights ? "light" : ""}`;
        const style = lights ? { ["--light-delay" as string]: `${i * 21}ms` } : undefined;
        return o.square ? (
          <rect key={i} x={x - 6 * k} y={y - 6 * k} width={12 * k} height={12 * k} strokeWidth={2 * k} className={cls} style={style} />
        ) : (
          <circle key={i} cx={x} cy={y} r={6.5 * Math.min(k, 1.6)} strokeWidth={2 * k} className={cls} style={style} />
        );
      })}
      {auditor && (() => {
        const [x, y] = around(0, 1, 289, 90);
        return <circle cx={x} cy={y} r={13 * k} strokeWidth={3 * k} className={`${FILL[auditor]} [stroke-dasharray:none]`} />;
      })()}
    </svg>
  );
}

/** A circular progress ring, value from 0 to 1. */
export function ProgressRing({
  value,
  size = 89,
  stroke = 8,
  tone = "bone",
  className = "",
}: {
  value: number;
  size?: number;
  stroke?: number;
  tone?: "bone" | "berry" | "ink";
  className?: string;
}) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(1, value));
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className={`-rotate-90 ${className}`} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" strokeWidth={stroke} className={tone === "ink" ? "stroke-ink/25" : "stroke-track"} />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={c}
        strokeDashoffset={c * (1 - v)}
        className={`hold-ring ${tone === "berry" ? "stroke-berry" : tone === "ink" ? "stroke-ink" : "stroke-bone"}`}
      />
    </svg>
  );
}

/** Six original glyphs for the six safeguards: ring, square, triangle, arc, twin circles, dot. */
export function Glyph({ kind, className = "" }: { kind: 0 | 1 | 2 | 3 | 4 | 5; className?: string }) {
  const common = { fill: "none", strokeWidth: 2.5 } as const;
  return (
    <svg viewBox="0 0 55 55" className={className} aria-hidden="true">
      {kind === 0 && (
        <>
          <circle cx="27.5" cy="27.5" r="21" className="stroke-bone" {...common} />
          <circle cx="27.5" cy="27.5" r="6" className="fill-berry" />
        </>
      )}
      {kind === 1 && (
        <>
          <rect x="8" y="8" width="39" height="39" rx="8" className="stroke-bone" {...common} />
          <rect x="8" y="30" width="39" height="17" rx="8" className="fill-berry" />
        </>
      )}
      {kind === 2 && (
        <>
          <path d="M27.5 6 L50 47 H5 Z" strokeLinejoin="round" className="stroke-bone" {...common} />
          <circle cx="27.5" cy="34" r="5" className="fill-berry" />
        </>
      )}
      {kind === 3 && (
        <>
          <path d="M8 40 A21 21 0 1 1 47 40" strokeLinecap="round" className="stroke-bone" {...common} />
          <path d="M37 21 L27.5 34" strokeLinecap="round" className="stroke-berry" {...common} />
        </>
      )}
      {kind === 4 && (
        <>
          <circle cx="20" cy="27.5" r="13" className="stroke-bone" {...common} />
          <circle cx="35" cy="27.5" r="13" className="stroke-berry" {...common} />
        </>
      )}
      {kind === 5 && (
        <>
          <circle cx="27.5" cy="27.5" r="21" strokeDasharray="4 6" className="stroke-line-strong" {...common} />
          <circle cx="27.5" cy="27.5" r="11" className="fill-bone" />
        </>
      )}
    </svg>
  );
}
