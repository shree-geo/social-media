"use client";

/**
 * "Create lead": pick what the customer asked about, who follows up and when. Opened from a
 * chat (customer and channel come from it), a customer's page, or the Leads page.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { CalendarClock, Minus, PenLine, Plus, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Modal } from "@/components/fulfilment";
import { CustomerPicker, INPUT, INPUT_BASE, ProductPicker } from "@/components/pickers";
import { useMe } from "@/components/tenant-shell";
import { Alert, Avatar, Button, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { followupPresets, fromLocalInput, toLocalInput, type Lead, type StaffMember } from "@/lib/leads";
import { LEAD_LABEL, SOURCE_LABEL, formatMoney } from "@/lib/sales";

type Item = { key: string; variant_id: string | null; name: string; quantity: string; unit_price: string };

export type LeadSheetProps = {
  conversationId?: string;
  customer?: { id: string; display_name: string } | null;
  /** Chat's assignee (default owner) when opened from a chat. */
  chatAssigneeId?: string | null;
  initialNote?: string;
  onClose: () => void;
  onCreated?: (lead: Lead) => void;
};

function Stepper({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  const n = Number(value) || 0;
  return (
    <div className="flex items-center rounded-control border border-line-strong">
      <button type="button" className="grid size-9 place-items-center text-ink-muted hover:bg-sunken" onClick={() => onChange(String(Math.max(1, n - 1)))} aria-label={`Fewer ${label}`}>
        <Minus className="size-4" aria-hidden />
      </button>
      <input className="tabular w-14 border-x border-line bg-surface py-1.5 text-center text-ink focus:outline-none" inputMode="decimal" value={value} onChange={(e) => onChange(e.target.value)} aria-label={`Quantity of ${label}`} />
      <button type="button" className="grid size-9 place-items-center text-ink-muted hover:bg-sunken" onClick={() => onChange(String(n + 1))} aria-label={`More ${label}`}>
        <Plus className="size-4" aria-hidden />
      </button>
    </div>
  );
}

export function LeadSheet({ conversationId, customer: presetCustomer, chatAssigneeId, initialNote, onClose, onCreated }: LeadSheetProps) {
  const router = useRouter();
  const me = useMe();
  const canAssign = me.data?.permissions.includes("lead.assign") ?? false;
  const staff = useQuery({
    queryKey: ["lead-staff"],
    queryFn: () => api<StaffMember[]>("tenant", "GET", "/api/v1/leads/staff"),
    enabled: canAssign,
  });

  const [customer, setCustomer] = useState(presetCustomer ?? null);
  const [source, setSource] = useState("phone");
  const [items, setItems] = useState<Item[]>([]);
  const [freeText, setFreeText] = useState<string | null>(null);
  const [leadSource, setLeadSource] = useState("");
  const defaultOwner = chatAssigneeId ?? me.data?.user_id ?? "";
  const [owner, setOwner] = useState<string | null>(null); // null: default
  const [followup, setFollowup] = useState<string | null>(followupPresets()[0]?.value ?? null);
  const [customTime, setCustomTime] = useState(false);
  const [note, setNote] = useState(initialNote ?? "");
  const [error, setError] = useState<string | null>(null);
  const presets = followupPresets();
  const total = items.reduce((sum, i) => sum + Number(i.quantity || 0) * Number(i.unit_price || 0), 0);

  const save = useMutation({
    mutationFn: () =>
      api<Lead>("tenant", "POST", "/api/v1/leads", {
        ...(conversationId ? { conversation_id: conversationId } : { customer_id: customer?.id, source_channel: source }),
        lead_source: leadSource || null,
        items: items.map((i) => ({
          variant_id: i.variant_id,
          description: i.variant_id ? null : i.name,
          quantity: i.quantity,
          unit_price: i.unit_price === "" ? null : i.unit_price,
        })),
        ...(owner !== null ? { assigned_to_user_id: owner || null } : {}),
        next_followup_at: followup,
        note: note.trim() || null,
      }),
    onSuccess: (lead) => {
      onCreated?.(lead);
      onClose();
    },
    onError: (err) => {
      if (err instanceof ApiError && err.code === "lead_exists" && typeof err.body?.lead_id === "string") {
        router.push(`/leads/${err.body.lead_id}`);
        return;
      }
      setError(err instanceof ApiError ? err.message : "Couldn't save the lead. Check your connection and try again.");
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (!customer && !conversationId) return setError("Choose the customer.");
    if (items.length === 0) return setError("Add at least one product the customer is asking about.");
    if (items.some((i) => !(Number(i.quantity) > 0))) return setError("Each quantity must be more than zero.");
    save.mutate();
  }

  const update = (key: string, patch: Partial<Item>) => setItems((list) => list.map((i) => (i.key === key ? { ...i, ...patch } : i)));

  return (
    <Modal title="New lead" onClose={onClose} wide>
      <form onSubmit={submit} noValidate className="grid gap-5">
        {error && <Alert tone="error">{error}</Alert>}

        {customer ? (
          <div className="flex items-center gap-3">
            <Avatar name={customer.display_name} size="sm" />
            <p className="min-w-0 flex-1 truncate font-medium text-ink">{customer.display_name}</p>
            {!presetCustomer && (
              <button type="button" onClick={() => setCustomer(null)} className="grid size-8 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Change customer">
                <X className="size-4" aria-hidden />
              </button>
            )}
          </div>
        ) : (
          <div>
            <p className="mb-2 text-sm font-medium text-ink">Customer</p>
            <CustomerPicker onPick={setCustomer} />
          </div>
        )}
        {!conversationId && (
          <label className="text-sm">
            <span className="mb-1 block font-medium text-ink">Came by</span>
            <select className={INPUT} value={source} onChange={(e) => setSource(e.target.value)}>
              {["phone", "walk_in", "other"].map((s) => (
                <option key={s} value={s}>
                  {SOURCE_LABEL[s]}
                </option>
              ))}
            </select>
          </label>
        )}

        <div>
          <p className="mb-2 text-sm font-medium text-ink">What do they want?</p>
          {items.length > 0 && (
            <ul className="mb-3 divide-y divide-line rounded-control border border-line">
              {items.map((i) => (
                <li key={i.key} className="flex flex-wrap items-center gap-2 p-2.5">
                  <span className="min-w-0 flex-1 basis-40 text-ink">
                    {i.name}
                    {!i.variant_id && <span className="ml-1.5 text-xs text-ink-subtle">(not in products)</span>}
                  </span>
                  <Stepper value={i.quantity} onChange={(v) => update(i.key, { quantity: v })} label={i.name} />
                  <input
                    className={cx(INPUT_BASE, "tabular w-24 px-2 py-1.5")}
                    inputMode="decimal"
                    placeholder="Price"
                    value={i.unit_price}
                    onChange={(e) => update(i.key, { unit_price: e.target.value })}
                    aria-label={`Price of ${i.name}`}
                  />
                  <button type="button" onClick={() => setItems((list) => list.filter((x) => x.key !== i.key))} className="grid size-9 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label={`Remove ${i.name}`}>
                    <Trash2 className="size-4" aria-hidden />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <ProductPicker
            onPick={(p, v) =>
              setItems((list) => {
                const existing = list.find((x) => x.variant_id === v.id);
                if (existing) return list.map((x) => (x === existing ? { ...x, quantity: String(Number(x.quantity) + 1) } : x));
                const name = p.variants.length > 1 ? `${p.name} (${v.name})` : p.name;
                return [...list, { key: crypto.randomUUID(), variant_id: v.id, name, quantity: "1", unit_price: v.price ?? "" }];
              })
            }
          />
          {freeText === null ? (
            <button type="button" onClick={() => setFreeText("")} className="mt-2 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
              <PenLine className="size-4" aria-hidden />
              Something not in your products
            </button>
          ) : (
            <div className="mt-2 flex gap-2">
              <input className={INPUT} placeholder="e.g. Blue sofa like in the photo" value={freeText} onChange={(e) => setFreeText(e.target.value)} aria-label="Describe the item" autoFocus />
              <Button
                type="button"
                size="sm"
                variant="secondary"
                disabled={!freeText.trim()}
                onClick={() => {
                  setItems((list) => [...list, { key: crypto.randomUUID(), variant_id: null, name: freeText.trim(), quantity: "1", unit_price: "" }]);
                  setFreeText(null);
                }}
              >
                Add
              </Button>
            </div>
          )}
          {total > 0 && <p className="tabular mt-2 text-sm text-ink-muted">Worth about {formatMoney(total, "NPR")}</p>}
        </div>

        <div>
          <p className="mb-2 flex items-center gap-1.5 text-sm font-medium text-ink">
            <CalendarClock className="size-4" aria-hidden />
            Follow up
          </p>
          <div className="flex flex-wrap gap-2">
            {presets.map((p) => (
              <Button key={p.label} type="button" size="sm" variant={!customTime && followup === p.value ? "primary" : "secondary"} onClick={() => { setCustomTime(false); setFollowup(p.value); }}>
                {p.label}
              </Button>
            ))}
            <Button type="button" size="sm" variant={customTime ? "primary" : "secondary"} onClick={() => setCustomTime(true)}>
              Pick time
            </Button>
            <Button type="button" size="sm" variant={!customTime && followup === null ? "primary" : "secondary"} onClick={() => { setCustomTime(false); setFollowup(null); }}>
              No reminder
            </Button>
          </div>
          {customTime && (
            <input type="datetime-local" className={cx(INPUT, "mt-2")} value={toLocalInput(followup)} onChange={(e) => setFollowup(fromLocalInput(e.target.value))} aria-label="Follow-up time" />
          )}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          {canAssign && (
            <label className="text-sm">
              <span className="mb-1 block font-medium text-ink">Who follows up</span>
              <select className={INPUT} value={owner ?? defaultOwner} onChange={(e) => setOwner(e.target.value)}>
                <option value="">Nobody yet</option>
                {staff.data?.map((s) => (
                  <option key={s.user_id} value={s.user_id}>
                    {s.full_name}
                    {s.user_id === me.data?.user_id ? " (you)" : ""}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="text-sm">
            <span className="mb-1 block font-medium text-ink">How did they find you?</span>
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

        <label className="text-sm">
          <span className="mb-1 block font-medium text-ink">Note (optional)</span>
          <textarea className={cx(INPUT, "min-h-16")} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Delivery to Itahari, wants black colour…" />
        </label>

        <div className="flex justify-end gap-3">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={save.isPending} disabled={items.length === 0}>
            Save lead
          </Button>
        </div>
      </form>
    </Modal>
  );
}
