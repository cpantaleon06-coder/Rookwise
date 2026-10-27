// The golden-ratio tokens of docs/DESIGN_DIRECTION.md section 3. index.css
// declares the same values as Tailwind theme variables; scale.test.ts checks both.

export const PHI = 1.618;

/** Margin, padding and gap, in px (Fibonacci). */
export const SPACING = [8, 13, 21, 34, 55, 89, 144] as const;

/** Font sizes, in px: an 18 px body, each step about 1.618 times the last. */
export const TYPE_SCALE = [18, 29, 47, 76, 123] as const;

/** The palette anchors: ink, bone and Stellar Strawberry. */
export const ANCHORS = { ink: "#142030", bone: "#eae4d3", strawberry: "#ff5c8d" } as const;

/** The semantic set, each used for one meaning only. */
export const SEMANTIC = {
  verified: "#3ed6b0",
  withdrawn: "#ffa53d",
  auditor: "#a5a8ff",
  money: "#f2cf5b",
} as const;

export const LINE_HEIGHT = { body: 1.618, display: 1.1 } as const;

/** The approval gate's hold time: 1.618 s. */
export const HOLD_MS = 1618;
