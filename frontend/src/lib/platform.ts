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
