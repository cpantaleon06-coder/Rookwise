// The golden-ratio tokens of docs/DESIGN_DIRECTION.md section 3. index.css
// declares the same values as Tailwind theme variables; scale.test.ts checks both.

export const PHI = 1.618;

/** Margin, padding and gap, in px (Fibonacci). */
export const SPACING = [8, 13, 21, 34, 55, 89, 144] as const;

/** Font sizes, in px. */
export const TYPE_SCALE = [16, 26, 42, 68, 110] as const;

export const LINE_HEIGHT = { body: 1.618, display: 1.1 } as const;

/** The approval gate's hold time: 1.618 s. */
export const HOLD_MS = 1618;
