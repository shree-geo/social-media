"use client";

import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Columns3, List, Plus, Search, Target } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useDeferredValue, useState, type DragEvent } from "react";

import { LostDialog, leadErrorText, useLeadRefresh } from "@/components/lead-actions";
import { LeadSheet } from "@/components/lead-sheet";
import { useMe } from "@/components/tenant-shell";
import { Alert, Avatar, Button, EmptyState, PageHeader, Pill, cx } from "@/components/ui";
import { api } from "@/lib/api";
import {
  ALL_STAGES,
  OPEN_STAGES,
  STAGE_HINT,
  STAGE_LABEL,
  STAGE_TONE,
  followupText,
  type LeadPage,
  type LeadStage,
  type LeadSummary,
  useHydrated,
} from "@/lib/leads";
import { SOURCE_LABEL, formatMoney } from "@/lib/sales";

type Tab = "followups" | "list" | "board";
type Who = "mine" | "all" | "unassigned";

const WHO: { key: Who; label: string }[] = [
  { key: "mine", label: "Mine" },
  { key: "all", label: "Everyone" },
  { key: "unassigned", label: "No owner" },
];

const STAGE_FILTERS = [
  { key: "open", label: "Open" },
  ...ALL_STAGES.map((s) => ({ key: s, label: STAGE_LABEL[s] })),
  { key: "", label: "All" },
];

export function FollowupBadge({ at }: { at: string | null }) {
  const due = followupText(at);
  if (!due) return null;
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 text-xs",
        due.overdue ? "font-semibold text-danger" : due.today ? "font-medium text-attention-ink" : "text-ink-muted",
      )}
    >
      <CalendarClock className="size-3.5" aria-hidden />
      {due.overdue ? `Overdue · ${due.text}` : due.text}
    </span>
  );
}

function LeadRow({ lead }: { lead: LeadSummary }) {
  return (
    <li>
      <Link href={`/leads/${lead.id}`} className="flex gap-3 px-4 py-3.5 hover:bg-sunken/70">
        <Avatar name={lead.customer.display_name} channel={lead.conversation_id ? lead.source_channel : undefined} />
        <span className="min-w-0 flex-1">
          <span className="flex items-baseline justify-between gap-2">
            <span className="truncate font-medium text-ink">{lead.customer.display_name}</span>
            <Pill tone={STAGE_TONE[lead.stage]}>{STAGE_LABEL[lead.stage]}</Pill>
          </span>
          <span className="mt-0.5 block truncate text-sm text-ink-muted">{lead.item_summary}</span>
          <span className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-subtle">
            <span className="tabular">{lead.lead_number}</span>
            {Number(lead.expected_value) > 0 && <span className="tabular text-ink-muted">{formatMoney(lead.expected_value, lead.currency)}</span>}
            <span>{lead.assigned_to?.full_name ?? "No owner"}</span>
            <FollowupBadge at={lead.next_followup_at} />
          </span>
        </span>
      </Link>
    </li>
  );
}

function ListView({ who, stage, channel, search, due }: { who: Who; stage: string; channel: string; search: string; due: boolean }) {
  const leads = useInfiniteQuery({
    queryKey: ["leads", "list", who, stage, channel, search, due],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ view: who, limit: "30" });
      if (due) params.set("due", "due");
      else if (stage) params.set("stage", stage);
      if (channel) params.set("channel", channel);
      if (search) params.set("q", search);
      if (pageParam) params.set("cursor", pageParam);
      return api<LeadPage>("tenant", "GET", `/api/v1/leads?${params}`);
    },
    initialPageParam: "",
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = leads.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="overflow-hidden rounded-panel border border-line bg-surface">
      <ul className="divide-y divide-line">
        {leads.isPending &&
          Array.from({ length: 4 }, (_, i) => (
            <li key={i} className="flex gap-3 px-4 py-3.5" aria-hidden>
              <span className="size-10 animate-pulse rounded-full bg-sunken" />
              <span className="flex-1 space-y-2 py-1">
                <span className="block h-3.5 w-1/2 animate-pulse rounded bg-sunken" />
                <span className="block h-3 w-4/5 animate-pulse rounded bg-sunken" />
              </span>
            </li>
          ))}
        {!leads.isPending && items.length === 0 && (
          <li>
            {due ? (
              <EmptyState icon={CalendarClock} title="No follow-ups due">
                Nothing overdue or due today. Nice work.
              </EmptyState>
            ) : (
              <EmptyState icon={Target} title="No leads here">
                Turn a chat into a lead with <strong>Create lead</strong>, or add one for a phone call or walk-in.
              </EmptyState>
            )}
          </li>
        )}
        {items.map((lead) => (
          <LeadRow key={lead.id} lead={lead} />
        ))}
      </ul>
      {leads.hasNextPage && (
        <button onClick={() => leads.fetchNextPage()} className="w-full border-t border-line py-2.5 text-sm font-medium text-primary hover:bg-primary-soft">
          Show more
        </button>
      )}
    </div>
  );
}

