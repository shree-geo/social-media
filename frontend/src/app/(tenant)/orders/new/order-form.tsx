"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Link2, Target, Trash2, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useRef, useState, type FormEvent } from "react";

import { CustomerPicker, INPUT, ProductPicker } from "@/components/pickers";
import { Alert, Avatar, Button, ChannelTag, PageHeader, Spinner, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ConversationItem } from "@/lib/inbox";
import { isOpen, type Lead, type LeadItem } from "@/lib/leads";
import { LEAD_LABEL, SOURCE_LABEL, formatMoney, formatQty, type Order, type Product, type Variant } from "@/lib/sales";

type Line = { key: string; variant_id: string; name: string; sku: string | null; quantity: string; unit_price: string; discount: string };

function variantName(product: Product, variant: Variant): string {
  return product.variants.length > 1 ? `${product.name} (${variant.name})` : product.name;
}

/** A free-text line from the lead ("blue sofa like the photo") that needs a real product before saving. */
function UnmatchedLine({ item, onMatch, onSkip }: { item: LeadItem; onMatch: (p: Product, v: Variant) => void; onSkip: () => void }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-ink">
          <span className="tabular font-medium">{formatQty(item.quantity)} ×</span> {item.description}
          {Number(item.unit_price) > 0 && <span className="text-ink-muted"> · quoted {formatMoney(item.unit_price, "NPR")}</span>}
        </p>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="secondary" icon={Link2} onClick={() => setOpen((o) => !o)}>
            Pick product
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onSkip}>
            Leave out
          </Button>
        </div>
      </div>
      {open && (
        <div className="mt-3">
          <ProductPicker onPick={onMatch} />
        </div>
      )}
    </li>
  );
}

export function OrderForm() {
  const params = useSearchParams();
  const leadId = params.get("lead");
  const lead = useQuery({
    queryKey: ["lead", leadId],
    queryFn: () => api<Lead>("tenant", "GET", `/api/v1/leads/${leadId}`),
    enabled: Boolean(leadId),
  });
  if (leadId && !lead.data) {
    return (
      <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
        {lead.isError ? <Alert tone="error">This lead isn&apos;t available.</Alert> : <Spinner />}
      </main>
    );
  }
  return <OrderFormBody lead={lead.data ?? null} />;
}

/** Lines to start with when converting a lead: its catalogue products; free-text ones are matched by hand. */
function leadLines(lead: Lead | null): Line[] {
  return (lead?.items ?? [])
    .filter((i) => i.variant_id)
    .map((i) => ({
      key: i.id,
      variant_id: i.variant_id!,
      name: i.description,
      sku: null,
      quantity: formatQty(i.quantity).replace(/,/g, ""),
      unit_price: i.unit_price,
      discount: "",
    }));
}

