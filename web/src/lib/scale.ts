// The golden-ratio tokens of docs/DESIGN_DIRECTION.md section 3. index.css
// declares the same values as Tailwind theme variables; scale.test.ts checks both.

export const PHI = 1.618;

/** Margin, padding and gap, in px (Fibonacci). */
export const SPACING = [8, 13, 21, 34, 55, 89, 144] as const;

/** Font sizes, in px: an 18 px body, each step about 1.618 times the last. */
export const TYPE_SCALE = [18, 29, 47, 76, 123] as const;

/** The palette anchors: ink, bone and Stellar Strawberry. */
export const ANCHORS = { ink: "#142030", bone: "#eae4d3", strawberry: "#ff5c8d" } as const;

/**
 * The semantic marks, one shade per theme: ink is the run view (bone on ink),
 * paper is the landing (ink on bone). Withdrawn is Strawberry on ink and a deep
 * shade of it on paper, where Strawberry itself is too light for text.
 */
export const SEMANTIC = {
  ink: { supported: "#7ccfa3", withdrawn: "#ff5c8d", auditor: "#aeb2f0", cost: "#d9aa52" },
  paper: { supported: "#1a5e3e", withdrawn: "#a3204f", auditor: "#3b3f8f", cost: "#6e4a0c" },
} as const;

export const LINE_HEIGHT = { body: 1.618, display: 1.1 } as const;

/** The approval gate's hold time: 1.618 s. */
export const HOLD_MS = 1618;
