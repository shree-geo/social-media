"use client";

import { useQuery } from "@tanstack/react-query";
import { Package, Plus } from "lucide-react";
import Link from "next/link";

import { EmptyState, PageHeader, Pill } from "@/components/ui";
import { api, type PlatformMe } from "@/lib/api";
import { CYCLE_LABEL, LIMIT_LABEL, type Plan } from "@/lib/platform";
import { formatMoney } from "@/lib/sales";

const CYCLES = Object.keys(CYCLE_LABEL);

function PlanCard({ plan }: { plan: Plan }) {
  const prices = plan.prices.filter((p) => p.is_active).sort((a, b) => CYCLES.indexOf(a.billing_cycle) - CYCLES.indexOf(b.billing_cycle));
  const limits = Object.entries(LIMIT_LABEL).map(([key, label]) => {
    const feature = plan.features.find((f) => f.feature_key === key);
    const value = feature?.enabled && feature.limit_value !== null ? feature.limit_value.toLocaleString() : "Unlimited";
    return { key, label, value };
  });
  return (
    <li className="rounded-panel border border-line bg-surface p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold text-ink">{plan.name}</h2>
        {!plan.is_active && <Pill tone="neutral">Not offered</Pill>}
      </div>
      <p className="tabular text-xs text-ink-subtle">{plan.code}</p>
      {plan.description && <p className="mt-2 text-sm text-ink-muted">{plan.description}</p>}
      <dl className="mt-4 grid gap-1.5 text-sm">
        {prices.map((p) => (
          <div key={p.id} className="flex justify-between gap-4">
            <dt className="text-ink-muted">{CYCLE_LABEL[p.billing_cycle] ?? p.billing_cycle}</dt>
            <dd className="tabular font-semibold text-ink">{formatMoney(p.amount, p.currency)}</dd>
          </div>
        ))}
      </dl>
      <dl className="mt-4 grid gap-1.5 border-t border-line pt-4 text-sm">
        {limits.map((l) => (
          <div key={l.key} className="flex justify-between gap-4">
            <dt className="text-ink-muted">{l.label}</dt>
            <dd className="tabular text-ink">{l.value}</dd>
          </div>
        ))}
      </dl>
    </li>
  );
}

export function PlansList() {
  const me = useQuery({ queryKey: ["platform-me"], queryFn: () => api<PlatformMe>("platform", "GET", "/api/v1/platform/auth/me") });
  const plans = useQuery({ queryKey: ["platform-plans"], queryFn: () => api<Plan[]>("platform", "GET", "/api/v1/platform/plans") });
  const canCreate = me.data?.role === "PLATFORM_SUPER_ADMIN";
  const create = (
    <Link
      href="/admin/plans/new"
      className="inline-flex min-h-11 items-center gap-2 rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover"
    >
      <Plus className="size-4" aria-hidden />
      New package
    </Link>
  );

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Packages"
        description="What businesses can subscribe to: prices for each payment schedule and the limits that come with it."
        actions={canCreate ? create : undefined}
      />
      {plans.isPending ? null : !plans.data?.length ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState icon={Package} title="No packages yet" action={canCreate ? create : undefined}>
            {canCreate ? "Create a package before adding the first business." : "A super admin needs to create a package first."}
          </EmptyState>
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {plans.data.map((plan) => (
            <PlanCard key={plan.id} plan={plan} />
          ))}
        </ul>
      )}
    </div>
  );
}
