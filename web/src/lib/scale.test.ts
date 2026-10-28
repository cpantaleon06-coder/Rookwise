import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { ANCHORS, HOLD_MS, LINE_HEIGHT, PHI, SEMANTIC, SPACING, TYPE_SCALE } from "./scale";

const CSS = readFileSync(resolve(__dirname, "../index.css"), "utf8");

function ratios(steps: readonly number[]): number[] {
  return steps.slice(1).map((value, i) => value / steps[i]);
}

describe("the spacing scale", () => {
  it("grows by the golden ratio, within 0.05, from 13 up", () => {
    for (const ratio of ratios(SPACING)) {
      expect(Math.abs(ratio - PHI)).toBeLessThan(0.05);
    }
  });

  it("is the one index.css declares", () => {
    const declared = [...CSS.matchAll(/--spacing-(\d+):\s*(\d+)px;/g)].map((m) => [Number(m[1]), Number(m[2])]);
    expect(declared.map(([, px]) => px)).toEqual([...SPACING]);
    for (const [name, px] of declared) expect(name).toBe(px);
  });
});

describe("the type scale", () => {
  it("grows by the golden ratio, within 0.05", () => {
    for (const ratio of ratios(TYPE_SCALE)) {
      expect(Math.abs(ratio - PHI)).toBeLessThan(0.05);
    }
  });

  it("is the one index.css declares, with the body and display line heights", () => {
    const sizes = [...CSS.matchAll(/--text-[a-z]+:\s*(\d+)px;/g)].map((m) => Number(m[1]));
    expect(sizes).toEqual([...TYPE_SCALE]);
    expect(CSS).toContain(`--text-body--line-height: ${LINE_HEIGHT.body};`);
    expect(CSS).toContain(`--text-display--line-height: ${LINE_HEIGHT.display};`);
  });
});

describe("the palette", () => {
  it("names only the three anchors and the semantic marks of both themes", () => {
    const hexes = new Set([...CSS.matchAll(/#[0-9a-f]{6}\b/gi)].map((m) => m[0].toLowerCase()));
    const marks = [...Object.values(SEMANTIC.ink), ...Object.values(SEMANTIC.paper)];
    expect([...hexes].sort()).toEqual([...new Set([...Object.values(ANCHORS), ...marks])].sort());
  });
});

it("holds the approval for 1.618 s", () => {
  expect(HOLD_MS).toBe(PHI * 1000);
});
