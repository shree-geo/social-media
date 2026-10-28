"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, MessageCircle, ReceiptText, X } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { useMe } from "@/components/tenant-shell";
import { Alert, Button, Panel, Pill, Spinner, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatTime } from "@/lib/inbox";
import {
  LEAD_LABEL,
  NEEDS_REASON,
  PAYMENT_LABEL,
  SOURCE_LABEL,
  STATUS_ACTION,
  STATUS_LABEL,
  STATUS_TONE,
  formatMoney,
  formatQty,
  type Order,
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

export function OrderDetail() {
  const { id } = useParams<{ id: string }>();
  const me = useMe();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState<{ kind: "status"; status: string } | { kind: "invoice"; invoiceId: string } | null>(null);
  const can = (p: string) => me.data?.permissions.includes(p) ?? false;

  const order = useQuery({ queryKey: ["order", id], queryFn: () => api<Order>("tenant", "GET", `/api/v1/orders/${id}`) });

  const onError = (err: unknown) => setError(err instanceof ApiError ? err.message : "That didn't work. Check your connection and try again.");
  const refresh = () => {
    setError(null);
    setAsking(null);
    void queryClient.invalidateQueries({ queryKey: ["orders"] });
    void queryClient.invalidateQueries({ queryKey: ["order", id] });
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
      <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8">
        <Alert tone="error">We couldn&apos;t open this order.</Alert>
      </main>
    );
  }

  const o = order.data;
  const t = o.totals;
  const forward = o.allowed_next.filter((s) => !NEEDS_REASON.has(s));
  const stops = o.allowed_next.filter((s) => NEEDS_REASON.has(s));
  const liveInvoice = o.invoices.find((v) => v.status === "ISSUED");
  const canInvoice = can("invoice.write") && !liveInvoice && !["NEW", "CANCELLED", "REJECTED"].includes(o.status);
  const address = o.delivery_address ? Object.values(o.delivery_address).filter(Boolean).join(", ") : null;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href="/orders" className="mb-4 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Orders
      </Link>

      <header className="mb-5 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="tabular text-2xl font-semibold text-ink">{o.order_number}</h1>
            <Pill tone={STATUS_TONE[o.status]}>{STATUS_LABEL[o.status] ?? o.status}</Pill>
          </div>
          <p className="mt-1 text-ink-muted">
            <Link href={`/customers/${o.customer.id}`} className="font-medium text-ink hover:underline">
              {o.customer.display_name}
            </Link>{" "}
            · {SOURCE_LABEL[o.source_channel] ?? o.source_channel}
            {o.lead_source && ` · found you via ${LEAD_LABEL[o.lead_source] ?? o.lead_source}`}
          </p>
        </div>
        {o.source_conversation_id && (
          <Link
            href={`/inbox/${o.source_conversation_id}`}
            className="inline-flex min-h-9 items-center gap-2 rounded-control border border-line-strong bg-surface px-3 text-sm font-medium text-ink hover:bg-sunken"
          >
            <MessageCircle className="size-4" aria-hidden />
            Open chat
          </Link>
        )}
      </header>

      {error && <Alert tone="error">{error}</Alert>}

      {can("order.write") && o.allowed_next.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {forward.map((s) => (
            <Button key={s} loading={move.isPending && move.variables?.status === s} onClick={() => move.mutate({ status: s })}>
              {STATUS_ACTION[s] ?? STATUS_LABEL[s]}
            </Button>
          ))}
          {stops.map((s) => (
            <Button key={s} variant="secondary" onClick={() => setAsking({ kind: "status", status: s })}>
              {STATUS_ACTION[s] ?? STATUS_LABEL[s]}
            </Button>
          ))}
        </div>
      )}

      <div className="grid gap-5">
        <Panel title="Items">
          <ul className="-mx-5 -my-4 divide-y divide-line">
            {o.lines.map((l) => (
              <li key={l.id} className="flex items-start justify-between gap-4 px-5 py-3">
                <div className="min-w-0">
                  <p className="font-medium text-ink">{l.description}</p>
                  <p className="tabular text-sm text-ink-muted">
                    {formatQty(l.quantity)} {l.unit} × {formatMoney(l.unit_price)}
                    {Number(l.discount_amount) > 0 && ` − ${formatMoney(l.discount_amount)} off`}
                    {Number(l.tax_rate) > 0 && ` · VAT ${formatQty(l.tax_rate)}%`}
                  </p>
                </div>
                <p className="tabular shrink-0 font-medium text-ink">{formatMoney(l.line_total)}</p>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Amount">
          <dl className="tabular grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
            <dt className="text-ink-muted">
              Items
              {Number(t.discount_total) > 0 && <span className="text-ink-subtle"> (after {formatMoney(t.discount_total)} discount)</span>}
            </dt>
            <dd className="text-right text-ink">{formatMoney(t.subtotal)}</dd>
            {Number(t.tax_total) > 0 && (
              <>
                <dt className="text-ink-muted">VAT</dt>
                <dd className="text-right text-ink">{formatMoney(t.tax_total)}</dd>
              </>
            )}
            {Number(t.shipping_fee) > 0 && (
              <>
                <dt className="text-ink-muted">Delivery</dt>
                <dd className="text-right text-ink">{formatMoney(t.shipping_fee)}</dd>
              </>
            )}
            <dt className="border-t border-line pt-2 text-base font-semibold text-ink">Total</dt>
            <dd className="border-t border-line pt-2 text-right text-base font-semibold text-ink">{formatMoney(t.grand_total, t.currency)}</dd>
            <dt className="text-ink-muted">Payment</dt>
            <dd className="text-right">
              <Pill tone={t.payment_status === "PAID" ? "success" : t.payment_status === "PARTIAL" ? "attention" : "neutral"}>
                {PAYMENT_LABEL[t.payment_status] ?? t.payment_status}
              </Pill>
            </dd>
            {Number(t.amount_due) > 0 && Number(t.amount_paid) > 0 && (
              <>
                <dt className="text-ink-muted">Still to pay</dt>
                <dd className="text-right text-ink">{formatMoney(t.amount_due)}</dd>
              </>
            )}
          </dl>
        </Panel>

        <Panel
          title="Invoice"
          actions={
            canInvoice && (
              <Button size="sm" icon={ReceiptText} loading={issue.isPending} onClick={() => issue.mutate()}>
                Make invoice
              </Button>
            )
          }
        >
          {o.invoices.length === 0 ? (
            <p className="text-sm text-ink-muted">
              {o.status === "NEW" ? "Confirm the order first, then you can make its invoice." : "No invoice yet."}
            </p>
          ) : (
            <ul className="-mx-5 -my-4 divide-y divide-line">
              {o.invoices.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
                  <div>
                    <p className={cx("tabular font-medium", v.status === "CANCELLED" ? "text-ink-subtle line-through" : "text-ink")}>
                      {v.invoice_number ?? "Draft"}
                    </p>
                    <p className="text-xs text-ink-subtle">
                      {v.status === "CANCELLED" ? "Cancelled" : `Issued ${v.issue_date ?? ""}`} · {formatMoney(v.grand_total, t.currency)}
                    </p>
                  </div>
                  <div className="flex gap-2">
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
                        Cancel invoice
                      </Button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {(address || o.notes) && (
          <Panel title="Delivery and notes">
            {address && <p className="text-ink">{address}</p>}
            {o.notes && <p className={cx("whitespace-pre-wrap text-sm text-ink-muted", address && "mt-2")}>{o.notes}</p>}
          </Panel>
        )}

        <Panel title="History">
          <ol className="grid gap-3">
            {o.history.map((h, i) => (
              <li key={i} className="flex gap-3 text-sm">
                <span className="mt-1.5 size-2 shrink-0 rounded-full bg-primary" aria-hidden />
                <span>
                  <span className="font-medium text-ink">{STATUS_LABEL[h.to_status] ?? h.to_status}</span>
                  <span className="text-ink-subtle"> · {formatTime(h.at)}</span>
                  {h.reason && <span className="block text-ink-muted">{h.reason}</span>}
                </span>
              </li>
            ))}
          </ol>
        </Panel>
      </div>

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
