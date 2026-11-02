"use client";

/** Customer and product search pickers shared by the order form and the lead sheet. */

import { useQuery } from "@tanstack/react-query";
import { Search, UserPlus } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { Alert, Avatar, Button, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { CustomerListItem } from "@/lib/inbox";
import { formatMoney, type Product, type Variant } from "@/lib/sales";

/** Base input look without a width, for compact inputs that set their own. */
export const INPUT_BASE =
  "rounded-control border border-line-strong bg-surface px-3 py-2 text-base text-ink focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none";

export const INPUT = "w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base text-ink focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none";

export function CustomerPicker({ onPick }: { onPick: (c: { id: string; display_name: string }) => void }) {
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [error, setError] = useState<string | null>(null);
  const search = useDeferredValue(q.trim());
  const results = useQuery({
    queryKey: ["customers", "picker", search],
    queryFn: () => api<{ items: CustomerListItem[] }>("tenant", "GET", `/api/v1/customers?limit=8&q=${encodeURIComponent(search)}`),
    enabled: search.length > 0,
  });

  async function create() {
    setError(null);
    try {
      const created = await api<{ id: string; display_name: string }>("tenant", "POST", "/api/v1/customers", { display_name: name, phone: phone || null });
      onPick(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the customer.");
    }
  }

  if (adding) {
    return (
      <div className="rounded-control border border-line p-4">
        {error && <Alert tone="error">{error}</Alert>}
        <div className="grid gap-3 sm:grid-cols-2">
          <input className={INPUT} placeholder="Customer name" value={name} onChange={(e) => setName(e.target.value)} aria-label="Customer name" />
          <input className={INPUT} placeholder="Phone (optional)" value={phone} onChange={(e) => setPhone(e.target.value)} inputMode="tel" aria-label="Phone" />
        </div>
        <div className="mt-3 flex gap-2">
          <Button type="button" size="sm" onClick={create} disabled={!name.trim()}>
            Add customer
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={() => setAdding(false)}>
            Back to search
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
        <input className={cx(INPUT, "pl-9")} placeholder="Search by name or phone" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find customer" />
      </div>
      {search && (
        <ul className="mt-2 overflow-hidden rounded-control border border-line">
          {results.data?.items.map((c) => (
            <li key={c.id}>
              <button type="button" onClick={() => onPick(c)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-sunken">
                <Avatar name={c.display_name} channel={c.channels[0]} size="sm" />
                <span className="min-w-0 flex-1 truncate text-ink">{c.display_name}</span>
                <span className="tabular text-sm text-ink-subtle">{c.phone_e164}</span>
              </button>
            </li>
          ))}
          {results.data?.items.length === 0 && <li className="px-3 py-2 text-sm text-ink-muted">No one found.</li>}
        </ul>
      )}
      <button type="button" onClick={() => setAdding(true)} className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
        <UserPlus className="size-4" aria-hidden />
        New customer (phone or walk-in)
      </button>
    </div>
  );
}

export function ProductPicker({ onPick }: { onPick: (p: Product, v: Variant) => void }) {
  const [q, setQ] = useState("");
  const search = useDeferredValue(q.trim());
  const products = useQuery({
    queryKey: ["products", "picker", search],
    queryFn: () => api<{ items: Product[] }>("tenant", "GET", `/api/v1/products?active=true&limit=10&q=${encodeURIComponent(search)}`),
  });
  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
        <input className={cx(INPUT, "pl-9")} placeholder="Search products" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Find product" />
      </div>
      <ul className="mt-2 max-h-64 overflow-y-auto rounded-control border border-line">
        {products.data?.items.flatMap((p) =>
          p.variants
            .filter((v) => v.is_active)
            .map((v) => (
              <li key={v.id}>
                <button type="button" onClick={() => onPick(p, v)} className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-sunken">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-ink">
                      {p.name}
                      {p.variants.length > 1 ? ` (${v.name})` : ""}
                    </span>
                    {v.stock !== null && <span className="text-xs text-ink-subtle">{Number(v.stock)} in stock</span>}
                  </span>
                  <span className="tabular text-sm text-ink">{formatMoney(v.price, "NPR")}</span>
                </button>
              </li>
            )),
        )}
        {products.data?.items.length === 0 && (
          <li className="px-3 py-2 text-sm text-ink-muted">
            No products found. <Link href="/products" className="text-primary underline">Add products</Link> first.
          </li>
        )}
      </ul>
    </div>
  );
}