/* Board (desktop): drag a card to another stage. Dropping on Lost asks why; on Won opens the order form. */

type BoardData = { columns: Record<string, LeadSummary[]> };

function BoardView({ who, canWrite }: { who: Who; canWrite: boolean }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const refresh = useLeadRefresh();
  const key = ["leads", "board", who === "mine" ? "mine" : "all"];
  const board = useQuery({
    queryKey: key,
    queryFn: () => api<BoardData>("tenant", "GET", `/api/v1/leads/board?view=${who === "mine" ? "mine" : "all"}`),
  });
  const [dragging, setDragging] = useState<LeadSummary | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const [losing, setLosing] = useState<LeadSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function move(lead: LeadSummary, to: LeadStage) {
    setError(null);
    if (to === lead.stage) return;
    if (to === "WON") return router.push(`/orders/new?lead=${lead.id}`);
    if (to === "LOST") return setLosing(lead);
    if (lead.stage === "WON") return setError("A won lead already became an order.");
    // Move it on screen right away; put it back if the server says no.
    const previous = queryClient.getQueryData<BoardData>(key);
    if (previous) {
      const columns = Object.fromEntries(Object.entries(previous.columns).map(([s, list]) => [s, list.filter((l) => l.id !== lead.id)]));
      columns[to] = [{ ...lead, stage: to }, ...(columns[to] ?? [])];
      queryClient.setQueryData<BoardData>(key, { columns });
    }
    try {
      await api("tenant", "POST", `/api/v1/leads/${lead.id}/stage`, { stage: to, version: lead.version });
    } catch (err) {
      if (previous) queryClient.setQueryData(key, previous);
      setError(leadErrorText(err));
    } finally {
      refresh(lead);
    }
  }

  const columns = board.data?.columns ?? {};
  const visible = who === "unassigned" ? (l: LeadSummary) => !l.assigned_to : () => true;

  return (
    <>
      {error && <Alert tone="error">{error}</Alert>}
      <div className="grid auto-cols-[minmax(15rem,1fr)] grid-flow-col gap-3 overflow-x-auto pb-4">
        {ALL_STAGES.map((stage) => {
          const cards = (columns[stage] ?? []).filter(visible);
          const total = cards.reduce((sum, l) => sum + Number(l.expected_value), 0);
          const droppable = canWrite && dragging !== null && dragging.stage !== stage && dragging.stage !== "WON";
          return (
            <section
              key={stage}
              aria-label={STAGE_LABEL[stage]}
              onDragOver={(e: DragEvent) => {
                if (droppable) {
                  e.preventDefault();
                  setOver(stage);
                }
              }}
              onDragLeave={() => setOver((o) => (o === stage ? null : o))}
              onDrop={(e: DragEvent) => {
                e.preventDefault();
                setOver(null);
                if (dragging && droppable) void move(dragging, stage);
                setDragging(null);
              }}
              className={cx(
                "flex min-h-64 flex-col rounded-panel border bg-sunken/50 transition-colors",
                over === stage ? "border-primary bg-primary-soft/60" : "border-line",
              )}
            >
              <header className="border-b border-line px-3 py-2.5">
                <p className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-ink">{STAGE_LABEL[stage]}</span>
                  <span className="tabular text-sm text-ink-muted">{cards.length}</span>
                </p>
                <p className="text-xs text-ink-subtle">
                  {stage === "WON" || stage === "LOST" ? "Last 30 days" : STAGE_HINT[stage]}
                  {total > 0 && <span className="tabular"> · {formatMoney(total, "NPR")}</span>}
                </p>
              </header>
              <ul className="flex flex-1 flex-col gap-2 p-2">
                {cards.map((lead) => (
                  <li
                    key={lead.id}
                    draggable={canWrite && lead.stage !== "WON"}
                    onDragStart={(e) => {
                      e.dataTransfer.effectAllowed = "move";
                      e.dataTransfer.setData("text/plain", lead.id);
                      setDragging(lead);
                    }}
                    onDragEnd={() => {
                      setDragging(null);
                      setOver(null);
                    }}
                    className={cx(
                      "rounded-control border border-line bg-surface p-3 shadow-sm",
                      canWrite && lead.stage !== "WON" && "cursor-grab active:cursor-grabbing",
                      dragging?.id === lead.id && "opacity-50",
                    )}
                  >
                    <Link href={`/leads/${lead.id}`} className="block font-medium text-ink hover:text-primary" draggable={false}>
                      {lead.customer.display_name}
                    </Link>
                    <p className="mt-0.5 line-clamp-2 text-sm text-ink-muted">{lead.item_summary}</p>
                    <div className="mt-2 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
                      {Number(lead.expected_value) > 0 && (
                        <span className="tabular text-sm font-medium text-ink">{formatMoney(lead.expected_value, lead.currency)}</span>
                      )}
                      <FollowupBadge at={lead.next_followup_at} />
                    </div>
                    <p className="mt-1.5 flex items-center justify-between gap-2 text-xs text-ink-subtle">
                      <span className="truncate">{lead.assigned_to?.full_name ?? "No owner"}</span>
                      {canWrite && lead.stage !== "WON" && (
                        <select
                          className="rounded border border-line bg-surface px-1 py-0.5 text-xs text-ink-muted"
                          value={lead.stage}
                          aria-label={`Move ${lead.lead_number}`}
                          onChange={(e) => void move(lead, e.target.value as LeadStage)}
                        >
                          {[...OPEN_STAGES, "WON", "LOST"].map((s) => (
                            <option key={s} value={s}>
                              {s === "WON" ? "Won (make order)…" : s === "LOST" ? "Lost…" : STAGE_LABEL[s]}
                            </option>
                          ))}
                        </select>
                      )}
                    </p>
                  </li>
                ))}
                {cards.length === 0 && <li className="px-1 py-6 text-center text-sm text-ink-subtle">{board.isPending ? "Loading…" : "Nothing here"}</li>}
              </ul>
            </section>
          );
        })}
      </div>
      {losing && <LostDialog lead={losing} onClose={() => setLosing(null)} />}
    </>
  );
}

