"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Check, CheckCheck, Clock, Lock, Paperclip, SendHorizontal, ShoppingBag, UserRound } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useRef, useState } from "react";

import { useMe } from "@/components/tenant-shell";
import { Avatar, ChannelTag, EmptyState, Spinner, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import {
  clockTime,
  dayLabel,
  windowRemaining,
  type ConversationItem,
  type MessageItem,
  type MessagePage,
} from "@/lib/inbox";

function DeliveryStatus({ status }: { status: string }) {
  const map: Record<string, { icon: typeof Check; label: string; className?: string }> = {
    queued: { icon: Clock, label: "Sending" },
    sending: { icon: Clock, label: "Sending" },
    sent: { icon: Check, label: "Sent" },
    delivered: { icon: CheckCheck, label: "Delivered" },
    read: { icon: CheckCheck, label: "Read", className: "text-attention" },
    failed: { icon: AlertCircle, label: "Not sent" },
  };
  const entry = map[status] ?? map.sent;
  const Icon = entry.icon;
  return (
    <span className={cx("inline-flex items-center", entry.className)} title={entry.label}>
      <Icon className="size-3.5" aria-hidden />
      <span className="sr-only">{entry.label}</span>
    </span>
  );
}

function Bubble({ message, groupedWithPrevious }: { message: MessageItem; groupedWithPrevious: boolean }) {
  const mine = message.direction === "outbound";
  const failed = message.status === "failed";
  return (
    <li className={cx("flex", mine ? "justify-end" : "justify-start", groupedWithPrevious ? "mt-1" : "mt-3")}>
      <div className="max-w-[85%] sm:max-w-[68%]">
        <div
          className={cx(
            "rounded-bubble px-3.5 py-2",
            mine
              ? cx("bg-primary text-on-primary", !groupedWithPrevious && "rounded-tr-md", failed && "opacity-75")
              : cx("bg-surface text-ink ring-1 ring-line", !groupedWithPrevious && "rounded-tl-md"),
          )}
        >
          {message.body ? (
            <p className="text-base break-words whitespace-pre-wrap">{message.body}</p>
          ) : (
            <p className="italic opacity-80">Sent a {message.message_type}</p>
          )}
          {message.attachments.map((a) => (
            <p key={a.id} className="mt-1 flex items-center gap-1.5 text-sm opacity-90">
              <Paperclip className="size-4" aria-hidden />
              {a.filename ?? a.mime_type ?? "Attachment"}
              {a.caption && <span className="opacity-80">{a.caption}</span>}
            </p>
          ))}
          <p
            className={cx(
              "tabular mt-0.5 flex items-center justify-end gap-1 text-xs",
              mine ? "text-on-primary/75" : "text-ink-subtle",
            )}
          >
            {message.sender_type === "external_app" && <span>From phone app</span>}
            <time dateTime={message.timestamp}>{clockTime(message.timestamp)}</time>
            {mine && <DeliveryStatus status={message.status} />}
          </p>
        </div>
        {failed && (
          <p className="mt-1 flex items-start justify-end gap-1 text-right text-xs text-danger">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Not sent{message.error_message ? `: ${message.error_message}` : ""}
          </p>
        )}
      </div>
    </li>
  );
}

function Composer({ conversation }: { conversation: ConversationItem }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  // One key per message the agent is trying to send, reused if they retry after a network error.
  const keyRef = useRef<string>(crypto.randomUUID());
  const remaining = windowRemaining(conversation.window_closes_at);

  const send = useMutation({
    mutationFn: (body: string) =>
      api<MessageItem>(
        "tenant",
        "POST",
        `/api/v1/conversations/${conversation.id}/messages`,
        { text: body },
        { "Idempotency-Key": keyRef.current },
      ),
    onSuccess: () => {
      setText("");
      setError(null);
      keyRef.current = crypto.randomUUID();
      queryClient.invalidateQueries({ queryKey: ["messages", conversation.id] });
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : "Couldn't send. Check your connection and try again."),
  });

  if (!conversation.window_open || !remaining) {
    return (
      <div className="flex items-start gap-3 border-t border-line bg-surface px-4 py-3 text-sm text-ink-muted">
        <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
        <p>
          You can reply for 24 hours after the customer&apos;s last message. This chat will open again when they write to you.
        </p>
      </div>
    );
  }

  const submit = () => {
    if (text.trim() && !send.isPending) send.mutate(text.trim());
  };

  return (
    <form
      className="border-t border-line bg-surface px-3 pt-2 pb-3 sm:px-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {error && (
        <p role="alert" className="mb-2 flex items-center gap-1.5 text-sm text-danger">
          <AlertCircle className="size-4" aria-hidden />
          {error}
        </p>
      )}
      <div className="flex items-end gap-2">
        <label htmlFor="reply" className="sr-only">
          Write a reply
        </label>
        <textarea
          id="reply"
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          placeholder="Write a reply"
          maxLength={4096}
          className="max-h-40 min-h-11 flex-1 resize-none rounded-bubble border border-line-strong bg-paper px-4 py-2.5 text-base text-ink placeholder:text-ink-subtle focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
        />
        <button
          type="submit"
          disabled={send.isPending || !text.trim()}
          className="grid size-11 shrink-0 place-items-center rounded-full bg-primary text-on-primary transition-colors hover:bg-primary-hover disabled:opacity-40"
          aria-label="Send"
        >
          <SendHorizontal className="size-5" aria-hidden />
        </button>
      </div>
      <p className="mt-1.5 px-1 text-xs text-ink-subtle">
        You can reply for {remaining} more.
        <span className="hidden sm:inline"> Enter sends, Shift+Enter adds a line.</span>
      </p>
    </form>
  );
}

