"use client";

/**
 * Delivery and payment pieces shared by the order screen and the Deliveries page.
 * Everything here records facts by hand: no courier or payment gateway is called.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Phone, X } from "lucide-react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";

import { Alert, Button, Field, SelectField, TextArea, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatPhone } from "@/lib/inbox";
import {
  DELIVERY_ACTION,
  DELIVERY_METHOD_LABEL,
  DELIVERY_NEEDS_NOTE,
  PAYMENT_METHOD_LABEL,
  formatMoney,
  type Delivery,
  type Order,
  type Payment,
} from "@/lib/sales";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "That didn't work. Check your connection and try again.");

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 grid items-end bg-black/40 sm:place-items-center sm:p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="max-h-[92dvh] w-full overflow-y-auto rounded-t-panel bg-surface p-5 shadow-xl sm:max-w-md sm:rounded-panel">
        <div className="mb-4 flex items-start justify-between gap-3">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          <button type="button" onClick={onClose} className="grid size-9 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Close">
            <X className="size-4" aria-hidden />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

/* Deliveries ---------------------------------------------------------------------------- */

type Staff = { user_id: string; full_name: string; roles: string[] };

export function NewDeliveryForm({ order, onSaved, onCancel }: { order: Order; onSaved: () => void; onCancel: () => void }) {
  const [method, setMethod] = useState("own_staff");
  const [courier, setCourier] = useState("");
  const [tracking, setTracking] = useState("");
  const [assignee, setAssignee] = useState("");
  const [date, setDate] = useState("");
  const [cod, setCod] = useState(order.totals.amount_due);
  const staff = useQuery({
    queryKey: ["delivery-staff"],
    queryFn: () => api<Staff[]>("tenant", "GET", "/api/v1/deliveries/staff"),
    enabled: method === "own_staff",
  });
  const save = useMutation({
    mutationFn: () =>
      api("tenant", "POST", `/api/v1/orders/${order.id}/deliveries`, {
        method,
        courier_name: method === "courier" ? courier : null,
        tracking_reference: tracking || null,
        assigned_to: method === "own_staff" && assignee ? assignee : null,
        scheduled_date: date || null,
        cod_amount: cod || "0",
      }),
    onSuccess: onSaved,
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }

  return (
    <form onSubmit={submit} noValidate>
      {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
      <fieldset className="mb-5">
        <legend className="mb-1.5 text-sm font-medium text-ink">Who delivers?</legend>
        <div className="grid grid-cols-3 gap-2">
          {Object.entries(DELIVERY_METHOD_LABEL).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={method === value}
              onClick={() => setMethod(value)}
              className={cx(
                "min-h-11 rounded-control border px-2 text-sm font-medium",
                method === value ? "border-primary bg-primary-soft text-primary" : "border-line-strong text-ink-muted hover:bg-sunken",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </fieldset>
      {method === "own_staff" && (
        <SelectField label="Assign to (optional)" value={assignee} onChange={(e) => setAssignee(e.target.value)}>
          <option value="">Decide later</option>
          {staff.data?.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.full_name}
            </option>
          ))}
        </SelectField>
      )}
      {method === "courier" && (
        <div className="grid gap-x-3 sm:grid-cols-2">
          <Field label="Courier" value={courier} onChange={(e) => setCourier(e.target.value)} placeholder="Pathao, Upaya…" />
          <Field label="Tracking number (optional)" value={tracking} onChange={(e) => setTracking(e.target.value)} />
        </div>
      )}
      <div className="grid gap-x-3 sm:grid-cols-2">
        {method !== "customer_pickup" && <Field label="Delivery date (optional)" type="date" value={date} onChange={(e) => setDate(e.target.value)} />}
        <Field
          label={method === "customer_pickup" ? "Cash to collect at pickup" : "Cash to collect (COD)"}
          inputMode="decimal"
          value={cod}
          onChange={(e) => setCod(e.target.value)}
          hint={`Still due: ${formatMoney(order.totals.amount_due, order.currency)}`}
        />
      </div>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" loading={save.isPending} disabled={method === "courier" && !courier.trim()}>
          Save delivery
        </Button>
      </div>
    </form>
  );
}

/** Status buttons for one delivery; asks for a note or the cash collected where needed. */
export function DeliveryActions({ delivery, canRecordCash, onChanged }: { delivery: Delivery; canRecordCash: boolean; onChanged: () => void }) {
  const [asking, setAsking] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [cash, setCash] = useState("");
  const move = useMutation({
    mutationFn: (v: { status: string; note?: string; cod_collected?: string }) => api("tenant", "POST", `/api/v1/deliveries/${delivery.id}/status`, v),
    onSuccess: () => {
      setAsking(null);
      onChanged();
    },
  });
  const collect = canRecordCash && Number(delivery.cod_amount) > 0;

  function choose(status: string) {
    if (DELIVERY_NEEDS_NOTE.has(status) || (status === "DELIVERED" && collect)) {
      move.reset();
      setNote("");
      setCash(delivery.cod_amount);
      setAsking(status);
    } else {
      move.mutate({ status });
    }
  }

  function confirm(event: FormEvent) {
    event.preventDefault();
    if (!asking) return;
    move.mutate({
      status: asking,
      note: note.trim() || undefined,
      cod_collected: asking === "DELIVERED" && Number(cash) > 0 ? cash : undefined,
    });
  }

  const forward = delivery.allowed_next.filter((s) => !DELIVERY_NEEDS_NOTE.has(s));
  const stops = delivery.allowed_next.filter((s) => DELIVERY_NEEDS_NOTE.has(s));
  if (delivery.allowed_next.length === 0) return null;

  return (
    <>
      {move.isError && !asking && <Alert tone="error">{errorText(move.error)}</Alert>}
      <div className="flex flex-wrap gap-2">
        {forward.map((s) => (
          <Button key={s} size="sm" loading={move.isPending && move.variables?.status === s} onClick={() => choose(s)}>
            {DELIVERY_ACTION[s] ?? s}
          </Button>
        ))}
        {stops.map((s) => (
          <Button key={s} size="sm" variant="secondary" onClick={() => choose(s)}>
            {DELIVERY_ACTION[s] ?? s}
          </Button>
        ))}
      </div>
      {asking && (
        <Modal title={asking === "DELIVERED" ? "Delivered" : `${DELIVERY_ACTION[asking]}?`} onClose={() => setAsking(null)}>
          <form onSubmit={confirm} noValidate>
            {move.isError && <Alert tone="error">{errorText(move.error)}</Alert>}
            {asking === "DELIVERED" ? (
              <Field
                label="Cash collected"
                inputMode="decimal"
                autoFocus
                value={cash}
                onChange={(e) => setCash(e.target.value)}
                hint={`Expected ${formatMoney(delivery.cod_amount, delivery.order.currency)}. Enter 0 if nothing was collected.`}
              />
            ) : (
              <TextArea
                label="What happened?"
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={asking === "FAILED" ? "For example: phone switched off, not at home" : "For example: wrong size"}
              />
            )}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" onClick={() => setAsking(null)}>
                Back
              </Button>
              <Button
                type="submit"
                variant={asking === "DELIVERED" ? "primary" : "danger"}
                loading={move.isPending}
                disabled={asking !== "DELIVERED" && note.trim().length < 3}
              >
                {asking === "DELIVERED" ? "Save" : DELIVERY_ACTION[asking]}
              </Button>
            </div>
          </form>
        </Modal>
      )}
    </>
  );
}

export function ContactLine({ delivery }: { delivery: Delivery }) {
  if (!delivery.contact_phone) return null;
  return (
    <a href={`tel:${delivery.contact_phone}`} className="tabular inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
      <Phone className="size-4" aria-hidden />
      {formatPhone(delivery.contact_phone)}
    </a>
  );
}

/* Payments ------------------------------------------------------------------------------ */

const QUICK_METHODS = ["cash", "esewa", "khalti", "fonepay", "bank_transfer"];

export function RecordPaymentForm({ order, refund = false, onSaved, onCancel }: { order: Order; refund?: boolean; onSaved: () => void; onCancel: () => void }) {
  const key = useRef(crypto.randomUUID());
  const [amount, setAmount] = useState(refund ? order.totals.amount_paid : order.totals.amount_due);
  const [method, setMethod] = useState("cash");
  const [reference, setReference] = useState("");
  const [date, setDate] = useState("");
  const [notes, setNotes] = useState("");
  const save = useMutation({
    mutationFn: () =>
      api(
        "tenant",
        "POST",
        `/api/v1/orders/${order.id}/payments`,
        {
          type: refund ? "refund" : "payment",
          amount,
          method,
          reference: reference.trim() || null,
          // A past date is recorded at noon Nepal time; no date means "now".
          paid_at: date ? `${date}T12:00:00+05:45` : null,
          notes: notes.trim() || null,
        },
        { "Idempotency-Key": key.current },
      ),
    onSuccess: onSaved,
  });
  const needsReference = !["cash", "cod", "other"].includes(method);

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      noValidate
    >
      {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
      <Field
        label={refund ? "Amount returned" : "Amount received"}
        inputMode="decimal"
        autoFocus
        value={amount}
        onChange={(e) => setAmount(e.target.value)}
        hint={refund ? `Paid so far: ${formatMoney(order.totals.amount_paid, order.currency)}` : `Still due: ${formatMoney(order.totals.amount_due, order.currency)}`}
      />
      <fieldset className="mb-5">
        <legend className="mb-1.5 text-sm font-medium text-ink">How?</legend>
        <div className="flex flex-wrap gap-2">
          {[...QUICK_METHODS, "cheque", "other"].map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={method === m}
              onClick={() => setMethod(m)}
              className={cx(
                "min-h-10 rounded-full border px-3.5 text-sm font-medium",
                method === m ? "border-primary bg-primary-soft text-primary" : "border-line-strong text-ink-muted hover:bg-sunken",
              )}
            >
              {PAYMENT_METHOD_LABEL[m]}
            </button>
          ))}
        </div>
      </fieldset>
      <div className="grid gap-x-3 sm:grid-cols-2">
        <Field
          label={needsReference ? "Transaction ID" : "Reference (optional)"}
          value={reference}
          onChange={(e) => setReference(e.target.value)}
          hint={needsReference ? "From the customer's screenshot or your statement." : undefined}
        />
        <Field label="Date (if not today)" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
      </div>
      <Field label="Note (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant={refund ? "danger" : "primary"} loading={save.isPending} disabled={!(Number(amount) > 0)}>
          {refund ? "Record refund" : "Record payment"}
        </Button>
      </div>
    </form>
  );
}

export function VoidPaymentForm({ payment, onSaved, onCancel }: { payment: Payment; onSaved: () => void; onCancel: () => void }) {
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => api("tenant", "POST", `/api/v1/payments/${payment.id}/void`, { reason: reason.trim() }),
    onSuccess: onSaved,
  });
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
      noValidate
    >
      {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
      <p className="mb-4 text-sm text-ink-muted">
        {payment.payment_number} · {formatMoney(payment.amount, payment.currency)} by {PAYMENT_METHOD_LABEL[payment.method] ?? payment.method}. The record stays in the history, marked as voided. Record the
        correct payment again afterwards.
      </p>
      <TextArea label="Reason" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: wrong amount entered" />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel}>
          Keep it
        </Button>
        <Button type="submit" variant="danger" loading={save.isPending} disabled={reason.trim().length < 3}>
          Void payment
        </Button>
      </div>
    </form>
  );
}
