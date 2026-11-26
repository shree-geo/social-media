"use client";

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  CalendarClock,
  Check,
  CheckCheck,
  Clock,
  Lock,
  MapPin,
  Package,
  Paperclip,
  SendHorizontal,
  ShoppingBag,
  Target,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Fragment, useEffect, useRef, useState } from "react";

import { Modal } from "@/components/fulfilment";
import { StageSelect, useLeadRefresh } from "@/components/lead-actions";
import { LeadSheet } from "@/components/lead-sheet";
import { ProductPicker } from "@/components/pickers";
import { useMe } from "@/components/tenant-shell";
import { Avatar, Button, ChannelTag, EmptyState, Pill, Spinner, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { bsDate } from "@/lib/dates";
import {
  clockTime,
  dayLabel,
  formatPhone,
  windowRemaining,
  type ConversationItem,
  type Customer360,
  type MessageItem,
  type MessagePage,
} from "@/lib/inbox";
import { LABEL_TEXT, STAGE_LABEL, STAGE_TONE, followupText, type Lead } from "@/lib/leads";
import { STATUS_LABEL, STATUS_TONE, formatMoney, type Product, type Variant } from "@/lib/sales";

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

function Bubble({
  message,
  groupedWithPrevious,
  onMakeLead,
}: {
  message: MessageItem;
  groupedWithPrevious: boolean;
  onMakeLead?: (text: string) => void;
}) {
  const mine = message.direction === "outbound";
  const failed = message.status === "failed";
  return (
    <li className={cx("group flex", mine ? "justify-end" : "justify-start", groupedWithPrevious ? "mt-1" : "mt-3")}>
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
        {onMakeLead && !mine && message.body && (
          <button
            type="button"
            onClick={() => onMakeLead(message.body ?? "")}
            className="mt-1 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100 hover:bg-primary-soft focus-visible:opacity-100 [@media(hover:none)]:hidden"
          >
            <Target className="size-3.5" aria-hidden />
            Add to lead
          </button>
        )}
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

const ASK_ADDRESS = "Could you send your delivery address, or share your location pin here?";
const THANKS = "Dhanyabad! Your order is confirmed. We'll message you when it's on the way.";

function productText(p: Product, v: Variant): string {
  const name = p.variants.length > 1 ? `${p.name} (${v.name})` : p.name;
  const price = v.price ? `: ${formatMoney(v.price, "NPR")}` : "";
  const stock = v.stock !== null && Number(v.stock) <= 0 ? " (out of stock right now)" : "";
  return [`${name}${price}${stock}`, p.description, p.website_url].filter(Boolean).join("\n");
}

function lastWrote(closesAt: string | null): string {
  if (!closesAt) return "more than a day ago";
  const hours = Math.round((Date.now() - (new Date(closesAt).getTime() - 24 * 3_600_000)) / 3_600_000);
  if (hours < 48) return `${hours} hours ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function Composer({ conversation, orderHref }: { conversation: ConversationItem; orderHref: string | null }) {
  const queryClient = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  // One key per message the agent is trying to send, reused if they retry after a network error.
  const keyRef = useRef<string>(crypto.randomUUID());
  const remaining = windowRemaining(conversation.window_closes_at);
  const [picking, setPicking] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const insert = (snippet: string) => {
    setText((t) => (t.trim() ? `${t.trimEnd()}\n${snippet}` : snippet));
    requestAnimationFrame(() => box.current?.focus());
  };

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
      <div className="flex items-start gap-3 border-t border-line bg-attention-soft px-4 py-3 text-sm text-attention-ink">
        <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
        <p>
          <strong className="font-semibold">Reply window closed.</strong> {conversation.customer.display_name.split(" ")[0]} last wrote{" "}
          {lastWrote(conversation.window_closes_at)}. WhatsApp and Messenger allow replies for 24 hours after a customer&apos;s message, so you
          can reply again as soon as they write.
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
      <div className="-mx-1 mb-2 flex gap-1.5 overflow-x-auto px-1 pb-0.5" aria-label="Quick replies">
        <QuickChip icon={Package} onClick={() => setPicking(true)}>
          Send product
        </QuickChip>
        <QuickChip icon={MapPin} onClick={() => insert(ASK_ADDRESS)}>
          Ask for address
        </QuickChip>
        {orderHref && (
          <Link
            href={orderHref}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1 text-sm font-medium whitespace-nowrap text-primary hover:bg-primary hover:text-on-primary"
          >
            <ShoppingBag className="size-3.5" aria-hidden />
            Create order
          </Link>
        )}
        <QuickChip icon={Check} onClick={() => insert(THANKS)}>
          Order confirmed
        </QuickChip>
      </div>
      <div className="flex items-end gap-2">
        <label htmlFor="reply" className="sr-only">
          Write a reply
        </label>
        <textarea
          ref={box}
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
      {picking && (
        <Modal title="Send a product" onClose={() => setPicking(false)}>
          <p className="mb-3 text-sm text-ink-muted">Adds the name, price and link to your reply. You can edit it before sending.</p>
          <ProductPicker
            onPick={(p, v) => {
              insert(productText(p, v));
              setPicking(false);
            }}
          />
        </Modal>
      )}
    </form>
  );
}

function QuickChip({ icon: Icon, onClick, children }: { icon: typeof Check; onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-primary-soft px-3 py-1 text-sm font-medium whitespace-nowrap text-primary hover:bg-primary hover:text-on-primary"
    >
      <Icon className="size-3.5" aria-hidden />
      {children}
    </button>
  );
}

/** The chat's open lead: stage, owner, follow-up, and the way to an order. */
function LeadStrip({ leadId, canWrite, canOrder }: { leadId: string; canWrite: boolean; canOrder: boolean }) {
  const lead = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => api<Lead>("tenant", "GET", `/api/v1/leads/${leadId}`),
  });
  if (!lead.data) return <div className="h-12 border-b border-line bg-primary-soft/40" aria-hidden />;
  const l = lead.data;
  const due = followupText(l.next_followup_at);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line bg-primary-soft/40 px-3 py-2 sm:px-4">
      <Link href={`/leads/${l.id}`} className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary hover:underline">
        <Target className="size-4" aria-hidden />
        {l.lead_number}
      </Link>
      {canWrite ? <StageSelect lead={l} /> : <Pill tone="primary">{l.stage}</Pill>}
      <span className="min-w-0 truncate text-sm text-ink-muted">
        {l.item_summary || (
          <Link href={`/leads/${l.id}`} className="text-primary hover:underline">
            Add products
          </Link>
        )}
        {Number(l.expected_value) > 0 && <span className="tabular"> · {formatMoney(l.expected_value, l.currency)}</span>}
      </span>
      <span className="text-sm text-ink-muted">{l.assigned_to ? l.assigned_to.full_name : "No owner"}</span>
      {due && (
        <span className={cx("inline-flex items-center gap-1 text-sm", due.overdue ? "font-semibold text-danger" : "text-ink-muted")}>
          <CalendarClock className="size-4" aria-hidden />
          {due.text}
        </span>
      )}
      {canOrder && (
        <Link
          href={`/orders/new?lead=${l.id}`}
          className="ml-auto inline-flex items-center gap-1.5 rounded-control bg-primary px-3 py-1.5 text-sm font-medium text-on-primary hover:bg-primary-hover"
        >
          <ShoppingBag className="size-4" aria-hidden />
          Convert to order
        </Link>
      )}
    </div>
  );
}

/** Who you're talking to, beside the chat on wide screens: spend, money owed, open lead, latest note. */
function CustomerPanel({ customerId, openLeadId, canOrder }: { customerId: string; openLeadId: string | null; canOrder: boolean }) {
  const customer = useQuery({
    queryKey: ["customer", customerId],
    queryFn: () => api<Customer360>("tenant", "GET", `/api/v1/customers/${customerId}`),
  });
  const lead = useQuery({
    queryKey: ["lead", openLeadId],
    queryFn: () => api<Lead>("tenant", "GET", `/api/v1/leads/${openLeadId}`),
    enabled: !!openLeadId,
  });
  const c = customer.data;
  const owed = Number(c?.sales.outstanding ?? 0);
  const place = c?.addresses.find((a) => a.is_default) ?? c?.addresses[0];
  const l = openLeadId ? lead.data : undefined;
  const due = l ? followupText(l.next_followup_at) : null;
  return (
    <aside className="hidden w-72 shrink-0 flex-col gap-5 overflow-y-auto border-l border-line bg-surface p-4 xl:flex" aria-label="Customer">
      {!c ? (
        <Spinner />
      ) : (
        <>
          <div>
            <p className="text-base font-semibold text-ink">{c.display_name}</p>
            <p className="text-sm text-ink-muted">
              {[formatPhone(c.phone_e164), place ? [place.area, place.city].filter(Boolean).join(", ") : null].filter(Boolean).join(". ") ||
                "No phone or address yet"}
            </p>
            <p className="text-xs text-ink-subtle">Customer since {bsDate(c.first_seen_at)}</p>
          </div>
          <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-ink-muted">Orders</dt>
            <dd className="tabular text-right font-semibold text-ink">{c.sales.orders}</dd>
            <dt className="text-ink-muted">Bought</dt>
            <dd className="tabular text-right font-semibold text-ink">{formatMoney(c.sales.total_sales, "NPR")}</dd>
            <dt className="text-ink-muted">To collect</dt>
            <dd className={cx("tabular text-right font-semibold", owed > 0 ? "text-attention-ink" : "text-ink")}>{formatMoney(owed, "NPR")}</dd>
          </dl>
          {l && (
            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-ink-muted">Open lead</h3>
              <div className="grid gap-2 rounded-panel border border-line p-3">
                <div className="flex items-center justify-between gap-2">
                  <Link href={`/leads/${l.id}`} className="truncate text-sm font-semibold text-ink hover:text-primary">
                    {l.item_summary || l.lead_number}
                  </Link>
                  <Pill tone={STAGE_TONE[l.stage]}>{STAGE_LABEL[l.stage]}</Pill>
                </div>
                <p className="flex justify-between gap-2 text-xs text-ink-muted">
                  <span className="tabular">{Number(l.expected_value) > 0 ? formatMoney(l.expected_value, l.currency) : "No value yet"}</span>
                  {due && <span className={due.overdue ? "font-semibold text-danger" : undefined}>Follow up {due.text}</span>}
                </p>
                {canOrder && (
                  <Link
                    href={`/orders/new?lead=${l.id}`}
                    className="inline-flex items-center justify-center gap-1.5 rounded-control bg-primary px-3 py-1.5 text-sm font-medium text-on-primary hover:bg-primary-hover"
                  >
                    <ShoppingBag className="size-4" aria-hidden />
                    Create order
                  </Link>
                )}
              </div>
            </section>
          )}
          {c.orders.length > 0 && (
            <section>
              <h3 className="mb-1.5 text-xs font-semibold text-ink-muted">Recent orders</h3>
              <ul className="grid gap-1">
                {c.orders.slice(0, 3).map((o) => (
                  <li key={o.id}>
                    <Link href={`/orders/${o.id}`} className="flex items-center justify-between gap-2 rounded-control px-2 py-1.5 text-sm hover:bg-sunken">
                      <Pill tone={STATUS_TONE[o.status]}>{STATUS_LABEL[o.status] ?? o.status}</Pill>
                      <span className="tabular text-ink">{formatMoney(o.grand_total, "NPR")}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <section>
            <h3 className="mb-1.5 text-xs font-semibold text-ink-muted">Team note</h3>
            {c.notes[0] ? (
              <p className="rounded-control bg-attention-soft px-3 py-2 text-sm text-attention-ink">{c.notes[0].body}</p>
            ) : (
              <p className="text-sm text-ink-subtle">No notes yet.</p>
            )}
          </section>
          <Link href={`/customers/${c.id}`} className="mt-auto inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
            <UserRound className="size-4" aria-hidden />
            Full customer profile
          </Link>
        </>
      )}
    </aside>
  );
}

const SORTS = [
  { key: "lead", label: "Lead" },
  { key: "support", label: "Support" },
  { key: "spam", label: "Spam" },
] as const;

/** Say what this chat is in one tap; tap the current choice again to clear it. */
function SortControl({ conversation }: { conversation: ConversationItem }) {
  const refresh = useLeadRefresh();
  const queryClient = useQueryClient();
  const classify = useMutation({
    mutationFn: (label: string | null) =>
      api<ConversationItem>("tenant", "POST", `/api/v1/conversations/${conversation.id}/classify`, { label }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["conversation", conversation.id], updated);
      refresh();
    },
  });
  const current = conversation.open_lead ? "lead" : conversation.classification;
  return (
    <div className="flex items-center gap-2">
      <div className="inline-flex overflow-hidden rounded-control border border-line-strong" role="group" aria-label="Sort this chat">
        {SORTS.map((o, i) => {
          const on = current === o.key;
          return (
            <button
              key={o.key}
              type="button"
              aria-pressed={on}
              disabled={classify.isPending || (o.key !== "lead" && !!conversation.open_lead)}
              onClick={() => classify.mutate(on ? null : o.key)}
              title={on ? `Marked as ${LABEL_TEXT[o.key]}. Tap again to clear.` : `Mark as ${LABEL_TEXT[o.key]}`}
              className={cx(
                "px-2.5 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed sm:px-3 sm:text-sm",
                i > 0 && "border-l border-line-strong",
                on ? "bg-stage-confirmed-soft text-stage-confirmed" : "text-ink-muted hover:bg-sunken hover:text-ink",
              )}
            >
              {o.label}
            </button>
          );
        })}
      </div>
      {classify.error && <span className="text-sm text-danger">{classify.error instanceof ApiError ? classify.error.message : "Couldn't save."}</span>}
    </div>
  );
}

export function Thread() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const me = useMe();
  const canReply = me.data?.permissions.includes("conversation.write") ?? false;
  const canOrder = me.data?.permissions.includes("order.write") ?? false;
  const canLead = me.data?.permissions.includes("lead.write") ?? false;
  const canReadLeads = me.data?.permissions.includes("lead.read") ?? false;
  // With the business rule on, a chat order is always converted from its lead.
  const directOrders = !(me.data?.orders_need_lead ?? true);
  const [leadSheet, setLeadSheet] = useState<{ note?: string } | null>(null);

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
    <div className="flex min-h-0 min-w-0 flex-1">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col bg-paper" aria-label={`Chat with ${c.customer.display_name}`}>
        <header className="flex items-center gap-3 border-b border-line bg-surface px-3 py-2.5 sm:px-4">
          <Link href="/inbox" className="grid size-10 place-items-center rounded-control text-ink-muted md:hidden" aria-label="Back to inbox">
            <ArrowLeft className="size-5" aria-hidden />
          </Link>
          <Link href={`/customers/${c.customer.id}`} className="flex min-w-0 flex-1 items-center gap-3 rounded-control" title="Customer profile">
            <Avatar name={c.customer.display_name} channel={c.provider} />
            <span className="min-w-0">
              <span className="block truncate text-base font-semibold text-ink">{c.customer.display_name}</span>
              <ChannelTag channel={c.provider} />
            </span>
          </Link>
          {canLead && (!c.open_lead || canReadLeads) && <SortControl conversation={c} />}
          {canLead && !c.open_lead && c.classification === "lead" && (
            <Button size="sm" icon={Target} onClick={() => setLeadSheet({})}>
              <span className="hidden sm:inline">Create lead</span>
              <span className="sr-only sm:hidden">Create lead</span>
            </Button>
          )}
          <Link
            href={`/customers/${c.customer.id}`}
            className="hidden items-center gap-1.5 rounded-control border border-line px-3 py-2 text-sm text-ink-muted hover:border-line-strong hover:text-ink lg:inline-flex xl:hidden"
          >
            <UserRound className="size-4" aria-hidden />
            Profile
          </Link>
        </header>
        {c.open_lead && canReadLeads && <LeadStrip leadId={c.open_lead.id} canWrite={canLead} canOrder={canOrder} />}

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
                  <Bubble
                    message={m}
                    groupedWithPrevious={grouped}
                    onMakeLead={canLead && !c.open_lead ? (text) => setLeadSheet({ note: text }) : undefined}
                  />
                </Fragment>
              );
            })}
          </ol>
          <div ref={bottom} />
        </div>

        {canReply && (
          <Composer
            conversation={c}
            orderHref={
              !canOrder ? null : c.open_lead ? `/orders/new?lead=${c.open_lead.id}` : directOrders ? `/orders/new?conversation=${c.id}` : null
            }
          />
        )}
        {leadSheet && (
          <LeadSheet
            conversationId={c.id}
            customer={c.customer}
            chatAssigneeId={c.assigned_to_user_id}
            initialNote={leadSheet.note}
            onClose={() => setLeadSheet(null)}
            onCreated={() => {
              void queryClient.invalidateQueries({ queryKey: ["conversation", c.id] });
              void queryClient.invalidateQueries({ queryKey: ["conversations"] });
              void queryClient.invalidateQueries({ queryKey: ["leads"] });
            }}
          />
        )}
      </section>
      <CustomerPanel customerId={c.customer.id} openLeadId={canReadLeads ? (c.open_lead?.id ?? null) : null} canOrder={canOrder} />
    </div>
  );
}
