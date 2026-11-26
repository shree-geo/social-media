/**
 * Dates as Nepali businesses read them: Bikram Sambat (BS) first, with the AD date
 * available beside it or as a tooltip. Times stay in the device's clock.
 *
 *   bsDay(d)      → "11 Kartik"            (lists, chips)
 *   bsDate(d)     → "11 Kartik 2083"       (detail pages)
 *   adDay(d)      → "28 Oct 2026"          (the AD equivalent, for titles/tooltips)
 *   bothDates(d)  → "11 Kartik 2083 (28 Oct 2026)"
 *   dateTime(d)   → "11 Kartik 2083, 7:48 AM"
 *   shortDay(d)   → "Today" / "Yesterday" / "11 Kartik" (+ year when not this BS year)
 */
import NepaliDate from "nepali-date-converter";

type DateInput = string | Date;

const toDate = (value: DateInput): Date => (value instanceof Date ? value : new Date(value));

function bs(value: DateInput): NepaliDate | null {
  try {
    return new NepaliDate(toDate(value));
  } catch {
    return null; // outside the converter's range (roughly 1943–2042 AD): fall back to AD
  }
}

export function adDay(value: DateInput): string {
  return toDate(value).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function bsDay(value: DateInput): string {
  const n = bs(value);
  return n ? n.format("D MMMM", "en") : toDate(value).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

export function bsDate(value: DateInput): string {
  const n = bs(value);
  return n ? n.format("D MMMM YYYY", "en") : adDay(value);
}

export function bsYear(value: DateInput): number | null {
  return bs(value)?.getYear() ?? null;
}

export function bothDates(value: DateInput): string {
  return `${bsDate(value)} (${adDay(value)})`;
}

export function clock(value: DateInput): string {
  return toDate(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

export function dateTime(value: DateInput): string {
  return `${bsDate(value)}, ${clock(value)}`;
}

function sameDay(a: Date, b: Date): boolean {
  return a.toDateString() === b.toDateString();
}

/** "Today", "Yesterday", else the BS day; adds the BS year when it isn't the current one. */
export function shortDay(value: DateInput, now = new Date()): string {
  const d = toDate(value);
  if (sameDay(d, now)) return "Today";
  const y = new Date(now);
  y.setDate(now.getDate() - 1);
  if (sameDay(d, y)) return "Yesterday";
  const year = bsYear(d);
  return year !== null && year !== bsYear(now) ? bsDate(d) : bsDay(d);
}
