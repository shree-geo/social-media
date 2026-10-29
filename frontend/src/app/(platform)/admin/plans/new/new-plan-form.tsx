"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { Alert, Button, Field, PageHeader, TextArea } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { CYCLE_LABEL, LIMIT_LABEL } from "@/lib/platform";

const amount = z.string().regex(/^(\d+(\.\d{1,2})?)?$/, "Enter an amount like 1500 or 1500.50");
const count = z.string().regex(/^\d*$/, "Enter a whole number, or leave empty for unlimited");

const schema = z
  .object({
    name: z.string().trim().min(1, "Enter the package name"),
    code: z.string().regex(/^PLAN_[A-Z0-9_]{2,40}$/, "Use PLAN_ then 2–40 capital letters, digits or _"),
    description: z.string().max(1000).optional(),
    prices: z.record(z.string(), amount),
    limits: z.record(z.string(), count),
  })
  .refine((v) => Object.values(v.prices).some(Boolean), { path: ["prices"], message: "Give a price for at least one payment schedule." });
type Values = z.infer<typeof schema>;

/** "Business Plus" → "PLAN_BUSINESS_PLUS" (the code is permanent and used in reports). */
function codeFor(name: string): string {
  const slug = name.toUpperCase().replace(/[^A-Z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40);
  return slug ? `PLAN_${slug}` : "";
}

function Step({ title, description, children }: { title: string; description: string; children: ReactNode }) {
  return (
    <section className="grid gap-4 border-b border-line py-8 first:pt-0 last:border-b-0 md:grid-cols-[14rem_minmax(0,1fr)] md:gap-10">
      <div>
        <h2 className="text-lg font-semibold text-ink">{title}</h2>
        <p className="mt-1 text-sm text-ink-muted">{description}</p>
      </div>
      <div>{children}</div>
    </section>
  );
}

export function NewPlanForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const [codeEdited, setCodeEdited] = useState(false);
  const form = useForm<Values>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", code: "", description: "", prices: {}, limits: {} },
  });
  const { errors, isSubmitting } = form.formState;
  // The record's own error (from the refine), not one of its keys; hidden as soon as a price is typed.
  const prices = useWatch({ control: form.control, name: "prices" });
  const pricesError = Object.values(prices ?? {}).some(Boolean) ? undefined : (errors.prices as { message?: string } | undefined)?.message;

  const name = form.register("name");
  const code = form.register("code");

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    try {
      await api("platform", "POST", "/api/v1/platform/plans", {
        code: v.code,
        name: v.name.trim(),
        description: v.description?.trim() || null,
        prices: Object.entries(v.prices)
          .filter(([, value]) => value)
          .map(([billing_cycle, value]) => ({ billing_cycle, amount: value, currency: "NPR" })),
        features: Object.entries(v.limits)
          .filter(([, value]) => value)
          .map(([feature_key, value]) => ({ feature_key, limit_value: Number(value), enabled: true })),
      });
      await queryClient.invalidateQueries({ queryKey: ["platform-plans"] });
      router.push("/admin/plans");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Check your connection and try again.");
    }
  });

  return (
    <div className="mx-auto max-w-4xl">
      <Link href="/admin/plans" className="mb-4 inline-flex items-center gap-1.5 text-sm text-primary hover:underline">
        <ArrowLeft className="size-4" aria-hidden />
        Packages
      </Link>
      <PageHeader title="New package" description="Businesses are put on a package when you add them. Prices are in NPR." />
      {error && <Alert>{error}</Alert>}
      <form onSubmit={onSubmit} noValidate className="rounded-panel border border-line bg-surface px-5 py-8 sm:px-8">
        <Step title="Package" description="The name businesses see. The code is permanent.">
          <Field
            label="Name"
            placeholder="e.g. Business"
            error={errors.name?.message}
            {...name}
            onChange={(e) => {
              void name.onChange(e);
              if (!codeEdited) form.setValue("code", codeFor(e.target.value), { shouldValidate: form.formState.isSubmitted });
            }}
          />
          <Field
            label="Code"
            hint="Filled in from the name. Can't be changed later."
            error={errors.code?.message}
            {...code}
            onChange={(e) => {
              setCodeEdited(true);
              e.target.value = e.target.value.toUpperCase();
              void code.onChange(e);
            }}
          />
          <TextArea label="Description (optional)" hint="What's included, in a sentence or two." {...form.register("description")} />
        </Step>

        <Step title="Prices" description="Leave a schedule empty if this package isn't sold that way.">
          {pricesError && <Alert>{pricesError}</Alert>}
          <div className="grid gap-x-4 sm:grid-cols-2">
            {Object.entries(CYCLE_LABEL).map(([cycle, label]) => (
              <Field
                key={cycle}
                label={`${label} (Rs.)`}
                inputMode="decimal"
                error={errors.prices?.[cycle]?.message}
                {...form.register(`prices.${cycle}`)}
              />
            ))}
          </div>
        </Step>

        <Step title="Limits" description="Leave empty for unlimited. Businesses see a clear message when they reach a limit.">
          <div className="grid gap-x-4 sm:grid-cols-2">
            {Object.entries(LIMIT_LABEL).map(([key, label]) => (
              <Field
                key={key}
                label={label}
                inputMode="numeric"
                placeholder="Unlimited"
                error={errors.limits?.[key]?.message}
                {...form.register(`limits.${key}`)}
              />
            ))}
          </div>
        </Step>

        <div className="flex justify-end pt-2">
          <Button type="submit" loading={isSubmitting}>
            Create package
          </Button>
        </div>
      </form>
    </div>
  );
}
