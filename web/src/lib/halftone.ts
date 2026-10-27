// The hero's dot-matrix rook: the silhouette of components/mark.tsx sampled on
// a square grid. Each sample inside the shape becomes a dot whose radius
// follows a cylinder's depth (largest on the vertical axis, smallest at the
// edges), so the flat mark reads as a lit, round tower.

import { ROOK_POLYGONS, ROOK_SLIT, ROOK_WIDTH, ROOK_HEIGHT, type Point } from "../components/mark";

export interface Dot {
  x: number;
  y: number;
  r: number;
  /** In the slit: drawn in Strawberry. */
  core: boolean;
}

function inPolygon(x: number, y: number, poly: readonly Point[]): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

/** Even-odd fill over every polygon, as the SVG path draws it. */
export function insideRook(x: number, y: number): boolean {
  let inside = false;
  for (const poly of ROOK_POLYGONS) if (inPolygon(x, y, poly)) inside = !inside;
  return inside;
}

/** Half the shape's width on row y, measured from the axis (for the depth). */
function halfWidth(y: number, step: number): number {
  const axis = ROOK_WIDTH / 2;
  let half = 0;
  for (let d = 0; d <= axis; d += step / 4) {
    if (insideRook(axis + d, y) || insideRook(axis - d, y)) half = d;
  }
  return Math.max(half, step);
}

/**
 * Samples the rook every `step` units. Columns are placed symmetrically
 * about x = 10.5, so the dots mirror exactly.
 */
export function rookDots(step = 0.75): Dot[] {
  const axis = ROOK_WIDTH / 2;
  // Columns sit half a step off the axis, so no sample falls on an edge of
  // the mark (its edges are on whole and half units).
  const cols = Math.ceil(axis / step);
  const dots: Dot[] = [];
  for (let y = step / 2; y < ROOK_HEIGHT; y += step) {
    const half = halfWidth(y, step);
    for (let c = -cols; c < cols; c++) {
      const x = axis + (c + 0.5) * step;
      const slit = inPolygon(x, y, ROOK_SLIT);
      if (!insideRook(x, y) && !slit) continue;
      const depth = Math.cos(Math.min(1, Math.abs(x - axis) / (half + step / 2)) * (Math.PI / 2));
      const r = slit ? step * 0.36 : step * (0.12 + 0.3 * depth);
      dots.push({ x: Number(x.toFixed(3)), y: Number(y.toFixed(3)), r: Number(r.toFixed(3)), core: slit });
    }
  }
  return dots;
}
