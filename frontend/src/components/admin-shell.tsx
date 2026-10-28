"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Button } from "@/components/ui";
import { ApiError, api, type PlatformMe } from "@/lib/api";

export function AdminShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const me = useQuery({
    queryKey: ["platform-me"],
    queryFn: () => api<PlatformMe>("platform", "GET", "/api/v1/platform/auth/me"),
  });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/admin/login");
    if (me.data?.must_change_password) router.replace("/admin/change-password");
  }, [me.error, me.data, router]);

  if (me.isPending) return <p className="p-6 text-muted">Loading…</p>;
  if (!me.data) return <p className="p-6 text-muted">Could not load your account.</p>;

  async function logout() {
    await api("platform", "POST", "/api/v1/platform/auth/logout").catch(() => undefined);
    router.replace("/admin/login");
  }

  return (
    <div className="flex flex-1 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-black/10 px-4 py-3 dark:border-white/10">
        <nav className="flex items-center gap-4">
          <span className="font-semibold">Admin</span>
          <Link href="/admin/tenants" className="text-sm hover:underline">
            Tenants
          </Link>
          <Link href="/admin/tenants/new" className="text-sm hover:underline">
            New tenant
          </Link>
        </nav>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted">{me.data.email}</span>
          <Button variant="secondary" onClick={logout}>
            Log out
          </Button>
        </div>
      </header>
      <main className="flex-1 px-4 py-6">{children}</main>
    </div>
  );
}
