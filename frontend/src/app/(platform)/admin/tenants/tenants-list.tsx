"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, PageHeader, SubscriptionPill, cx } from "@/components/ui";
import { api } from "@/lib/api";
import type { TenantListItem } from "@/lib/platform";

const FILTERS = [
  { key: "all", label: "All", test: () => true },
  {
    key: "renewals",
    label: "Renewals due",
    test: (t: TenantListItem) => t.days_remaining !== null && t.days_remaining >= 0 && t.days_remaining <= 30,
  },
  { key: "lapsed", label: "Grace or expired", test: (t: TenantListItem) => t.subscription_status === "GRACE" || t.subscription_status === "EXPIRED" },
  { key: "suspended", label: "Suspended", test: (t: TenantListItem) => t.subscription_status === "SUSPENDED" },
] as const;

function daysLeft(t: TenantListItem): { text: string; urgent: boolean } {
  if (t.days_remaining === null) return { text: "", urgent: false };
  if (t.days_remaining < 0) return { text: `${-t.days_remaining} days ago`, urgent: true };
  if (t.days_remaining === 0) return { text: "Today", urgent: true };
  return { text: `${t.days_remaining} days`, urgent: t.days_remaining <= 15 };
}

export function TenantsList() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["key"]>("all");
  const tenants = useQuery({
    queryKey: ["platform-tenants"],
    queryFn: () => api<TenantListItem[]>("platform", "GET", "/api/v1/platform/tenants?limit=100"),
  });
  const all = tenants.data ?? [];
  const active = FILTERS.find((f) => f.key === filter)!;
  const rows = all.filter(active.test);

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        title="Businesses"
        description="Every SME using the platform, with their package and when it renews."
        actions={
          <Link
            href="/admin/tenants/new"
            className="inline-flex min-h-11 items-center gap-2 rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover"
          >
            <Plus className="size-4" aria-hidden />
            Add a business
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Filter">
        {FILTERS.map((f) => {
          const count = all.filter(f.test).length;
          return (
            <button
              key={f.key}
              role="tab"
              aria-selected={filter === f.key}
              onClick={() => setFilter(f.key)}
              className={cx(
                "inline-flex items-center gap-2 rounded-full border px-3.5 py-1.5 text-sm transition-colors",
                filter === f.key ? "border-primary bg-primary-soft font-medium text-primary" : "border-line bg-surface text-ink-muted hover:border-line-strong",
              )}
            >
              {f.label}
              <span className="tabular text-xs">{count}</span>
            </button>
          );
        })}
      </div>

      {tenants.isPending ? null : all.length === 0 ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState
            icon={Building2}
            title="No businesses yet"
            action={
              <Link href="/admin/tenants/new" className="font-medium text-primary hover:underline">
                Add the first business
              </Link>
            }
          >
            When an SME signs up, add them here and send them their login details.
          </EmptyState>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-panel border border-line bg-surface">
          <table className="w-full min-w-[680px] text-left">
            <thead className="border-b border-line bg-sunken/60 text-sm text-ink-muted">
              <tr>
                <th scope="col" className="px-4 py-3 font-medium">Business</th>
                <th scope="col" className="px-4 py-3 font-medium">Package</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3 font-medium">Renews</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">Time left</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const left = daysLeft(t);
                return (
                  <tr key={t.tenant_id} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-3">
                      <p className="font-medium text-ink">{t.business_name}</p>
                      <p className="text-xs text-ink-subtle">Joined {new Date(t.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</p>
                    </td>
                    <td className="px-4 py-3 text-ink-muted">{t.plan_code?.replace(/^PLAN_/, "").replace(/_/g, " ").toLowerCase().replace(/^\w/, (m) => m.toUpperCase()) ?? "None"}</td>
                    <td className="px-4 py-3">
                      <SubscriptionPill status={t.subscription_status} />
                    </td>
                    <td className="tabular px-4 py-3 text-ink-muted">
                      {t.expiry_date ? new Date(t.expiry_date).toLocaleDateString(undefined, { dateStyle: "medium" }) : "None"}
                    </td>
                    <td className={cx("tabular px-4 py-3 text-right", left.urgent ? "font-semibold text-attention-ink" : "text-ink-muted")}>
                      {left.text}
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-8 text-center text-ink-muted">
                    No businesses in this list.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
