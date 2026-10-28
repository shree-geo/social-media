"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, Minus, Package, Plus, Search, Trash2, X } from "lucide-react";
import { useDeferredValue, useState, type FormEvent } from "react";

import { useMe } from "@/components/tenant-shell";
import { Alert, Button, Checkbox, EmptyState, Field, PageHeader, Pill, SelectField, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatMoney, formatQty, type Product, type TaxRate, type Variant } from "@/lib/sales";

const UNITS = ["pcs", "set", "pair", "box", "kg", "m", "litre"];

function stockState(v: Variant): { label: string; tone: "danger" | "attention" | null } {
  if (v.stock === null) return { label: "", tone: null };
  const stock = Number(v.stock);
  if (stock <= 0) return { label: "Out of stock", tone: "danger" };
  if (v.low_stock_threshold !== null && stock <= Number(v.low_stock_threshold)) return { label: "Low stock", tone: "attention" };
  return { label: "", tone: null };
}

type VariantDraft = { name: string; sku: string; price: string; opening_stock: string };

function AddProduct({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const taxRates = useQuery({ queryKey: ["tax-rates"], queryFn: () => api<TaxRate[]>("tenant", "GET", "/api/v1/tax-rates") });
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("pcs");
  const [taxRateId, setTaxRateId] = useState("");
  const [trackStock, setTrackStock] = useState(true);
  const [variants, setVariants] = useState<VariantDraft[]>([{ name: "", sku: "", price: "", opening_stock: "" }]);
  const [error, setError] = useState<string | null>(null);
  const multiple = variants.length > 1;

  const save = useMutation({
    mutationFn: () =>
      api<Product>("tenant", "POST", "/api/v1/products", {
        name,
        unit,
        tax_rate_id: taxRateId || null,
        track_inventory: trackStock,
        variants: variants.map((v) => ({
          name: v.name || "Default",
          sku: v.sku || null,
          price: v.price,
          opening_stock: trackStock ? v.opening_stock || "0" : "0",
        })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["products"] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Couldn't save the product."),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!name.trim()) return setError("Enter the product name.");
    if (variants.some((v) => v.price === "" || Number(v.price) < 0)) return setError("Enter a price for every option.");
    save.mutate();
  }

  const update = (i: number, patch: Partial<VariantDraft>) => setVariants((vs) => vs.map((v, j) => (j === i ? { ...v, ...patch } : v)));

  return (
    <div className="fixed inset-0 z-30 flex items-end justify-center bg-ink/40 sm:items-center sm:p-4" role="dialog" aria-modal="true" aria-labelledby="add-product">
      <form onSubmit={submit} className="max-h-[92dvh] w-full max-w-2xl overflow-y-auto rounded-t-panel bg-surface p-5 shadow-xl sm:rounded-panel sm:p-6">
        <div className="mb-4 flex items-center justify-between">
          <h2 id="add-product" className="text-xl font-semibold text-ink">
            Add a product
          </h2>
          <button type="button" onClick={onClose} className="grid size-10 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Close">
            <X className="size-5" aria-hidden />
          </button>
        </div>
        {error && <Alert tone="error">{error}</Alert>}
        <Field label="Product name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Office chair" autoFocus />
        <div className="grid gap-x-4 sm:grid-cols-2">
          <SelectField label="Sold by" value={unit} onChange={(e) => setUnit(e.target.value)}>
            {UNITS.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </SelectField>
          <SelectField label="VAT" value={taxRateId} onChange={(e) => setTaxRateId(e.target.value)}>
            <option value="">Business default</option>
            {taxRates.data?.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </SelectField>
        </div>
        <Checkbox label="Track stock for this product" hint="Stock goes down when an order is confirmed, and back up if it's cancelled." checked={trackStock} onChange={(e) => setTrackStock(e.target.checked)} />

        <fieldset className="mt-2">
          <legend className="mb-2 text-sm font-medium text-ink">{multiple ? "Options (colour, size …)" : "Price and stock"}</legend>
          <div className="space-y-3">
            {variants.map((v, i) => (
              <div key={i} className="grid grid-cols-2 gap-2 rounded-control bg-sunken/60 p-3 sm:grid-cols-[1.4fr_1fr_1fr_1fr_auto] sm:items-end">
                {multiple && (
                  <label className="col-span-2 text-sm sm:col-span-1">
                    <span className="mb-1 block text-ink-muted">Option</span>
                    <input value={v.name} onChange={(e) => update(i, { name: e.target.value })} placeholder="Black" className="w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base" />
                  </label>
                )}
                <label className="text-sm">
                  <span className="mb-1 block text-ink-muted">Price (Rs.)</span>
                  <input value={v.price} onChange={(e) => update(i, { price: e.target.value })} inputMode="decimal" placeholder="4500" className="tabular w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base" />
                </label>
                {trackStock && (
                  <label className="text-sm">
                    <span className="mb-1 block text-ink-muted">In stock now</span>
                    <input value={v.opening_stock} onChange={(e) => update(i, { opening_stock: e.target.value })} inputMode="decimal" placeholder="0" className="tabular w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base" />
                  </label>
                )}
                <label className="text-sm">
                  <span className="mb-1 block text-ink-muted">Code (optional)</span>
                  <input value={v.sku} onChange={(e) => update(i, { sku: e.target.value })} placeholder="CH-BLK" className="w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base" />
                </label>
                {multiple && (
                  <button type="button" onClick={() => setVariants((vs) => vs.filter((_, j) => j !== i))} className="grid size-10 place-items-center rounded-control text-ink-muted hover:bg-surface" aria-label="Remove option">
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                )}
              </div>
            ))}
          </div>
          <button type="button" onClick={() => setVariants((vs) => [...vs, { name: "", sku: "", price: "", opening_stock: "" }])} className="mt-2 inline-flex items-center gap-1.5 rounded-control px-2 py-1.5 text-sm font-medium text-primary hover:bg-primary-soft">
            <Plus className="size-4" aria-hidden />
            {multiple ? "Add another option" : "This product comes in options (colour, size …)"}
          </button>
        </fieldset>

        <div className="mt-6 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending}>
            Save product
          </Button>
        </div>
      </form>
    </div>
  );
}

function VariantRow({ product, variant, canEdit }: { product: Product; variant: Variant; canEdit: boolean }) {
  const queryClient = useQueryClient();
  const [price, setPrice] = useState(variant.price ?? "");
  const [change, setChange] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["products"] });
  const onError = (e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't save.");
  const savePrice = useMutation({
    mutationFn: () => api("tenant", "PATCH", `/api/v1/products/variants/${variant.id}`, { price }),
    onSuccess: refresh,
    onError,
  });
  const adjust = useMutation({
    mutationFn: (delta: string) => api("tenant", "POST", `/api/v1/products/variants/${variant.id}/stock`, { change: delta, note: note || null }),
    onSuccess: () => {
      setChange("");
      setNote("");
      refresh();
    },
    onError,
  });
  const state = stockState(variant);
  return (
    <li className="grid gap-3 border-t border-line px-4 py-3 sm:grid-cols-[1fr_auto] sm:items-center">
      <div>
        <p className="font-medium text-ink">{variant.is_default && product.variants.length === 1 ? "Price and stock" : variant.name}</p>
        <p className="text-xs text-ink-subtle">Code {variant.sku}</p>
        {error && <p className="mt-1 text-sm text-danger">{error}</p>}
      </div>
      {canEdit ? (
        <div className="flex flex-wrap items-end gap-3">
          <label className="text-sm">
            <span className="mb-1 block text-ink-muted">Price (Rs.)</span>
            <span className="flex gap-1">
              <input value={price} onChange={(e) => setPrice(e.target.value)} inputMode="decimal" className="tabular w-28 rounded-control border border-line-strong bg-surface px-2 py-1.5" />
              {price !== (variant.price ?? "") && (
                <Button size="sm" onClick={() => savePrice.mutate()} loading={savePrice.isPending}>
                  Save
                </Button>
              )}
            </span>
          </label>
          {product.track_inventory && (
            <div className="text-sm">
              <span className="mb-1 block text-ink-muted">
                Stock <strong className="tabular text-ink">{formatQty(variant.stock)}</strong> {state.tone && <Pill tone={state.tone}>{state.label}</Pill>}
              </span>
              <span className="flex gap-1">
                <input value={change} onChange={(e) => setChange(e.target.value)} inputMode="decimal" placeholder="Qty" aria-label="Quantity" className="tabular w-16 rounded-control border border-line-strong bg-surface px-2 py-1.5" />
                <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional)" aria-label="Note" className="w-32 rounded-control border border-line-strong bg-surface px-2 py-1.5" />
                <Button size="sm" variant="secondary" icon={Plus} disabled={!Number(change)} onClick={() => adjust.mutate(String(Math.abs(Number(change))))} aria-label="Add to stock">
                  In
                </Button>
                <Button size="sm" variant="secondary" icon={Minus} disabled={!Number(change)} onClick={() => adjust.mutate(String(-Math.abs(Number(change))))} aria-label="Remove from stock">
                  Out
                </Button>
              </span>
            </div>
          )}
        </div>
      ) : (
        <p className="tabular text-sm text-ink">
          {formatMoney(variant.price, "NPR")} {product.track_inventory && `· ${formatQty(variant.stock)} in stock`}
        </p>
      )}
    </li>
  );
}

function ProductRow({ product, canEdit }: { product: Product; canEdit: boolean }) {
  const [open, setOpen] = useState(false);
  const prices = product.variants.map((v) => Number(v.price ?? 0));
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const totalStock = product.track_inventory ? product.variants.reduce((sum, v) => sum + Number(v.stock ?? 0), 0) : null;
  const warning = product.variants.map(stockState).find((s) => s.tone === "danger") ?? product.variants.map(stockState).find((s) => s.tone);
  return (
    <li className="border-b border-line last:border-b-0">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex w-full items-center gap-3 px-4 py-3 text-left hover:bg-sunken/60">
        <span className="grid size-10 shrink-0 place-items-center rounded-control bg-primary-soft text-primary">
          <Package className="size-5" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2">
            <span className="truncate font-medium text-ink">{product.name}</span>
            {!product.is_active && <Pill>Hidden</Pill>}
            {warning?.tone && <Pill tone={warning.tone}>{warning.label}</Pill>}
          </span>
          <span className="tabular block text-sm text-ink-muted">
            {low === high ? formatMoney(low, "NPR") : `${formatMoney(low, "NPR")} – ${formatMoney(high, "NPR")}`}
            {product.variants.length > 1 && ` · ${product.variants.length} options`}
            {totalStock !== null && ` · ${formatQty(String(totalStock))} ${product.unit} in stock`}
          </span>
        </span>
        <ChevronDown className={cx("size-5 text-ink-subtle transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open && (
        <ul className="bg-paper/60">
          {product.variants.map((v) => (
            <VariantRow key={v.id} product={product} variant={v} canEdit={canEdit} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function ProductsView() {
  const me = useMe();
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const search = useDeferredValue(q.trim());
  const products = useQuery({
    queryKey: ["products", search],
    queryFn: () => api<{ items: Product[] }>("tenant", "GET", `/api/v1/products?limit=100&q=${encodeURIComponent(search)}`),
  });
  const canEdit = me.data?.permissions.includes("product.write") ?? false;

  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader
        title="Products"
        description="What you sell, with prices and stock. Orders use these prices."
        actions={canEdit && <Button icon={Plus} onClick={() => setAdding(true)}>Add product</Button>}
      />
      <div className="relative mb-4">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-ink-subtle" aria-hidden />
        <label htmlFor="product-search" className="sr-only">
          Search products
        </label>
        <input
          id="product-search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name or code"
          className="w-full rounded-control border border-line-strong bg-surface py-2.5 pr-3 pl-10 text-base text-ink placeholder:text-ink-subtle focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
        />
      </div>
      {products.isPending ? null : products.data?.items.length === 0 ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState
            icon={Package}
            title={search ? `Nothing matches "${search}"` : "No products yet"}
            action={!search && canEdit ? <Button icon={Plus} onClick={() => setAdding(true)}>Add your first product</Button> : undefined}
          >
            {search ? "Try part of the name or the product code." : "Add what you sell so orders can be created straight from a chat."}
          </EmptyState>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-panel border border-line bg-surface">
          {products.data?.items.map((p) => (
            <ProductRow key={p.id} product={p} canEdit={canEdit} />
          ))}
        </ul>
      )}
      {adding && <AddProduct onClose={() => setAdding(false)} />}
    </main>
  );
}
