"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Button, Card, ErrorBanner, Field } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Plan, TenantCreated } from "@/lib/platform";

const today = () => new Date().toISOString().slice(0, 10);

const schema = z
  .object({
    business_name: z.string().min(1, "Required"),
    legal_name: z.string().optional(),
    phone: z.string().optional(),
    email: z.union([z.email("Enter a valid email"), z.literal("")]).optional(),
    tax_number: z.string().optional(),
    vat_registered: z.boolean(),
    numbering_period: z.enum(["ad_year", "np_fiscal_year"]),
    plan_id: z.string().min(1, "Choose a package"),
    billing_cycle: z.enum(["monthly", "quarterly", "half_yearly", "yearly"]),
    start_date: z.string().min(1, "Required"),
    trial_days: z.string().optional(),
    owner_full_name: z.string().min(1, "Required"),
    owner_email: z.email("Enter the owner's email (used to log in)"),
    owner_phone: z.string().optional(),
    record_payment: z.boolean(),
    payment_amount: z.string().optional(),
    payment_method: z.enum(["bank_transfer", "esewa", "khalti", "fonepay", "cash", "cheque", "other"]),
    payment_reference: z.string().optional(),
  })
  .refine((v) => !v.record_payment || Number(v.payment_amount) > 0, {
    path: ["payment_amount"],
    message: "Enter the amount received",
  });

type FormValues = z.infer<typeof schema>;

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant="secondary"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      {copied ? "Copied ✓" : label}
    </Button>
  );
}

