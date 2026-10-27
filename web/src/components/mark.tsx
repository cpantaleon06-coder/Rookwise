/**
 * The rook mark: 21 by 34 units (1:1.619), symmetric about x = 10.5. Three
 * merlons, a tapered body with a slit, a collar and a base. The polygons below
 * are the one source of the silhouette: the SVG paths, the favicon
 * (public/favicon.svg, same paths) and the hero's dot matrix (lib/halftone.ts)
 * all come from them.
 */
export type Point = readonly [number, number];

export const ROOK_WIDTH = 21;
export const ROOK_HEIGHT = 34;

/** Filled with the even-odd rule: the slit is a hole in the body. */
export const ROOK_POLYGONS: readonly (readonly Point[])[] = [
  [
    [1, 0], [6, 0], [6, 3], [8, 3], [8, 0], [13, 0], [13, 3], [15, 3], [15, 0], [20, 0],
    [20, 9], [17, 9], [15.5, 25], [18, 25], [18, 28], [3, 28], [3, 25], [5.5, 25], [4, 9], [1, 9],
  ],
  [[9.5, 13], [11.5, 13], [11.5, 19], [9.5, 19]],
  [[1, 29.5], [20, 29.5], [20, 34], [1, 34]],
];

/** The slit, where the hero puts its Strawberry core. */
export const ROOK_SLIT = ROOK_POLYGONS[1];

function toPath(poly: readonly Point[]): string {
  return `M${poly.map(([x, y]) => `${x} ${y}`).join("L")}Z`;
}

export const ROOK_PATHS = [toPath(ROOK_POLYGONS[0]) + toPath(ROOK_POLYGONS[1]), toPath(ROOK_POLYGONS[2])] as const;

export function RookMark({ className = "", title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox={`0 0 ${ROOK_WIDTH} ${ROOK_HEIGHT}`}
      className={className}
      fill="currentColor"
      fillRule="evenodd"
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {ROOK_PATHS.map((d) => (
        <path key={d} d={d} />
      ))}
    </svg>
  );
}
