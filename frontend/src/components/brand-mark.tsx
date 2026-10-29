import { cx } from "@/components/ui";

/** MyLeadToday logo mark: an "M" rising into an arrow, marigold on brand indigo. Same drawing as
 * public/brand/app-icon.svg (the Meta app icon and favicon); keep the two in step. */
export function BrandMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 1024 1024" className={cx("shrink-0 rounded-[22%]", className)} aria-hidden="true" focusable="false">
      <rect width="1024" height="1024" fill="#24306e" />
      <g fill="none" stroke="#e9a23b" strokeWidth="110" strokeLinecap="round" strokeLinejoin="round">
        <polyline points="250,770 250,330 500,610 760,300" />
        <polyline points="600,290 772,288 770,460" />
      </g>
    </svg>
  );
}
