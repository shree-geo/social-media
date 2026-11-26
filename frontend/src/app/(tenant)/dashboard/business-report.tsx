"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { ArrowDownRight, ArrowUpRight, Minus, Table2, BarChart3 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { cx } from "@/components/ui";
import { PERIODS, change, compactMoney, compactNumber, type Dashboard, type Period } from "@/lib/reports";
import { LOST_REASON_LABEL } from "@/lib/leads";
import { LEAD_LABEL, SOURCE_LABEL, STATUS_LABEL, formatMoney } from "@/lib/sales";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Wall-clock parts straight from the API's ISO string, so labels stay in the business's timezone
 * whatever timezone the browser is in. */
function bucketLabel(iso: string, bucket: Dashboard["window"]["bucket"], long = false): string {
  const [day, clock] = iso.split("T");
  const [, month, date] = day.split("-").map(Number);
  if (bucket === "hour") {
    const hour = Number(clock.slice(0, 2));
    const h = hour % 12 || 12;
    return `${h} ${hour < 12 ? "AM" : "PM"}${long ? `, ${date} ${MONTHS[month - 1]}` : ""}`;
  }
  const label = `${date} ${MONTHS[month - 1]}`;
  return bucket === "week" && long ? `Week of ${label}` : label;
}

function Panel({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("min-w-0 rounded-panel border border-line bg-surface p-5", className)}>
      <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-semibold text-ink">{title}</h2>
          {description && <p className="text-sm text-ink-muted">{description}</p>}
        </div>
        {action}
      </header>
      {children}
    </section>
  );
}

/* Stat tiles ------------------------------------------------------------------------------ */

function Delta({ current, previous, against }: { current: string | number; previous: string | number; against: string }) {
  const pct = change(current, previous);
  if (pct === null) return null; // one note under the strip explains missing comparisons
  const Icon = pct > 0 ? ArrowUpRight : pct < 0 ? ArrowDownRight : Minus;
  return (
    <p className="mt-1 flex items-center gap-1 text-xs text-ink-muted">
      <Icon className={cx("size-3.5", pct > 0 ? "text-success" : pct < 0 ? "text-danger" : "text-ink-subtle")} aria-hidden />
      <span>
        {pct > 0 ? "Up" : pct < 0 ? "Down" : "Same as"} {pct !== 0 && `${Math.abs(pct)}% on`} the {against}
      </span>
    </p>
  );
}

