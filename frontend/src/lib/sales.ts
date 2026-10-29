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
  deliveries: Delivery[];
  payments: Payment[];
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

export type Person = { id: string; name: string };

export type OrderRef = {
  id: string;
  order_number: string;
  status: string;
  customer: Person;
  grand_total: string;
  amount_due: string;
  currency: string;
};

export type Delivery = {
  id: string;
  delivery_number: string;
  order: OrderRef;
  method: string;
  courier_name: string | null;
  tracking_reference: string | null;
  assigned_to: Person | null;
  delivery_address: Record<string, string> | null;
  contact_name: string | null;
  contact_phone: string | null;
  cod_amount: string;
  status: string;
  scheduled_date: string | null;
  delivered_at: string | null;
  notes: string | null;
  allowed_next: string[];
  history: { from_status: string | null; to_status: string; note: string | null; at: string }[];
  created_at: string;
};

export type Payment = {
  id: string;
  payment_number: string;
  order: OrderRef;
  delivery_id: string | null;
  type: "payment" | "refund";
  amount: string;
  currency: string;
  method: string;
  reference: string | null;
  paid_at: string;
  notes: string | null;
  status: "recorded" | "voided";
  void_reason: string | null;
  recorded_by: Person | null;
};

export const DELIVERY_METHOD_LABEL: Record<string, string> = {
  own_staff: "Our staff",
  courier: "Courier",
  customer_pickup: "Customer picks up",
};

export const DELIVERY_STATUS_LABEL: Record<string, string> = {
  PENDING: "Not assigned",
  ASSIGNED: "Assigned",
  PICKED_UP: "Picked up",
  OUT_FOR_DELIVERY: "On the way",
  DELIVERED: "Delivered",
  FAILED: "Failed",
  RETURNED: "Returned",
  CANCELLED: "Cancelled",
};

export const DELIVERY_TONE: Record<string, "neutral" | "primary" | "attention" | "success" | "danger"> = {
  PENDING: "attention",
  ASSIGNED: "primary",
  PICKED_UP: "primary",
  OUT_FOR_DELIVERY: "primary",
  DELIVERED: "success",
  FAILED: "danger",
  RETURNED: "danger",
  CANCELLED: "neutral",
};

/** Button wording for each next delivery status. */
export const DELIVERY_ACTION: Record<string, string> = {
  PICKED_UP: "Courier picked up",
  OUT_FOR_DELIVERY: "On the way",
  DELIVERED: "Delivered",
  FAILED: "Couldn't deliver",
  RETURNED: "Customer returned it",
  CANCELLED: "Cancel delivery",
};

export const DELIVERY_NEEDS_NOTE = new Set(["FAILED", "RETURNED", "CANCELLED"]);

export const PAYMENT_METHOD_LABEL: Record<string, string> = {
  cash: "Cash",
  cod: "Cash on delivery",
  esewa: "eSewa",
  khalti: "Khalti",
  fonepay: "Fonepay / QR",
  bank_transfer: "Bank transfer",
  cheque: "Cheque",
  other: "Other",
};

export function addressText(address: Record<string, string> | null | undefined): string {
  return address ? Object.values(address).filter(Boolean).join(", ") : "";
}