export function LeadsView() {
  const me = useMe();
  const router = useRouter();
  const params = useSearchParams();
  const hydrated = useHydrated();
  const canWrite = hydrated && (me.data?.permissions.includes("lead.write") ?? false);
  const isSales = hydrated && (me.data?.roles.includes("SALES") ?? false);
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) ?? "list");
  const [who, setWho] = useState<Who | null>(null);
  const [stage, setStage] = useState("open");
  const [channel, setChannel] = useState("");
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const search = useDeferredValue(q.trim());
  // Sales staff start with their own leads; owners and managers with everyone's.
  const whoNow: Who = who ?? (isSales ? "mine" : "all");

  const tabs: { key: Tab; label: string; icon: typeof List; desktopOnly?: boolean }[] = [
    { key: "followups", label: "Follow up", icon: CalendarClock },
    { key: "list", label: "List", icon: List },
    { key: "board", label: "Board", icon: Columns3, desktopOnly: true },
  ];

  return (
    <main className={cx("mx-auto w-full px-4 py-6 sm:px-8 sm:py-8", tab === "board" ? "max-w-[96rem]" : "max-w-4xl")}>
      <PageHeader
        title="Leads"
        description="People who are interested in buying. Follow up until they order, or note why they didn't."
        actions={
          canWrite && (
            <Button icon={Plus} onClick={() => setCreating(true)}>
              New lead
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="grid grid-flow-col rounded-control bg-sunken p-1" role="tablist" aria-label="Show as">
          {tabs.map((t) => (
            <button
              key={t.key}
              role="tab"
              aria-selected={tab === t.key}
              onClick={() => setTab(t.key)}
              className={cx(
                "items-center gap-1.5 rounded-[6px] px-3 py-1.5 text-sm font-medium transition-colors",
                t.desktopOnly ? "hidden md:inline-flex" : "inline-flex",
                tab === t.key ? "bg-surface text-ink shadow-sm" : "text-ink-muted hover:text-ink",
              )}
            >
              <t.icon className="size-4" aria-hidden />
              {t.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1.5" aria-label="Whose leads">
          {WHO.map((w) => (
            <button
              key={w.key}
              onClick={() => setWho(w.key)}
              aria-pressed={whoNow === w.key}
              className={cx(
                "rounded-full border px-3 py-1 text-sm transition-colors",
                whoNow === w.key ? "border-primary bg-primary-soft text-primary" : "border-line text-ink-muted hover:border-line-strong",
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "list" && (
        <div className="mb-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-subtle" aria-hidden />
            <input
              className="w-full rounded-control border border-line-strong bg-surface py-2 pr-3 pl-9 text-ink focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
              placeholder="Search name or lead number"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              aria-label="Search leads"
            />
          </div>
          <select className="rounded-control border border-line-strong bg-surface px-3 py-2 text-ink" value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Stage">
            {STAGE_FILTERS.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          <select className="rounded-control border border-line-strong bg-surface px-3 py-2 text-ink" value={channel} onChange={(e) => setChannel(e.target.value)} aria-label="Channel">
            <option value="">All channels</option>
            {Object.entries(SOURCE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </div>
      )}

      {tab === "followups" && <ListView who={whoNow} stage="" channel="" search="" due />}
      {tab === "list" && <ListView who={whoNow} stage={stage} channel={channel} search={search} due={false} />}
      {tab === "board" && <BoardView who={whoNow} canWrite={canWrite} />}

      {creating && <LeadSheet onClose={() => setCreating(false)} onCreated={(lead) => router.push(`/leads/${lead.id}`)} />}
    </main>
  );
}
