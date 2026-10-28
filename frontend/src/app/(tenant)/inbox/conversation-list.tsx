"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Inbox } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Avatar, EmptyState, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatTime, useInboxEvents, type ConversationPage } from "@/lib/inbox";

const VIEWS = [
  { key: "all", label: "All" },
  { key: "unread", label: "Waiting" },
  { key: "mine", label: "Mine" },
] as const;

const CHANNELS = [
  { key: "", label: "All channels" },
  { key: "whatsapp", label: "WhatsApp" },
  { key: "messenger", label: "Messenger" },
] as const;

const EMPTY: Record<string, { title: string; body: string }> = {
  all: { title: "No messages yet", body: "When customers message your WhatsApp or Facebook Page, their chats appear here." },
  unread: { title: "You're all caught up", body: "Nobody is waiting for a reply right now." },
  mine: { title: "Nothing assigned to you", body: "Chats assigned to you will appear here." },
};

export function ConversationList() {
  const params = useParams<{ id?: string }>();
  const [view, setView] = useState<(typeof VIEWS)[number]["key"]>("all");
  const [channel, setChannel] = useState<string>("");
  const live = useInboxEvents();

  const conversations = useInfiniteQuery({
    queryKey: ["conversations", view, channel],
    queryFn: ({ pageParam }) => {
      const query = new URLSearchParams({ view, limit: "30" });
      if (channel) query.set("provider", channel);
      if (pageParam) query.set("cursor", pageParam);
      return api<ConversationPage>("tenant", "GET", `/api/v1/conversations?${query}`);
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: live ? false : 15_000, // polling fallback when the event stream is down
  });
  const items = conversations.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <aside
      aria-label="Conversations"
      className={cx(
        "min-h-0 w-full flex-col border-line bg-surface md:w-80 md:border-r lg:w-96",
        params.id ? "hidden md:flex" : "flex",
      )}
    >
      <div className="border-b border-line px-4 pt-4 pb-3">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-ink">Inbox</h1>
          <span className={cx("flex items-center gap-1.5 text-xs", live ? "text-success" : "text-ink-subtle")}>
            <span className={cx("size-2 rounded-full", live ? "bg-success" : "bg-ink-subtle")} aria-hidden />
            {live ? "Live" : "Refreshing every 15s"}
          </span>
        </div>
        <div className="mt-3 grid grid-cols-3 rounded-control bg-sunken p-1" role="tablist" aria-label="Show">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              role="tab"
              aria-selected={view === v.key}
              onClick={() => setView(v.key)}
              className={cx(
                "rounded-[6px] py-1.5 text-sm font-medium transition-colors",
                view === v.key ? "bg-surface text-ink shadow-sm" : "text-ink-muted hover:text-ink",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        <div className="mt-2 flex gap-1.5 overflow-x-auto" aria-label="Channel">
          {CHANNELS.map((c) => (
            <button
              key={c.key}
              onClick={() => setChannel(c.key)}
              aria-pressed={channel === c.key}
              className={cx(
                "shrink-0 rounded-full border px-3 py-1 text-sm transition-colors",
                channel === c.key ? "border-primary bg-primary-soft text-primary" : "border-line text-ink-muted hover:border-line-strong",
              )}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {conversations.isPending &&
          Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="flex gap-3 px-4 py-3.5" aria-hidden>
              <span className="size-10 animate-pulse rounded-full bg-sunken" />
              <span className="flex-1 space-y-2 py-1">
                <span className="block h-3.5 w-1/2 animate-pulse rounded bg-sunken" />
                <span className="block h-3 w-4/5 animate-pulse rounded bg-sunken" />
              </span>
            </li>
          ))}
        {!conversations.isPending && items.length === 0 && (
          <li>
            <EmptyState icon={Inbox} title={EMPTY[view].title}>
              {EMPTY[view].body}
            </EmptyState>
          </li>
        )}
        {items.map((c) => {
          const selected = params.id === c.id;
          const waiting = c.unread_count > 0;
          return (
            <li key={c.id}>
              <Link
                href={`/inbox/${c.id}`}
                aria-current={selected ? "page" : undefined}
                className={cx(
                  "relative flex gap-3 px-4 py-3.5 transition-colors",
                  selected ? "bg-primary-soft" : "hover:bg-sunken/70",
                )}
              >
                {waiting && <span className="absolute inset-y-2 left-0 w-1 rounded-r-full bg-attention" aria-hidden />}
                <Avatar name={c.customer.display_name} channel={c.provider} />
                <span className="min-w-0 flex-1">
                  <span className="flex items-baseline justify-between gap-2">
                    <span className={cx("truncate text-base", waiting ? "font-semibold text-ink" : "text-ink")}>
                      {c.customer.display_name}
                    </span>
                    <span className={cx("tabular shrink-0 text-xs", waiting ? "font-semibold text-attention-ink" : "text-ink-subtle")}>
                      {formatTime(c.last_message_at)}
                    </span>
                  </span>
                  <span className="mt-0.5 flex items-center justify-between gap-2">
                    <span className={cx("truncate text-sm", waiting ? "text-ink" : "text-ink-muted")}>{c.last_message_preview}</span>
                    {waiting && (
                      <span className="tabular min-w-5 shrink-0 rounded-full bg-attention px-1.5 text-center text-xs leading-5 font-semibold text-on-attention">
                        <span className="sr-only">Unread messages: </span>
                        {c.unread_count}
                      </span>
                    )}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
        {conversations.hasNextPage && (
          <li className="p-3">
            <button
              onClick={() => conversations.fetchNextPage()}
              className="w-full rounded-control py-2 text-sm font-medium text-primary hover:bg-primary-soft"
            >
              Show older chats
            </button>
          </li>
        )}
      </ul>
    </aside>
  );
}
