"use client";

import { useQuery } from "@tanstack/react-query";
import { Check } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { useMe } from "@/components/tenant-shell";
import { Alert, SubscriptionPill, cx } from "@/components/ui";
import { api, type Me } from "@/lib/api";
import type { ChannelsResponse } from "@/lib/channels";
import { adDay, bothDates, bsDate } from "@/lib/dates";
import type { ConversationPage } from "@/lib/inbox";
import type { Dashboard, Period } from "@/lib/reports";
import { formatMoney } from "@/lib/sales";

import { BusinessReport, PeriodPicker, SalesHero } from "./business-report";

function SubscriptionNotice({ subscription }: { subscription: Me["subscription"] }) {
  const { status, days_remaining, expiry_date } = subscription;
  const date = expiry_date ? bothDates(expiry_date) : "";
  if (status === "GRACE") {
    return (
      <Alert tone="warning" title="Your subscription has ended">
        It ended on {date}. Everything still works for a few more days — renew now to avoid interruption.
      </Alert>
    );
  }
  if (status === "EXPIRED") {
    return (
      <Alert tone="error" title="Your subscription has expired">
        You can still see your customers and messages, but you can&apos;t reply or make changes until it&apos;s renewed.
      </Alert>
    );
  }
  if (days_remaining !== null && days_remaining <= 15) {
    return (
      <Alert tone="info" title={`Renews in ${days_remaining} days`}>
        Your subscription runs until {date}. Contact us to renew.
      </Alert>
    );
  }
  return null;
}

// The setup order from ONBOARDING_AND_CHANNEL_SETUP.md §5. Steps light up as each module ships.
const STEPS = [
  { key: "password", title: "Set your password", body: "Done when you first logged in." },
  { key: "business", title: "Check your business details", body: "Name, PAN/VAT and address used on invoices." },
  { key: "facebook", title: "Connect your Facebook Page", body: "About 5 minutes. Page messages arrive in your inbox." },
  { key: "whatsapp", title: "Connect WhatsApp", body: "About 10 minutes. Use a new number or keep your WhatsApp Business app." },
  { key: "test", title: "Send yourself a test message", body: "Message your Page or number and watch it arrive here." },
  { key: "products", title: "Add your products", body: "So orders can be created straight from a chat." },
  { key: "staff", title: "Add your staff", body: "Give each person their own login and role." },
] as const;

const CONNECT_LINKS: Record<string, { href: string; label: string }> = {
  facebook: { href: "/channels/connect/messenger", label: "Connect Facebook Page" },
  whatsapp: { href: "/channels/connect/whatsapp", label: "Connect WhatsApp" },
  products: { href: "/products", label: "Add products" },
};