function LoginDetailsCard({ created }: { created: TenantCreated }) {
  const login = created.owner_login;
  return (
    <Card title={`Login details for ${created.business_name}`}>
      <dl className="mb-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
        <dt className="text-muted">Login page</dt>
        <dd className="break-all">{login.login_url}</dd>
        <dt className="text-muted">Email</dt>
        <dd className="break-all">{login.email}</dd>
        {login.temporary_password ? (
          <>
            <dt className="text-muted">Temporary password</dt>
            <dd className="font-mono text-lg">{login.temporary_password}</dd>
            <dt className="text-muted">Valid until</dt>
            <dd>{login.expires_at?.slice(0, 10)}</dd>
          </>
        ) : (
          <>
            <dt className="text-muted">Password</dt>
            <dd>This email already has a login; the owner uses their existing password.</dd>
          </>
        )}
        <dt className="text-muted">Subscription</dt>
        <dd>
          {created.subscription.status} · {created.subscription.start_date} → {created.subscription.expiry_date}
        </dd>
        {created.receipt_number && (
          <>
            <dt className="text-muted">Receipt</dt>
            <dd>{created.receipt_number}</dd>
          </>
        )}
      </dl>
      {login.temporary_password && (
        <p className="mb-4 rounded-lg bg-amber-500/15 px-3 py-2 text-sm">
          This password will not be shown again. Copy it now and send it to the owner.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {login.share_message && <CopyButton text={login.share_message} label="Copy message for WhatsApp" />}
        {login.temporary_password && <CopyButton text={login.temporary_password} label="Copy password" />}
        <Link href="/admin/tenants" className="inline-flex min-h-11 items-center px-4 text-blue-600 hover:underline">
          Back to tenants
        </Link>
      </div>
    </Card>
  );
}

function Select({
  label,
  error,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string }) {
  return (
    <div className="mb-4">
      <label htmlFor={props.name} className="mb-1 block text-sm font-medium">
        {label}
      </label>
      <select
        id={props.name}
        className="w-full rounded-lg border border-black/20 bg-transparent px-3 py-2 text-base dark:border-white/25"
        {...props}
      >
        {children}
      </select>
      {error && <p className="mt-1 text-sm text-red-600">{error}</p>}
    </div>
  );
}

export function NewTenantForm() {
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<TenantCreated | null>(null);
  const plans = useQuery({
    queryKey: ["platform-plans"],
    queryFn: () => api<Plan[]>("platform", "GET", "/api/v1/platform/plans"),
  });
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      vat_registered: false,
      numbering_period: "ad_year",
      billing_cycle: "yearly",
      start_date: today(),
      record_payment: true,
      payment_method: "esewa",
    },
  });
  const { errors } = form.formState;
  const [planId, cycle, recordPayment] = useWatch({
    control: form.control,
    name: ["plan_id", "billing_cycle", "record_payment"],
  });
  const price = plans.data
    ?.find((p) => p.id === planId)
    ?.prices.find((p) => p.billing_cycle === cycle && p.is_active);

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      const result = await api<TenantCreated>("platform", "POST", "/api/v1/platform/tenants", {
        business_name: v.business_name,
        legal_name: v.legal_name || null,
        phone: v.phone || null,
        email: v.email || null,
        tax_number: v.tax_number || null,
        vat_registered: v.vat_registered,
        numbering_period: v.numbering_period,
        plan_id: v.plan_id,
        billing_cycle: v.billing_cycle,
        start_date: v.start_date,
        trial_days: v.trial_days ? Number(v.trial_days) : null,
        owner_full_name: v.owner_full_name,
        owner_email: v.owner_email,
        owner_phone: v.owner_phone || null,
        initial_payment: v.record_payment
          ? {
              amount: v.payment_amount,
              payment_method: v.payment_method,
              paid_at: new Date().toISOString(),
              transaction_reference: v.payment_reference || null,
            }
          : null,
      });
      setCreated(result);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server.");
    }
  });

  if (created) return <div className="mx-auto max-w-xl"><LoginDetailsCard created={created} /></div>;

  return (
    <form onSubmit={onSubmit} noValidate className="mx-auto grid max-w-3xl gap-6">
      <h1 className="text-xl font-semibold">New tenant</h1>
      <ErrorBanner message={error} />

      <Card title="1 · Business">
        <Field label="Business name*" error={errors.business_name?.message} {...form.register("business_name")} />
        <Field label="Legal name" {...form.register("legal_name")} />
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field label="Phone" type="tel" placeholder="+977 98XXXXXXXX" {...form.register("phone")} />
          <Field label="Business email" type="email" error={errors.email?.message} {...form.register("email")} />
          <Field label="PAN / VAT number" {...form.register("tax_number")} />
          <Select label="Document numbering" {...form.register("numbering_period")}>
            <option value="ad_year">Calendar year (2026)</option>
            <option value="np_fiscal_year">Nepali fiscal year (2083-84)</option>
          </Select>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...form.register("vat_registered")} /> VAT registered
        </label>
      </Card>

      <Card title="2 · Package">
        {plans.data?.length === 0 && (
          <p className="mb-4 text-sm text-amber-700">No packages yet. A super admin must create one first.</p>
        )}
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Select label="Package*" error={errors.plan_id?.message} {...form.register("plan_id")}>
            <option value="">Choose…</option>
            {plans.data
              ?.filter((p) => p.is_active)
              .map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
          </Select>
          <Select label="Billing cycle" {...form.register("billing_cycle")}>
            <option value="monthly">Monthly</option>
            <option value="quarterly">Quarterly</option>
            <option value="half_yearly">Half-yearly</option>
            <option value="yearly">Yearly</option>
          </Select>
          <Field label="Start date*" type="date" error={errors.start_date?.message} {...form.register("start_date")} />
          <Field label="Trial days (optional)" type="number" min={1} max={90} {...form.register("trial_days")} />
        </div>
        <p className="text-sm text-muted">
          {planId && !price
            ? "This package has no price for that billing cycle."
            : price
              ? `Price: ${price.currency} ${price.amount}. Expiry is calculated from the start date.`
              : "Expiry is calculated from the start date and billing cycle."}
        </p>
      </Card>

      <Card title="3 · Owner login">
        <Field label="Owner name*" error={errors.owner_full_name?.message} {...form.register("owner_full_name")} />
        <div className="grid gap-x-4 sm:grid-cols-2">
          <Field
            label="Login email*"
            type="email"
            hint="The owner logs in with this email."
            error={errors.owner_email?.message}
            {...form.register("owner_email")}
          />
          <Field label="Mobile" type="tel" {...form.register("owner_phone")} />
        </div>
      </Card>

      <Card title="4 · Payment received">
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input type="checkbox" {...form.register("record_payment")} /> Record a payment now
        </label>
        {recordPayment && (
          <div className="grid gap-x-4 sm:grid-cols-3">
            <Field
              label="Amount*"
              inputMode="decimal"
              error={errors.payment_amount?.message}
              {...form.register("payment_amount")}
            />
            <Select label="Method" {...form.register("payment_method")}>
              <option value="esewa">eSewa</option>
              <option value="khalti">Khalti</option>
              <option value="fonepay">Fonepay</option>
              <option value="bank_transfer">Bank transfer</option>
              <option value="cash">Cash</option>
              <option value="cheque">Cheque</option>
              <option value="other">Other</option>
            </Select>
            <Field label="Reference" {...form.register("payment_reference")} />
          </div>
        )}
      </Card>

      <div>
        <Button type="submit" disabled={form.formState.isSubmitting}>
          {form.formState.isSubmitting ? "Creating…" : "Create tenant and owner login"}
        </Button>
      </div>
    </form>
  );
}
