export type Plan = {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
  prices: { id: string; billing_cycle: string; amount: string; currency: string; is_active: boolean }[];
  features: { feature_key: string; limit_value: number | null; enabled: boolean }[];
};

export const CYCLE_LABEL: Record<string, string> = {
  monthly: "Monthly",
  quarterly: "Every 3 months",
  half_yearly: "Every 6 months",
  yearly: "Yearly",
};

/** Package limits the backend enforces (backend/app/services/entitlements.py). No row or no number = unlimited. */
export const LIMIT_LABEL: Record<string, string> = {
  max_users: "Staff logins",
  max_products: "Products",
  max_monthly_orders: "Orders per month",
  max_messenger_pages: "Facebook Pages",
  max_whatsapp_numbers: "WhatsApp numbers",
};

export type TenantListItem = {
  tenant_id: string;
  business_name: string;
  status: string;
  plan_code: string | null;
  subscription_status: string | null;
  expiry_date: string | null;
  days_remaining: number | null;
  created_at: string;
};

export type TenantCreated = {
  tenant_id: string;
  business_name: string;
  receipt_number: string | null;
  subscription: { status: string; start_date: string; expiry_date: string; billing_cycle: string; price_amount: string };
  owner_login: import("./api").LoginDetails;
};

export type SubscriptionDetail = {
  id: string;
  plan_id: string;
  plan_name: string;
  plan_code: string;
  status: string;
  effective_status: string;
  billing_cycle: string;
  price_amount: string;
  discount_amount: string;
  currency: string;
  start_date: string;
  expiry_date: string;
  trial_ends_at: string | null;
  grace_period_days: number;
  days_remaining: number;
};

export type SubscriptionPayment = {
  id: string;
  receipt_number: string;
  amount: string;
  currency: string;
  payment_method: string;
  transaction_reference: string | null;
  paid_at: string;
  period_start: string;
  period_end: string;
  notes: string | null;
  voided_at: string | null;
};

export type SubscriptionEvent = {
  id: string;
  event_type: "created" | "renewed" | "plan_changed" | "status_changed" | "dates_changed";
  from_status: string | null;
  to_status: string | null;
  from_plan_name: string | null;
  to_plan_name: string | null;
  from_expiry_date: string | null;
  to_expiry_date: string | null;
  reason: string | null;
  actor_type: "platform_user" | "system";
  created_at: string;
};

export type TenantDetail = {
  tenant_id: string;
  business_name: string;
  legal_name: string | null;
  email: string | null;
  phone: string | null;
  address: Record<string, string> | null;
  tax_number: string | null;
  vat_registered: boolean;
  timezone: string;
  status: string;
  created_at: string;
  owner: { full_name: string; email: string; phone: string | null } | null;
  subscription: SubscriptionDetail | null;
  payments: SubscriptionPayment[];
  history: SubscriptionEvent[];
};

export const CYCLE_MONTHS: Record<string, number> = { monthly: 1, quarterly: 3, half_yearly: 6, yearly: 12 };

export const SUBSCRIPTION_PAYMENT_METHODS: [string, string][] = [
  ["esewa", "eSewa"],
  ["khalti", "Khalti"],
  ["fonepay", "Fonepay"],
  ["bank_transfer", "Bank transfer"],
  ["cash", "Cash"],
  ["cheque", "Cheque"],
  ["other", "Other"],
];