export function Thread() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const me = useMe();
  const canReply = me.data?.permissions.includes("conversation.write") ?? false;
  const canOrder = me.data?.permissions.includes("order.write") ?? false;

  const conversation = useQuery({
    queryKey: ["conversation", id],
    queryFn: () => api<ConversationItem>("tenant", "GET", `/api/v1/conversations/${id}`),
  });
  const messages = useInfiniteQuery({
    queryKey: ["messages", id],
    queryFn: ({ pageParam }) =>
      api<MessagePage>(
        "tenant",
        "GET",
        `/api/v1/conversations/${id}/messages?limit=50${pageParam ? `&cursor=${pageParam}` : ""}`,
      ),
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const unread = conversation.data?.unread_count ?? 0;
  useEffect(() => {
    if (unread > 0) {
      api("tenant", "POST", `/api/v1/conversations/${id}/read`)
        .then(() => queryClient.invalidateQueries({ queryKey: ["conversations"] }))
        .catch(() => undefined);
    }
  }, [id, unread, queryClient]);

  const bottom = useRef<HTMLDivElement>(null);
  const newestId = messages.data?.pages[0]?.items[0]?.id;
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "end" });
  }, [newestId]);

  if (conversation.error) {
    return (
      <section className="flex flex-1 items-center justify-center">
        <EmptyState icon={AlertCircle} title="This chat isn't available">
          It may have been removed, or you may not have access to it.
        </EmptyState>
      </section>
    );
  }
  if (!conversation.data) return <section className="flex-1"><Spinner /></section>;

  const c = conversation.data;
  // API returns newest first; show oldest at the top.
  const ordered = (messages.data?.pages.flatMap((p) => p.items) ?? []).slice().reverse();

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-paper" aria-label={`Chat with ${c.customer.display_name}`}>
      <header className="flex items-center gap-3 border-b border-line bg-surface px-3 py-2.5 sm:px-4">
        <Link href="/inbox" className="grid size-10 place-items-center rounded-control text-ink-muted md:hidden" aria-label="Back to inbox">
          <ArrowLeft className="size-5" aria-hidden />
        </Link>
        <Avatar name={c.customer.display_name} channel={c.provider} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-base font-semibold text-ink">{c.customer.display_name}</p>
          <ChannelTag channel={c.provider} />
        </div>
        {canOrder && (
          <Link
            href={`/orders/new?conversation=${c.id}`}
            className="inline-flex items-center gap-1.5 rounded-control bg-primary px-3 py-2 text-sm font-medium text-on-primary hover:bg-primary-hover"
          >
            <ShoppingBag className="size-4" aria-hidden />
            <span className="hidden sm:inline">Create order</span>
            <span className="sm:hidden">Order</span>
          </Link>
        )}
        <Link
          href={`/customers/${c.customer.id}`}
          className="inline-flex items-center gap-1.5 rounded-control border border-line px-3 py-2 text-sm text-ink-muted hover:border-line-strong hover:text-ink"
        >
          <UserRound className="size-4" aria-hidden />
          <span className="hidden sm:inline">Customer profile</span>
          <span className="sm:hidden">Profile</span>
        </Link>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-6">
        {messages.hasNextPage && (
          <button
            onClick={() => messages.fetchNextPage()}
            className="mx-auto mb-2 block rounded-full px-4 py-1.5 text-sm font-medium text-primary hover:bg-primary-soft"
          >
            Show earlier messages
          </button>
        )}
        <ol className="mx-auto max-w-3xl">
          {ordered.map((m, i) => {
            const previous = ordered[i - 1];
            const newDay = !previous || dayLabel(previous.timestamp) !== dayLabel(m.timestamp);
            const grouped =
              !newDay &&
              previous?.direction === m.direction &&
              new Date(m.timestamp).getTime() - new Date(previous.timestamp).getTime() < 5 * 60_000;
            return (
              <Fragment key={m.id}>
                {newDay && (
                  <li className="my-4 flex justify-center" role="separator">
                    <span className="rounded-full bg-sunken px-3 py-0.5 text-xs font-medium text-ink-muted">{dayLabel(m.timestamp)}</span>
                  </li>
                )}
                <Bubble message={m} groupedWithPrevious={grouped} />
              </Fragment>
            );
          })}
        </ol>
        <div ref={bottom} />
      </div>

      {canReply && <Composer conversation={c} />}
    </section>
  );
}
