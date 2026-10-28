"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Check, Copy, KeyRound } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Alert, Button, Checkbox, Field, PageHeader, SelectField } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { Plan, TenantCreated } from "@/lib/platform";

/** Today's date in the browser's own timezone, as YYYY-MM-DD for <input type="date">. */
function localToday(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

const schema = z
  .object({
    business_name: z.string().min(1, "Enter the business name"),
    legal_name: z.string().optional(),
    phone: z.string().optional(),
    email: z.union([z.email("Enter a valid email"), z.literal("")]).optional(),
    tax_number: z.string().optional(),
    vat_registered: z.boolean(),
    numbering_period: z.enum(["ad_year", "np_fiscal_year"]),
    plan_id: z.string().min(1, "Choose a package"),
    billing_cycle: z.enum(["monthly", "quarterly", "half_yearly", "yearly"]),
    start_date: z.string().min(1, "Choose a start date"),
    trial_days: z.string().optional(),
    owner_full_name: z.string().min(1, "Enter the owner's name"),
    owner_email: z.email("Enter the owner's email — they log in with it"),
    owner_phone: z.string().optional(),
    record_payment: z.boolean(),
    payment_amount: z.string().optional(),
    payment_method: z.enum(["bank_transfer", "esewa", "khalti", "fonepay", "cash", "cheque", "other"]),
    payment_reference: z.string().optional(),
  })
  .refine((v) => !v.record_payment || Number(v.payment_amount) > 0, {
    path: ["payment_amount"],
    message: "Enter the amount you received",
  });

type FormValues = z.infer<typeof schema>;

const CYCLE_LABEL: Record<string, string> = {
  monthly: "Monthly",
  quarterly: "Every 3 months",
  half_yearly: "Every 6 months",
  yearly: "Yearly",
};

function Step({ number, title, description, children }: { number: number; title: string; description: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-b border-line py-8 first:pt-0 last:border-b-0 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-10">
      <div>
        <p className="tabular text-sm font-semibold text-primary">Step {number}</p>
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <p className="mt-1 text-sm text-ink-muted">{description}</p>
      </div>
      <div>{children}</div>
    </section>
  );
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      type="button"
      variant={copied ? "secondary" : "primary"}
      icon={copied ? Check : Copy}
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2500);
      }}
    >
      {copied ? "Copied" : label}
    </Button>
  );
}

