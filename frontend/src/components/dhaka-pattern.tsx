/**
 * Geometric band inspired by Dhaka weave: stacked diamonds and chevrons in brand
 * colors. Used only on brand surfaces (login screens, sidebar foot). Colors come from the nav tokens,
 * so it always sits on the indigo brand background in light and dark mode.
 */
export function DhakaPattern({ className }: { className?: string }) {
  return (
    <svg className={className} aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <pattern id="dhaka" width="56" height="56" patternUnits="userSpaceOnUse">
          <path d="M28 4 52 28 28 52 4 28Z" fill="none" stroke="var(--sc-nav-ink)" strokeOpacity="0.18" strokeWidth="2" />
          <path d="M28 16 40 28 28 40 16 28Z" fill="var(--sc-nav-marker)" fillOpacity="0.85" />
          <path d="M28 22 34 28 28 34 22 28Z" fill="var(--sc-nav-bg)" />
          <path d="M0 0 8 8 0 16M56 0 48 8 56 16M0 40 8 48 0 56M56 40 48 48 56 56" fill="none" stroke="var(--sc-nav-ink)" strokeOpacity="0.28" strokeWidth="2" />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill="url(#dhaka)" />
    </svg>
  );
}
