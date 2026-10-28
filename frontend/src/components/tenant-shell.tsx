"use client";

import { useQuery } from "@tanstack/react-query";
import { Home, LogOut, MessageCircle, MessagesSquare, Users, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, type ReactNode } from "react";

import { DhakaPattern } from "@/components/dhaka-pattern";
import { cx } from "@/components/ui";
import { brand } from "@/config/brand";
import { ApiError, api, type Me } from "@/lib/api";
import type { ConversationPage } from "@/lib/inbox";

type NavItem = { href: string; label: string; icon: LucideIcon; permission: string | null; badge?: number };

const NAV: Omit<NavItem, "badge">[] = [
  { href: "/dashboard", label: "Home", icon: Home, permission: null },
  { href: "/inbox", label: "Inbox", icon: MessagesSquare, permission: "conversation.read" },
  { href: "/customers", label: "Customers", icon: Users, permission: "customer.read" },
];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => api<Me>("tenant", "GET", "/api/v1/auth/me") });
}

/** Number of conversations with unread customer messages (shown on the Inbox tab). */
function useWaitingCount(enabled: boolean): number {
  const waiting = useQuery({
    queryKey: ["conversations", "unread-count"],
    queryFn: () => api<ConversationPage>("tenant", "GET", "/api/v1/conversations?view=unread&limit=100"),
    enabled,
    refetchInterval: 30_000,
  });
  return waiting.data?.items.length ?? 0;
}

// Reads the URL, so it sits in its own Suspense boundary: on dynamic routes the pathname
// is only known at request time, and the rest of the shell can still be prerendered.
function NavLinks({ items, variant }: { items: NavItem[]; variant: "side" | "bottom" }) {
  const pathname = usePathname();
  return items.map((item) => (
    <NavLink key={item.href} item={item} variant={variant} active={pathname.startsWith(item.href)} />
  ));
}

function NavLink({ item, variant, active }: { item: NavItem; variant: "side" | "bottom"; active: boolean }) {
  const Icon = item.icon;
  const badge = item.badge ? (
    <span className="tabular min-w-5 rounded-full bg-attention px-1.5 text-center text-xs leading-5 font-semibold text-on-attention">
      {item.badge > 99 ? "99+" : item.badge}
    </span>
  ) : null;
  if (variant === "side") {
    return (
      <Link
        href={item.href}
        aria-current={active ? "page" : undefined}
        className={cx(
          "relative flex items-center gap-3 rounded-control px-3 py-2.5 text-base transition-colors",
          active ? "bg-nav-active font-semibold text-nav-ink" : "text-nav-ink-muted hover:bg-nav-hover hover:text-nav-ink",
        )}
      >
        {active && <span className="absolute inset-y-2 -left-2 w-1 rounded-r-full bg-nav-marker" aria-hidden />}
        <Icon className="size-5" aria-hidden />
        <span className="flex-1">{item.label}</span>
        {badge}
      </Link>
    );
  }
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cx("relative flex flex-col items-center gap-0.5 py-2 text-xs", active ? "font-semibold text-primary" : "text-ink-muted")}
    >
      <span className="relative">
        <Icon className="size-6" aria-hidden />
        {badge && <span className="absolute -top-1.5 -right-3">{badge}</span>}
      </span>
      {item.label}
    </Link>
  );
}

export function TenantShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const me = useMe();
  const canReadInbox = me.data?.permissions.includes("conversation.read") ?? false;
  const waiting = useWaitingCount(canReadInbox && !me.data?.must_change_password);
  const loadFailed = me.isError && !(me.error instanceof ApiError && me.error.status === 401);

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
    if (me.data?.must_change_password) router.replace("/change-password");
  }, [me.error, me.data, router]);

  // Always render the page below (children): Next.js renders and validates each route
  // segment, and pages handle their own loading states. Only the shell's account details wait.
  const allowed = new Set(me.data?.permissions ?? []);
  const nav: NavItem[] = NAV.filter((item) => item.permission === null || allowed.has(item.permission)).map((item) => ({
    ...item,
    badge: item.href === "/inbox" ? waiting : undefined,
  }));

  async function logout() {
    await api("tenant", "POST", "/api/v1/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col overflow-hidden bg-nav text-nav-ink md:flex">
        <div className="px-4 pt-5 pb-6">
          <p className="flex items-center gap-2 text-sm font-semibold text-nav-ink-muted">
            <MessageCircle className="size-5" aria-hidden />
            {brand.name}
          </p>
          {me.data ? (
            <p className="mt-3 truncate text-lg font-semibold text-nav-ink">{me.data.business_name}</p>
          ) : (
            <span className="mt-4 block h-5 w-36 animate-pulse rounded bg-nav-hover" aria-hidden />
          )}
        </div>
        <nav aria-label="Main" className="flex flex-col gap-1 px-2">
          <Suspense fallback={nav.map((item) => <NavLink key={item.href} item={item} variant="side" active={false} />)}>
            <NavLinks items={nav} variant="side" />
          </Suspense>
        </nav>
        <DhakaPattern className="mt-auto h-14 w-full shrink-0 opacity-50" />
        <div className="border-t border-nav-line px-4 py-4">
          <p className="truncate text-sm font-medium text-nav-ink">{me.data?.full_name ?? "\u00a0"}</p>
          <p className="truncate text-xs text-nav-ink-muted">{me.data?.email ?? "\u00a0"}</p>
          <button
            onClick={logout}
            className="mt-3 inline-flex items-center gap-2 rounded-control text-sm text-nav-ink-muted hover:text-nav-ink"
          >
            <LogOut className="size-4" aria-hidden />
            Log out
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 bg-nav px-4 py-3 text-nav-ink md:hidden">
          <p className="truncate text-base font-semibold">{me.data?.business_name ?? "\u00a0"}</p>
          <button onClick={logout} className="grid size-10 place-items-center rounded-control text-nav-ink-muted" aria-label="Log out">
            <LogOut className="size-5" aria-hidden />
          </button>
        </header>
        {loadFailed && (
          <p role="alert" className="border-b border-danger/30 bg-danger-soft px-4 py-2 text-sm text-danger">
            We couldn&apos;t load your account. Refresh the page to try again.
          </p>
        )}
        <div className="flex min-h-0 flex-1 flex-col pb-16 md:pb-0">{children}</div>
      </div>

      {/* Phone navigation: most staff use the app on a phone. */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 grid border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
        style={{ gridTemplateColumns: `repeat(${nav.length}, minmax(0, 1fr))` }}
      >
        <Suspense fallback={nav.map((item) => <NavLink key={item.href} item={item} variant="bottom" active={false} />)}>
          <NavLinks items={nav} variant="bottom" />
        </Suspense>
      </nav>
    </div>
  );
}