function SetupSteps({ done }: { done: Set<string> }) {
  const next = STEPS.find((s) => !done.has(s.key))?.key;
  const progress = Math.round((done.size / STEPS.length) * 100);
  return (
    <section className="rounded-panel border border-line bg-surface">
      <header className="border-b border-line px-5 py-4">
        <h2 className="text-lg font-semibold text-ink">Set up your business</h2>
        <div className="mt-3 flex items-center gap-3">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-sunken" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Setup progress">
            <div className="h-full rounded-full bg-primary" style={{ width: `${progress}%` }} />
          </div>
          <span className="tabular text-sm text-ink-muted">
            {done.size} of {STEPS.length}
          </span>
        </div>
      </header>
      <ol>
        {STEPS.map((step, index) => {
          const complete = done.has(step.key);
          const isNext = step.key === next;
          return (
            <li key={step.key} className={cx("flex gap-4 border-b border-line px-5 py-4 last:border-b-0", isNext && "bg-primary-soft/60")}>
              <span
                className={cx(
                  "tabular grid size-8 shrink-0 place-items-center rounded-full text-sm font-semibold",
                  complete ? "bg-success text-white" : isNext ? "bg-primary text-on-primary" : "border border-line-strong text-ink-subtle",
                )}
                aria-hidden
              >
                {complete ? <Check className="size-4" /> : index + 1}
              </span>
              <div className="min-w-0 flex-1">
                <p className={cx("font-medium", complete ? "text-ink-muted line-through decoration-ink-subtle" : "text-ink")}>
                  {step.title}
                  <span className="sr-only">{complete ? " (done)" : isNext ? " (next step)" : ""}</span>
                </p>
                <p className="text-sm text-ink-muted">{step.body}</p>
                {isNext && !complete && step.key in CONNECT_LINKS && (
                  <Link
                    href={CONNECT_LINKS[step.key].href}
                    className="mt-2 inline-flex min-h-9 items-center rounded-control bg-primary px-3 text-sm font-medium text-on-primary hover:bg-primary-hover"
                  >
                    {CONNECT_LINKS[step.key].label}
                  </Link>
                )}
                {isNext && !complete && !(step.key in CONNECT_LINKS) && step.key !== "test" && (
                  <p className="mt-1 text-xs font-medium text-primary">Available soon</p>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function OwnerSetup() {
  const channels = useQuery({
    queryKey: ["channels"],
    queryFn: () => api<ChannelsResponse>("tenant", "GET", "/api/v1/channels"),
  });
  const done = new Set<string>(["password"]);
  const connected = channels.data?.items.filter((c) => c.status === "connected") ?? [];
  if (connected.some((c) => c.provider === "messenger")) done.add("facebook");
  if (connected.some((c) => c.provider === "whatsapp")) done.add("whatsapp");
  if (connected.some((c) => c.last_webhook_at)) done.add("test");
  const products = useQuery({
    queryKey: ["products", "any"],
    queryFn: () => api<{ items: unknown[] }>("tenant", "GET", "/api/v1/products?limit=1"),
  });
  if ((products.data?.items.length ?? 0) > 0) done.add("products");
  return <SetupSteps done={done} />;
}

type NeedRow = { key: string; count: number; hot: boolean; title: string; detail: string; href: string; action: string };

function waitedFor(iso: string | null): string {
  if (!iso) return "";
  const minutes = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 60) return `${minutes} ${minutes === 1 ? "minute" : "minutes"}`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? "hour" : "hours"}`;
  const days = Math.round(hours / 24);
  return `${days} ${days === 1 ? "day" : "days"}`;
}

/**
 * Everything that needs someone now, in one list: customers waiting, follow-ups due,
 * deliveries going out and money overdue. Collapses to one line when nothing is due.
 */
function NeedsNow({ me, report }: { me: Me; report: Dashboard | undefined }) {
  const can = (p: string) => me.permissions.includes(p);
  const rider = me.roles.includes("DELIVERY");
  const waiting = useQuery({
    queryKey: ["conversations", "unread-count"],
    queryFn: () => api<ConversationPage>("tenant", "GET", "/api/v1/conversations?view=unread&limit=100"),
    enabled: can("conversation.read"),
  });
  const followups = useQuery({
    queryKey: ["lead-followups"],
    queryFn: () => api<{ overdue: number; today: number }>("tenant", "GET", "/api/v1/leads/followups/count"),
    enabled: can("lead.read"),
  });
  const deliveryView = rider ? "mine" : "today";
  const deliveries = useQuery({
    queryKey: ["deliveries", deliveryView, "count"],
    queryFn: () => api<{ items: unknown[] }>("tenant", "GET", `/api/v1/deliveries?view=${deliveryView}&limit=100`),
    enabled: can("delivery.read"),
  });

  const loading = [waiting, followups, deliveries].some((q) => q.isPending && q.fetchStatus !== "idle");
  const rows: NeedRow[] = [];
  const chats = waiting.data?.items ?? [];
  if (chats.length) {
    const oldest = [...chats].sort((a, b) => (a.last_message_at ?? "").localeCompare(b.last_message_at ?? ""))[0];
    rows.push({
      key: "waiting",
      count: chats.length,
      hot: true,
      title: chats.length === 1 ? "Customer waiting for a reply" : "Customers waiting for a reply",
      detail: `${oldest.customer.display_name} has waited ${waitedFor(oldest.last_message_at)}`,
      href: "/inbox",
      action: "Open inbox",
    });
  }
  const due = (followups.data?.overdue ?? 0) + (followups.data?.today ?? 0);
  if (due) {
    const overdue = followups.data?.overdue ?? 0;
    rows.push({
      key: "followups",
      count: due,
      hot: overdue > 0,
      title: due === 1 ? "Follow-up due" : "Follow-ups due",
      detail: overdue ? `${overdue} overdue, the rest today` : "Due today",
      href: "/leads?tab=followups",
      action: "See leads",
    });
  }
  const trips = deliveries.data?.items.length ?? 0;
  if (trips) {
    rows.push({
      key: "deliveries",
      count: trips,
      hot: false,
      title: rider ? (trips === 1 ? "Delivery assigned to you" : "Deliveries assigned to you") : trips === 1 ? "Delivery to send out" : "Deliveries to send out",
      detail: rider ? "Open to see addresses and cash to collect" : "Due today or not yet scheduled",
      href: "/deliveries",
      action: rider ? "Start" : "See deliveries",
    });
  }
  if (report && report.snapshot.overdue_invoices > 0) {
    const n = report.snapshot.overdue_invoices;
    rows.push({
      key: "overdue",
      count: n,
      hot: true,
      title: n === 1 ? "Invoice overdue for payment" : "Invoices overdue for payment",
      detail: `${formatMoney(report.snapshot.overdue, report.currency)} past the due date`,
      href: "/orders",
      action: "See orders",
    });
  }

  if (loading) return <div className="h-48 animate-pulse rounded-panel bg-nav/80" aria-hidden />;

  if (!rows.length) {
    return (
      <section className="flex items-center gap-4 rounded-panel bg-nav px-5 py-4 text-nav-ink">
        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-nav-active">
          <Check className="size-5" aria-hidden />
        </span>
        <div>
          <h2 className="font-semibold">You&apos;re all caught up</h2>
          <p className="text-sm text-nav-ink-muted">No one is waiting, and nothing is due today.</p>
        </div>
      </section>
    );
  }

  return (
    <section className="rounded-panel bg-nav px-5 pt-4 pb-1 text-nav-ink" aria-labelledby="needs-now">
      <header className="mb-1 flex items-baseline justify-between gap-3">
        <h2 id="needs-now" className="font-semibold">Needs you now</h2>
        <span className="text-xs text-nav-ink-muted">Updates on its own</span>
      </header>
      <ul>
        {rows.map((r) => (
          <li key={r.key} className="border-t border-nav-line">
            <Link href={r.href} className="group grid grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-3 py-3">
              <span className={cx("figure text-right text-[1.9rem]", r.hot ? "text-attention" : "text-nav-ink")}>{r.count}</span>
              <span className="min-w-0">
                <span className="block font-semibold">{r.title}</span>
                <span className="block truncate text-sm text-nav-ink-muted">{r.detail}</span>
              </span>
              <span className="hidden rounded-control border border-nav-line px-3 py-1.5 text-sm font-medium whitespace-nowrap group-hover:bg-nav-hover sm:inline-block">
                {r.action}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function Dashboard() {
  const me = useMe(); // session checks and redirects live in TenantShell
  const [period, setPeriod] = useState<Period>("7d");
  const canReadReports = me.data?.permissions.includes("report.read") ?? false;
  const report = useQuery({
    queryKey: ["reports", "dashboard", period],
    queryFn: () => api<Dashboard>("tenant", "GET", `/api/v1/reports/dashboard?period=${period}`),
    placeholderData: (previous) => previous,
    enabled: canReadReports,
  });
  if (!me.data) return null;
  const isOwner = me.data.roles.some((r) => r === "OWNER" || r === "ADMIN");
  const firstName = me.data.full_name.split(" ")[0];
  const today = new Date();

  return (
    <div className={cx("mx-auto grid w-full min-w-0 gap-6 [&>*]:min-w-0", canReadReports ? "max-w-6xl" : "max-w-3xl")}>
      <header className="flex min-w-0 flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold text-ink sm:text-[2rem]">Namaste, {firstName}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-ink-muted">
            <span>
              {today.toLocaleDateString("en-GB", { weekday: "long" })}, {bsDate(today)}{" "}
              <span className="text-ink-subtle">({adDay(today)})</span>
            </span>
            {me.data.subscription.status !== "ACTIVE" && <SubscriptionPill status={me.data.subscription.status} />}
          </p>
        </div>
        {canReadReports && <PeriodPicker period={period} onChange={setPeriod} />}
      </header>
      <SubscriptionNotice subscription={me.data.subscription} />
      <div className={cx("grid min-w-0 items-start gap-6", canReadReports && "lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]")}>
        <NeedsNow me={me.data} report={report.data} />
        {canReadReports && <SalesHero report={report} period={period} />}
      </div>
      {canReadReports && <BusinessReport report={report} period={period} />}
      {isOwner && <OwnerSetup />}
    </div>
  );
}
