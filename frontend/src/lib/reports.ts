/** Dashboard figures from GET /api/v1/reports/dashboard (definitions: backend/app/services/reports.py). */

export type Period = "today" | "7d" | "30d" | "this_month" | "last_month" | "90d";

export const PERIODS: { key: Period; label: string; previous: string }[] = [
  { key: "today", label: "Today", previous: "yesterday" },
  { key: "7d", label: "7 days", previous: "previous 7 days" },
  { key: "30d", label: "30 days", previous: "previous 30 days" },
  { key: "this_month", label: "This month", previous: "same number of days before" },
  { key: "last_month", label: "Last month", previous: "month before" },
  { key: "90d", label: "90 days", previous: "previous 90 days" },
];

export type ReportTotals = {
  sales: string;
  sales_orders: number;
  received: string;
  new_orders: number;
  new_customers: number;
  messages_in: number;
};

export type Dashboard = {
  window: { first_day: string; last_day: string; start: string; end: string; bucket: "hour" | "day" | "week" };
  currency: string;
  totals: ReportTotals;
  previous: ReportTotals;
  series: { start: string; sales: string; orders: number }[];
  channels: { channel: string; messages_in: number; conversations: number; orders: number; sales: string }[];
  lead_sources: { lead_source: string | null; orders: number; sales: string }[];
  orders_by_status: Record<string, number>;
  funnel: { conversations: number; converted_conversations: number; orders: number; sales: string };
  snapshot: {
    open_orders: number;
    outstanding: string;
    outstanding_orders: number;
    overdue: string;
    overdue_invoices: number;
    deliveries_open: number;
    deliveries_due_today: number;
    delivered_in_period: number;
  };
  buyers: { total: number; returning: number };
};

const compact = new Intl.NumberFormat("en-IN", { notation: "compact", maximumFractionDigits: 1 });

/** Short money for tiles and axes: Rs. 7.2L, Rs. 12.5K (Indian/Nepali lakh and crore). */
export function compactMoney(value: string | number, currency: string): string {
  const prefix = currency === "NPR" ? "Rs." : currency;
  return `${prefix} ${compact.format(Number(value))}`;
}

export function compactNumber(value: number): string {
  return compact.format(value);
}

/** Change against the previous period, or null when there is nothing to compare with. */
export function change(current: string | number, previous: string | number): number | null {
  const now = Number(current);
  const before = Number(previous);
  if (before === 0) return null;
  return Math.round(((now - before) / before) * 100);
}
