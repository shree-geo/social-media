"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type ConversationItem = {
  id: string;
  provider: "whatsapp" | "messenger";
  channel_account_id: string;
  channel_name: string | null;
  customer: { id: string; display_name: string };
  status: string;
  last_message_preview: string | null;
  last_message_at: string | null;
  unread_count: number;
  assigned_to_user_id: string | null;
  window_open: boolean;
  window_closes_at: string | null;
};

export type ConversationPage = { items: ConversationItem[]; next_cursor: string | null };

export type MessageItem = {
  id: string;
  direction: "inbound" | "outbound";
  sender_type: "customer" | "user" | "system" | "external_app";
  sender_user_id: string | null;
  message_type: string;
  body: string | null;
  status: string;
  error_code: string | null;
  error_message: string | null;
  timestamp: string;
  attachments: { id: string; mime_type: string | null; filename: string | null; caption: string | null }[];
};

export type MessagePage = { items: MessageItem[]; next_cursor: string | null };

export type Customer360 = {
  id: string;
  display_name: string;
  phone_e164: string | null;
  email: string | null;
  external_ref: string | null;
  status: string;
  first_seen_at: string;
  last_interaction_at: string | null;
  version: number;
  identities: { id: string; provider: string; profile_name: string | null; phone_e164: string | null; last_seen_at: string | null }[];
  addresses: { id: string; label: string | null; line1: string | null; area: string | null; city: string | null; is_default: boolean }[];
  notes: { id: string; body: string; created_at: string }[];
  conversations: { id: string; provider: string; last_message_at: string | null; last_message_preview: string | null }[];
  open_duplicates: number;
};

export type CustomerListItem = {
  id: string;
  display_name: string;
  phone_e164: string | null;
  email: string | null;
  channels: string[];
  last_interaction_at: string | null;
};

export const PROVIDER_LABEL: Record<string, string> = { whatsapp: "WhatsApp", messenger: "Messenger" };

/** Short relative time for lists: "now", "5m", "3h", "Yesterday", "12 Oct". */
export function formatTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(iso);
  const minutes = Math.round((Date.now() - date.getTime()) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  if (minutes < 12 * 60 && date.toDateString() === new Date().toDateString()) return `${Math.round(minutes / 60)}h`;
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString([], { day: "numeric", month: "short" });
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

/** Day heading in a thread: "Today", "Yesterday", or a date. */
export function dayLabel(iso: string): string {
  const date = new Date(iso);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(today.getDate() - 1);
  if (date.toDateString() === today.toDateString()) return "Today";
  if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
  return date.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" });
}

/** "21 hours" / "45 minutes" left in the reply window, or null when closed. */
export function windowRemaining(closesAt: string | null): string | null {
  if (!closesAt) return null;
  const minutes = Math.floor((new Date(closesAt).getTime() - Date.now()) / 60_000);
  if (minutes <= 0) return null;
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.floor(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"}`;
}

/**
 * Live inbox updates over server-sent events. Events only carry ids, so we just
 * invalidate queries and let the normal (authorized) endpoints refetch.
 * Returns whether the stream is connected; callers poll when it isn't.
 */
export function useInboxEvents(): boolean {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const source = new EventSource("/api/v1/events/stream", { withCredentials: true });
    const refresh = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as { conversation_id?: string };
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      if (data.conversation_id) {
        queryClient.invalidateQueries({ queryKey: ["messages", data.conversation_id] });
        queryClient.invalidateQueries({ queryKey: ["conversation", data.conversation_id] });
      }
    };
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false); // the browser reconnects on its own
    for (const type of ["message.created", "message.status", "conversation.updated"]) {
      source.addEventListener(type, refresh);
    }
    return () => source.close();
  }, [queryClient]);

  return connected;
}

/** "+9779812345678" → "+977 981-234 5678" (Nepali mobiles); other numbers unchanged. */
export function formatPhone(e164: string | null): string {
  if (!e164) return "";
  const nepal = /^\+977(9\d{2})(\d{3})(\d{4})$/.exec(e164);
  return nepal ? `+977 ${nepal[1]}-${nepal[2]} ${nepal[3]}` : e164;
}
