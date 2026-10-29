"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { MapPin, Truck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ContactLine, DeliveryActions } from "@/components/fulfilment";
import { useMe } from "@/components/tenant-shell";
import { EmptyState, PageHeader, Pill, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { DELIVERY_METHOD_LABEL, DELIVERY_STATUS_LABEL, DELIVERY_TONE, addressText, formatMoney, type Delivery } from "@/lib/sales";

const VIEWS = [
  { key: "mine", label: "Mine" },
  { key: "today", label: "Today" },
  { key: "open", label: "All open" },
  { key: "all", label: "History" },
] as const;
type View = (typeof VIEWS)[number]["key"];

const EMPTY: Record<View, string> = {
  mine: "Nothing assigned to you right now.",
  today: "No deliveries due today.",
  open: "No deliveries waiting.",
  all: "No deliveries yet.",
};

function DeliveryCard({ d, canWrite, canRecordCash, onChanged }: { d: Delivery; canWrite: boolean; canRecordCash: boolean; onChanged: () => void }) {
  const address = addressText(d.delivery_address);
  return (
    <li className="grid gap-2 border-b border-line px-4 py-4 last:border-b-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-ink">{d.contact_name ?? d.order.customer.name}</span>
          <Pill tone={DELIVERY_TONE[d.status]}>{DELIVERY_STATUS_LABEL[d.status] ?? d.status}</Pill>
        </div>
        {Number(d.cod_amount) > 0 && !["DELIVERED", "CANCELLED", "RETURNED"].includes(d.status) && (
          <span className="tabular rounded-control bg-attention-soft px-2 py-0.5 text-sm font-semibold text-ink">
            Collect {formatMoney(d.cod_amount, d.order.currency)}
          </span>
        )}
      </div>
      {address && (
        <p className="flex items-start gap-1.5 text-sm text-ink">
          <MapPin className="mt-0.5 size-4 shrink-0 text-ink-subtle" aria-hidden />
          {address}
        </p>
      )}
      <ContactLine delivery={d} />
      <p className="text-xs text-ink-subtle">
        <Link href={`/orders/${d.order.id}`} className="tabular text-primary hover:underline">
          {d.order.order_number}
        </Link>{" "}
        · {d.delivery_number} · {d.method === "courier" ? d.courier_name : DELIVERY_METHOD_LABEL[d.method]}
        {d.assigned_to && ` · ${d.assigned_to.name}`}
        {d.scheduled_date && ` · ${d.scheduled_date}`}
      </p>
      {canWrite && <DeliveryActions delivery={d} canRecordCash={canRecordCash} onChanged={onChanged} />}
    </li>
  );
}

export function DeliveriesView() {
  const me = useMe();
  const queryClient = useQueryClient();
  const [view, setView] = useState<View>("mine");
  const can = (p: string) => me.data?.permissions.includes(p) ?? false;

  const deliveries = useInfiniteQuery({
    queryKey: ["deliveries", view],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ view, limit: "30" });
      if (pageParam) params.set("cursor", pageParam);
      return api<{ items: Delivery[]; next_cursor: string | null }>("tenant", "GET", `/api/v1/deliveries?${params}`);
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = deliveries.data?.pages.flatMap((p) => p.items) ?? [];
  const changed = () => {
    void queryClient.invalidateQueries({ queryKey: ["deliveries"] });
    void queryClient.invalidateQueries({ queryKey: ["orders"] });
  };

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader title="Deliveries" description="Send orders out from the order screen; update them here as they go." />
      <div className="mb-4 grid grid-cols-4 rounded-control bg-sunken p-1" role="tablist" aria-label="Show">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            role="tab"
            aria-selected={view === v.key}
            onClick={() => setView(v.key)}
            className={cx("rounded-[6px] px-2 py-1.5 text-sm font-medium", view === v.key ? "bg-surface text-ink shadow-sm" : "text-ink-muted")}
          >
            {v.label}
          </button>
        ))}
      </div>
      {deliveries.isPending ? null : items.length === 0 ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState icon={Truck} title={EMPTY[view]}>
            Open a confirmed order and choose <strong>Send for delivery</strong>.
          </EmptyState>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-panel border border-line bg-surface">
          {items.map((d) => (
            <DeliveryCard key={d.id} d={d} canWrite={can("delivery.write")} canRecordCash={can("payment.write")} onChanged={changed} />
          ))}
          {deliveries.hasNextPage && (
            <li className="p-3">
              <button onClick={() => deliveries.fetchNextPage()} className="w-full rounded-control py-2 text-sm font-medium text-primary hover:bg-primary-soft">
                Show more
              </button>
            </li>
          )}
        </ul>
      )}
    </main>
  );
}