function LoginDetails({ created }: { created: TenantCreated }) {
  const login = created.owner_login;
  const expires = login.expires_at ? new Date(login.expires_at).toLocaleDateString(undefined, { dateStyle: "long" }) : "";
  return (
    <div className="mx-auto max-w-2xl">
      <PageHeader
        title={`${created.business_name} is ready`}
        description={`Subscription ${created.subscription.status.toLowerCase()} until ${new Date(created.subscription.expiry_date).toLocaleDateString(undefined, { dateStyle: "long" })}${created.receipt_number ? `. Receipt ${created.receipt_number}.` : "."}`}
      />
      {login.temporary_password ? (
        <>
          <Alert tone="warning" title="Send these login details now">
            The temporary password is shown only once. It works until {expires}, and the owner must change it when they first log in.
          </Alert>
          <section className="rounded-panel border border-line bg-surface">
            <dl className="divide-y divide-line">
              {[
                ["Login page", login.login_url],
                ["Email", login.email],
              ].map(([term, value]) => (
                <div key={term} className="grid gap-1 px-5 py-3 sm:grid-cols-[10rem_1fr]">
                  <dt className="text-sm text-ink-muted">{term}</dt>
                  <dd className="break-all text-ink">{value}</dd>
                </div>
              ))}
              <div className="grid gap-1 px-5 py-4 sm:grid-cols-[10rem_1fr]">
                <dt className="flex items-center gap-1.5 text-sm text-ink-muted">
                  <KeyRound className="size-4" aria-hidden />
                  Temporary password
                </dt>
                <dd className="tabular text-2xl font-semibold tracking-wide text-ink">{login.temporary_password}</dd>
              </div>
            </dl>
          </section>
          {login.share_message && (
            <section className="mt-6">
              <h2 className="mb-2 text-base font-semibold text-ink">Message to send on WhatsApp</h2>
              <pre className="rounded-panel bg-sunken px-4 py-3 font-sans text-sm whitespace-pre-wrap text-ink">{login.share_message}</pre>
            </section>
          )}
          <div className="mt-6 flex flex-wrap items-center gap-3">
            {login.share_message && <CopyButton text={login.share_message} label="Copy WhatsApp message" />}
            <CopyButton text={login.temporary_password} label="Copy password only" />
          </div>
        </>
      ) : (
        <Alert tone="info" title="The owner already has a login">
          {login.email} already uses the app for another business, so they keep their current password and will see {created.business_name} after logging in.
        </Alert>
      )}
      <Link href="/admin/tenants" className="mt-8 inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline">
        <ArrowLeft className="size-4" aria-hidden />
        Back to businesses
      </Link>
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
      start_date: "", // filled in after load: this page is prerendered, so reading the clock here would freeze the build date
      record_payment: true,
      payment_method: "esewa",
    },
  });
  const { errors, isSubmitting } = form.formState;
  useEffect(() => {
    if (!form.getValues("start_date")) form.setValue("start_date", localToday());
  }, [form]);
  const [planId, cycle, recordPayment] = useWatch({
    control: form.control,
    name: ["plan_id", "billing_cycle", "record_payment"],
  });
  const activePlans = plans.data?.filter((p) => p.is_active) ?? [];
  const price = activePlans.find((p) => p.id === planId)?.prices.find((p) => p.billing_cycle === cycle && p.is_active);

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
      window.scrollTo({ top: 0 });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Check your connection and try again.");
    }
  });

  if (created) return <LoginDetails created={created} />;

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Add a business" description="Set up the account, choose their package, and create the owner's login." />
      {error && <Alert tone="error">{error}</Alert>}
      <form onSubmit={onSubmit} noValidate className="rounded-panel border border-line bg-surface px-5 py-8 sm:px-8">
        <Step number={1} title="Business" description="Shown on invoices and in the app.">
          <Field label="Business name" error={errors.business_name?.message} {...form.register("business_name")} />
          <Field label="Registered name (optional)" {...form.register("legal_name")} />
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field label="Phone" type="tel" placeholder="+977 98XXXXXXXX" {...form.register("phone")} />
            <Field label="Business email (optional)" type="email" error={errors.email?.message} {...form.register("email")} />
            <Field label="PAN / VAT number" {...form.register("tax_number")} />
            <SelectField label="Number invoices by" {...form.register("numbering_period")}>
              <option value="ad_year">Calendar year (2026)</option>
              <option value="np_fiscal_year">Nepali fiscal year (2083-84)</option>
            </SelectField>
          </div>
          <Checkbox label="VAT registered" hint="Adds 13% VAT to invoices by default." {...form.register("vat_registered")} />
        </Step>

        <Step number={2} title="Package" description="The renewal date is worked out from the start date and how often they pay.">
          {plans.data && activePlans.length === 0 && (
            <Alert tone="warning">No packages exist yet. A super admin needs to create one first.</Alert>
          )}
          <div className="grid gap-x-4 sm:grid-cols-2">
            <SelectField label="Package" error={errors.plan_id?.message} {...form.register("plan_id")}>
              <option value="">Choose a package</option>
              {activePlans.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </SelectField>
            <SelectField label="Pays" {...form.register("billing_cycle")}>
              {Object.entries(CYCLE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </SelectField>
            <Field label="Starts on" type="date" error={errors.start_date?.message} {...form.register("start_date")} />
            <Field label="Free trial days (optional)" type="number" min={1} max={90} inputMode="numeric" {...form.register("trial_days")} />
          </div>
          {planId && (
            <p className="tabular rounded-control bg-sunken px-3 py-2 text-sm text-ink">
              {price ? `${price.currency} ${Number(price.amount).toLocaleString()} ${CYCLE_LABEL[cycle].toLowerCase()}` : "This package has no price for that payment schedule."}
            </p>
          )}
        </Step>

        <Step number={3} title="Owner's login" description="We create a temporary password for you to send them.">
          <Field label="Owner's name" error={errors.owner_full_name?.message} {...form.register("owner_full_name")} />
          <div className="grid gap-x-4 sm:grid-cols-2">
            <Field
              label="Email they log in with"
              type="email"
              autoComplete="off"
              error={errors.owner_email?.message}
              {...form.register("owner_email")}
            />
            <Field label="Mobile (optional)" type="tel" placeholder="+977 98XXXXXXXX" {...form.register("owner_phone")} />
          </div>
        </Step>

        <Step number={4} title="Payment" description="Record money already received. You can also add it later.">
          <Checkbox label="I've received a payment" {...form.register("record_payment")} />
          {recordPayment && (
            <div className="grid gap-x-4 sm:grid-cols-3">
              <Field label="Amount (NPR)" inputMode="decimal" error={errors.payment_amount?.message} {...form.register("payment_amount")} />
              <SelectField label="Paid by" {...form.register("payment_method")}>
                <option value="esewa">eSewa</option>
                <option value="khalti">Khalti</option>
                <option value="fonepay">Fonepay</option>
                <option value="bank_transfer">Bank transfer</option>
                <option value="cash">Cash</option>
                <option value="cheque">Cheque</option>
                <option value="other">Other</option>
              </SelectField>
              <Field label="Reference (optional)" {...form.register("payment_reference")} />
            </div>
          )}
        </Step>

        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-6">
          <Link href="/admin/tenants" className="px-3 py-2 text-ink-muted hover:text-ink">
            Cancel
          </Link>
          <Button type="submit" loading={isSubmitting}>
            Create business and login
          </Button>
        </div>
      </form>
    </div>
  );
}
