import { describe, expect, it } from "vitest";
import { ROOK_WIDTH } from "../components/mark";
import { insideRook, rookDots } from "./halftone";

describe("the dot-matrix rook", () => {
  const dots = rookDots();

  it("follows the silhouette: holes and gaps stay empty", () => {
    expect(insideRook(3.5, 1)).toBe(true); // a merlon
    expect(insideRook(7, 1)).toBe(false); // the gap between merlons
    expect(insideRook(10.5, 16)).toBe(false); // the slit
    expect(insideRook(10.5, 31)).toBe(true); // the base
    expect(dots.length).toBeGreaterThan(300);
  });

  it("is symmetric about the vertical axis", () => {
    const key = (x: number, y: number) => `${x.toFixed(2)}:${y.toFixed(2)}`;
    const radii = new Map(dots.map((d) => [key(d.x, d.y), d.r]));
    for (const d of dots) expect(radii.get(key(ROOK_WIDTH - d.x, d.y))).toBe(d.r);
  });

  it("draws larger dots on the axis than at the edges, and a core in the slit", () => {
    const row = dots.filter((d) => Math.abs(d.y - 22.875) < 0.01 && !d.core);
    const middle = row.reduce((a, b) => (Math.abs(b.x - 10.5) < Math.abs(a.x - 10.5) ? b : a));
    const edge = row.reduce((a, b) => (Math.abs(b.x - 10.5) > Math.abs(a.x - 10.5) ? b : a));
    expect(middle.r).toBeGreaterThan(edge.r);
    expect(dots.some((d) => d.core)).toBe(true);
  });
});
