"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";

import { NAV, splitPhoneNav, useMe } from "@/components/tenant-shell";
import { PageHeader } from "@/components/ui";

/** Phone-only list of sections that don't fit in the tab bar. */
export function MoreMenu() {
  const me = useMe();
  const allowed = new Set(me.data?.permissions ?? []);
  const items = splitPhoneNav(NAV.filter((item) => item.permission === null || allowed.has(item.permission))).more;
  return (
    <main className="mx-auto w-full max-w-xl px-4 py-6">
      <PageHeader title="More" />
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
    </main>
  );
}
