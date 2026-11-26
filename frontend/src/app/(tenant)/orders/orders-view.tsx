"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Plus, Search, ShoppingBag } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { useMe } from "@/components/tenant-shell";
import { EmptyState, PageHeader, Pill, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/inbox";
import { PAYMENT_LABEL, PAYMENT_TONE, SOURCE_LABEL, STATUS_LABEL, STATUS_TONE, formatMoney, type OrderSummary } from "@/lib/sales";

const VIEWS = [
  { key: "open", label: "Open" },
  { key: "all", label: "All" },
] as const;

export function OrdersView() {
  const me = useMe();
  const [view, setView] = useState<(typeof VIEWS)[number]["key"]>("open");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const search = useDeferredValue(q.trim());
  const canCreate = me.data?.permissions.includes("order.write") ?? false;

  const orders = useInfiniteQuery({
    queryKey: ["orders", view, status, search],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "30" });
      if (view === "open") params.set("open_only", "true");
      if (status) params.set("status", status);
      if (search) params.set("q", search);
      if (pageParam) params.set("cursor", pageParam);
      return api<{ items: OrderSummary[]; next_cursor: string | null }>("tenant", "GET", `/api/v1/orders?${params}`);
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = orders.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader
        title="Orders"
        description="Orders taken in chats, on the phone or in the shop."
        actions={
          canCreate && (
            <Link href="/orders/new" className="inline-flex min-h-11 items-center gap-2 rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover">
              <Plus className="size-4" aria-hidden />
              New order
            </Link>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="grid grid-cols-2 rounded-control bg-sunken p-1" role="tablist" aria-label="Show">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              role="tab"
              aria-selected={view === v.key}
              onClick={() => setView(v.key)}
              className={cx("rounded-[6px] px-4 py-1.5 text-sm font-medium", view === v.key ? "bg-surface text-ink shadow-sm" : "text-ink-muted")}
            >
              {v.label}
            </button>
          ))}
        </div>
        <select
          aria-label="Status"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-control border border-line-strong bg-surface px-3 py-2 text-sm"
        >
          <option value="">Any status</option>
          {Object.entries(STATUS_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <div className="relative min-w-48 flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Order number or customer"
            aria-label="Search orders"
            className="w-full rounded-control border border-line-strong bg-surface py-2 pr-3 pl-9 text-sm"
          />
        </div>
      </div>

      {orders.isPending ? null : items.length === 0 ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState icon={ShoppingBag} title={view === "open" ? "No open orders" : "No orders yet"}>
            Create one from a chat with the <strong>Create order</strong> button, or use <strong>New order</strong> for phone and walk-in customers.
          </EmptyState>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-panel border border-line bg-surface">
          <li
            aria-hidden
            className="hidden grid-cols-[minmax(0,1.1fr)_minmax(0,1.3fr)_9.5rem_7rem_8rem] gap-4 border-b border-line bg-sunken/60 px-4 py-2 text-xs font-semibold text-ink-muted md:grid"
          >
            <span>Order</span>
            <span>Customer</span>
            <span>Status</span>
            <span>Payment</span>
            <span className="text-right">Amount</span>
          </li>
          {items.map((o) => (
            <li key={o.id} className="border-b border-line last:border-b-0">
              <Link
                href={`/orders/${o.id}`}
                className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-sunken/60 md:grid-cols-[minmax(0,1.1fr)_minmax(0,1.3fr)_9.5rem_7rem_8rem] md:gap-x-4"
              >
                <span className="min-w-0">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="tabular font-medium text-ink">{o.order_number}</span>
                    <span className="md:hidden">
                      <Pill tone={STATUS_TONE[o.status]}>{STATUS_LABEL[o.status] ?? o.status}</Pill>
                    </span>
                  </span>
                  <span className="block truncate text-sm text-ink-muted md:hidden">
                    {o.customer.display_name} · {SOURCE_LABEL[o.source_channel] ?? o.source_channel}
                  </span>
                  <span className="hidden text-sm text-ink-subtle md:block">{formatTime(o.created_at)}</span>
                </span>
                <span className="hidden min-w-0 md:block">
                  <span className="block truncate text-ink">{o.customer.display_name}</span>
                  <span className="block text-sm text-ink-muted">{SOURCE_LABEL[o.source_channel] ?? o.source_channel}</span>
                </span>
                <span className="hidden md:block">
                  <Pill tone={STATUS_TONE[o.status]}>{STATUS_LABEL[o.status] ?? o.status}</Pill>
                </span>
                <span className="hidden md:block">
                  <Pill tone={PAYMENT_TONE[o.payment_status] ?? "new"}>{PAYMENT_LABEL[o.payment_status] ?? o.payment_status}</Pill>
                </span>
                <span className="text-right">
                  <span className="tabular block font-semibold text-ink">{formatMoney(o.grand_total, o.currency)}</span>
                  <span className="block text-xs text-ink-subtle md:hidden">
                    {PAYMENT_LABEL[o.payment_status]} · {formatTime(o.created_at)}
                  </span>
                </span>
              </Link>
            </li>
          ))}
          {orders.hasNextPage && (
            <li className="p-3">
              <button onClick={() => orders.fetchNextPage()} className="w-full rounded-control py-2 text-sm font-medium text-primary hover:bg-primary-soft">
                Show more
              </button>
            </li>
          )}
        </ul>
      )}
    </main>
  );
}
