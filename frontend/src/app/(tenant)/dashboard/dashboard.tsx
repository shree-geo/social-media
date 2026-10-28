"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Button, Card } from "@/components/ui";
import { ApiError, api, type Me } from "@/lib/api";

function SubscriptionBanner({ subscription }: { subscription: Me["subscription"] }) {
  const { status, days_remaining, expiry_date } = subscription;
  if (status === "GRACE") {
    return (
      <div role="status" className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm">
        Your subscription expired on {expiry_date}. Renew soon to keep making changes.
      </div>
    );
  }
  if (status === "EXPIRED") {
    return (
      <div role="status" className="mb-4 rounded-lg border border-red-600/40 bg-red-600/10 px-4 py-3 text-sm">
        Your subscription has expired. You can view your data, but changes are paused until it is renewed.
      </div>
    );
  }
  if (days_remaining !== null && days_remaining <= 15) {
    return (
      <div role="status" className="mb-4 rounded-lg border border-blue-600/30 bg-blue-600/10 px-4 py-3 text-sm">
        Your subscription renews on {expiry_date} ({days_remaining} days left).
      </div>
    );
  }
  return null;
}

// Setup checklist from ONBOARDING_AND_CHANNEL_SETUP.md §5. Items light up as each module ships.
const CHECKLIST = [
  { key: "password", label: "Set your password" },
  { key: "business", label: "Confirm business details" },
  { key: "facebook", label: "Connect your Facebook Page", note: "~5 min" },
  { key: "whatsapp", label: "Connect WhatsApp", note: "~10 min" },
  { key: "test", label: "Send a test message" },
  { key: "products", label: "Add your products" },
  { key: "staff", label: "Add your staff" },
] as const;

export function Dashboard() {
  const router = useRouter();
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<Me>("tenant", "GET", "/api/v1/auth/me") });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) router.replace("/login");
    if (me.data?.must_change_password) router.replace("/change-password");
  }, [me.error, me.data, router]);

  if (me.isPending) return <p className="text-muted">Loading…</p>;
  if (me.error || !me.data) return <p className="text-muted">Could not load your account.</p>;

  const done = new Set<string>(["password"]);
  async function logout() {
    await api("tenant", "POST", "/api/v1/auth/logout").catch(() => undefined);
    router.replace("/login");
  }

  return (
    <div className="mx-auto w-full max-w-2xl">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <p className="text-sm text-muted">{me.data.business_name}</p>
          <h1 className="text-2xl font-semibold">Hello, {me.data.full_name}</h1>
        </div>
        <Button variant="secondary" onClick={logout}>
          Log out
        </Button>
      </header>

      <SubscriptionBanner subscription={me.data.subscription} />

      <Card title={`Get started · ${done.size} of ${CHECKLIST.length} done`}>
        <ul className="divide-y divide-black/10 dark:divide-white/10">
          {CHECKLIST.map((item) => (
            <li key={item.key} className="flex items-center justify-between gap-3 py-3">
              <span className="flex items-center gap-3">
                <span aria-hidden className={done.has(item.key) ? "text-green-600" : "text-muted"}>
                  {done.has(item.key) ? "✓" : "○"}
                </span>
                <span className={done.has(item.key) ? "line-through text-muted" : ""}>{item.label}</span>
              </span>
              {!done.has(item.key) && <span className="text-sm text-muted">{"note" in item ? item.note : "Soon"}</span>}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
