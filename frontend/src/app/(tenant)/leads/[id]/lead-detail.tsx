"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertCircle,
  ArrowLeft,
  CalendarClock,
  Check,
  MessagesSquare,
  PenLine,
  RotateCcw,
  ShoppingBag,
  Trash2,
  UserRound,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { LostDialog, leadErrorText, useLeadRefresh, useStageChange } from "@/components/lead-actions";
import { INPUT, INPUT_BASE, ProductPicker } from "@/components/pickers";
import { useMe } from "@/components/tenant-shell";
import { Alert, Avatar, Button, EmptyState, Panel, Pill, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import {
  LOST_REASON_LABEL,
  OPEN_STAGES,
  STAGE_LABEL,
  STAGE_TONE,
  followupPresets,
  followupText,
  fromLocalInput,
  isOpen,
  toLocalInput,
  type Lead,
  type LeadActivity,
  type StaffMember,
} from "@/lib/leads";
import { LEAD_LABEL, SOURCE_LABEL, formatMoney, formatQty } from "@/lib/sales";

type EditItem = { key: string; variant_id: string | null; description: string; quantity: string; unit_price: string };

function usePatch(lead: Lead) {
  const refresh = useLeadRefresh();
  return useMutation({
    // Only product edits check the version: two people editing the list at once would overwrite each other.
    mutationFn: (body: Record<string, unknown>) =>
      api<Lead>("tenant", "PATCH", `/api/v1/leads/${lead.id}`, "items" in body ? { ...body, version: lead.version } : body),
    onSettled: () => refresh(lead),
  });
}

function StageStepper({ lead, canWrite }: { lead: Lead; canWrite: boolean }) {
  const change = useStageChange(lead);
  const current = OPEN_STAGES.indexOf(lead.stage);
  const open = isOpen(lead.stage);
  return (
    <div>
      <ol className="grid grid-cols-4 gap-1.5" aria-label="Stage">
        {OPEN_STAGES.map((stage, i) => {
          const done = open ? i < current : lead.stage === "WON";
          const here = stage === lead.stage;
          return (
            <li key={stage}>
              <button
                type="button"
                disabled={!canWrite || !open || here || change.isPending}
                onClick={() => change.mutate({ stage })}
                aria-current={here ? "step" : undefined}
                className={cx(
                  "flex w-full flex-col items-start gap-1 rounded-control border-t-4 px-2 pt-2 pb-1 text-left text-sm transition-colors",
                  here ? "border-primary font-semibold text-primary" : done ? "border-primary/40 text-ink-muted" : "border-line text-ink-subtle",
                  canWrite && open && !here && "hover:bg-sunken",
                )}
              >
                <span className="flex items-center gap-1">
                  {done && <Check className="size-3.5" aria-hidden />}
                  {STAGE_LABEL[stage]}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
      {change.isError && <p className="mt-2 text-sm text-danger">{leadErrorText(change.error)}</p>}
    </div>
  );
}

function ItemsPanel({ lead, canWrite }: { lead: Lead; canWrite: boolean }) {
  const patch = usePatch(lead);
  const [editing, setEditing] = useState<EditItem[] | null>(null);
  const [freeText, setFreeText] = useState("");
  const open = isOpen(lead.stage);

  const start = () =>
    setEditing(
      lead.items.map((i) => ({
        key: i.id,
        variant_id: i.variant_id,
        description: i.description,
        quantity: formatQty(i.quantity).replace(/,/g, ""),
        unit_price: i.unit_price,
      })),
    );
  const update = (key: string, p: Partial<EditItem>) => setEditing((list) => list?.map((i) => (i.key === key ? { ...i, ...p } : i)) ?? null);

  function save() {
    if (!editing || editing.length === 0) return;
    patch.mutate(
      {
        items: editing.map((i) => ({
          variant_id: i.variant_id,
          description: i.variant_id ? null : i.description,
          quantity: i.quantity,
          unit_price: i.unit_price === "" ? null : i.unit_price,
        })),
      },
      { onSuccess: () => setEditing(null) },
    );
  }

  return (
    <Panel
      title="What they want"
      actions={
        canWrite && open && !editing ? (
          <Button size="sm" variant="secondary" icon={PenLine} onClick={start}>
            Edit
          </Button>
        ) : undefined
      }
    >
      {patch.isError && <Alert tone="error">{leadErrorText(patch.error)}</Alert>}
      {editing ? (
        <div className="grid gap-3">
          <ul className="divide-y divide-line rounded-control border border-line">
            {editing.map((i) => (
              <li key={i.key} className="flex flex-wrap items-center gap-2 p-2.5">
                <span className="min-w-0 flex-1 basis-40 text-ink">
                  {i.description}
                  {!i.variant_id && <span className="ml-1.5 text-xs text-ink-subtle">(not in products)</span>}
                </span>
                <input className={cx(INPUT_BASE, "tabular w-20 px-2 py-1.5")} inputMode="decimal" value={i.quantity} onChange={(e) => update(i.key, { quantity: e.target.value })} aria-label={`Quantity of ${i.description}`} />
                <input className={cx(INPUT_BASE, "tabular w-24 px-2 py-1.5")} inputMode="decimal" value={i.unit_price} onChange={(e) => update(i.key, { unit_price: e.target.value })} aria-label={`Price of ${i.description}`} />
                <button type="button" onClick={() => setEditing((list) => list?.filter((x) => x.key !== i.key) ?? null)} className="grid size-9 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label={`Remove ${i.description}`}>
                  <Trash2 className="size-4" aria-hidden />
                </button>
              </li>
            ))}
          </ul>
          <ProductPicker
            onPick={(p, v) =>
              setEditing((list) => [
                ...(list ?? []),
                { key: crypto.randomUUID(), variant_id: v.id, description: p.variants.length > 1 ? `${p.name} (${v.name})` : p.name, quantity: "1", unit_price: v.price ?? "" },
              ])
            }
          />
          <div className="flex gap-2">
            <input className={INPUT} placeholder="Or describe something not in your products" value={freeText} onChange={(e) => setFreeText(e.target.value)} aria-label="Describe an item" />
            <Button
              type="button"
              size="sm"
              variant="secondary"
              disabled={!freeText.trim()}
              onClick={() => {
                setEditing((list) => [...(list ?? []), { key: crypto.randomUUID(), variant_id: null, description: freeText.trim(), quantity: "1", unit_price: "" }]);
                setFreeText("");
              }}
            >
              Add
            </Button>
          </div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button type="button" loading={patch.isPending} disabled={editing.length === 0} onClick={save}>
              Save
            </Button>
          </div>
        </div>
      ) : (
        <>
          <ul className="divide-y divide-line">
            {lead.items.map((i) => (
              <li key={i.id} className="flex items-baseline justify-between gap-3 py-2">
                <span className="text-ink">
                  <span className="tabular font-medium">{formatQty(i.quantity)} ×</span> {i.description}
                  {!i.variant_id && <span className="ml-1.5 text-xs text-ink-subtle">(not in products)</span>}
                </span>
                <span className="tabular text-sm text-ink-muted">
                  {Number(i.unit_price) > 0 ? formatMoney(Number(i.unit_price) * Number(i.quantity), lead.currency) : "No price yet"}
                </span>
              </li>
            ))}
          </ul>
          <p className="tabular mt-3 flex justify-between border-t border-line pt-3 font-semibold text-ink">
            <span>Expected value</span>
            {formatMoney(lead.expected_value, lead.currency)}
          </p>
        </>
      )}
    </Panel>
  );
}

function FollowupPanel({ lead, canWrite }: { lead: Lead; canWrite: boolean }) {
  const patch = usePatch(lead);
  const [custom, setCustom] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const due = followupText(lead.next_followup_at);
  const open = isOpen(lead.stage);
  return (
    <Panel title="Next follow-up">
      {patch.isError && <Alert tone="error">{leadErrorText(patch.error)}</Alert>}
      {due ? (
        <p className={cx("flex items-center gap-2 text-lg", due.overdue ? "font-semibold text-danger" : "text-ink")}>
          <CalendarClock className="size-5" aria-hidden />
          {due.overdue ? `Overdue: ${due.text}` : due.text}
        </p>
      ) : (
        <p className="text-ink-muted">{open ? "No follow-up set." : "Closed leads don't need follow-up."}</p>
      )}
      {lead.followup_note && <p className="mt-1 text-sm text-ink-muted">{lead.followup_note}</p>}
      {canWrite && open && (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            {followupPresets().map((p) => (
              <Button key={p.label} size="sm" variant="secondary" loading={patch.isPending && patch.variables?.next_followup_at === p.value} onClick={() => patch.mutate({ next_followup_at: p.value })}>
                {p.label}
              </Button>
            ))}
            <Button size="sm" variant="secondary" onClick={() => setCustom((c) => !c)}>
              Pick time
            </Button>
            {lead.next_followup_at && (
              <Button size="sm" variant="ghost" onClick={() => patch.mutate({ next_followup_at: null })}>
                Clear
              </Button>
            )}
          </div>
          {custom && (
            <input
              type="datetime-local"
              className={cx(INPUT, "mt-2")}
              defaultValue={toLocalInput(lead.next_followup_at)}
              onBlur={(e) => e.target.value && patch.mutate({ next_followup_at: fromLocalInput(e.target.value) })}
              aria-label="Follow-up time"
            />
          )}
          <form
            className="mt-3 flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (note !== null) patch.mutate({ followup_note: note.trim() || null }, { onSuccess: () => setNote(null) });
            }}
          >
            <input className={INPUT} placeholder="What to follow up about (optional)" value={note ?? lead.followup_note ?? ""} onChange={(e) => setNote(e.target.value)} aria-label="Follow-up note" />
            {note !== null && (
              <Button type="submit" size="sm" loading={patch.isPending}>
                Save
              </Button>
            )}
          </form>
        </>
      )}
    </Panel>
  );
}

function OwnerPanel({ lead }: { lead: Lead }) {
  const me = useMe();
  const refresh = useLeadRefresh();
  const canAssign = me.data?.permissions.includes("lead.assign") ?? false;
  const canWrite = me.data?.permissions.includes("lead.write") ?? false;
  const staff = useQuery({
    queryKey: ["lead-staff"],
    queryFn: () => api<StaffMember[]>("tenant", "GET", "/api/v1/leads/staff"),
    enabled: canAssign,
  });
  const assign = useMutation({
    mutationFn: (userId: string | null) => api<Lead>("tenant", "POST", `/api/v1/leads/${lead.id}/assign`, { user_id: userId }),
    onSettled: () => refresh(lead),
  });
  const patch = usePatch(lead);
  const open = isOpen(lead.stage);
  return (
    <Panel title="Details">
      {(assign.isError || patch.isError) && <Alert tone="error">{leadErrorText(assign.error ?? patch.error)}</Alert>}
      <dl className="grid gap-3 text-sm">
        <div>
          <dt className="text-ink-muted">Who follows up</dt>
          <dd className="mt-1">
            {canAssign && open ? (
              <select
                className={INPUT}
                value={lead.assigned_to?.id ?? ""}
                disabled={assign.isPending}
                onChange={(e) => assign.mutate(e.target.value || null)}
                aria-label="Who follows up"
              >
                <option value="">Nobody yet</option>
                {staff.data?.map((s) => (
                  <option key={s.user_id} value={s.user_id}>
                    {s.full_name}
                    {s.user_id === me.data?.user_id ? " (you)" : ""}
                  </option>
                ))}
              </select>
            ) : (
              <span className="flex items-center gap-2 text-base text-ink">
                {lead.assigned_to?.full_name ?? "Nobody yet"}
                {!lead.assigned_to && canWrite && open && (
                  <Button size="sm" variant="secondary" loading={assign.isPending} onClick={() => assign.mutate(me.data?.user_id ?? null)}>
                    Take it
                  </Button>
                )}
              </span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-ink-muted">Came by</dt>
          <dd className="text-base text-ink">{SOURCE_LABEL[lead.source_channel] ?? lead.source_channel}</dd>
        </div>
        <div>
          <dt className="text-ink-muted">How they found you</dt>
          <dd className="mt-1">
            {canWrite && open ? (
              <select className={INPUT} value={lead.lead_source ?? ""} onChange={(e) => patch.mutate({ lead_source: e.target.value || null })} aria-label="How they found you">
                <option value="">Don&apos;t know</option>
                {Object.entries(LEAD_LABEL).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-base text-ink">{lead.lead_source ? LEAD_LABEL[lead.lead_source] : "Don't know"}</span>
            )}
          </dd>
        </div>
        <div>
          <dt className="text-ink-muted">Created</dt>
          <dd className="text-base text-ink">
            {new Date(lead.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
            {lead.created_by && <span className="text-ink-muted"> by {lead.created_by.full_name}</span>}
          </dd>
        </div>
      </dl>
    </Panel>
  );
}

function describe(a: LeadActivity, currency: string): string {
  switch (a.event) {
    case "created":
      return "Created the lead";
    case "stage_changed":
      return `Moved from ${STAGE_LABEL[a.from_value ?? ""] ?? a.from_value} to ${STAGE_LABEL[a.to_value ?? ""] ?? a.to_value}`;
    case "assigned":
      return a.to_value ? `Gave it to ${a.to_value}` : "Removed the owner";
    case "note":
      return "Note";
    case "followup_set":
      return a.to_value ? `Follow-up set for ${new Date(a.to_value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}` : "Cleared the follow-up";
    case "items_changed":
      return `Changed the products (now ${formatMoney(a.to_value, currency)})`;
    case "converted":
      return `Turned it into order ${a.to_value}`;
    case "lost":
      return `Marked lost: ${LOST_REASON_LABEL[a.to_value ?? ""] ?? a.to_value}`;
    case "reopened":
      return `Reopened as ${STAGE_LABEL[a.to_value ?? ""] ?? a.to_value}`;
  }
}

function Timeline({ lead, canWrite }: { lead: Lead; canWrite: boolean }) {
  const refresh = useLeadRefresh();
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api<Lead>("tenant", "POST", `/api/v1/leads/${lead.id}/notes`, { body: text.trim() }),
    onSuccess: () => setText(""),
    onSettled: () => refresh(lead),
  });
  return (
    <Panel title="Timeline">
      {canWrite && (
        <form
          className="mb-4 flex gap-2"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (text.trim()) add.mutate();
          }}
        >
          <input className={INPUT} placeholder="Add a note: called, sent photos, will visit Friday…" value={text} onChange={(e) => setText(e.target.value)} aria-label="Note" />
          <Button type="submit" size="sm" loading={add.isPending} disabled={!text.trim()}>
            Add
          </Button>
        </form>
      )}
      <ol className="space-y-3">
        {lead.activities.map((a) => (
          <li key={a.id} className="flex gap-3">
            <span className="mt-1.5 size-2 shrink-0 rounded-full bg-line-strong" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-ink">
                {describe(a, lead.currency)}
                {a.body && a.event !== "note" && <span className="text-ink-muted"> — {a.body}</span>}
              </p>
              {a.event === "note" && a.body && <p className="mt-0.5 rounded-control bg-sunken px-3 py-2 whitespace-pre-wrap text-ink">{a.body}</p>}
              <p className="text-xs text-ink-subtle">
                {a.actor?.full_name ?? "System"} · {new Date(a.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </Panel>
  );
}

export function LeadDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const canWrite = me.data?.permissions.includes("lead.write") ?? false;
  const canOrder = me.data?.permissions.includes("order.write") ?? false;
  const canChat = me.data?.permissions.includes("conversation.read") ?? false;
  const [losing, setLosing] = useState(false);
  const lead = useQuery({
    queryKey: ["lead", id],
    queryFn: () => api<Lead>("tenant", "GET", `/api/v1/leads/${id}`),
  });
  const reopen = useStageChange(lead.data ?? { id, version: 0, conversation_id: null });

  if (lead.isPending) return <Spinner />;
  if (!lead.data)
    return (
      <EmptyState icon={AlertCircle} title="This lead isn't available">
        It may have been removed, or you may not have access to it.
      </EmptyState>
    );
  const l = lead.data;
  const open = isOpen(l.stage);

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href="/leads" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Leads
      </Link>
      <header className="mb-6 flex flex-wrap items-center gap-4">
        <Avatar name={l.customer.display_name} size="lg" />
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-ink sm:text-2xl">{l.customer.display_name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-ink-muted">
            <span className="tabular">{l.lead_number}</span>
            <Pill tone={STAGE_TONE[l.stage]}>{STAGE_LABEL[l.stage]}</Pill>
            <span className="tabular">{formatMoney(l.expected_value, l.currency)}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {l.conversation_id && canChat && (
            <Link href={`/inbox/${l.conversation_id}`} className="inline-flex min-h-11 items-center gap-2 rounded-control border border-line-strong px-4 text-ink hover:bg-sunken">
              <MessagesSquare className="size-4" aria-hidden />
              Open chat
            </Link>
          )}
          <Link href={`/customers/${l.customer.id}`} className="inline-flex min-h-11 items-center gap-2 rounded-control border border-line-strong px-4 text-ink hover:bg-sunken">
            <UserRound className="size-4" aria-hidden />
            Customer
          </Link>
          {open && canOrder && (
            <Link href={`/orders/new?lead=${l.id}`} className="inline-flex min-h-11 items-center gap-2 rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover">
              <ShoppingBag className="size-4" aria-hidden />
              Convert to order
            </Link>
          )}
        </div>
      </header>

      {l.stage === "WON" && l.won_order && (
        <Alert tone="success" title="Won">
          This lead became order{" "}
          <Link href={`/orders/${l.won_order.id}`} className="font-medium underline">
            {l.won_order.order_number}
          </Link>
          .
        </Alert>
      )}
      {l.stage === "LOST" && (
        <Alert tone="warning" title={`Lost: ${LOST_REASON_LABEL[l.lost_reason ?? ""] ?? l.lost_reason}`}>
          {l.lost_note && <span className="block">{l.lost_note}</span>}
          {canWrite && (
            <Button size="sm" variant="secondary" icon={RotateCcw} className="mt-2" loading={reopen.isPending} onClick={() => reopen.mutate({ stage: "CONTACTED" })}>
              Reopen
            </Button>
          )}
          {reopen.isError && <span className="mt-2 block text-danger">{leadErrorText(reopen.error)}</span>}
        </Alert>
      )}

      {open && (
        <div className="mb-6 flex flex-wrap items-end gap-3">
          <div className="min-w-0 flex-1">
            <StageStepper lead={l} canWrite={canWrite} />
          </div>
          {canWrite && (
            <Button variant="ghost" icon={XCircle} onClick={() => setLosing(true)}>
              Mark lost
            </Button>
          )}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="grid content-start gap-6">
          <ItemsPanel lead={l} canWrite={canWrite} />
          <Timeline lead={l} canWrite={canWrite} />
        </div>
        <div className="grid content-start gap-6">
          <FollowupPanel lead={l} canWrite={canWrite} />
          <OwnerPanel lead={l} />
        </div>
      </div>
      {losing && <LostDialog lead={l} onClose={() => setLosing(false)} />}
    </main>
  );
}
