export type Variant = {
  id: string;
  sku: string;
  name: string;
  is_default: boolean;
  is_active: boolean;
  price: string | null;
  stock: string | null;
  low_stock_threshold: string | null;
};

export type Product = {
  id: string;
  name: string;
  description: string | null;
  unit: string;
  tax_rate_id: string | null;
  tax_rate: string | null;
  track_inventory: boolean;
  is_active: boolean;
  variants: Variant[];
  updated_at: string;
};

export type TaxRate = { id: string; name: string; rate: string; is_default: boolean };

export type Totals = {
  currency: string;
  subtotal: string;
  discount_total: string;
  tax_total: string;
  shipping_fee: string;
  grand_total: string;
  amount_paid: string;
  amount_due: string;
  payment_status: string;
};

export type Line = {
  id: string;
  variant_id: string | null;
  description: string;
  sku: string | null;
  unit: string;
  quantity: string;
  unit_price: string;
  discount_amount: string;
  tax_rate: string;
  tax_amount: string;
  line_total: string;
};

export type OrderSummary = {
  id: string;
  order_number: string;
  status: string;
  customer: { id: string; display_name: string };
  source_channel: string;
  lead_source: string | null;
  grand_total: string;
  currency: string;
  payment_status: string;
  created_at: string;
};

export type InvoiceSummary = {
  id: string;
  invoice_number: string | null;
  status: string;
  issue_date: string | null;
  grand_total: string;
};

export type Order = OrderSummary & {
  totals: Totals;
  lines: Line[];
  delivery_address: Record<string, string> | null;
  notes: string | null;
  source_conversation_id: string | null;
  history: { from_status: string | null; to_status: string; reason: string | null; at: string }[];
  invoices: InvoiceSummary[];
  allowed_next: string[];
  version: number;
};

/** 1234567.5 → "12,34,567.50" (South Asian grouping, as on our invoices). */
export function formatMoney(value: string | number | null | undefined, currency?: string): string {
  if (value === null || value === undefined || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  const text = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(n);
  return currency ? `${currency === "NPR" ? "Rs." : currency} ${text}` : text;
}

export function formatQty(value: string | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(Number(value));
}

export const STATUS_LABEL: Record<string, string> = {
  NEW: "New",
  CONFIRMED: "Confirmed",
  PROCESSING: "Processing",
  READY_FOR_DELIVERY: "Ready for delivery",
  OUT_FOR_DELIVERY: "Out for delivery",
  DELIVERED: "Delivered",
  CANCELLED: "Cancelled",
  REJECTED: "Rejected",
  RETURNED: "Returned",
};

export const STATUS_TONE: Record<string, "neutral" | "primary" | "attention" | "success" | "danger"> = {
  NEW: "attention",
  CONFIRMED: "primary",
  PROCESSING: "primary",
  READY_FOR_DELIVERY: "primary",
  OUT_FOR_DELIVERY: "primary",
  DELIVERED: "success",
  CANCELLED: "neutral",
  REJECTED: "neutral",
  RETURNED: "danger",
};

/** Button wording for each next status (verbs, not states). */
export const STATUS_ACTION: Record<string, string> = {
  CONFIRMED: "Confirm order",
  PROCESSING: "Start preparing",
  READY_FOR_DELIVERY: "Mark ready for delivery",
  OUT_FOR_DELIVERY: "Mark out for delivery",
  DELIVERED: "Mark delivered",
  CANCELLED: "Cancel order",
  REJECTED: "Reject order",
  RETURNED: "Mark returned",
};

export const NEEDS_REASON = new Set(["CANCELLED", "REJECTED", "RETURNED"]);

export const SOURCE_LABEL: Record<string, string> = {
  whatsapp: "WhatsApp",
  messenger: "Messenger",
  phone: "Phone call",
  walk_in: "Walk-in",
  other: "Other",
};

export const LEAD_LABEL: Record<string, string> = {
  tiktok: "TikTok",
  facebook_post: "Facebook post",
  instagram: "Instagram",
  referral: "Someone referred them",
  walk_in: "Saw the shop",
  other: "Other",
};

export const PAYMENT_LABEL: Record<string, string> = {
  UNPAID: "Unpaid",
  PARTIAL: "Part paid",
  PAID: "Paid",
  REFUNDED: "Refunded",
};
