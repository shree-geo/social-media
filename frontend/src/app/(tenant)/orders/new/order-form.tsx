"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Search, Trash2, UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useDeferredValue, useRef, useState, type FormEvent } from "react";

import { Alert, Avatar, Button, ChannelTag, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ConversationItem, CustomerListItem } from "@/lib/inbox";
import { LEAD_LABEL, SOURCE_LABEL, formatMoney, type Order, type Product, type Variant } from "@/lib/sales";

type Line = { key: string; product: Product; variant: Variant; quantity: string; unit_price: string; discount: string };

const INPUT = "w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base text-ink focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none";

function CustomerPicker({ onPick }: { onPick: (c: { id: string; display_name: string }) => void }) {
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

function ProductPicker({ onPick }: { onPick: (p: Product, v: Variant) => void }) {
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

export function OrderForm() {
  const router = useRouter();
  const params = useSearchParams();
  const conversationId = params.get("conversation");
  const presetCustomerId = params.get("customer");
  const idempotencyKey = useRef(crypto.randomUUID());

  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api<ConversationItem>("tenant", "GET", `/api/v1/conversations/${conversationId}`),
    enabled: Boolean(conversationId),
  });
  const presetCustomer = useQuery({
    queryKey: ["customer", presetCustomerId],
    queryFn: () => api<{ id: string; display_name: string }>("tenant", "GET", `/api/v1/customers/${presetCustomerId}`),
    enabled: Boolean(presetCustomerId),
  });

  const [picked, setPicked] = useState<{ id: string; display_name: string } | null>(null);
  const [source, setSource] = useState("phone");
  const [lead, setLead] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [shipping, setShipping] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const customer = conversation.data?.customer ?? picked ?? presetCustomer.data ?? null;
  const subtotal = lines.reduce((sum, l) => sum + Number(l.quantity || 0) * Number(l.unit_price || 0) - Number(l.discount || 0), 0);

  function addLine(product: Product, variant: Variant) {
    setLines((ls) => {
      const existing = ls.find((l) => l.variant.id === variant.id);
      if (existing) return ls.map((l) => (l === existing ? { ...l, quantity: String(Number(l.quantity) + 1) } : l));
      return [...ls, { key: crypto.randomUUID(), product, variant, quantity: "1", unit_price: variant.price ?? "", discount: "" }];
    });
  }
  const update = (key: string, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!customer) return setError("Choose the customer.");
    if (lines.length === 0) return setError("Add at least one product.");
    setSaving(true);
    try {
      const order = await api<Order>(
        "tenant",
        "POST",
        "/api/v1/orders",
        {
          ...(conversationId ? { conversation_id: conversationId } : { customer_id: customer.id, source_channel: source }),
          lead_source: lead || null,
          items: lines.map((l) => ({
            variant_id: l.variant.id,
            quantity: l.quantity,
            unit_price: l.unit_price || null,
            discount_amount: l.discount || "0",
          })),
          shipping_fee: shipping || "0",
          delivery_address: address.trim() ? { line1: address.trim() } : null,
          notes: notes.trim() || null,
        },
        { "Idempotency-Key": idempotencyKey.current },
      );
      router.replace(`/orders/${order.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the order. Check your connection and try again.");
      setSaving(false);
    }
  }

  const back = conversationId ? `/inbox/${conversationId}` : presetCustomerId ? `/customers/${presetCustomerId}` : "/orders";

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href={back} className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Back
      </Link>
      <PageHeader title="New order" />
      {error && <Alert tone="error">{error}</Alert>}
      <form onSubmit={submit} noValidate className="grid gap-6">
        <section className="rounded-panel border border-line bg-surface p-5">
          <h2 className="mb-3 text-lg font-semibold text-ink">Customer</h2>
          {customer ? (
            <div className="flex items-center gap-3">
              <Avatar name={customer.display_name} channel={conversation.data?.provider} />
              <div className="min-w-0 flex-1">
                <p className="font-medium text-ink">{customer.display_name}</p>
                {conversation.data && <ChannelTag channel={conversation.data.provider} />}
              </div>
              {!conversationId && !presetCustomerId && (
                <button type="button" onClick={() => setPicked(null)} className="grid size-9 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Change customer">
                  <X className="size-4" aria-hidden />
                </button>
              )}
            </div>
          ) : (
            <CustomerPicker onPick={setPicked} />
          )}
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {!conversationId && (
              <label className="text-sm">
                <span className="mb-1 block font-medium text-ink">Order came by</span>
                <select className={INPUT} value={source} onChange={(e) => setSource(e.target.value)}>
                  {["phone", "walk_in", "other"].map((s) => (
                    <option key={s} value={s}>
                      {SOURCE_LABEL[s]}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className="text-sm">
              <span className="mb-1 block font-medium text-ink">How did they find you? (optional)</span>
              <select className={INPUT} value={lead} onChange={(e) => setLead(e.target.value)}>
                <option value="">Don&apos;t know</option>
                {Object.entries(LEAD_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
        </section>

        <section className="rounded-panel border border-line bg-surface p-5">
          <h2 className="mb-3 text-lg font-semibold text-ink">Products</h2>
          {lines.length > 0 && (
            <ul className="mb-4 divide-y divide-line rounded-control border border-line">
              {lines.map((l) => (
                <li key={l.key} className="grid grid-cols-[1fr_auto] gap-3 p-3 sm:grid-cols-[1fr_5rem_7rem_6rem_auto] sm:items-end">
                  <div className="col-span-2 sm:col-span-1">
                    <p className="font-medium text-ink">
                      {l.product.name}
                      {l.product.variants.length > 1 ? ` (${l.variant.name})` : ""}
                    </p>
                    <p className="text-xs text-ink-subtle">Code {l.variant.sku}</p>
                  </div>
                  <label className="text-xs text-ink-muted">
                    Qty
                    <input className={cx(INPUT, "tabular mt-1 px-2 py-1.5")} inputMode="decimal" value={l.quantity} onChange={(e) => update(l.key, { quantity: e.target.value })} />
                  </label>
                  <label className="text-xs text-ink-muted">
                    Price (Rs.)
                    <input className={cx(INPUT, "tabular mt-1 px-2 py-1.5")} inputMode="decimal" value={l.unit_price} onChange={(e) => update(l.key, { unit_price: e.target.value })} />
                  </label>
                  <label className="text-xs text-ink-muted">
                    Discount
                    <input className={cx(INPUT, "tabular mt-1 px-2 py-1.5")} inputMode="decimal" placeholder="0" value={l.discount} onChange={(e) => update(l.key, { discount: e.target.value })} />
                  </label>
                  <button type="button" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))} className="grid size-9 place-items-center self-end rounded-control text-ink-muted hover:bg-sunken" aria-label={`Remove ${l.product.name}`}>
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <ProductPicker onPick={addLine} />
        </section>

        <section className="rounded-panel border border-line bg-surface p-5">
          <h2 className="mb-3 text-lg font-semibold text-ink">Delivery and notes</h2>
          <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
            <label className="text-sm">
              <span className="mb-1 block font-medium text-ink">Delivery address (optional)</span>
              <input className={INPUT} value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Itahari-6, near Bus Park" />
            </label>
            <label className="text-sm">
              <span className="mb-1 block font-medium text-ink">Delivery charge</span>
              <input className={cx(INPUT, "tabular")} inputMode="decimal" value={shipping} onChange={(e) => setShipping(e.target.value)} placeholder="0" />
            </label>
          </div>
          <label className="mt-3 block text-sm">
            <span className="mb-1 block font-medium text-ink">Notes for your team (optional)</span>
            <textarea className={cx(INPUT, "min-h-20")} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </label>
        </section>

        <div className="sticky bottom-16 flex flex-wrap items-center justify-between gap-3 rounded-panel border border-line bg-surface p-4 shadow-lg md:bottom-4">
          <div>
            <p className="tabular text-lg font-semibold text-ink">{formatMoney(subtotal + Number(shipping || 0), "NPR")}</p>
            <p className="text-xs text-ink-muted">VAT, if any, is added when you save.</p>
          </div>
          <Button type="submit" loading={saving} disabled={!customer || lines.length === 0}>
            Save order
          </Button>
        </div>
      </form>
    </main>
  );
}
