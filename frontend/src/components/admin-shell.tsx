"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, LogOut, PlusCircle, ShieldCheck, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";

import { cx } from "@/components/ui";
import { brand } from "@/config/brand";
import { ApiError, api, type PlatformMe } from "@/lib/api";

const NAV: { href: string; label: string; icon: LucideIcon; exact: boolean }[] = [
  { href: "/admin/tenants", label: "Businesses", icon: Building2, exact: true },
  { href: "/admin/tenants/new", label: "Add a business", icon: PlusCircle, exact: true },
];

function AdminNav() {
  const pathname = usePathname();
  return NAV.map((item) => <AdminNavLink key={item.href} item={item} active={pathname === item.href} />);
}

function AdminNavLink({ item, active }: { item: (typeof NAV)[number]; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cx(
        "flex items-center gap-3 rounded-control px-3 py-2.5 transition-colors",
        active ? "bg-nav-active font-semibold text-nav-ink" : "text-nav-ink-muted hover:bg-nav-hover hover:text-nav-ink",
      )}
    >
      <Icon className="size-5" aria-hidden />
      {item.label}
    </Link>
  );
}

const ROLE_LABEL: Record<string, string> = {
  PLATFORM_SUPER_ADMIN: "Super admin",
  PLATFORM_ADMIN: "Admin",
  PLATFORM_SUPPORT: "Support",
};

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

  // Always render the page below (children); see TenantShell for why.

  async function logout() {
    await api("platform", "POST", "/api/v1/platform/auth/logout").catch(() => undefined);
    router.replace("/admin/login");
  }

  return (
    <div className="flex min-h-dvh flex-col lg:flex-row">
      {/* Darker ink-navy sidebar (--sc-admin-nav-bg) so the admin console is never mistaken for a business's app. */}
      <aside className="flex shrink-0 flex-col bg-admin-nav text-nav-ink lg:sticky lg:top-0 lg:h-dvh lg:w-64">
        <div className="flex items-center justify-between gap-3 px-4 py-4 lg:block lg:px-5 lg:pt-6">
          <p className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="size-5" aria-hidden />
            {brand.name} admin
          </p>
          <button onClick={logout} className="grid size-10 place-items-center rounded-control lg:hidden" aria-label="Log out">
            <LogOut className="size-5" aria-hidden />
          </button>
        </div>
        <nav aria-label="Admin" className="flex gap-1 overflow-x-auto px-2 pb-2 lg:mt-4 lg:flex-col lg:pb-0">
          <Suspense fallback={NAV.map((item) => <AdminNavLink key={item.href} item={item} active={false} />)}>
            <AdminNav />
          </Suspense>
        </nav>
        <div className="mt-auto hidden border-t border-nav-line px-5 py-4 lg:block">
          <p className="truncate text-sm font-medium">{me.data?.full_name ?? "\u00a0"}</p>
          <p className="truncate text-xs opacity-75">{me.data ? (ROLE_LABEL[me.data.role] ?? me.data.role) : "\u00a0"}</p>
          <button onClick={logout} className="mt-3 inline-flex items-center gap-2 text-sm opacity-80 hover:opacity-100">
            <LogOut className="size-4" aria-hidden />
            Log out
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-4 py-6 sm:px-8 sm:py-8">{children}</main>
    </div>
  );
}