/** A figure in a strip: no box of its own; the strip draws the dividers. */
function Tile({
  label,
  value,
  children,
  href,
  tone = "ink",
}: {
  label: string;
  value: string;
  children?: ReactNode;
  href?: string;
  tone?: "ink" | "attention";
}) {
  const body = (
    <>
      <p className="text-sm text-ink-muted">{label}</p>
      <p className={cx("figure mt-1 text-[1.6rem]", tone === "attention" ? "text-attention-ink" : "text-ink")}>{value}</p>
      {children}
    </>
  );
  const className = "block min-w-0 px-4 py-3";
  return href ? (
    <Link href={href} className={cx(className, "transition-colors hover:bg-surface")}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

function Strip({ children, columns }: { children: ReactNode; columns: string }) {
  return (
    <div
      className={cx(
        "grid grid-cols-2 border-y border-line [&>*]:border-line max-sm:[&>*:nth-child(even)]:border-l max-sm:[&>*:nth-child(n+3)]:border-t sm:[&>*+*]:border-l",
        columns,
      )}
    >
      {children}
    </div>
  );
}

/* Sales chart ------------------------------------------------------------------------------ */

/** The window runs up to now (so the last bar is "today so far"). */
function isCurrent(data: Dashboard): boolean {
  return new Date(data.window.end).getTime() > Date.now() - 60_000;
}

function niceMax(max: number): number {
  if (max <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * magnitude >= max / 2) ?? 10;
  return Math.ceil(max / (step * magnitude)) * step * magnitude;
}

function SalesChart({ data, height = 220 }: { data: Dashboard; height?: number }) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0); // measured before drawing, so the chart never widens its panel
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const points = data.series.map((p) => ({ ...p, value: Number(p.sales) }));
  const top = niceMax(Math.max(...points.map((p) => p.value), 0));
  const pad = { top: 12, right: 8, bottom: 26, left: 56 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const band = plotW / points.length;
  const barW = Math.min(24, Math.max(2, band - 2)); // 2px surface gap between touching bars
  const every = Math.ceil(points.length / Math.max(2, Math.floor(plotW / 64)));
  const y = (v: number) => pad.top + plotH - (v / top) * plotH;
  const ticks = [0, top / 2, top];
  const active = hover === null ? null : points[hover];

  return (
    <div ref={box} className="relative w-full min-w-0" style={{ height }} onMouseLeave={() => setHover(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Sales over the period" className="block">
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)} className="stroke-line" strokeWidth={1} />
              <text x={pad.left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="fill-ink-subtle text-[11px] tabular-nums">
                {t === 0 ? "0" : compactMoney(t, data.currency)}
              </text>
            </g>
          ))}
          {points.map((p, i) => {
            const x = pad.left + i * band + (band - barW) / 2;
            const h = Math.max(0, y(0) - y(p.value));
            const r = Math.min(4, barW / 2, h);
            return (
              <g key={p.start}>
                {h > 0 && (
                  <path
                    d={`M${x},${y(0)} V${y(0) - h + r} Q${x},${y(0) - h} ${x + r},${y(0) - h} H${x + barW - r} Q${x + barW},${y(0) - h} ${x + barW},${y(0) - h + r} V${y(0)} Z`}
                    className={cx(
                      "transition-opacity",
                      i === points.length - 1 && data.window.bucket !== "week" && isCurrent(data) ? "fill-attention" : "fill-primary",
                      hover !== null && hover !== i && "opacity-40",
                    )}
                  />
                )}
                {i % every === 0 && (
                  <text x={pad.left + i * band + band / 2} y={height - 8} textAnchor="middle" className="fill-ink-subtle text-[11px]">
                    {bucketLabel(p.start, data.window.bucket)}
                  </text>
                )}
                {/* Hit target: the whole column, bigger than the bar. */}
                <rect x={pad.left + i * band} y={pad.top} width={band} height={plotH} fill="transparent" onMouseEnter={() => setHover(i)} />
              </g>
            );
          })}
        </svg>
      )}
      {active && hover !== null && (
        <div
          className="pointer-events-none absolute top-0 z-10 rounded-control border border-line bg-surface px-3 py-2 text-sm shadow-lg"
          style={{
            left: Math.min(Math.max(pad.left + hover * band + band / 2 - 80, 0), width - 160),
            width: 160,
          }}
        >
          <p className="text-xs text-ink-muted">{bucketLabel(active.start, data.window.bucket, true)}</p>
          <p className="tabular font-semibold text-ink">{formatMoney(active.sales, data.currency)}</p>
          <p className="text-xs text-ink-muted">
            {active.orders} {active.orders === 1 ? "order" : "orders"}
          </p>
        </div>
      )}
    </div>
  );
}

