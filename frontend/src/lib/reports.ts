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
  new_leads: number;
};

export type LeadStats = {
  created: number;
  open_now: number;
  won: number;
  lost: number;
  win_rate: number | null;
  won_value: string;
  avg_days_to_win: number | null;
  lost_reasons: Record<string, number>;
  staff: {
    user_id: string | null;
    full_name: string;
    open: number;
    created: number;
    won: number;
    lost: number;
    won_value: string;
    overdue_followups: number;
  }[];
};

export type Dashboard = {
  window: { first_day: string; last_day: string; start: string; end: string; bucket: "hour" | "day" | "week" };
  currency: string;
  totals: ReportTotals;
  previous: ReportTotals;
  series: { start: string; sales: string; orders: number }[];
  channels: { channel: string; messages_in: number; conversations: number; leads: number; orders: number; sales: string }[];
  lead_sources: { lead_source: string | null; orders: number; sales: string }[];
  orders_by_status: Record<string, number>;
  funnel: { conversations: number; leads: number; converted_conversations: number; orders: number; sales: string };
  snapshot: {
    open_orders: number;
    open_by_status: Record<string, { orders: number; value: string }>;
    outstanding: string;
    outstanding_orders: number;
    overdue: string;
    overdue_invoices: number;
    deliveries_open: number;
    deliveries_due_today: number;
    delivered_in_period: number;
  };
  buyers: { total: number; returning: number };
  leads: LeadStats;
};

const grouped = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const short = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/** Nepali counting for tight spaces: 89,000 → "89,000", 1,38,500 → "1.39 lakh", 2,50,00,000 → "2.5 crore". */
function lakhCrore(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1_00_00_000) return `${short.format(n / 1_00_00_000)} crore`;
  if (abs >= 1_00_000) return `${short.format(n / 1_00_000)} lakh`;
  return grouped.format(n);
}

/** Money for tiles and axes: "Rs. 89,000", "Rs. 1.39 lakh". */
export function compactMoney(value: string | number, currency: string): string {
  const prefix = currency === "NPR" ? "Rs." : currency;
  return `${prefix} ${lakhCrore(Number(value))}`;
}

export function compactNumber(value: number): string {
  return lakhCrore(value);
}

/** Change against the previous period, or null when there is nothing to compare with. */
export function change(current: string | number, previous: string | number): number | null {
  const now = Number(current);
  const before = Number(previous);
  if (before === 0) return null;
  return Math.round(((now - before) / before) * 100);
}
