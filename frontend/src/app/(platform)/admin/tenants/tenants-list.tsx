"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { api } from "@/lib/api";
import type { TenantListItem } from "@/lib/platform";

const STATUS_STYLE: Record<string, string> = {
  ACTIVE: "bg-green-600/15 text-green-700 dark:text-green-300",
  TRIAL: "bg-blue-600/15 text-blue-700 dark:text-blue-300",
  GRACE: "bg-amber-500/20 text-amber-800 dark:text-amber-300",
  EXPIRED: "bg-red-600/15 text-red-700 dark:text-red-300",
  SUSPENDED: "bg-red-600/15 text-red-700 dark:text-red-300",
};

export function TenantsList() {
  const tenants = useQuery({
    queryKey: ["platform-tenants"],
    queryFn: () => api<TenantListItem[]>("platform", "GET", "/api/v1/platform/tenants"),
  });

  if (tenants.isPending) return <p className="text-muted">Loading…</p>;
  if (tenants.error) return <p className="text-red-600">Could not load tenants.</p>;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Tenants</h1>
        <Link href="/admin/tenants/new" className="rounded-lg bg-blue-600 px-4 py-2 text-white hover:bg-blue-700">
          New tenant
        </Link>
      </div>
      {tenants.data.length === 0 ? (
        <p className="text-muted">No tenants yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-black/10 dark:border-white/15">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="bg-black/5 dark:bg-white/5">
              <tr>
                <th className="px-3 py-2 font-medium">Business</th>
                <th className="px-3 py-2 font-medium">Package</th>
                <th className="px-3 py-2 font-medium">Status</th>
                <th className="px-3 py-2 font-medium">Expiry</th>
                <th className="px-3 py-2 text-right font-medium">Days left</th>
              </tr>
            </thead>
            <tbody>
              {tenants.data.map((t) => (
                <tr key={t.tenant_id} className="border-t border-black/10 dark:border-white/10">
                  <td className="px-3 py-2">{t.business_name}</td>
                  <td className="px-3 py-2">{t.plan_code ?? "—"}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLE[t.subscription_status ?? ""] ?? ""}`}>
                      {t.subscription_status ?? "None"}
                    </span>
                  </td>
                  <td className="px-3 py-2">{t.expiry_date ?? "—"}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{t.days_remaining ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
