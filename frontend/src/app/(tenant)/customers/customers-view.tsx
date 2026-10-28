"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Users } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { useMe } from "@/components/tenant-shell";
import { Alert, Avatar, Button, ChannelTag, EmptyState, PageHeader } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { formatPhone, formatTime, type CustomerListItem } from "@/lib/inbox";

type Duplicate = {
  id: string;
  score: string;
  reasons: string[];
  customer_a: CustomerListItem;
  customer_b: CustomerListItem;
};

const REASON: Record<string, string> = {
  same_phone: "They have the same phone number.",
  same_email: "They have the same email address.",
  phone_in_message: "One of them typed the other's phone number in a chat.",
};

function DuplicateCard({ d, onMerge, onDismiss, busy }: {
  d: Duplicate;
  onMerge: (source: string, target: string) => void;
  onDismiss: () => void;
  busy: boolean;
}) {
  const person = (c: CustomerListItem) => (
    <div className="flex min-w-0 items-center gap-3">
      <Avatar name={c.display_name} channel={c.channels[0]} size="sm" />
      <div className="min-w-0">
        <p className="truncate font-medium text-ink">{c.display_name}</p>
        <p className="truncate text-sm text-ink-muted">{formatPhone(c.phone_e164) || c.email || "No contact details"}</p>
      </div>
    </div>
  );
  return (
    <li className="rounded-panel border border-line bg-surface p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        {person(d.customer_a)}
        {person(d.customer_b)}
      </div>
      <p className="mt-3 text-sm text-ink-muted">{d.reasons.map((r) => REASON[r] ?? r).join(" ")}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => onMerge(d.customer_b.id, d.customer_a.id)}>
          Keep {d.customer_a.display_name}
        </Button>
        <Button size="sm" variant="secondary" disabled={busy} onClick={() => onMerge(d.customer_a.id, d.customer_b.id)}>
          Keep {d.customer_b.display_name}
        </Button>
        <Button size="sm" variant="ghost" disabled={busy} onClick={onDismiss}>
          They&apos;re different people
        </Button>
      </div>
    </li>
  );
}

function Duplicates() {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const duplicates = useQuery({
    queryKey: ["duplicates"],
    queryFn: () => api<Duplicate[]>("tenant", "GET", "/api/v1/customers/duplicates"),
  });
  const refresh = () => {
    setError(null);
    queryClient.invalidateQueries({ queryKey: ["duplicates"] });
    queryClient.invalidateQueries({ queryKey: ["customers"] });
  };
  const merge = useMutation({
    mutationFn: (v: { source: string; target: string }) =>
      api("tenant", "POST", "/api/v1/customers/merge", { source_customer_id: v.source, target_customer_id: v.target }),
    onSuccess: refresh,
    onError: (e) => setError(e instanceof ApiError ? e.message : "Couldn't merge these customers."),
  });
  const dismiss = useMutation({
    mutationFn: (id: string) => api("tenant", "POST", `/api/v1/customers/duplicates/${id}/dismiss`),
    onSuccess: refresh,
  });

  if (!duplicates.data?.length) return null;
  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold text-ink">
        {duplicates.data.length === 1 ? "1 customer may be listed twice" : `${duplicates.data.length} customers may be listed twice`}
      </h2>
      <p className="mt-0.5 mb-3 text-sm text-ink-muted">
        Keeping one moves all chats, notes and addresses onto it. You can undo this later.
      </p>
      {error && <Alert tone="error">{error}</Alert>}
      <ul className="grid gap-3">
        {duplicates.data.map((d) => (
          <DuplicateCard
            key={d.id}
            d={d}
            busy={merge.isPending || dismiss.isPending}
            onMerge={(source, target) => merge.mutate({ source, target })}
            onDismiss={() => dismiss.mutate(d.id)}
          />
        ))}
      </ul>
    </section>
  );
}

export function CustomersView() {
  const me = useMe();
  const [q, setQ] = useState("");
  const search = useDeferredValue(q.trim());
  const customers = useQuery({
    queryKey: ["customers", search],
    queryFn: () =>
      api<{ items: CustomerListItem[] }>("tenant", "GET", `/api/v1/customers?limit=50&q=${encodeURIComponent(search)}`),
  });
  const canMerge = me.data?.permissions.includes("customer.merge") ?? false;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader title="Customers" description="Everyone who has messaged you, on any channel." />
      {canMerge && <Duplicates />}
      <div className="relative mb-4">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-5 -translate-y-1/2 text-ink-subtle" aria-hidden />
        <label htmlFor="search" className="sr-only">
          Search customers
        </label>
        <input
          id="search"
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search by name, phone or email"
          className="w-full rounded-control border border-line-strong bg-surface py-2.5 pr-3 pl-10 text-base text-ink placeholder:text-ink-subtle focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
        />
      </div>
      {customers.isPending ? null : customers.data?.items.length === 0 ? (
        <div className="rounded-panel border border-line bg-surface">
          <EmptyState icon={Users} title={search ? `No one matches "${search}"` : "No customers yet"}>
            {search ? "Try a phone number or part of the name." : "Customers are added automatically when they message you."}
          </EmptyState>
        </div>
      ) : (
        <ul className="overflow-hidden rounded-panel border border-line bg-surface">
          {customers.data?.items.map((c) => (
            <li key={c.id} className="border-b border-line last:border-b-0">
              <Link href={`/customers/${c.id}`} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-sunken/70">
                <Avatar name={c.display_name} channel={c.channels[0]} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-ink">{c.display_name}</span>
                  <span className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
                    {c.phone_e164 && <span className="tabular text-sm text-ink-muted">{formatPhone(c.phone_e164)}</span>}
                    {c.channels.map((ch) => (
                      <ChannelTag key={ch} channel={ch} />
                    ))}
                  </span>
                </span>
                <span className="tabular shrink-0 text-xs text-ink-subtle">{formatTime(c.last_interaction_at)}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
