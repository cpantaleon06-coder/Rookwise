/**
 * The rook mark: 21 by 34 units (1:1.619), symmetric about x = 10.5. Three
 * merlons, a tapered body with a slit, a collar and a base. public/favicon.svg
 * draws the same paths.
 */
export const ROOK_PATHS = [
  "M1 0h5v3h2V0h5v3h2V0h5v9h-3l-1.5 16H18v3H3v-3h2.5L4 9H1zM9.5 13h2v6h-2z",
  "M1 29.5h19V34H1z",
] as const;

export function RookMark({ className = "", title }: { className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 21 34"
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
