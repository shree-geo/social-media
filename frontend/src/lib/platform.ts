export type Plan = {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
  prices: { id: string; billing_cycle: string; amount: string; currency: string; is_active: boolean }[];
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
