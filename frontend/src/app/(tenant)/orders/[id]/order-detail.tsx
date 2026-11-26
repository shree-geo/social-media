"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, FileText, MessageCircle, Plus, ReceiptText, Truck, Undo2, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState, type FormEvent, type ReactNode } from "react";

import { ContactLine, DeliveryActions, Modal, NewDeliveryForm, RecordPaymentForm, VoidPaymentForm } from "@/components/fulfilment";
import { useMe } from "@/components/tenant-shell";
import { Alert, Button, Panel, Pill, Spinner, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { bsDate, bsDay, clock, dateTime, shortDay } from "@/lib/dates";
import {
  DELIVERY_METHOD_LABEL,
  DELIVERY_STATUS_LABEL,
  DELIVERY_TONE,
  LEAD_LABEL,
  NEEDS_REASON,
  PAYMENT_METHOD_LABEL,
  PAYMENT_LABEL,
  PAYMENT_TONE,
  SOURCE_LABEL,
  STATUS_ACTION,
  STATUS_LABEL,
  STATUS_TONE,
  formatMoney,
  formatQty,
  addressText,
  type Order,
  type Payment,
} from "@/lib/sales";

function ReasonDialog({ title, confirmLabel, onSubmit, onClose, busy }: {
  title: string;
  confirmLabel: string;
  onSubmit: (reason: string) => void;
  onClose: () => void;
  busy: boolean;
}) {
  const [reason, setReason] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (reason.trim().length >= 3) onSubmit(reason.trim());
  }
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="reason-title">
      <form onSubmit={submit} className="w-full max-w-md rounded-panel bg-surface p-5 shadow-xl">
        <div className="mb-3 flex items-start justify-between gap-3">
          <h2 id="reason-title" className="text-lg font-semibold text-ink">
            {title}
          </h2>
          <button type="button" onClick={onClose} className="grid size-9 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Close">
            <X className="size-4" aria-hidden />
          </button>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-ink">Reason</span>
          <textarea
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="min-h-24 w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-base text-ink focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
            placeholder="For example: customer changed their mind"
          />
        </label>
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Keep it
          </Button>
          <Button type="submit" variant="danger" loading={busy} disabled={reason.trim().length < 3}>
            {confirmLabel}
          </Button>
        </div>
      </form>
    </div>
  );
}

const STEP_RANK: Record<string, number> = {
  NEW: 0,
  CONFIRMED: 1,
  PROCESSING: 2,
  READY_FOR_DELIVERY: 3,
  OUT_FOR_DELIVERY: 4,
  DELIVERED: 5,
};

const STEPS = [
  { label: "New", statuses: ["NEW"] },
  { label: "Confirmed", statuses: ["CONFIRMED", "PROCESSING"] },
  { label: "Ready", statuses: ["READY_FOR_DELIVERY"] },
  { label: "Out for delivery", statuses: ["OUT_FOR_DELIVERY"] },
  { label: "Delivered", statuses: ["DELIVERED"] },
];

/** Where the order is in its flow, with when each step happened. */
function Progress({ order }: { order: Order }) {
  const reached = (statuses: string[]) => order.history.filter((h) => statuses.includes(h.to_status)).at(-1)?.at ?? null;
  const currentIndex = STEPS.findIndex((s) => s.statuses.includes(order.status));
  const lastGood = Math.max(
    currentIndex,
    ...STEPS.map((s, i) => (reached(s.statuses) ? i : -1)),
  );
  const stoppedAt = ["CANCELLED", "REJECTED", "RETURNED"].includes(order.status) ? order.history.at(-1) : null;
  return (
    <section aria-label="Order progress" className="rounded-panel border border-line bg-surface px-5 py-4">
      <ol className="grid grid-cols-5 gap-2">
        {STEPS.map((step, i) => {
          const at = reached(step.statuses);
          const done = i < lastGood || (i === lastGood && step.statuses.includes("DELIVERED") && !!at);
          const current = !stoppedAt && i === currentIndex && !done;
          return (
            <li key={step.label} className="relative min-w-0 pt-5" aria-current={current ? "step" : undefined}>
              <span className={cx("absolute top-[5px] right-0 left-0 h-[3px] rounded-full", i <= lastGood ? "bg-stage-ready" : "bg-line")} aria-hidden />
              <span
                className={cx(
                  "absolute top-0 left-0 size-[13px] rounded-full border-2",
                  done ? "border-stage-ready bg-stage-ready" : current ? "border-stage-ready bg-surface ring-4 ring-stage-ready-soft" : "border-line-strong bg-surface",
                )}
                aria-hidden
              />
              <p className={cx("truncate text-xs sm:text-sm", done || current ? "font-semibold text-ink" : "text-ink-subtle")}>{step.label}</p>
              <p className="truncate text-xs text-ink-subtle max-sm:hidden">{at ? `${shortDay(at)}, ${clock(at)}` : done || current ? "" : "Not yet"}</p>
            </li>
          );
        })}
      </ol>
      {stoppedAt && (
        <p className="mt-3 rounded-control bg-stage-bad-soft px-3 py-2 text-sm text-stage-bad">
          <strong className="font-semibold">{STATUS_LABEL[order.status]}</strong> {shortDay(stoppedAt.at)}
          {stoppedAt.reason && `: ${stoppedAt.reason}`}
        </p>
      )}
    </section>
  );
}

