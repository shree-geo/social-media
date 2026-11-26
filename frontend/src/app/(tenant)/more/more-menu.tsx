"use client";

import { ChevronRight, LogOut } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { BrandMark } from "@/components/brand-mark";
import { NAV, roleName, splitPhoneNav, useMe } from "@/components/tenant-shell";
import { PageHeader } from "@/components/ui";
import { brand } from "@/config/brand";
import { api } from "@/lib/api";

/** Phone-only: the business and your account, sections that don't fit in the tab bar, and log out. */
export function MoreMenu() {
  const me = useMe();
  const router = useRouter();
  const allowed = new Set(me.data?.permissions ?? []);
  const items = splitPhoneNav(NAV.filter((item) => item.permission === null || allowed.has(item.permission))).more;

  async function logout() {
    await api("tenant", "POST", "/api/v1/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  return (
    <main className="mx-auto grid w-full max-w-xl gap-5 px-4 py-6">
      <PageHeader title="More" />
      <section className="flex items-center gap-3 rounded-panel bg-nav px-4 py-4 text-nav-ink">
        <BrandMark className="size-10 shrink-0 ring-1 ring-nav-line" />
        <div className="min-w-0">
          <p className="truncate font-semibold">{me.data?.business_name ?? "\u00a0"}</p>
          <p className="truncate text-sm text-nav-ink-muted">
            {me.data ? `${me.data.full_name}, ${roleName(me.data.roles)}` : "\u00a0"}
          </p>
        </div>
      </section>
      {items.length > 0 && (
        <ul className="overflow-hidden rounded-panel border border-line bg-surface">
          {items.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.href} className="border-b border-line last:border-b-0">
                <Link href={item.href} className="flex items-center gap-3 px-4 py-4 text-ink hover:bg-sunken/70">
                  <Icon className="size-5 text-primary" aria-hidden />
                  <span className="flex-1">{item.label}</span>
                  <ChevronRight className="size-5 text-ink-subtle" aria-hidden />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <button
        type="button"
        onClick={logout}
        className="flex items-center gap-3 rounded-panel border border-line bg-surface px-4 py-4 text-left text-ink hover:bg-sunken/70"
      >
        <LogOut className="size-5 text-ink-muted" aria-hidden />
        <span className="flex-1">Log out</span>
      </button>
      <p className="text-center text-xs text-ink-subtle">{brand.name}</p>
    </main>
  );
}
