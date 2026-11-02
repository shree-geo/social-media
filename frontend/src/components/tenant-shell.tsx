"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BellRing,
  Home,
  LogOut,
  MessagesSquare,
  Menu,
  Package,
  Plug,
  ShoppingBag,
  Target,
  X,
  Truck,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";

import { BrandMark } from "@/components/brand-mark";
import { cx } from "@/components/ui";
import { brand } from "@/config/brand";
import { ApiError, api, type Me } from "@/lib/api";
import type { ConversationPage } from "@/lib/inbox";

type NavItem = { href: string; label: string; icon: LucideIcon; permission: string | null; phone: boolean; badge?: number };

// ``phone``: may be a phone tab (the first four someone can see); the rest are under "More" there.
export const NAV: Omit<NavItem, "badge">[] = [
  { href: "/dashboard", label: "Home", icon: Home, permission: null, phone: true },
  { href: "/inbox", label: "Inbox", icon: MessagesSquare, permission: "conversation.read", phone: true },
  { href: "/leads", label: "Leads", icon: Target, permission: "lead.read", phone: true },
  { href: "/orders", label: "Orders", icon: ShoppingBag, permission: "order.read", phone: true },
  { href: "/customers", label: "Customers", icon: Users, permission: "customer.read", phone: true },
  { href: "/deliveries", label: "Deliveries", icon: Truck, permission: "delivery.read", phone: true },
  { href: "/payments", label: "Payments", icon: Wallet, permission: "payment.read", phone: false },
  { href: "/products", label: "Products", icon: Package, permission: "product.read", phone: false },
  { href: "/channels", label: "Channels", icon: Plug, permission: "channel.manage", phone: false },
];

const PHONE_TABS = 4;

/** Splits the items someone may see into phone tabs (first four ``phone`` items) and the "More" list. */
export function splitPhoneNav<T extends Pick<NavItem, "phone">>(items: T[]): { tabs: T[]; more: T[] } {
  const tabs = items.filter((item) => item.phone).slice(0, PHONE_TABS);
  return { tabs, more: items.filter((item) => !tabs.includes(item)) };
}

const MORE: NavItem = { href: "/more", label: "More", icon: Menu, permission: null, phone: true };

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

/** Your open leads with a follow-up overdue or due today (shown on the Leads tab). */
function useFollowupCount(enabled: boolean): number {
  const count = useQuery({
    queryKey: ["lead-followups"],
    queryFn: () => api<{ overdue: number; today: number }>("tenant", "GET", "/api/v1/leads/followups/count"),
    enabled,
    refetchInterval: 60_000,
  });
  return (count.data?.overdue ?? 0) + (count.data?.today ?? 0);
}

type Notice = { key: string; text: string; href: string };

/**
 * Lead events from the live stream: refresh lead screens anywhere in the app, and tell the
 * owner when a lead is given to them or a follow-up comes due.
 */
function useLeadEvents(enabled: boolean, userId: string | undefined): [Notice[], (key: string) => void] {
  const queryClient = useQueryClient();
  const [notices, setNotices] = useState<Notice[]>([]);
  useEffect(() => {
    if (!enabled) return;
    const source = new EventSource("/api/v1/events/stream", { withCredentials: true });
    const handle = (event: MessageEvent<string>) => {
      const data = JSON.parse(event.data) as { type: string; lead_id?: string; lead_number?: string; assigned_to_user_id?: string | null };
      void queryClient.invalidateQueries({ queryKey: ["leads"] });
      void queryClient.invalidateQueries({ queryKey: ["lead-followups"] });
      if (data.lead_id) void queryClient.invalidateQueries({ queryKey: ["lead", data.lead_id] });
      if (!data.lead_id || !userId || data.assigned_to_user_id !== userId) return;
      const text =
        data.type === "lead.followup_due"
          ? `Time to follow up${data.lead_number ? ` on ${data.lead_number}` : ""}`
          : data.type === "lead.assigned"
            ? "A lead was given to you"
            : null;
      if (!text) return;
      const key = `${data.type}-${data.lead_id}-${Date.now()}`;
      setNotices((list) => [...list.slice(-2), { key, text, href: `/leads/${data.lead_id}` }]);
      setTimeout(() => setNotices((list) => list.filter((n) => n.key !== key)), 10_000);
    };
    for (const type of ["lead.created", "lead.updated", "lead.assigned", "lead.followup_due"]) source.addEventListener(type, handle);
    return () => source.close();
  }, [enabled, userId, queryClient]);
  return [notices, (key) => setNotices((list) => list.filter((n) => n.key !== key))];
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
  const canReadLeads = (me.data?.permissions.includes("lead.read") ?? false) && !me.data?.must_change_password;
  const followups = useFollowupCount(canReadLeads);
  const [notices, dismiss] = useLeadEvents(canReadLeads, me.data?.user_id);
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
    badge: item.href === "/inbox" ? waiting : item.href === "/leads" ? followups : undefined,
  }));

  const { tabs, more } = splitPhoneNav(nav);
  const phoneNav = more.length ? [...tabs, MORE] : tabs;

  async function logout() {
    await api("tenant", "POST", "/api/v1/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col overflow-hidden bg-nav text-nav-ink md:flex">
        <div className="px-4 pt-5 pb-6">
          <p className="flex items-center gap-2 text-sm font-semibold text-nav-ink-muted">
            <BrandMark className="size-7 ring-1 ring-nav-line" />
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
        <div className="mt-auto border-t border-nav-line px-4 py-4">
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

      {notices.length > 0 && (
        <div className="fixed right-4 bottom-20 z-40 flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2 md:bottom-4" aria-live="polite">
          {notices.map((n) => (
            <div key={n.key} className="flex items-center gap-3 rounded-panel border border-line bg-surface p-3 shadow-lg">
              <BellRing className="size-5 shrink-0 text-primary" aria-hidden />
              <Link href={n.href} onClick={() => dismiss(n.key)} className="min-w-0 flex-1 font-medium text-ink hover:text-primary">
                {n.text}
              </Link>
              <button type="button" onClick={() => dismiss(n.key)} className="grid size-8 place-items-center rounded-control text-ink-muted hover:bg-sunken" aria-label="Dismiss">
                <X className="size-4" aria-hidden />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Phone navigation: most staff use the app on a phone. */}
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-20 grid border-t border-line bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
        style={{ gridTemplateColumns: `repeat(${phoneNav.length}, minmax(0, 1fr))` }}
      >
        <Suspense fallback={phoneNav.map((item) => <NavLink key={item.href} item={item} variant="bottom" active={false} />)}>
          <NavLinks items={phoneNav} variant="bottom" />
        </Suspense>
      </nav>
    </div>
  );
}
