"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, Mail, MessagesSquare, Phone, Plus, ShoppingBag, StickyNote } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { useMe } from "@/components/tenant-shell";
import { Alert, Avatar, Button, ChannelTag, EmptyState, Panel, Pill, Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatPhone, formatTime, type Customer360 } from "@/lib/inbox";
import { PAYMENT_LABEL, STATUS_LABEL, STATUS_TONE, formatMoney } from "@/lib/sales";

function longDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function CustomerProfile() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const customer = useQuery({
    queryKey: ["customer", id],
    queryFn: () => api<Customer360>("tenant", "GET", `/api/v1/customers/${id}`),
  });
  const addNote = useMutation({
    mutationFn: (body: string) => api("tenant", "POST", `/api/v1/customers/${id}/notes`, { body }),
    onSuccess: () => {
      setNote("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["customer", id] });
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Couldn't save the note."),
  });

  if (customer.error) {
    return (
      <main className="flex flex-1 items-center justify-center">
        <EmptyState icon={AlertCircle} title="This customer isn't available">
          They may have been merged into another customer record.
        </EmptyState>
      </main>
    );
  }
  if (!customer.data) return <Spinner />;
  const c = customer.data;
  const canWrite = me.data?.permissions.includes("customer.write") ?? false;
  const canOrder = me.data?.permissions.includes("order.write") ?? false;
  const channels = [...new Set(c.identities.map((i) => i.provider))];

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href="/customers" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Customers
      </Link>

      <header className="mb-6 flex flex-wrap items-center gap-4">
        <Avatar name={c.display_name} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-2xl font-semibold text-ink">{c.display_name}</h1>
          <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-ink-muted">
            {c.phone_e164 && (
              <a href={`tel:${c.phone_e164}`} className="tabular inline-flex items-center gap-1.5 hover:text-ink">
                <Phone className="size-4" aria-hidden />
                {formatPhone(c.phone_e164)}
              </a>
            )}
            {c.email && (
              <a href={`mailto:${c.email}`} className="inline-flex items-center gap-1.5 hover:text-ink">
                <Mail className="size-4" aria-hidden />
                {c.email}
              </a>
            )}
            {channels.map((ch) => (
              <ChannelTag key={ch} channel={ch} />
            ))}
          </div>
          <p className="mt-1 text-sm text-ink-subtle">Customer since {longDate(c.first_seen_at)}</p>
        </div>
        {c.conversations[0] && (
          <Link
            href={`/inbox/${c.conversations[0].id}`}
            className="inline-flex min-h-11 items-center gap-2 rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover"
          >
            <MessagesSquare className="size-4" aria-hidden />
            Open chat
          </Link>
        )}
      </header>

      {c.open_duplicates > 0 && (
        <Alert tone="warning" title="This customer may be listed twice">
          Review it on the <Link href="/customers" className="font-medium underline">Customers</Link> page to keep one record.
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="grid content-start gap-6">
          <Panel
            title="Orders"
            actions={
              canOrder && (
                <Link
                  href={`/orders/new?${c.conversations[0] ? `conversation=${c.conversations[0].id}` : `customer=${c.id}`}`}
                  className="inline-flex min-h-9 items-center gap-1.5 rounded-control border border-line-strong px-3 text-sm font-medium text-ink hover:bg-sunken"
                >
                  <Plus className="size-4" aria-hidden />
                  New order
                </Link>
              )
            }
          >
            {c.sales.orders === 0 ? (
              <div className="flex items-start gap-3 text-sm text-ink-muted">
                <ShoppingBag className="mt-0.5 size-5 shrink-0 text-ink-subtle" aria-hidden />
                <p>No orders from {c.display_name.split(" ")[0]} yet.</p>
              </div>
            ) : (
              <>
                <dl className="mb-4 grid grid-cols-3 gap-3 text-center">
                  <div className="rounded-control bg-sunken px-2 py-3">
                    <dt className="text-xs text-ink-muted">Orders</dt>
                    <dd className="tabular text-lg font-semibold text-ink">{c.sales.orders}</dd>
                  </div>
                  <div className="rounded-control bg-sunken px-2 py-3">
                    <dt className="text-xs text-ink-muted">Bought</dt>
                    <dd className="tabular text-lg font-semibold text-ink">{formatMoney(c.sales.total_sales)}</dd>
                  </div>
                  <div className="rounded-control bg-sunken px-2 py-3">
                    <dt className="text-xs text-ink-muted">To collect</dt>
                    <dd className="tabular text-lg font-semibold text-ink">{formatMoney(c.sales.outstanding)}</dd>
                  </div>
                </dl>
                <ul className="-mx-5 -mb-4 divide-y divide-line border-t border-line">
                  {c.orders.map((o) => (
                    <li key={o.id}>
                      <Link href={`/orders/${o.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-sunken/60">
                        <span className="min-w-0">
                          <span className="flex flex-wrap items-center gap-2">
                            <span className="tabular font-medium text-ink">{o.order_number}</span>
                            <Pill tone={STATUS_TONE[o.status]}>{STATUS_LABEL[o.status] ?? o.status}</Pill>
                          </span>
                          <span className="block text-xs text-ink-subtle">{formatTime(o.created_at)}</span>
                        </span>
                        <span className="text-right">
                          <span className="tabular block font-medium text-ink">{formatMoney(o.grand_total, "NPR")}</span>
                          <span className="block text-xs text-ink-subtle">{PAYMENT_LABEL[o.payment_status]}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Panel>

          <Panel title="Chats">
            {c.conversations.length === 0 ? (
              <p className="text-sm text-ink-muted">No chats yet. This customer was added by hand.</p>
            ) : (
              <ul className="-my-2">
                {c.conversations.map((cv) => (
                  <li key={cv.id} className="border-b border-line last:border-b-0">
                    <Link href={`/inbox/${cv.id}`} className="flex items-center gap-3 py-3 hover:text-primary">
                      <span className="min-w-0 flex-1">
                        <ChannelTag channel={cv.provider} />
                        <span className="block truncate text-ink">{cv.last_message_preview}</span>
                      </span>
                      <span className="tabular shrink-0 text-xs text-ink-subtle">{formatTime(cv.last_message_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>

        <Panel title="Notes" description="Only your team can see these.">
          {canWrite && (
            <form
              className="mb-4"
              onSubmit={(e) => {
                e.preventDefault();
                if (note.trim()) addNote.mutate(note.trim());
              }}
            >
              <label htmlFor="note" className="sr-only">
                New note
              </label>
              <textarea
                id="note"
                rows={2}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Prefers delivery after 5 pm, pays by eSewa…"
                className="w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base text-ink placeholder:text-ink-subtle focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
              />
              <Button type="submit" size="sm" className="mt-2" loading={addNote.isPending} disabled={!note.trim()}>
                Save note
              </Button>
            </form>
          )}
          {error && <Alert tone="error">{error}</Alert>}
          {c.notes.length === 0 ? (
            <p className="flex items-center gap-2 text-sm text-ink-muted">
              <StickyNote className="size-4 text-ink-subtle" aria-hidden />
              No notes yet.
            </p>
          ) : (
            <ul className="grid gap-3">
              {c.notes.map((n) => (
                <li key={n.id} className="border-l-2 border-attention pl-3">
                  <p className="text-sm whitespace-pre-wrap text-ink">{n.body}</p>
                  <p className="mt-0.5 text-xs text-ink-subtle">{new Date(n.created_at).toLocaleString()}</p>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </main>
  );
}
