import { useSyncExternalStore } from "react";

import type { Pill } from "@/components/ui";

export type LeadStage = "NEW" | "CONTACTED" | "INTERESTED" | "NEGOTIATING" | "WON" | "LOST";

export const OPEN_STAGES: LeadStage[] = ["NEW", "CONTACTED", "INTERESTED", "NEGOTIATING"];
export const ALL_STAGES: LeadStage[] = [...OPEN_STAGES, "WON", "LOST"];

export const STAGE_LABEL: Record<string, string> = {
  NEW: "New",
  CONTACTED: "Contacted",
  INTERESTED: "Interested",
  NEGOTIATING: "Negotiating",
  WON: "Won",
  LOST: "Lost",
};

export const STAGE_HINT: Record<string, string> = {
  NEW: "Just came in",
  CONTACTED: "We replied or called",
  INTERESTED: "Wants it, asking details",
  NEGOTIATING: "Talking price or delivery",
  WON: "Became an order",
  LOST: "Didn't buy",
};

export const STAGE_TONE: Record<string, Parameters<typeof Pill>[0]["tone"]> = {
  NEW: "primary",
  CONTACTED: "neutral",
  INTERESTED: "attention",
  NEGOTIATING: "attention",
  WON: "success",
  LOST: "danger",
};

export const LOST_REASON_LABEL: Record<string, string> = {
  price: "Price too high",
  out_of_stock: "Out of stock",
  no_reply: "Stopped replying",
  bought_elsewhere: "Bought elsewhere",
  delivery_area: "We don't deliver there",
  not_serious: "Just asking",
  other: "Other",
};

export const LABEL_TEXT: Record<string, string> = { lead: "Lead", support: "Support", spam: "Spam" };

export type Person = { id: string; full_name: string };

export type LeadSummary = {
  id: string;
  lead_number: string;
  stage: LeadStage;
  customer: { id: string; display_name: string };
  conversation_id: string | null;
  source_channel: string;
  lead_source: string | null;
  assigned_to: Person | null;
  expected_value: string;
  currency: string;
  item_summary: string;
  next_followup_at: string | null;
  followup_note: string | null;
  lost_reason: string | null;
  won_order: { id: string; order_number: string | null } | null;
  created_at: string;
  last_activity_at: string;
  version: number;
};

export type LeadItem = { id: string; variant_id: string | null; description: string; quantity: string; unit_price: string };

export type LeadActivity = {
  id: string;
  event: "created" | "stage_changed" | "assigned" | "note" | "followup_set" | "items_changed" | "converted" | "lost" | "reopened";
  from_value: string | null;
  to_value: string | null;
  body: string | null;
  actor: Person | null;
  created_at: string;
};

export type Lead = LeadSummary & {
  items: LeadItem[];
  activities: LeadActivity[];
  lost_note: string | null;
  closed_at: string | null;
  created_by: Person | null;
};

export type LeadPage = { items: LeadSummary[]; next_cursor: string | null };
export type StaffMember = { user_id: string; full_name: string; roles: string[] };

export type OpenLeadRef = {
  id: string;
  lead_number: string;
  stage: LeadStage;
  assigned_to_user_id: string | null;
  next_followup_at: string | null;
};

export function isOpen(stage: string): boolean {
  return (OPEN_STAGES as string[]).includes(stage);
}

/** "Today 4:30 PM", "Tomorrow 10:00 AM", "Fri 2:00 PM", "12 Nov", plus whether it's overdue. */
export function followupText(iso: string | null): { text: string; overdue: boolean; today: boolean } | null {
  if (!iso) return null;
  const at = new Date(iso);
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayDiff = Math.round((new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime() - startOfToday.getTime()) / 86_400_000);
  const time = at.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  let text: string;
  if (dayDiff === 0) text = `Today ${time}`;
  else if (dayDiff === 1) text = `Tomorrow ${time}`;
  else if (dayDiff === -1) text = `Yesterday ${time}`;
  else if (dayDiff > 1 && dayDiff < 7) text = `${at.toLocaleDateString([], { weekday: "short" })} ${time}`;
  else text = at.toLocaleDateString([], { day: "numeric", month: "short" });
  return { text, overdue: at.getTime() < now.getTime(), today: dayDiff === 0 };
}

/** Quick follow-up choices, as ISO strings computed from "now" in the browser's timezone. */
export function followupPresets(now = new Date()): { label: string; value: string }[] {
  const at = (days: number, hour: number) => {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() + days, hour, 0, 0);
    return d.toISOString();
  };
  const presets: { label: string; value: string }[] = [];
  if (now.getHours() < 17) presets.push({ label: "This evening", value: at(0, 18) });
  presets.push({ label: "Tomorrow", value: at(1, 10) });
  presets.push({ label: "In 3 days", value: at(3, 10) });
  presets.push({ label: "Next week", value: at(7, 10) });
  return presets;
}

/** ISO → value for <input type="datetime-local"> in the browser's timezone. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

const noop = () => () => undefined;

/**
 * False during server rendering and hydration, true afterwards. Pages inside a Suspense
 * boundary hydrate after the account has loaded, so permission-dependent controls wait for this
 * to keep the first client render identical to the server's.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}
