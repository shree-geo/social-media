"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { Wallet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Checkbox, EmptyState, PageHeader, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/inbox";
import { PAYMENT_METHOD_LABEL, formatMoney, type Payment } from "@/lib/sales";

export function PaymentsView() {
  const [method, setMethod] = useState("");
  const [voided, setVoided] = useState(false);

  const payments = useInfiniteQuery({
    queryKey: ["payments", method, voided],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: "30" });
      if (method) params.set("method", method);
      if (voided) params.set("include_voided", "true");
      if (pageParam) params.set("cursor", pageParam);
      return api<{ items: Payment[]; next_cursor: string | null }>("tenant", "GET", `/api/v1/payments?${params}`);
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = payments.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader title="Payments" description="Money received and returned, as recorded on each order." />
      <div className="mb-4 flex flex-wrap items-center gap-x-4 gap-y-2">
        <select
          aria-label="Method"
          value={method}
          onChange={(e) => setMethod(e.target.value)}
          className="rounded-control border border-line-strong bg-surface px-3 py-2 text-sm"
        >
          <option value="">Any method</option>
          {Object.entries(PAYMENT_METHOD_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <div className="-mb-5">
          <Checkbox label="Show voided" checked={voided} onChange={(e) => setVoided(e.target.checked)} />
        </div>
      </div>

      {payments.isPending ? null : items.length === 0 ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState icon={Wallet} title="No payments recorded">
            Record payments on each order as they come in: cash, eSewa, Khalti, bank transfer or cash on delivery.
          </EmptyState>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-panel border border-line bg-surface">
          {items.map((p) => (
            <li key={p.id} className="border-b border-line last:border-b-0">
              <Link href={`/orders/${p.order.id}`} className="grid grid-cols-[1fr_auto] items-center gap-x-3 gap-y-1 px-4 py-3 hover:bg-sunken/60">
                <span className="min-w-0">
                  <span className="block truncate font-medium text-ink">{p.order.customer.name}</span>
                  <span className="block truncate text-sm text-ink-muted">
                    {PAYMENT_METHOD_LABEL[p.method] ?? p.method}
                    {p.reference && ` · ${p.reference}`} · <span className="tabular">{p.order.order_number}</span>
                  </span>
                  {p.status === "voided" && <span className="block text-xs text-danger">Voided: {p.void_reason}</span>}
                </span>
                <span className="text-right">
                  <span
                    className={cx(
                      "tabular block font-semibold",
                      p.status === "voided" ? "text-ink-subtle line-through" : p.type === "refund" ? "text-danger" : "text-ink",
                    )}
                  >
                    {p.type === "refund" ? "− " : ""}
                    {formatMoney(p.amount, p.currency)}
                  </span>
                  <span className="block text-xs text-ink-subtle">{formatTime(p.paid_at)}</span>
                </span>
              </Link>
            </li>
          ))}
          {payments.hasNextPage && (
            <li className="p-3">
              <button onClick={() => payments.fetchNextPage()} className="w-full rounded-control py-2 text-sm font-medium text-primary hover:bg-primary-soft">
                Show more
              </button>
            </li>
          )}
        </ul>
      )}
    </main>
  );
}
