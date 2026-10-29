"use client";

import { useQuery } from "@tanstack/react-query";
import { Check, MessagesSquare, Truck } from "lucide-react";
import Link from "next/link";

import { useMe } from "@/components/tenant-shell";
import { Alert, PageHeader, SubscriptionPill, cx } from "@/components/ui";
import { api, type Me } from "@/lib/api";
import type { ChannelsResponse } from "@/lib/channels";
import type { ConversationPage } from "@/lib/inbox";

import { BusinessReport } from "./business-report";

function SubscriptionNotice({ subscription }: { subscription: Me["subscription"] }) {
  const { status, days_remaining, expiry_date } = subscription;
  const date = expiry_date ? new Date(expiry_date).toLocaleDateString(undefined, { dateStyle: "medium" }) : "";
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

function WaitingSummary() {
  const waiting = useQuery({
    queryKey: ["conversations", "unread-count"],
    queryFn: () => api<ConversationPage>("tenant", "GET", "/api/v1/conversations?view=unread&limit=100"),
  });
  if (waiting.isPending) {
    return <div className="h-[82px] animate-pulse rounded-panel border border-line bg-surface" aria-hidden />;
  }
  const count = waiting.data?.items.length ?? 0;
  return (
    <Link
      href="/inbox"
      className={cx(
        "flex items-center gap-4 rounded-panel border px-5 py-4 transition-colors",
        count ? "border-attention/50 bg-attention-soft hover:border-attention" : "border-line bg-surface hover:border-line-strong",
      )}
    >
      <span className={cx("grid size-11 place-items-center rounded-full", count ? "bg-attention text-on-attention" : "bg-primary-soft text-primary")}>
        <MessagesSquare className="size-5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-lg font-semibold text-ink">
          {count === 0 ? "No one is waiting" : count === 1 ? "1 customer is waiting for a reply" : `${count} customers are waiting for a reply`}
        </span>
        <span className="block text-sm text-ink-muted">{count ? "Open the inbox to reply" : "New messages will show up in your inbox"}</span>
      </span>
    </Link>
  );
}

function DeliveriesSummary({ mine }: { mine: boolean }) {
  const view = mine ? "mine" : "today";
  const due = useQuery({
    queryKey: ["deliveries", view, "count"],
    queryFn: () => api<{ items: unknown[] }>("tenant", "GET", `/api/v1/deliveries?view=${view}&limit=100`),
  });
  const count = due.data?.items.length ?? 0;
  return (
    <Link href="/deliveries" className="flex items-center gap-4 rounded-panel border border-line bg-surface px-5 py-4 transition-colors hover:border-line-strong">
      <span className="grid size-11 place-items-center rounded-full bg-primary-soft text-primary">
        <Truck className="size-5" aria-hidden />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-lg font-semibold text-ink">
          {count === 0 ? "No deliveries due" : count === 1 ? "1 delivery to make" : `${count} deliveries to make`}
        </span>
        <span className="block text-sm text-ink-muted">{mine ? "Assigned to you" : "Due today or not yet scheduled"}</span>
      </span>
    </Link>
  );
}

export function Dashboard() {
  const me = useMe(); // session checks and redirects live in TenantShell
  if (!me.data) return null;
  const canReadInbox = me.data.permissions.includes("conversation.read");
  const canReadReports = me.data.permissions.includes("report.read");
  const isOwner = me.data.roles.some((r) => r === "OWNER" || r === "ADMIN");
  const firstName = me.data.full_name.split(" ")[0];

  return (
    <div className={cx("mx-auto w-full", canReadReports ? "max-w-6xl" : "max-w-3xl")}>
      <PageHeader
        title={`Namaste, ${firstName}`}
        description={
          <span className="inline-flex flex-wrap items-center gap-2">
            {me.data.business_name}
            <SubscriptionPill status={me.data.subscription.status} />
          </span>
        }
      />
      <SubscriptionNotice subscription={me.data.subscription} />
      <div className="grid gap-6">
        <div className={cx("grid gap-6", canReadReports && "lg:grid-cols-2")}>
          {canReadInbox && <WaitingSummary />}
          {me.data.permissions.includes("delivery.read") && <DeliveriesSummary mine={me.data.roles.includes("DELIVERY")} />}
        </div>
        {canReadReports && <BusinessReport />}
        {isOwner && <OwnerSetup />}
      </div>
    </div>
  );
}