function SideBox({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-panel border border-line bg-surface px-5 py-4">
      <header className="mb-2 flex items-center justify-between gap-3">
        <h2 className="font-semibold text-ink">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

/** Less common steps (skip ahead, cancel) live here so the main button stays obvious. */
function MoreMenu({ actions }: { actions: { key: string; label: string; danger: boolean; run: () => void }[] }) {
  const ref = useRef<HTMLDetailsElement>(null);
  return (
    <details ref={ref} className="relative">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center gap-1.5 rounded-control border border-line-strong bg-surface px-4 font-medium text-ink hover:bg-sunken">
        More
        <ChevronDown className="size-4" aria-hidden />
      </summary>
      <ul className="absolute right-0 z-30 mt-1 w-60 overflow-hidden rounded-panel border border-line bg-surface py-1 shadow-lg">
        {actions.map((a) => (
          <li key={a.key}>
            <button
              type="button"
              onClick={() => {
                ref.current?.removeAttribute("open");
                a.run();
              }}
              className={cx("w-full px-4 py-2 text-left text-sm hover:bg-sunken", a.danger ? "text-danger" : "text-ink")}
            >
              {a.label}
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<{ kind: "status"; status: string } | { kind: "invoice"; invoiceId: string } | null>(null);
  const [sheet, setSheet] = useState<"delivery" | "payment" | "refund" | { void: Payment } | null>(null);
  const can = (p: string) => me.data?.permissions.includes(p) ?? false;

  const order = useQuery({ queryKey: ["order", id], queryFn: () => api<Order>("tenant", "GET", `/api/v1/orders/${id}`) });

  const onError = (err: unknown) => setError(err instanceof ApiError ? err.message : "That didn't work. Check your connection and try again.");
  const refresh = () => {
    setError(null);
    setAsking(null);
    void queryClient.invalidateQueries({ queryKey: ["orders"] });
    void queryClient.invalidateQueries({ queryKey: ["order", id] });
    void queryClient.invalidateQueries({ queryKey: ["deliveries"] });
    void queryClient.invalidateQueries({ queryKey: ["payments"] });
  };

  const move = useMutation({
    mutationFn: (v: { status: string; reason?: string }) => api<Order>("tenant", "POST", `/api/v1/orders/${id}/status`, v),
    onSuccess: (data) => {
      queryClient.setQueryData(["order", id], data);
      refresh();
    },
    onError,
  });
  const issue = useMutation({ mutationFn: () => api("tenant", "POST", `/api/v1/orders/${id}/invoice`), onSuccess: refresh, onError });
  const cancelInvoice = useMutation({
    mutationFn: (v: { invoiceId: string; reason: string }) => api("tenant", "POST", `/api/v1/invoices/${v.invoiceId}/cancel`, { reason: v.reason }),
    onSuccess: refresh,
    onError,
  });

  if (order.isPending) return <Spinner />;
  if (order.isError) {
    return (
      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8">
        <Alert tone="error">We couldn&apos;t open this order.</Alert>
      </main>
    );
  }

  const o = order.data;
  const t = o.totals;
  const forward = o.allowed_next.filter((s) => !NEEDS_REASON.has(s));
  // A delivered order is returned from its delivery card, which keeps both records in step.
  const delivered = o.deliveries.some((d) => d.status === "DELIVERED");
  const stops = o.allowed_next.filter((s) => NEEDS_REASON.has(s) && !(s === "RETURNED" && delivered));
  const liveInvoice = o.invoices.find((v) => v.status === "ISSUED");
  const canInvoice = can("invoice.write") && !liveInvoice && !["NEW", "CANCELLED", "REJECTED"].includes(o.status);
  const openDelivery = o.deliveries.find((d) => !["DELIVERED", "FAILED", "RETURNED", "CANCELLED"].includes(d.status));
  const address = o.delivery_address ? Object.values(o.delivery_address).filter(Boolean).join(", ") : null;
  const due = Number(t.amount_due);
  const paid = Number(t.amount_paid);
  const total = Number(t.grand_total);
  const stopped = ["CANCELLED", "REJECTED", "RETURNED"].includes(o.status);
  const canSendDelivery =
    can("delivery.write") && !openDelivery && ["CONFIRMED", "PROCESSING", "READY_FOR_DELIVERY"].includes(o.status);
  const canRecordPayment = can("payment.write") && due > 0 && !["CANCELLED", "REJECTED"].includes(o.status);

  // One primary action: the next step in the flow. Everything else goes under "More".
  const ranked = [...forward].sort((x, y) => STEP_RANK[x] - STEP_RANK[y]);
  const primary: { label: string; icon?: typeof Truck; run: () => void; busy?: boolean } | null = !can("order.write")
    ? canSendDelivery
      ? { label: "Send for delivery", icon: Truck, run: () => setSheet("delivery") }
      : null
    : o.status === "READY_FOR_DELIVERY" && canSendDelivery
      ? { label: "Send for delivery", icon: Truck, run: () => setSheet("delivery") }
      : ranked[0]
        ? {
            label: STATUS_ACTION[ranked[0]] ?? STATUS_LABEL[ranked[0]],
            run: () => move.mutate({ status: ranked[0] }),
            busy: move.isPending && move.variables?.status === ranked[0],
          }
        : canSendDelivery
          ? { label: "Send for delivery", icon: Truck, run: () => setSheet("delivery") }
          : null;
  const moreActions = [
    ...(can("order.write") ? ranked.filter((s) => primary?.label !== (STATUS_ACTION[s] ?? STATUS_LABEL[s])) : []).map((s) => ({
      key: s,
      label: STATUS_ACTION[s] ?? STATUS_LABEL[s],
      danger: false,
      run: () => move.mutate({ status: s }),
    })),
    ...(canSendDelivery && primary?.label !== "Send for delivery"
      ? [{ key: "delivery", label: "Send for delivery", danger: false, run: () => setSheet("delivery") }]
      : []),
    ...(can("order.write") ? stops : []).map((s) => ({
      key: s,
      label: STATUS_ACTION[s] ?? STATUS_LABEL[s],
      danger: true,
      run: () => setAsking({ kind: "status", status: s }),
    })),
  ];
  const placedAt = o.history[0]?.at;

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href="/orders" className="mb-3 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Orders
      </Link>

      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <h1 className="font-display tabular text-2xl font-semibold text-ink sm:text-[2rem]">{o.order_number}</h1>
            <Pill tone={STATUS_TONE[o.status]}>{STATUS_LABEL[o.status] ?? o.status}</Pill>
          </div>
          <p className="mt-1 text-ink-muted">
            <Link href={`/customers/${o.customer.id}`} className="font-medium text-ink hover:underline">
              {o.customer.display_name}
            </Link>
            , {SOURCE_LABEL[o.source_channel] ?? o.source_channel}
            {placedAt && <>. Ordered {shortDay(placedAt)}</>}
            {o.lead_source && <>. Found you via {LEAD_LABEL[o.lead_source] ?? o.lead_source}</>}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {o.source_conversation_id && (
            <Link
              href={`/inbox/${o.source_conversation_id}`}
              className="inline-flex min-h-11 items-center gap-2 rounded-control border border-line-strong bg-surface px-4 font-medium text-ink hover:bg-sunken"
            >
              <MessageCircle className="size-4" aria-hidden />
              Open chat
            </Link>
          )}
          {moreActions.length > 0 && <MoreMenu actions={moreActions} />}
          {primary && (
            <Button icon={primary.icon} loading={primary.busy} onClick={primary.run} className="max-sm:order-first max-sm:w-full">
              {primary.label}
            </Button>
          )}
        </div>
      </header>

      {error && <Alert tone="error">{error}</Alert>}

      <Progress order={o} />

      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]">
        <div className="grid min-w-0 gap-6">
          <section className="rounded-panel border border-line bg-surface" aria-label="Items">
            <div className="overflow-x-auto">
              <table className="tabular w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs font-semibold text-ink-muted">
                    <th className="px-5 py-3 font-semibold">Item</th>
                    <th className="px-3 py-3 text-right font-semibold">Qty</th>
                    <th className="px-3 py-3 text-right font-semibold max-sm:hidden">Rate</th>
                    <th className="px-5 py-3 text-right font-semibold">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {o.lines.map((l) => (
                    <tr key={l.id} className="border-b border-line align-top">
                      <td className="px-5 py-3">
                        <p className="font-medium text-ink">{l.description}</p>
                        <p className="text-xs text-ink-muted">
                          {[
                            l.sku,
                            `${formatMoney(l.unit_price)} each`,
                            Number(l.discount_amount) > 0 && `${formatMoney(l.discount_amount)} off`,
                            Number(l.tax_rate) > 0 && `VAT ${formatQty(l.tax_rate)}%`,
                          ]
                            .filter(Boolean)
                            .join(". ")}
                        </p>
                      </td>
                      <td className="px-3 py-3 text-right whitespace-nowrap text-ink">
                        {formatQty(l.quantity)} {l.unit}
                      </td>
                      <td className="px-3 py-3 text-right text-ink max-sm:hidden">{formatMoney(l.unit_price)}</td>
                      <td className="px-5 py-3 text-right font-medium text-ink">{formatMoney(l.line_total)}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="text-ink-muted">
                  {Number(t.discount_total) > 0 && (
                    <tr>
                      <td colSpan={4} className="px-5 pt-3">
                        <div className="flex justify-between gap-4">
                          <span>Discount included</span>
                          <span>− {formatMoney(t.discount_total)}</span>
                        </div>
                      </td>
                    </tr>
                  )}
                  {Number(t.tax_total) > 0 && (
                    <tr>
                      <td colSpan={4} className="px-5 pt-2">
                        <div className="flex justify-between gap-4">
                          <span>VAT</span>
                          <span>{formatMoney(t.tax_total)}</span>
                        </div>
                      </td>
                    </tr>
                  )}
                  {Number(t.shipping_fee) > 0 && (
                    <tr>
                      <td colSpan={4} className="px-5 pt-2">
                        <div className="flex justify-between gap-4">
                          <span>Delivery</span>
                          <span>{formatMoney(t.shipping_fee)}</span>
                        </div>
                      </td>
                    </tr>
                  )}
                  <tr>
                    <td colSpan={4} className="px-5 pt-3 pb-4">
                      <div className="flex items-baseline justify-between gap-4 border-t-2 border-ink pt-3">
                        <span className="text-base font-semibold text-ink">Total</span>
                        <span className="figure text-2xl text-ink">{formatMoney(t.grand_total, t.currency)}</span>
                      </div>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </section>

          {o.notes && (
            <Panel title="Notes">
              <p className="whitespace-pre-wrap text-sm text-ink-muted">{o.notes}</p>
            </Panel>
          )}

          <details className="group rounded-panel border border-line bg-surface">
            <summary className="flex cursor-pointer list-none items-center justify-between px-5 py-3 font-semibold text-ink">
              History
              <span className="text-sm font-normal text-ink-muted group-open:hidden">
                {o.history.length} {o.history.length === 1 ? "change" : "changes"}
              </span>
            </summary>
            <ol className="grid gap-3 border-t border-line px-5 py-4">
              {o.history.map((h, i) => (
                <li key={i} className="flex gap-3 text-sm">
                  <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-hidden />
                  <span>
                    <span className="font-medium text-ink">{STATUS_LABEL[h.to_status] ?? h.to_status}</span>
                    <span className="text-ink-subtle"> {dateTime(h.at)}</span>
                    {h.reason && <span className="block text-ink-muted">{h.reason}</span>}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        </div>

        <div className="grid min-w-0 gap-4">
          {can("payment.read") && (
            <section
              aria-labelledby="payment-title"
              className={cx(
                "rounded-panel border bg-surface",
                due > 0 && !stopped ? "border-attention shadow-[inset_4px_0_0_var(--sc-attention)]" : "border-line",
              )}
            >
              <div className="grid gap-3 px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <h2 id="payment-title" className="font-semibold text-ink">
                    Payment
                  </h2>
                  <Pill tone={PAYMENT_TONE[t.payment_status] ?? "new"}>{PAYMENT_LABEL[t.payment_status] ?? t.payment_status}</Pill>
                </div>
                <p className="figure text-[1.75rem] text-ink">
                  {due > 0 ? `${formatMoney(due, t.currency)} due` : paid > 0 ? "Paid in full" : formatMoney(total, t.currency)}
                </p>
                <div className="h-1.5 overflow-hidden rounded-full bg-sunken" aria-hidden>
                  <div className="h-full rounded-full bg-stage-done" style={{ width: `${total > 0 ? Math.min(100, (paid / total) * 100) : 0}%` }} />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-ink-muted">
                  <span>{paid > 0 ? `${formatMoney(paid, t.currency)} received of ${formatMoney(total, t.currency)}` : "Nothing received yet"}</span>
                  <span className="flex gap-1">
                    {can("payment.write") && paid > 0 && (
                      <Button size="sm" variant="quiet" icon={Undo2} onClick={() => setSheet("refund")}>
                        Refund
                      </Button>
                    )}
                    {canRecordPayment && (
                      <Button size="sm" variant="secondary" icon={Plus} onClick={() => setSheet("payment")}>
                        Record payment
                      </Button>
                    )}
                  </span>
                </div>
              </div>
              {o.payments.length > 0 && (
                <ul className="divide-y divide-line border-t border-line">
                  {o.payments.map((p) => (
                    <li key={p.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                      <div className="min-w-0">
                        <p className={cx("font-medium", p.status === "voided" ? "text-ink-subtle line-through" : "text-ink")}>
                          <span className="tabular">
                            {p.type === "refund" ? "− " : ""}
                            {formatMoney(p.amount, p.currency)}
                          </span>{" "}
                          <span className="font-normal text-ink-muted">
                            {p.type === "refund" ? "refunded" : "by"} {PAYMENT_METHOD_LABEL[p.method] ?? p.method}
                          </span>
                        </p>
                        <p className="text-xs text-ink-subtle">
                          {[p.payment_number, shortDay(p.paid_at), p.reference && `Ref ${p.reference}`, p.recorded_by?.name].filter(Boolean).join(". ")}
                        </p>
                        {p.status === "voided" && <p className="text-xs text-danger">Voided: {p.void_reason}</p>}
                      </div>
                      {p.status === "recorded" && can("payment.write") && (
                        <Button size="sm" variant="ghost" onClick={() => setSheet({ void: p })}>
                          Void
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {can("delivery.read") && (
            <SideBox
              title="Delivery"
              action={
                canSendDelivery &&
                primary?.label !== "Send for delivery" && (
                  <Button size="sm" variant="quiet" icon={Truck} onClick={() => setSheet("delivery")}>
                    Send
                  </Button>
                )
              }
            >
              {o.deliveries.length === 0 ? (
                <p className="text-sm text-ink-muted">
                  {address ? `To: ${address}` : "No address yet. Ask the customer in the chat, or add it when you send the delivery."}
                  {o.status === "NEW" && " Confirm the order to send it for delivery."}
                </p>
              ) : (
                <ul className="-mx-5 -mb-4 divide-y divide-line border-t border-line">
                  {o.deliveries.map((d) => (
                    <li key={d.id} className="grid gap-2 px-5 py-4">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="tabular font-medium text-ink">{d.delivery_number}</span>
                        <Pill tone={DELIVERY_TONE[d.status]}>{DELIVERY_STATUS_LABEL[d.status] ?? d.status}</Pill>
                      </div>
                      <p className="text-sm text-ink-muted">
                        {[
                          d.method === "courier" ? d.courier_name : DELIVERY_METHOD_LABEL[d.method],
                          d.assigned_to?.name,
                          d.scheduled_date && bsDay(d.scheduled_date),
                        ]
                          .filter(Boolean)
                          .join(". ")}
                      </p>
                      <p className="text-sm text-ink-muted">
                        {addressText(d.delivery_address) || "No address"}
                        {Number(d.cod_amount) > 0 && d.allowed_next.some((n) => n === "DELIVERED") && (
                          <span className="tabular font-medium text-attention-ink"> Collect {formatMoney(d.cod_amount, d.order.currency)}</span>
                        )}
                        {d.tracking_reference && `. Tracking ${d.tracking_reference}`}
                      </p>
                      <ContactLine delivery={d} />
                      {d.history.at(-1)?.note && <p className="text-sm text-ink-subtle">“{d.history.at(-1)?.note}”</p>}
                      {can("delivery.write") && <DeliveryActions delivery={d} canRecordCash={can("payment.write")} onChanged={refresh} />}
                    </li>
                  ))}
                </ul>
              )}
            </SideBox>
          )}

          <SideBox
            title="Invoice"
            action={
              canInvoice && (
                <Button size="sm" variant="quiet" icon={ReceiptText} loading={issue.isPending} onClick={() => issue.mutate()}>
                  Make invoice
                </Button>
              )
            }
          >
            {o.invoices.length === 0 ? (
              <p className="text-sm text-ink-muted">
                {o.status === "NEW"
                  ? "Confirm the order first, then you can make its invoice."
                  : "No invoice yet. It's numbered for the current fiscal year when you make it."}
              </p>
            ) : (
              <ul className="-mx-5 -mb-4 divide-y divide-line border-t border-line">
                {o.invoices.map((v) => (
                  <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                    <div>
                      <p className={cx("tabular font-medium", v.status === "CANCELLED" ? "text-ink-subtle line-through" : "text-ink")}>
                        {v.invoice_number ?? "Draft"}
                      </p>
                      <p className="text-xs text-ink-subtle">
                        {v.status === "CANCELLED" ? "Cancelled" : `Issued ${v.issue_date ? bsDate(v.issue_date) : ""}`}.{" "}
                        {formatMoney(v.grand_total, t.currency)}
                      </p>
                    </div>
                    <div className="flex gap-1">
                      <a
                        href={`/api/v1/invoices/${v.id}/pdf`}
                        target="_blank"
                        rel="noopener"
                        className="inline-flex min-h-9 items-center gap-2 rounded-control border border-line-strong bg-surface px-3 text-sm font-medium text-ink hover:bg-sunken"
                      >
                        <FileText className="size-4" aria-hidden />
                        PDF
                      </a>
                      {v.status === "ISSUED" && can("invoice.write") && (
                        <Button size="sm" variant="ghost" onClick={() => setAsking({ kind: "invoice", invoiceId: v.id })}>
                          Cancel
                        </Button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </SideBox>

          {o.lead && (
            <Link href={`/leads/${o.lead.id}`} className="text-sm font-medium text-primary hover:underline">
              From lead {o.lead.lead_number}
            </Link>
          )}
        </div>
      </div>

      {sheet === "delivery" && (
        <Modal title="Send for delivery" onClose={() => setSheet(null)}>
          <NewDeliveryForm order={o} onSaved={() => (setSheet(null), refresh())} onCancel={() => setSheet(null)} />
        </Modal>
      )}
      {(sheet === "payment" || sheet === "refund") && (
        <Modal title={sheet === "refund" ? "Record a refund" : "Record a payment"} onClose={() => setSheet(null)}>
          <RecordPaymentForm order={o} refund={sheet === "refund"} onSaved={() => (setSheet(null), refresh())} onCancel={() => setSheet(null)} />
        </Modal>
      )}
      {sheet && typeof sheet === "object" && (
        <Modal title="Void this payment?" onClose={() => setSheet(null)}>
          <VoidPaymentForm payment={sheet.void} onSaved={() => (setSheet(null), refresh())} onCancel={() => setSheet(null)} />
        </Modal>
      )}
      {asking?.kind === "status" && (
        <ReasonDialog
          title={`${STATUS_ACTION[asking.status]}?`}
          confirmLabel={STATUS_ACTION[asking.status] ?? "Confirm"}
          busy={move.isPending}
          onClose={() => setAsking(null)}
          onSubmit={(reason) => move.mutate({ status: asking.status, reason })}
        />
      )}
      {asking?.kind === "invoice" && (
        <ReasonDialog
          title="Cancel this invoice?"
          confirmLabel="Cancel invoice"
          busy={cancelInvoice.isPending}
          onClose={() => setAsking(null)}
          onSubmit={(reason) => cancelInvoice.mutate({ invoiceId: asking.invoiceId, reason })}
        />
      )}
    </main>
  );
}