function OrderFormBody({ lead }: { lead: Lead | null }) {
  const router = useRouter();
  const params = useSearchParams();
  const leadId = lead?.id ?? null;
  const presetCustomerId = params.get("customer");
  const idempotencyKey = useRef(crypto.randomUUID());

  const conversationId = params.get("conversation") ?? lead?.conversation_id ?? null;
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
  const [source, setSource] = useState(lead && !lead.conversation_id ? lead.source_channel : "phone");
  const [leadSource, setLeadSource] = useState(lead?.lead_source ?? "");
  const [lines, setLines] = useState<Line[]>(() => leadLines(lead));
  const [unmatched, setUnmatched] = useState<LeadItem[]>(() => (lead?.items ?? []).filter((i) => !i.variant_id));
  const [shipping, setShipping] = useState("");
  const [address, setAddress] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const leadCustomer = lead?.customer ?? null;
  const customer = leadCustomer ?? conversation.data?.customer ?? picked ?? presetCustomer.data ?? null;
  const subtotal = lines.reduce((sum, l) => sum + Number(l.quantity || 0) * Number(l.unit_price || 0) - Number(l.discount || 0), 0);
  const leadClosed = lead ? !isOpen(lead.stage) : false;

  function addLine(product: Product, variant: Variant, quantity = "1", price?: string) {
    setLines((ls) => {
      const existing = ls.find((l) => l.variant_id === variant.id);
      if (existing) return ls.map((l) => (l === existing ? { ...l, quantity: String(Number(l.quantity) + Number(quantity)) } : l));
      return [
        ...ls,
        {
          key: crypto.randomUUID(),
          variant_id: variant.id,
          name: variantName(product, variant),
          sku: variant.sku,
          quantity,
          unit_price: price ?? variant.price ?? "",
          discount: "",
        },
      ];
    });
  }
  const update = (key: string, patch: Partial<Line>) => setLines((ls) => ls.map((l) => (l.key === key ? { ...l, ...patch } : l)));

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!customer) return setError("Choose the customer.");
    if (unmatched.length > 0) return setError("Pick a product for each item the customer asked about, or leave it out.");
    if (lines.length === 0) return setError("Add at least one product.");
    setSaving(true);
    try {
      const who = leadId
        ? { lead_id: leadId, ...(lead?.conversation_id ? {} : { source_channel: source }) }
        : conversationId
          ? { conversation_id: conversationId }
          : { customer_id: customer.id, source_channel: source };
      const order = await api<Order>(
        "tenant",
        "POST",
        "/api/v1/orders",
        {
          ...who,
          lead_source: leadSource || null,
          items: lines.map((l) => ({
            variant_id: l.variant_id,
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

  const back = leadId
    ? `/leads/${leadId}`
    : conversationId
      ? `/inbox/${conversationId}`
      : presetCustomerId
        ? `/customers/${presetCustomerId}`
        : "/orders";
  const fixedCustomer = Boolean(leadId || conversationId || presetCustomerId);

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href={back} className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Back
      </Link>
      <PageHeader title={lead ? `Order from lead ${lead.lead_number}` : "New order"} />
      {lead && !leadClosed && (
        <Alert tone="info" title="Converting a lead">
          Check the products and prices with the customer. Saving creates the order and marks {lead.lead_number} as won.
        </Alert>
      )}
      {leadClosed && (
        <Alert tone="warning" title="This lead is already closed">
          {lead?.won_order ? `It became order ${lead.won_order.order_number}.` : "Reopen it first if the customer is buying after all."}
        </Alert>
      )}
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
              {!fixedCustomer && (
                <button type="button" onClick={() => setPicked(null)} className="grid size-9 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Change customer">
                  <X className="size-4" aria-hidden />
                </button>
              )}
            </div>
          ) : leadId ? (
            <p className="text-ink-muted">Loading…</p>
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
              <select className={INPUT} value={leadSource} onChange={(e) => setLeadSource(e.target.value)}>
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
          {unmatched.length > 0 && (
            <div className="mb-4 rounded-control border border-attention/40 bg-attention-soft/40">
              <p className="flex items-center gap-2 px-3 pt-3 text-sm font-medium text-attention-ink">
                <Target className="size-4" aria-hidden />
                Not in your products yet: pick the matching product for each
              </p>
              <ul className="divide-y divide-line">
                {unmatched.map((item) => (
                  <UnmatchedLine
                    key={item.id}
                    item={item}
                    onMatch={(p, v) => {
                      addLine(p, v, formatQty(item.quantity).replace(/,/g, ""), Number(item.unit_price) > 0 ? item.unit_price : undefined);
                      setUnmatched((u) => u.filter((x) => x.id !== item.id));
                    }}
                    onSkip={() => setUnmatched((u) => u.filter((x) => x.id !== item.id))}
                  />
                ))}
              </ul>
            </div>
          )}
          {lines.length > 0 && (
            <ul className="mb-4 divide-y divide-line rounded-control border border-line">
              {lines.map((l) => (
                <li key={l.key} className="grid grid-cols-[1fr_auto] gap-3 p-3 sm:grid-cols-[1fr_5rem_7rem_6rem_auto] sm:items-end">
                  <div className="col-span-2 sm:col-span-1">
                    <p className="font-medium text-ink">{l.name}</p>
                    {l.sku && <p className="text-xs text-ink-subtle">Code {l.sku}</p>}
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
                  <button type="button" onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))} className="grid size-9 place-items-center self-end rounded-control text-ink-muted hover:bg-sunken" aria-label={`Remove ${l.name}`}>
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <ProductPicker onPick={(p, v) => addLine(p, v)} />
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
          <Button type="submit" loading={saving} disabled={!customer || lines.length === 0 || unmatched.length > 0 || leadClosed}>
            {lead ? "Save order and mark won" : "Save order"}
          </Button>
        </div>
      </form>
    </main>
  );
}