function SalesTable({ data }: { data: Dashboard }) {
  return (
    <div className="max-h-64 overflow-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-surface text-left text-ink-muted">
          <tr>
            <th className="py-1.5 font-medium">
              {data.window.bucket === "hour" ? "Hour" : data.window.bucket === "week" ? "Week" : "Day"}
            </th>
            <th className="py-1.5 text-right font-medium">Orders</th>
            <th className="py-1.5 text-right font-medium">Sales</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {data.series.map((p) => (
            <tr key={p.start} className="border-t border-line">
              <td className="py-1.5 text-ink">{bucketLabel(p.start, data.window.bucket, true)}</td>
              <td className="py-1.5 text-right text-ink">{p.orders}</td>
              <td className="py-1.5 text-right text-ink">{formatMoney(p.sales, data.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PeriodPicker({ period, onChange }: { period: Period; onChange: (p: Period) => void }) {
  return (
    <div className="flex w-full min-w-0 gap-1 overflow-x-auto rounded-control bg-sunken p-1 sm:w-auto" role="tablist" aria-label="Period">
      {PERIODS.map((p) => (
        <button
          key={p.key}
          role="tab"
          aria-selected={period === p.key}
          onClick={() => onChange(p.key)}
          className={cx(
            "shrink-0 rounded-[6px] px-3 py-1.5 text-sm font-medium whitespace-nowrap",
            period === p.key ? "bg-surface text-ink shadow-sm" : "text-ink-muted hover:text-ink",
          )}
        >
          {p.label}
        </button>
      ))}
    </div>
  );
}

type ReportQuery = UseQueryResult<Dashboard>;

/** The one big number: sales for the period, its change in rupees, and the chart. */
export function SalesHero({ report, period }: { report: ReportQuery; period: Period }) {
  const [asTable, setAsTable] = useState(false);
  const data = report.data;
  const meta = PERIODS.find((p) => p.key === period)!;
  if (!data) return <div className="h-72 animate-pulse rounded-panel border border-line bg-surface" aria-hidden />;
  const empty = data.series.every((p) => Number(p.sales) === 0);
  const diff = Number(data.totals.sales) - Number(data.previous.sales);
  const big = Math.abs(Number(data.totals.sales)) >= 1_00_00_000;
  return (
    <section className={cx("flex min-w-0 flex-col rounded-panel border border-line bg-surface p-5 transition-opacity", report.isFetching && "opacity-60")}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm text-ink-muted">Sales, {meta.label.toLowerCase()}</h2>
          <p className="figure mt-1 text-[2.6rem] text-ink">
            {big ? compactMoney(data.totals.sales, data.currency) : formatMoney(data.totals.sales, data.currency)}
          </p>
          <p className={cx("mt-1 text-sm font-medium", diff > 0 ? "text-success" : diff < 0 ? "text-danger" : "text-ink-subtle")}>
            {Number(data.previous.sales) === 0 && diff === 0
              ? "No sales yet in this or the previous period"
              : diff === 0
                ? `Same as the ${meta.previous}`
                : `${diff > 0 ? "Up" : "Down"} ${formatMoney(Math.abs(diff), data.currency)} on the ${meta.previous}`}
          </p>
        </div>
        {!empty && (
          <button
            onClick={() => setAsTable((v) => !v)}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-control px-2 py-1 text-sm text-primary hover:bg-primary-soft"
          >
            {asTable ? <BarChart3 className="size-4" aria-hidden /> : <Table2 className="size-4" aria-hidden />}
            {asTable ? "Chart" : "Table"}
          </button>
        )}
      </header>
      <div className="mt-4 flex-1">
        {empty ? (
          <p className="grid h-28 place-items-center rounded-control bg-sunken px-4 text-center text-sm text-ink-muted">
            The chart fills in as orders are confirmed.
          </p>
        ) : asTable ? (
          <SalesTable data={data} />
        ) : (
          <SalesChart data={data} height={170} />
        )}
      </div>
    </section>
  );
}

/** Open orders per stage, each in its stage color, so a pile-up is visible at a glance. */
function Pipeline({ data }: { data: Dashboard }) {
  const by = data.snapshot.open_by_status ?? {};
  const pick = (...statuses: string[]) =>
    statuses.reduce(
      (acc, s) => ({ orders: acc.orders + (by[s]?.orders ?? 0), value: acc.value + Number(by[s]?.value ?? 0) }),
      { orders: 0, value: 0 },
    );
  const stages = [
    { key: "new", label: "New", ...pick("NEW"), className: "bg-stage-new-soft text-stage-new" },
    { key: "confirmed", label: "Confirmed", ...pick("CONFIRMED", "PROCESSING"), className: "bg-stage-confirmed-soft text-stage-confirmed" },
    { key: "ready", label: "Ready", ...pick("READY_FOR_DELIVERY"), className: "bg-stage-ready-soft text-stage-ready" },
    { key: "out", label: "Out for delivery", ...pick("OUT_FOR_DELIVERY"), className: "bg-stage-out-soft text-stage-out" },
  ];
  return (
    <section aria-labelledby="pipeline">
      <header className="mb-2 flex items-baseline justify-between gap-3">
        <h2 id="pipeline" className="font-semibold text-ink">
          Orders in progress
        </h2>
        <Link href="/orders" className="rounded-control px-2 py-1 text-sm font-medium text-primary hover:bg-primary-soft">
          All orders
        </Link>
      </header>
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        {stages.map((s) => (
          <li key={s.key} className={cx("rounded-panel px-4 py-3", s.className)}>
            <p className="text-sm font-semibold">{s.label}</p>
            <p className="mt-0.5 flex items-baseline gap-2">
              <span className="figure text-[1.7rem] text-ink">{s.orders}</span>
              {s.orders > 0 && <span className="tabular text-xs text-ink-muted">{compactMoney(s.value, data.currency)}</span>}
            </p>
          </li>
        ))}
        <li className="col-span-2 rounded-panel bg-stage-done-soft px-4 py-3 text-stage-done sm:col-span-1">
          <p className="text-sm font-semibold">Delivered</p>
          <p className="mt-0.5 flex items-baseline gap-2">
            <span className="figure text-[1.7rem] text-ink">{data.snapshot.delivered_in_period}</span>
            <span className="text-xs text-ink-muted">in this period</span>
          </p>
        </li>
      </ol>
    </section>
  );
}

/* Bars with labels (one hue; the label carries identity) ----------------------------------- */

function BarList({
  rows,
  empty,
}: {
  rows: { key: string; label: string; value: number; display: string; detail?: string }[];
  empty: string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  if (!rows.length || max === 0) return <p className="text-sm text-ink-muted">{empty}</p>;
  return (
    <ul className="grid gap-3">
      {rows.map((r) => (
        <li key={r.key}>
          <div className="flex items-baseline justify-between gap-3 text-sm">
            <span className="text-ink">{r.label}</span>
            <span className="tabular font-medium text-ink">{r.display}</span>
          </div>
          <div className="mt-1 h-2 rounded-full bg-sunken">
            <div className="h-2 rounded-full bg-primary" style={{ width: `${Math.max(2, (r.value / max) * 100)}%` }} />
          </div>
          {r.detail && <p className="mt-0.5 text-xs text-ink-subtle">{r.detail}</p>}
        </li>
      ))}
    </ul>
  );
}

function Channels({ data }: { data: Dashboard }) {
  if (!data.channels.length) return <p className="text-sm text-ink-muted">No messages or sales in this period yet.</p>;
  const max = Math.max(...data.channels.map((c) => Number(c.sales)), 0);
  return (
    <div>
      <table className="w-full text-sm">
        <thead className="text-left text-ink-muted">
          <tr>
            <th className="pb-2 font-medium">Channel</th>
            <th className="pb-2 text-right font-medium">Messages</th>
            <th className="hidden pb-2 text-right font-medium sm:table-cell">Chats</th>
            <th className="pb-2 text-right font-medium">Leads</th>
            <th className="pb-2 text-right font-medium">Orders</th>
            <th className="pb-2 pl-3 font-medium sm:pl-4">Sales</th>
          </tr>
        </thead>
        <tbody className="tabular">
          {data.channels.map((c) => (
            <tr key={c.channel} className="border-t border-line">
              <td className="py-2.5 font-medium text-ink">{SOURCE_LABEL[c.channel] ?? c.channel}</td>
              <td className="py-2.5 text-right text-ink">{c.messages_in ? compactNumber(c.messages_in) : "–"}</td>
              <td className="hidden py-2.5 text-right text-ink sm:table-cell">{c.conversations || "–"}</td>
              <td className="py-2.5 text-right text-ink">{c.leads || "–"}</td>
              <td className="py-2.5 text-right text-ink">{c.orders}</td>
              <td className="w-2/5 py-2.5 pl-3 sm:pl-4">
                <div className="flex items-center gap-2">
                  <div className="h-2 flex-1 rounded-full bg-sunken">
                    {Number(c.sales) > 0 && (
                      <div className="h-2 rounded-full bg-primary" style={{ width: `${Math.max(2, (Number(c.sales) / max) * 100)}%` }} />
                    )}
                  </div>
                  <span className="w-16 shrink-0 text-right text-ink sm:w-20">{compactMoney(c.sales, data.currency)}</span>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Funnel({ data }: { data: Dashboard }) {
  const f = data.funnel;
  const rate = f.conversations ? Math.round((f.converted_conversations / f.conversations) * 100) : 0;
  const steps = [
    { label: "Chats with customers", value: f.conversations, display: compactNumber(f.conversations) },
    {
      label: "Chats that became leads",
      value: f.leads,
      display: `${compactNumber(f.leads)} · ${f.conversations ? Math.round((f.leads / f.conversations) * 100) : 0}%`,
    },
    {
      label: "Chats that became orders",
      value: f.converted_conversations,
      display: `${compactNumber(f.converted_conversations)} · ${rate}%`,
    },
    { label: "Orders from chats", value: f.orders, display: compactNumber(f.orders) },
  ];
  if (!f.conversations) return <p className="text-sm text-ink-muted">No customer chats in this period yet.</p>;
  return (
    <div>
      <ol className="grid gap-3">
        {steps.map((s) => (
          <li key={s.label}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="text-ink">{s.label}</span>
              <span className="tabular font-medium text-ink">{s.display}</span>
            </div>
            <div className="mt-1 h-3 rounded-full bg-sunken">
              <div className="h-3 rounded-full bg-primary" style={{ width: `${Math.max(2, (s.value / f.conversations) * 100)}%` }} />
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-4 border-t border-line pt-3 text-sm text-ink-muted">
        Sales from chats <span className="tabular float-right font-semibold text-ink">{formatMoney(f.sales, data.currency)}</span>
      </p>
    </div>
  );
}

/* Leads ------------------------------------------------------------------------------------- */

function LeadsSection({ data, against }: { data: Dashboard; against: string }) {
  const l = data.leads;
  const reasons = Object.entries(l.lost_reasons);
  return (
    <section className="grid min-w-0 gap-4" aria-labelledby="leads-heading">
      <h2 id="leads-heading" className="font-semibold text-ink">
        Leads
      </h2>
      <Strip columns="sm:grid-cols-4">
        <Tile label="New leads" value={compactNumber(data.totals.new_leads)} href="/leads">
          <Delta current={data.totals.new_leads} previous={data.previous.new_leads} against={against} />
        </Tile>
        <Tile label="Win rate" value={l.win_rate === null ? "–" : `${Math.round(l.win_rate * 100)}%`} href="/leads">
          <p className="mt-1 text-xs text-ink-muted">
            {l.won} won, {l.lost} lost in this period
          </p>
        </Tile>
        <Tile label="Value won" value={compactMoney(l.won_value, data.currency)}>
          <p className="mt-1 text-xs text-ink-muted">Confirmed orders that came from leads</p>
        </Tile>
        <Tile label="Open leads" value={compactNumber(l.open_now)} href="/leads">
          <p className="mt-1 text-xs text-ink-muted">
            {l.avg_days_to_win === null
              ? "Right now"
              : `Right now. A win takes ${l.avg_days_to_win < 1 ? "under a day" : `${l.avg_days_to_win} days`} on average`}
          </p>
        </Tile>
      </Strip>
      <div className="grid min-w-0 gap-6 lg:grid-cols-[3fr_2fr]">
        <Panel title="Team" description="Leads each person looks after">
          {l.staff.length === 0 ? (
            <p className="text-sm text-ink-muted">No leads yet. Create one from a chat with “Create lead”.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[30rem] text-sm">
                <thead className="text-left text-ink-muted">
                  <tr>
                    <th className="pb-2 font-medium">Person</th>
                    <th className="pb-2 text-right font-medium">Open</th>
                    <th className="pb-2 text-right font-medium">Won</th>
                    <th className="pb-2 text-right font-medium">Lost</th>
                    <th className="pb-2 text-right font-medium">Win rate</th>
                    <th className="pb-2 text-right font-medium">Value won</th>
                    <th className="pb-2 text-right font-medium">Overdue</th>
                  </tr>
                </thead>
                <tbody className="tabular">
                  {l.staff.map((s) => {
                    const closed = s.won + s.lost;
                    return (
                      <tr key={s.user_id ?? "none"} className="border-t border-line">
                        <td className={cx("py-2.5 font-medium", s.user_id ? "text-ink" : "text-ink-muted")}>{s.full_name}</td>
                        <td className="py-2.5 text-right text-ink">{s.open}</td>
                        <td className="py-2.5 text-right text-ink">{s.won}</td>
                        <td className="py-2.5 text-right text-ink">{s.lost}</td>
                        <td className="py-2.5 text-right text-ink">{closed ? `${Math.round((s.won / closed) * 100)}%` : "–"}</td>
                        <td className="py-2.5 text-right text-ink">{compactMoney(s.won_value, data.currency)}</td>
                        <td className={cx("py-2.5 text-right", s.overdue_followups ? "font-semibold text-danger" : "text-ink-muted")}>
                          {s.overdue_followups || "–"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        <Panel title="Why leads were lost" description="Leads marked lost in this period">
          <BarList
            empty="No lost leads in this period."
            rows={reasons
              .sort((a, b) => b[1] - a[1])
              .map(([reason, n]) => ({ key: reason, label: LOST_REASON_LABEL[reason] ?? reason, value: n, display: String(n) }))}
          />
        </Panel>
      </div>
    </section>
  );
}

/* The report ---------------------------------------------------------------------------- */

export function BusinessReport({ report, period }: { report: ReportQuery; period: Period }) {
  const data = report.data;
  const against = PERIODS.find((p) => p.key === period)!.previous;

  return (
    <div className="grid min-w-0 gap-6" aria-busy={report.isFetching}>
      {report.isError && (
        <p className="rounded-control bg-danger-soft px-4 py-3 text-sm text-danger">
          Couldn&apos;t load the figures. Try again in a moment.
        </p>
      )}
      {!data ? (
        <div className="h-24 animate-pulse rounded-panel bg-sunken" aria-hidden />
      ) : (
        <div className={cx("grid min-w-0 gap-8 transition-opacity", report.isFetching && "opacity-60")}>
          <div>
            <Strip columns="sm:grid-cols-4">
              <Tile label="Money received" value={compactMoney(data.totals.received, data.currency)} href="/payments">
                <Delta current={data.totals.received} previous={data.previous.received} against={against} />
              </Tile>
              <Tile
                label="To collect"
                value={compactMoney(data.snapshot.outstanding, data.currency)}
                href="/orders"
                tone={Number(data.snapshot.outstanding) > 0 ? "attention" : "ink"}
              >
                <p className="mt-1 text-xs text-ink-muted">
                  {data.snapshot.outstanding_orders === 0
                    ? "Nothing owed right now"
                    : `On ${data.snapshot.outstanding_orders} ${data.snapshot.outstanding_orders === 1 ? "order" : "orders"}, right now`}
                </p>
              </Tile>
              <Tile label="New orders" value={compactNumber(data.totals.new_orders)} href="/orders">
                <Delta current={data.totals.new_orders} previous={data.previous.new_orders} against={against} />
              </Tile>
              <Tile label="Customer messages" value={compactNumber(data.totals.messages_in)} href="/inbox">
                <Delta current={data.totals.messages_in} previous={data.previous.messages_in} against={against} />
              </Tile>
            </Strip>
            {[
              [data.totals.received, data.previous.received],
              [data.totals.new_orders, data.previous.new_orders],
              [data.totals.messages_in, data.previous.messages_in],
            ].every(([, prev]) => Number(prev) === 0) && (
              <p className="mt-2 text-xs text-ink-subtle">Comparisons with the {against} appear once that period has activity.</p>
            )}
          </div>

          <Pipeline data={data} />

          <LeadsSection data={data} against={against} />

          <div className="grid min-w-0 gap-6 lg:grid-cols-[3fr_2fr]">
            <Panel title="Channel performance" description="Which channel brings in business">
              <Channels data={data} />
            </Panel>
            <Panel title="From chat to order" description="Customer chats in this period">
              <Funnel data={data} />
            </Panel>
          </div>

          <div className="grid min-w-0 gap-6 lg:grid-cols-3">
            <Panel title="Where customers found you" description="Sales by lead source">
              <BarList
                empty="No sales in this period yet."
                rows={data.lead_sources.map((r) => ({
                  key: r.lead_source ?? "none",
                  label: r.lead_source ? (LEAD_LABEL[r.lead_source] ?? r.lead_source) : "Not recorded",
                  value: Number(r.sales),
                  display: compactMoney(r.sales, data.currency),
                  detail: `${r.orders} ${r.orders === 1 ? "order" : "orders"}`,
                }))}
              />
            </Panel>
            <Panel title="Orders by status" description="Orders created in this period">
              <BarList
                empty="No orders in this period yet."
                rows={Object.entries(data.orders_by_status)
                  .filter(([, n]) => n > 0)
                  .map(([status, n]) => ({ key: status, label: STATUS_LABEL[status] ?? status, value: n, display: String(n) }))}
              />
            </Panel>
            <Panel title="Customers" description="People who bought in this period">
              <dl className="grid grid-cols-2 gap-4">
                <div>
                  <dt className="text-sm text-ink-muted">New customers</dt>
                  <dd className="text-2xl font-semibold text-ink">{compactNumber(data.totals.new_customers)}</dd>
                </div>
                <div>
                  <dt className="text-sm text-ink-muted">Bought</dt>
                  <dd className="text-2xl font-semibold text-ink">{compactNumber(data.buyers.total)}</dd>
                </div>
                <div className="col-span-2 border-t border-line pt-3">
                  <dt className="text-sm text-ink-muted">Came back to buy again</dt>
                  <dd className="text-ink">
                    <span className="text-xl font-semibold">{data.buyers.returning}</span>{" "}
                    <span className="text-sm text-ink-muted">
                      of {data.buyers.total} {data.buyers.total === 1 ? "buyer" : "buyers"}
                    </span>
                  </dd>
                </div>
              </dl>
            </Panel>
          </div>
        </div>
      )}
    </div>
  );
}
