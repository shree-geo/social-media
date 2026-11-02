"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CalendarPlus, Ban, CircleCheck, Pencil, Repeat, Wallet, XCircle } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent, type ReactNode } from "react";

import { Modal } from "@/components/fulfilment";
import { Alert, Button, Field, PageHeader, Panel, SelectField, Spinner, SubscriptionPill, TextArea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import {
  CYCLE_LABEL,
  CYCLE_MONTHS,
  SUBSCRIPTION_PAYMENT_METHODS,
  type Plan,
  type SubscriptionDetail,
  type SubscriptionEvent,
  type TenantDetail,
} from "@/lib/platform";

const errorText = (err: unknown) => (err instanceof ApiError ? err.message : "That didn't work. Check your connection and try again.");

/* Dates are plain YYYY-MM-DD calendar days; never let a timezone shift them. */

function parseDay(value: string): Date {
  const [y, m, d] = value.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function formatDay(value: string | Date): string {
  const date = typeof value === "string" ? parseDay(value) : value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

function showDay(value: string | null): string {
  return value ? parseDay(value).toLocaleDateString(undefined, { dateStyle: "medium" }) : "—";
}

function addDays(value: string, days: number): string {
  const date = parseDay(value);
  date.setDate(date.getDate() + days);
  return formatDay(date);
}

function addMonths(value: string, months: number): string {
  const date = parseDay(value);
  const day = date.getDate();
  date.setDate(1);
  date.setMonth(date.getMonth() + months);
  const lastDay = new Date(date.getFullYear(), date.getMonth() + 1, 0).getDate();
  date.setDate(Math.min(day, lastDay));
  return formatDay(date);
}

/** Last day of one billing period starting on ``start`` (same rule as the backend's period_end). */
function periodEnd(start: string, cycle: string): string {
  return addDays(addMonths(start, CYCLE_MONTHS[cycle] ?? 12), -1);
}

function todayDay(): string {
  return formatDay(new Date());
}

function money(amount: string, currency = "NPR"): string {
  return `${currency} ${Number(amount).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function daysText(days: number): string {
  if (days < 0) return `ended ${-days} day${days === -1 ? "" : "s"} ago`;
  if (days === 0) return "ends today";
  return `${days} day${days === 1 ? "" : "s"} left`;
}

/* Page ---------------------------------------------------------------------------------- */

type Dialog = "renew" | "plan" | "expiry" | "suspend" | "cancel" | "business" | null;

export function TenantDetailView() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const tenant = useQuery({
    queryKey: ["platform-tenant", id],
    queryFn: () => api<TenantDetail>("platform", "GET", `/api/v1/platform/tenants/${id}`),
  });

  const done = (message: string) => {
    setDialog(null);
    setNotice(message);
    void queryClient.invalidateQueries({ queryKey: ["platform-tenant", id] });
    void queryClient.invalidateQueries({ queryKey: ["platform-tenants"] });
  };

  const reactivate = useMutation({
    mutationFn: (subscriptionId: string) =>
      api("platform", "POST", `/api/v1/platform/subscriptions/${subscriptionId}/status`, { action: "reactivate" }),
    onSuccess: () => done("Subscription reactivated."),
  });

  if (tenant.isPending) return <Spinner />;
  if (tenant.isError || !tenant.data)
    return (
      <div className="mx-auto max-w-5xl">
        <Alert tone="error">{errorText(tenant.error)}</Alert>
        <BackLink />
      </div>
    );

  const t = tenant.data;
  const sub = t.subscription;
  const status = sub?.effective_status ?? null;

  return (
    <div className="mx-auto max-w-5xl">
      <BackLink />
      <PageHeader
        title={t.business_name}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            <SubscriptionPill status={status} />
            {sub && (
              <span className="text-sm">
                {sub.plan_name} · {CYCLE_LABEL[sub.billing_cycle]?.toLowerCase() ?? sub.billing_cycle} · {daysText(sub.days_remaining)}
              </span>
            )}
          </span>
        }
      />

      {notice && (
        <Alert tone="success" title={notice}>
          The business sees the change the next time their app loads.
        </Alert>
      )}
      {reactivate.isError && <Alert tone="error">{errorText(reactivate.error)}</Alert>}
      {sub && <StatusAdvice sub={sub} />}

      <div className="grid gap-6">
        {sub ? (
          <Panel
            title="Subscription"
            actions={
              <div className="flex flex-wrap justify-end gap-2">
                <Button size="sm" icon={Wallet} onClick={() => setDialog("renew")}>
                  Record payment
                </Button>
                <Button size="sm" variant="secondary" icon={CalendarPlus} onClick={() => setDialog("expiry")}>
                  Extend
                </Button>
                <Button size="sm" variant="secondary" icon={Repeat} onClick={() => setDialog("plan")}>
                  Change package
                </Button>
              </div>
            }
          >
            <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
              <Item term="Package">{sub.plan_name}</Item>
              <Item term="Pays">{CYCLE_LABEL[sub.billing_cycle] ?? sub.billing_cycle}</Item>
              <Item term="Price">
                {money(sub.price_amount, sub.currency)}
                {Number(sub.discount_amount) > 0 && <span className="text-ink-muted"> − {money(sub.discount_amount, sub.currency)} discount</span>}
              </Item>
              <Item term="Started">{showDay(sub.start_date)}</Item>
              <Item term={sub.status === "TRIAL" ? "Trial ends" : "Paid until"}>
                {showDay(sub.expiry_date)} <span className="text-ink-muted">({daysText(sub.days_remaining)})</span>
              </Item>
              <Item term="Grace period">{sub.grace_period_days} days after expiry</Item>
            </dl>
            <div className="mt-5 flex flex-wrap gap-2 border-t border-line pt-4">
              {sub.status === "SUSPENDED" ? (
                <Button
                  size="sm"
                  variant="secondary"
                  icon={CircleCheck}
                  loading={reactivate.isPending}
                  onClick={() => reactivate.mutate(sub.id)}
                >
                  Reactivate
                </Button>
              ) : (
                <Button size="sm" variant="ghost" icon={Ban} onClick={() => setDialog("suspend")}>
                  Suspend
                </Button>
              )}
              <Button size="sm" variant="ghost" icon={XCircle} onClick={() => setDialog("cancel")}>
                Cancel subscription
              </Button>
            </div>
          </Panel>
        ) : (
          <Alert tone="warning" title="No current subscription">
            This business has no active or past-due subscription (it may have been cancelled), so it can&apos;t use the app.
          </Alert>
        )}

        <Panel
          title="Business details"
          actions={
            <Button size="sm" variant="secondary" icon={Pencil} onClick={() => setDialog("business")}>
              Edit
            </Button>
          }
        >
          <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            <Item term="Business name">{t.business_name}</Item>
            <Item term="Registered name">{t.legal_name || "—"}</Item>
            <Item term="PAN / VAT number">{t.tax_number || "—"}</Item>
            <Item term="Phone">{t.phone || "—"}</Item>
            <Item term="Email">{t.email || "—"}</Item>
            <Item term="VAT registered">{t.vat_registered ? "Yes" : "No"}</Item>
            <Item term="Owner">
              {t.owner ? (
                <>
                  {t.owner.full_name}
                  <span className="block text-sm text-ink-muted">{t.owner.email}</span>
                  {t.owner.phone && <span className="block text-sm text-ink-muted">{t.owner.phone}</span>}
                </>
              ) : (
                "—"
              )}
            </Item>
            <Item term="Joined">{new Date(t.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</Item>
          </dl>
        </Panel>

        <Panel title="Payments">
          {t.payments.length === 0 ? (
            <p className="text-ink-muted">No payments recorded yet.</p>
          ) : (
            <div className="-mx-5 overflow-x-auto">
              <table className="w-full min-w-[620px] text-left text-sm">
                <thead className="border-b border-line text-ink-muted">
                  <tr>
                    <th scope="col" className="px-5 py-2 font-medium">Receipt</th>
                    <th scope="col" className="px-5 py-2 font-medium">Paid on</th>
                    <th scope="col" className="px-5 py-2 font-medium">Method</th>
                    <th scope="col" className="px-5 py-2 font-medium">Covers</th>
                    <th scope="col" className="px-5 py-2 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {t.payments.map((p) => (
                    <tr key={p.id} className="border-b border-line last:border-b-0">
                      <td className="tabular px-5 py-2.5 text-ink">
                        {p.receipt_number}
                        {p.voided_at && <span className="ml-2 text-danger">void</span>}
                      </td>
                      <td className="px-5 py-2.5 text-ink-muted">{new Date(p.paid_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</td>
                      <td className="px-5 py-2.5 text-ink-muted">
                        {SUBSCRIPTION_PAYMENT_METHODS.find(([k]) => k === p.payment_method)?.[1] ?? p.payment_method}
                        {p.transaction_reference && <span className="block text-xs">{p.transaction_reference}</span>}
                      </td>
                      <td className="px-5 py-2.5 text-ink-muted">
                        {showDay(p.period_start)} – {showDay(p.period_end)}
                      </td>
                      <td className="tabular px-5 py-2.5 text-right font-medium text-ink">{money(p.amount, p.currency)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {t.history.length > 0 && (
          <Panel title="History">
            <ol className="space-y-3">
              {t.history.map((h) => (
                <li key={h.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5">
                  <span className="text-ink">
                    {describeEvent(h)}
                    {h.reason && <span className="text-ink-muted"> — {h.reason}</span>}
                  </span>
                  <span className="text-sm text-ink-subtle">
                    {new Date(h.created_at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}
                    {h.actor_type === "system" && " · automatic"}
                  </span>
                </li>
              ))}
            </ol>
          </Panel>
        )}
      </div>

      {dialog === "renew" && sub && <RenewDialog sub={sub} onClose={() => setDialog(null)} onDone={done} />}
      {dialog === "expiry" && sub && <ExpiryDialog sub={sub} onClose={() => setDialog(null)} onDone={done} />}
      {dialog === "plan" && sub && <PlanDialog sub={sub} onClose={() => setDialog(null)} onDone={done} />}
      {(dialog === "suspend" || dialog === "cancel") && sub && (
        <StatusDialog action={dialog} sub={sub} onClose={() => setDialog(null)} onDone={done} />
      )}
      {dialog === "business" && <BusinessDialog tenant={t} onClose={() => setDialog(null)} onDone={done} />}
    </div>
  );
}

function BackLink() {
  return (
    <Link href="/admin/tenants" className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
      <ArrowLeft className="size-4" aria-hidden />
      Businesses
    </Link>
  );
}

function Item({ term, children }: { term: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-sm text-ink-muted">{term}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  );
}

function StatusAdvice({ sub }: { sub: SubscriptionDetail }) {
  switch (sub.effective_status) {
    case "EXPIRED":
      return (
        <Alert tone="error" title="Expired: the business can only view and export">
          Record their payment to start a new period from today, or extend the expiry date if you are giving them extra time.
        </Alert>
      );
    case "GRACE":
      return (
        <Alert tone="warning" title="In the grace period">
          They can still use everything until {showDay(addDays(sub.expiry_date, sub.grace_period_days))}. Record their payment to renew.
        </Alert>
      );
    case "SUSPENDED":
      return (
        <Alert tone="error" title="Suspended: the business can't use the app">
          A payment alone does not lift a suspension. Reactivate when you are ready.
        </Alert>
      );
    default:
      return null;
  }
}

const STATUS_WORD: Record<string, string> = {
  TRIAL: "trial",
  ACTIVE: "active",
  GRACE: "grace period",
  EXPIRED: "expired",
  SUSPENDED: "suspended",
  CANCELLED: "cancelled",
};

function describeEvent(h: SubscriptionEvent): string {
  switch (h.event_type) {
    case "created":
      return `Subscription started on ${h.to_plan_name ?? "a package"}, until ${showDay(h.to_expiry_date)}`;
    case "renewed":
      return `Renewed until ${showDay(h.to_expiry_date)}`;
    case "plan_changed":
      return h.from_plan_name === h.to_plan_name
        ? `Payment schedule or price changed on ${h.to_plan_name ?? "the package"}`
        : `Package changed from ${h.from_plan_name ?? "?"} to ${h.to_plan_name ?? "?"}`;
    case "dates_changed":
      return `Expiry moved from ${showDay(h.from_expiry_date)} to ${showDay(h.to_expiry_date)}`;
    case "status_changed":
      return `Status changed from ${STATUS_WORD[h.from_status ?? ""] ?? h.from_status} to ${STATUS_WORD[h.to_status ?? ""] ?? h.to_status}`;
  }
}

/* Dialogs --------------------------------------------------------------------------------- */

type DialogProps = { sub: SubscriptionDetail; onClose: () => void; onDone: (message: string) => void };

function DialogActions({ onClose, loading, label, variant = "primary" }: { onClose: () => void; loading: boolean; label: string; variant?: "primary" | "danger" }) {
  return (
    <div className="mt-2 flex justify-end gap-3">
      <Button type="button" variant="ghost" onClick={onClose}>
        Close
      </Button>
      <Button type="submit" variant={variant} loading={loading}>
        {label}
      </Button>
    </div>
  );
}

function RenewDialog({ sub, onClose, onDone }: DialogProps) {
  const due = Math.max(0, Number(sub.price_amount) - Number(sub.discount_amount));
  const [amount, setAmount] = useState(String(due));
  const [method, setMethod] = useState("esewa");
  const [paidOn, setPaidOn] = useState(todayDay());
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  // Same rule as the backend: an expired or trial subscription starts again today; otherwise it continues.
  const restart = sub.effective_status === "EXPIRED" || sub.effective_status === "TRIAL";
  const start = restart ? todayDay() : addDays(sub.expiry_date, 1);
  const end = periodEnd(start, sub.billing_cycle);

  const save = useMutation({
    mutationFn: () =>
      api("platform", "POST", `/api/v1/platform/subscriptions/${sub.id}/payments`, {
        amount,
        payment_method: method,
        // Midday local time so the receipt date stays on the chosen day in every timezone.
        paid_at: new Date(`${paidOn}T12:00:00`).toISOString(),
        transaction_reference: reference || null,
        notes: notes || null,
      }),
    onSuccess: () => onDone(`Payment recorded. Paid until ${showDay(end)}.`),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (Number(amount) > 0) save.mutate();
  };

  return (
    <Modal title="Record payment and renew" onClose={onClose}>
      <form onSubmit={submit} noValidate>
        {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
        <p className="mb-4 rounded-control bg-sunken px-3 py-2 text-sm text-ink">
          Adds one {CYCLE_LABEL[sub.billing_cycle]?.toLowerCase() ?? sub.billing_cycle} period: <strong>{showDay(start)}</strong> to{" "}
          <strong>{showDay(end)}</strong>.{" "}
          <span className="text-ink-muted">To change the package or schedule first, use Change package.</span>
        </p>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field
            label={`Amount (${sub.currency})`}
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            error={Number(amount) > 0 ? undefined : "Enter the amount you received"}
          />
          <SelectField label="Paid by" value={method} onChange={(e) => setMethod(e.target.value)}>
            {SUBSCRIPTION_PAYMENT_METHODS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </SelectField>
          <Field label="Paid on" type="date" value={paidOn} max={todayDay()} onChange={(e) => setPaidOn(e.target.value)} />
          <Field label="Reference (optional)" value={reference} onChange={(e) => setReference(e.target.value)} />
        </div>
        <TextArea label="Notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <DialogActions onClose={onClose} loading={save.isPending} label="Record payment" />
      </form>
    </Modal>
  );
}

function ExpiryDialog({ sub, onClose, onDone }: DialogProps) {
  // Extending an already-lapsed subscription counts from today, not from the old expiry.
  const base = sub.days_remaining < 0 ? todayDay() : sub.expiry_date;
  const [expiry, setExpiry] = useState(addDays(base, 7));
  const [reason, setReason] = useState("");
  const quick = (
    [
      ["+7 days", addDays(base, 7)],
      ["+15 days", addDays(base, 15)],
      ["+1 month", addMonths(base, 1)],
      ["+3 months", addMonths(base, 3)],
      ["+1 year", addMonths(base, 12)],
    ] as [string, string][]
  ).filter(([, value], i, all) => all.findIndex(([, v]) => v === value) === i);
  const save = useMutation({
    mutationFn: () =>
      api("platform", "PATCH", `/api/v1/platform/subscriptions/${sub.id}`, { expiry_date: expiry, reason: reason || null }),
    onSuccess: () => onDone(`Expiry moved to ${showDay(expiry)}.`),
  });
  const tooEarly = expiry < sub.start_date;

  return (
    <Modal title="Extend or change the expiry date" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (expiry && !tooEarly) save.mutate();
        }}
        noValidate
      >
        {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
        <p className="mb-4 text-sm text-ink-muted">
          Gives extra time without recording a payment, for example a goodwill extension or while you wait for their transfer. It currently ends{" "}
          {showDay(sub.expiry_date)}.
        </p>
        <div className="mb-4 flex flex-wrap gap-2">
          {quick.map(([label, value]) => (
            <Button key={label} type="button" size="sm" variant={expiry === value ? "primary" : "secondary"} onClick={() => setExpiry(value)}>
              {label}
            </Button>
          ))}
        </div>
        <Field
          label="New expiry date"
          type="date"
          value={expiry}
          min={sub.start_date}
          onChange={(e) => setExpiry(e.target.value)}
          error={tooEarly ? "Can't be before the start date" : undefined}
        />
        <Field label="Reason (optional)" placeholder="e.g. Waiting for bank transfer" value={reason} onChange={(e) => setReason(e.target.value)} />
        <DialogActions onClose={onClose} loading={save.isPending} label="Save new date" />
      </form>
    </Modal>
  );
}

function PlanDialog({ sub, onClose, onDone }: DialogProps) {
  const plans = useQuery({
    queryKey: ["platform-plans"],
    queryFn: () => api<Plan[]>("platform", "GET", "/api/v1/platform/plans"),
  });
  const [planId, setPlanId] = useState(sub.plan_id);
  const [cycle, setCycle] = useState(sub.billing_cycle);
  const [grace, setGrace] = useState(String(sub.grace_period_days));
  const [discount, setDiscount] = useState(String(Number(sub.discount_amount)));
  const [reason, setReason] = useState("");
  const available = plans.data?.filter((p) => p.is_active || p.id === sub.plan_id) ?? [];
  const price = available.find((p) => p.id === planId)?.prices.find((p) => p.billing_cycle === cycle && p.is_active);
  const graceValid = /^\d+$/.test(grace) && Number(grace) <= 60;
  const discountValid = discount === "" || Number(discount) >= 0;

  const save = useMutation({
    mutationFn: () =>
      api("platform", "PATCH", `/api/v1/platform/subscriptions/${sub.id}`, {
        plan_id: planId,
        billing_cycle: cycle,
        grace_period_days: Number(grace),
        discount_amount: discount || "0",
        reason: reason || null,
      }),
    onSuccess: () => onDone("Package updated."),
  });

  return (
    <Modal title="Change package" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (price && graceValid && discountValid) save.mutate();
        }}
        noValidate
      >
        {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
        <p className="mb-4 text-sm text-ink-muted">
          Takes effect now; the paid-until date ({showDay(sub.expiry_date)}) stays the same. The new price applies from the next payment.
        </p>
        <SelectField label="Package" value={planId} onChange={(e) => setPlanId(e.target.value)}>
          {available.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
              {p.is_active ? "" : " (no longer offered)"}
            </option>
          ))}
        </SelectField>
        <SelectField label="Pays" value={cycle} onChange={(e) => setCycle(e.target.value)}>
          {Object.entries(CYCLE_LABEL).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </SelectField>
        <p className="tabular -mt-2 mb-5 rounded-control bg-sunken px-3 py-2 text-sm text-ink">
          {plans.isPending
            ? "Loading prices…"
            : price
              ? `${money(price.amount, price.currency)} ${CYCLE_LABEL[cycle]?.toLowerCase()}`
              : "This package has no price for that payment schedule. Pick another."}
        </p>
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field
            label="Grace period (days)"
            inputMode="numeric"
            value={grace}
            onChange={(e) => setGrace(e.target.value)}
            error={graceValid ? undefined : "0 to 60 days"}
          />
          <Field
            label={`Discount per period (${sub.currency})`}
            inputMode="decimal"
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
            error={discountValid ? undefined : "Enter 0 or more"}
          />
        </div>
        <Field label="Reason (optional)" value={reason} onChange={(e) => setReason(e.target.value)} />
        <DialogActions onClose={onClose} loading={save.isPending} label="Save package" />
      </form>
    </Modal>
  );
}

function StatusDialog({ action, sub, onClose, onDone }: DialogProps & { action: "suspend" | "cancel" }) {
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => api("platform", "POST", `/api/v1/platform/subscriptions/${sub.id}/status`, { action, reason: reason || null }),
    onSuccess: () => onDone(action === "suspend" ? "Subscription suspended." : "Subscription cancelled."),
  });
  return (
    <Modal title={action === "suspend" ? "Suspend this business?" : "Cancel the subscription?"} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (reason.trim()) save.mutate();
        }}
        noValidate
      >
        {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
        <Alert tone="warning">
          {action === "suspend"
            ? "Everyone at this business is blocked from the app until you reactivate. Their data is kept."
            : "This ends the subscription for good and blocks the app. It can't be undone from this screen; their data is kept."}
        </Alert>
        <Field label="Reason" value={reason} onChange={(e) => setReason(e.target.value)} error={reason.trim() ? undefined : "Say why, for the history"} />
        <DialogActions onClose={onClose} loading={save.isPending} label={action === "suspend" ? "Suspend" : "Cancel subscription"} variant="danger" />
      </form>
    </Modal>
  );
}

function BusinessDialog({ tenant, onClose, onDone }: { tenant: TenantDetail; onClose: () => void; onDone: (message: string) => void }) {
  const [values, setValues] = useState({
    business_name: tenant.business_name,
    legal_name: tenant.legal_name ?? "",
    phone: tenant.phone ?? "",
    email: tenant.email ?? "",
    tax_number: tenant.tax_number ?? "",
  });
  const set = (key: keyof typeof values) => (e: { target: { value: string } }) => setValues((v) => ({ ...v, [key]: e.target.value }));
  const emailValid = !values.email || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email);
  const save = useMutation({
    mutationFn: () =>
      api("platform", "PATCH", `/api/v1/platform/tenants/${tenant.tenant_id}`, {
        business_name: values.business_name.trim(),
        legal_name: values.legal_name.trim() || null,
        phone: values.phone.trim() || null,
        email: values.email.trim() || null,
        tax_number: values.tax_number.trim() || null,
      }),
    onSuccess: () => onDone("Business details saved."),
  });
  return (
    <Modal title="Edit business details" onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (values.business_name.trim() && emailValid) save.mutate();
        }}
        noValidate
      >
        {save.isError && <Alert tone="error">{errorText(save.error)}</Alert>}
        <Field
          label="Business name"
          value={values.business_name}
          onChange={set("business_name")}
          error={values.business_name.trim() ? undefined : "Enter the business name"}
        />
        <Field label="Registered name (optional)" value={values.legal_name} onChange={set("legal_name")} />
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Phone" type="tel" value={values.phone} onChange={set("phone")} />
          <Field label="Email" type="email" value={values.email} onChange={set("email")} error={emailValid ? undefined : "Enter a valid email"} />
        </div>
        <Field label="PAN / VAT number" value={values.tax_number} onChange={set("tax_number")} />
        <DialogActions onClose={onClose} loading={save.isPending} label="Save" />
      </form>
    </Modal>
  );
}
