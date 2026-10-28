"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Loader2, MessageCircle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, Avatar, Button, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import {
  SETUP_ERRORS,
  facebookLogin,
  loadFacebookSdk,
  type Authorized,
  type PageOption,
  type PageResult,
  type SetupStarted,
} from "@/lib/channels";
import type { ConversationPage } from "@/lib/inbox";

type Step = "intro" | "choose" | "connecting" | "test";

const STEPS: { key: Step; label: string }[] = [
  { key: "intro", label: "Log in" },
  { key: "choose", label: "Choose Page" },
  { key: "connecting", label: "Connect" },
  { key: "test", label: "Test" },
];

const PAGE_STATUS: Record<PageOption["status"], string | null> = {
  connectable: null,
  connected_here: "Already connected. Connect again to refresh access.",
  connected_elsewhere: "Connected to another business on our platform. Contact us if this is your Page.",
  needs_full_control: "You need full control of this Page. Check Page settings → Page access.",
};

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return SETUP_ERRORS[err.code] ?? err.message;
  if (err instanceof Error && SETUP_ERRORS[err.message]) return SETUP_ERRORS[err.message];
  return "Something went wrong talking to Facebook. Try again.";
}

function Stepper({ current }: { current: Step }) {
  const index = STEPS.findIndex((s) => s.key === current);
  return (
    <ol className="mb-8 flex items-center gap-2" aria-label="Progress">
      {STEPS.map((step, i) => (
        <li key={step.key} className="flex flex-1 items-center gap-2">
          <span
            className={cx(
              "tabular grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold",
              i < index ? "bg-success text-white" : i === index ? "bg-primary text-on-primary" : "border border-line-strong text-ink-subtle",
            )}
            aria-current={i === index ? "step" : undefined}
          >
            {i < index ? <Check className="size-4" aria-hidden /> : i + 1}
          </span>
          <span className={cx("hidden text-sm sm:inline", i === index ? "font-medium text-ink" : "text-ink-muted")}>{step.label}</span>
          {i < STEPS.length - 1 && <span className="h-px flex-1 bg-line" aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

function Intro({
  ready,
  unavailable,
  busy,
  error,
  onContinue,
}: {
  ready: boolean;
  unavailable: boolean;
  busy: boolean;
  error: string | null;
  onContinue: () => void;
}) {
  return (
    <section>
      <h1 className="text-2xl font-semibold text-ink">Connect your Facebook Page</h1>
      <p className="mt-2 text-ink-muted">Messages people send to your Page will arrive in your inbox, and you can reply from here.</p>
      <ol className="mt-6 space-y-3">
        {[
          "Log in to Facebook in a pop-up window.",
          "Choose your business Page.",
          "Allow us to read and reply to your Page's messages.",
        ].map((text, i) => (
          <li key={text} className="flex gap-3">
            <span className="tabular grid size-6 shrink-0 place-items-center rounded-full bg-primary-soft text-xs font-semibold text-primary">{i + 1}</span>
            <span className="text-ink">{text}</span>
          </li>
        ))}
      </ol>
      <div className="mt-6 rounded-panel bg-sunken p-4 text-sm text-ink-muted">
        <p className="font-medium text-ink">Before you start</p>
        <ul className="mt-2 list-disc space-y-1 pl-5">
          <li>Use the Facebook account that has full control of your Page.</li>
          <li>Allow pop-ups for this site.</li>
          <li>A computer is easiest, but a phone works too.</li>
        </ul>
      </div>
      <p className="mt-4 flex items-center gap-2 text-sm text-ink-muted">
        <ShieldCheck className="size-4 text-success" aria-hidden />
        You type your password into Facebook&apos;s own window. We never see it.
      </p>
      {error && (
        <div className="mt-6">
          <Alert tone="error">{error}</Alert>
        </div>
      )}
      <Button className="mt-6 w-full sm:w-auto" onClick={onContinue} disabled={!ready} loading={busy} icon={MessageCircle}>
        {ready ? "Continue with Facebook" : unavailable ? "Not available right now" : "Getting ready…"}
      </Button>
    </section>
  );
}

function ChoosePages({
  authorized,
  error,
  busy,
  onConnect,
  onRetry,
}: {
  authorized: Authorized;
  error: string | null;
  busy: boolean;
  onConnect: (ids: string[]) => void;
  onRetry: () => void;
}) {
  const selectable = authorized.pages.filter((p) => p.status === "connectable" || p.status === "connected_here");
  const [selected, setSelected] = useState<string[]>(selectable.length === 1 ? [selectable[0].id] : []);
  const remaining = authorized.limit === null ? Infinity : authorized.limit - authorized.used;
  const newCount = selected.filter((id) => authorized.pages.find((p) => p.id === id)?.status !== "connected_here").length;

  if (authorized.pages.length === 0) {
    return (
      <section>
        <h1 className="text-2xl font-semibold text-ink">No Pages found</h1>
        <Alert tone="warning">{SETUP_ERRORS.no_pages}</Alert>
        <Button onClick={onRetry}>Log in to Facebook again</Button>
      </section>
    );
  }

  return (
    <section>
      <h1 className="text-2xl font-semibold text-ink">Choose your Page</h1>
      <p className="mt-2 mb-6 text-ink-muted">
        {authorized.limit === null
          ? "Pick the Pages whose messages should arrive here."
          : `Your package allows ${authorized.limit} Facebook Page${authorized.limit === 1 ? "" : "s"}${authorized.used ? ` (${authorized.used} connected)` : ""}.`}
      </p>
      {error && <Alert tone="error">{error}</Alert>}
      <ul className="overflow-hidden rounded-panel border border-line bg-surface">
        {authorized.pages.map((page) => {
          const enabled = page.status === "connectable" || page.status === "connected_here";
          const checked = selected.includes(page.id);
          const note = PAGE_STATUS[page.status];
          return (
            <li key={page.id} className="border-b border-line last:border-b-0">
              <label className={cx("flex items-start gap-3 px-4 py-3", enabled ? "cursor-pointer hover:bg-sunken/60" : "opacity-60")}>
                <input
                  type="checkbox"
                  className="mt-3 size-4 accent-[var(--sc-primary)]"
                  disabled={!enabled}
                  checked={checked}
                  onChange={(e) =>
                    setSelected((s) => (e.target.checked ? [...s, page.id] : s.filter((id) => id !== page.id)))
                  }
                />
                {page.picture ? (
                  // eslint-disable-next-line @next/next/no-img-element -- Facebook CDN avatar, not worth an image loader
                  <img src={page.picture} alt="" className="size-10 rounded-full object-cover" />
                ) : (
                  <Avatar name={page.name} />
                )}
                <span className="min-w-0 flex-1">
                  <span className="block font-medium text-ink">{page.name}</span>
                  {note && (
                    <span className={cx("mt-0.5 flex items-start gap-1.5 text-sm", enabled ? "text-ink-muted" : "text-attention-ink")}>
                      {!enabled && <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />}
                      {note}
                    </span>
                  )}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
      {newCount > remaining && (
        <p className="mt-3 text-sm text-danger">You&apos;ve chosen more Pages than your package allows.</p>
      )}
      <div className="mt-6 flex flex-wrap items-center gap-3">
        <Button onClick={() => onConnect(selected)} disabled={selected.length === 0 || newCount > remaining} loading={busy}>
          {selected.length > 1 ? `Connect ${selected.length} Pages` : "Connect this Page"}
        </Button>
        <button onClick={onRetry} className="text-sm text-ink-muted hover:text-ink">
          Use a different Facebook account
        </button>
      </div>
    </section>
  );
}

function Connecting({ results }: { results: PageResult[] | null }) {
  const checks = ["Saving secure access to your Page", "Subscribing to new messages", "Checking everything works"];
  return (
    <section>
      <h1 className="text-2xl font-semibold text-ink">{results ? "Connection results" : "Connecting…"}</h1>
      {!results ? (
        <ul className="mt-6 space-y-3">
          {checks.map((c) => (
            <li key={c} className="flex items-center gap-3 text-ink">
              <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
              {c}
            </li>
          ))}
        </ul>
      ) : (
        <ul className="mt-6 space-y-3">
          {results.map((r) => (
            <li key={r.page_id} className="flex items-start gap-3">
              {r.ok ? (
                <CheckCircle2 className="mt-0.5 size-5 text-success" aria-hidden />
              ) : (
                <AlertTriangle className="mt-0.5 size-5 text-danger" aria-hidden />
              )}
              <span>
                <span className="block font-medium text-ink">{r.name}</span>
                <span className="text-sm text-ink-muted">{r.ok ? "Connected" : r.message}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function TestMessage({ pages, since }: { pages: PageResult[]; since: number }) {
  const arrived = useQuery({
    queryKey: ["messenger-test", since],
    queryFn: () => api<ConversationPage>("tenant", "GET", "/api/v1/conversations?provider=messenger&limit=5"),
    refetchInterval: (query) =>
      query.state.data?.items.some((c) => c.last_message_at && new Date(c.last_message_at).getTime() >= since) ? false : 3000,
  });
  const first = arrived.data?.items.find((c) => c.last_message_at && new Date(c.last_message_at).getTime() >= since);
  const names = pages.map((p) => p.name).join(" and ");
  return (
    <section>
      <h1 className="text-2xl font-semibold text-ink">{names} {pages.length > 1 ? "are" : "is"} connected</h1>
      <p className="mt-2 text-ink-muted">Let&apos;s check messages arrive. From your personal Facebook or Messenger, send &ldquo;Hello&rdquo; to your Page.</p>
      <div className="mt-6 rounded-panel border border-line bg-surface p-5">
        {first ? (
          <p className="flex items-start gap-3">
            <CheckCircle2 className="mt-0.5 size-5 text-success" aria-hidden />
            <span>
              <span className="block font-medium text-ink">Message received from {first.customer.display_name}</span>
              <span className="text-sm text-ink-muted">{first.last_message_preview}</span>
            </span>
          </p>
        ) : (
          <p className="flex items-center gap-3 text-ink-muted">
            <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
            Waiting for your test message…
          </p>
        )}
      </div>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link href={first ? `/inbox/${first.id}` : "/inbox"} className="inline-flex min-h-11 items-center rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover">
          Open inbox
        </Link>
        <Link href="/channels" className="inline-flex min-h-11 items-center px-3 text-ink-muted hover:text-ink">
          {first ? "Done" : "Skip the test"}
        </Link>
      </div>
    </section>
  );
}

export function MessengerWizard() {
  const [step, setStep] = useState<Step>("intro");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authorized, setAuthorized] = useState<Authorized | null>(null);
  const [results, setResults] = useState<PageResult[] | null>(null);
  const [connectedAt, setConnectedAt] = useState(0);

  // Start a setup session and load Facebook's SDK *before* the click: the login pop-up
  // must open directly from the click, or browsers block it. A new attempt starts a new session.
  const preparation = useQuery({
    queryKey: ["messenger-setup", attempt],
    queryFn: async () => {
      const started = await api<SetupStarted>("tenant", "POST", "/api/v1/channels/setup-sessions", { provider: "messenger" });
      await loadFacebookSdk(started.app_id, started.graph_api_version);
      return started;
    },
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const setup: SetupStarted | null = preparation.data ?? null;
  const sdkReady = preparation.isSuccess;
  const prepareError = preparation.error
    ? preparation.error instanceof Error && preparation.error.message === "sdk_failed"
      ? "Facebook couldn't be loaded. Check your connection or ad blocker, then refresh."
      : errorMessage(preparation.error)
    : null;
  const prepare = () => setAttempt((n) => n + 1);

  async function login() {
    if (!setup) return;
    setError(null);
    let token: string;
    try {
      token = await facebookLogin(setup.login_config_id); // opens synchronously within the click
    } catch (err) {
      setError(errorMessage(err));
      return;
    }
    setBusy(true);
    try {
      const result = await api<Authorized>("tenant", "POST", `/api/v1/channels/setup-sessions/${setup.id}/authorize`, {
        state: setup.state,
        access_token: token,
      });
      setAuthorized(result);
      setStep("choose");
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof ApiError && ["setup_expired", "invalid_state", "setup_closed"].includes(err.code)) prepare();
    } finally {
      setBusy(false);
    }
  }

  async function connect(pageIds: string[]) {
    if (!setup) return;
    setError(null);
    setBusy(true);
    setStep("connecting");
    setConnectedAt(Date.now());
    try {
      const outcome = await api<PageResult[]>("tenant", "POST", `/api/v1/channels/setup-sessions/${setup.id}/complete`, { page_ids: pageIds });
      setResults(outcome);
      if (outcome.some((r) => r.ok)) setTimeout(() => setStep("test"), 1200);
    } catch (err) {
      setError(errorMessage(err));
      setStep("choose");
    } finally {
      setBusy(false);
    }
  }

  function restart() {
    setAuthorized(null);
    setResults(null);
    setError(null);
    setStep("intro");
    prepare();
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href="/channels" className="mb-6 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Channels
      </Link>
      <Stepper current={step} />
      {step === "intro" && <Intro ready={sdkReady} unavailable={preparation.isError} busy={busy} error={error ?? prepareError} onContinue={login} />}
      {step === "choose" && authorized && (
        <ChoosePages authorized={authorized} error={error} busy={busy} onConnect={connect} onRetry={restart} />
      )}
      {step === "connecting" && (
        <>
          <Connecting results={results} />
          {results && !results.some((r) => r.ok) && (
            <Button className="mt-6" onClick={restart}>
              Try again
            </Button>
          )}
        </>
      )}
      {step === "test" && results && <TestMessage pages={results.filter((r) => r.ok)} since={connectedAt} />}
    </main>
  );
}
