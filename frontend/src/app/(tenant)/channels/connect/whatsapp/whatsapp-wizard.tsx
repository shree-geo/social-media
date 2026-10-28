"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Clock, Loader2, ShieldCheck, Smartphone, SmartphoneNfc } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, Button, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import {
  SETUP_ERRORS,
  SignupStopped,
  loadFacebookSdk,
  whatsappSignup,
  type SetupStarted,
  type SignupResult,
  type WhatsAppConnected,
} from "@/lib/channels";
import type { ConversationPage } from "@/lib/inbox";

type Mode = "new_number" | "coexistence";
type Step = "choose" | "finishing" | "test";

const STEPS: { key: Step | "signup"; label: string }[] = [
  { key: "choose", label: "Choose how" },
  { key: "signup", label: "Meta sign-up" },
  { key: "finishing", label: "Activate" },
  { key: "test", label: "Test" },
];

const MODES: { key: Mode; icon: typeof Smartphone; title: string; body: string; needs: string[] }[] = [
  {
    key: "new_number",
    icon: Smartphone,
    title: "Use a new or spare number",
    body: "Recommended. The number works only through this app, so your whole team can reply.",
    needs: [
      "A number you own that can receive an SMS or voice call now",
      "The number must not be on WhatsApp at the moment",
      "Your business name as customers should see it",
    ],
  },
  {
    key: "coexistence",
    icon: SmartphoneNfc,
    title: "Keep using my WhatsApp Business app",
    body: "Chats appear both in the app on your phone and here.",
    needs: [
      "The number is on the WhatsApp Business app (not normal WhatsApp)",
      "The phone with the app is with you — you'll scan a code",
      "Not available for every country yet; we'll tell you if it isn't",
    ],
  },
];

function errorMessage(err: unknown): string {
  if (err instanceof SignupStopped) {
    return err.reason === "cancelled"
      ? `The sign-up window was closed${err.step ? ` at "${err.step.toLowerCase().replace(/_/g, " ")}"` : ""}. Try again — Meta remembers the steps you finished.`
      : `${SETUP_ERRORS.wa_error}${err.detail ? ` ${err.detail}` : ""}`;
  }
  if (err instanceof ApiError) return SETUP_ERRORS[err.code] ?? err.message;
  if (err instanceof Error && SETUP_ERRORS[err.message]) return SETUP_ERRORS[err.message];
  return "Something went wrong talking to Meta. Try again.";
}

function Stepper({ current }: { current: number }) {
  return (
    <ol className="mb-8 flex items-center gap-2" aria-label="Progress">
      {STEPS.map((step, i) => (
        <li key={step.key} className="flex flex-1 items-center gap-2">
          <span
            className={cx(
              "tabular grid size-7 shrink-0 place-items-center rounded-full text-xs font-semibold",
              i < current ? "bg-success text-white" : i === current ? "bg-primary text-on-primary" : "border border-line-strong text-ink-subtle",
            )}
            aria-current={i === current ? "step" : undefined}
          >
            {i < current ? <Check className="size-4" aria-hidden /> : i + 1}
          </span>
          <span className={cx("hidden text-sm sm:inline", i === current ? "font-medium text-ink" : "text-ink-muted")}>{step.label}</span>
          {i < STEPS.length - 1 && <span className="h-px flex-1 bg-line" aria-hidden />}
        </li>
      ))}
    </ol>
  );
}

function NameStatus({ status }: { status: string | null }) {
  const value = (status ?? "").toUpperCase();
  if (value === "APPROVED") {
    return (
      <p className="flex items-center gap-2 text-sm text-success">
        <CheckCircle2 className="size-4" aria-hidden />
        Display name approved
      </p>
    );
  }
  if (value === "DECLINED" || value === "REJECTED") {
    return (
      <p className="flex items-start gap-2 text-sm text-danger">
        <AlertTriangle className="mt-0.5 size-4" aria-hidden />
        Meta didn&apos;t approve the display name. Use a name that matches your business and submit it again in WhatsApp Manager.
      </p>
    );
  }
  return (
    <p className="flex items-start gap-2 text-sm text-attention-ink">
      <Clock className="mt-0.5 size-4" aria-hidden />
      Meta is reviewing your display name. Until it&apos;s approved customers may see your number instead — you can already send and receive messages.
    </p>
  );
}

function TestMessage({ connected, since }: { connected: WhatsAppConnected; since: number }) {
  const arrived = useQuery({
    queryKey: ["whatsapp-test", since],
    queryFn: () => api<ConversationPage>("tenant", "GET", "/api/v1/conversations?provider=whatsapp&limit=5"),
    refetchInterval: (query) =>
      query.state.data?.items.some((c) => c.last_message_at && new Date(c.last_message_at).getTime() >= since) ? false : 3000,
  });
  const first = arrived.data?.items.find((c) => c.last_message_at && new Date(c.last_message_at).getTime() >= since);
  return (
    <section>
      <h1 className="text-2xl font-semibold text-ink">WhatsApp is connected</h1>
      <p className="tabular mt-1 text-lg text-ink">{connected.display_phone}</p>
      <div className="mt-3">
        <NameStatus status={connected.name_status} />
      </div>
      <p className="mt-6 text-ink-muted">
        Let&apos;s check messages arrive. From another phone, send &ldquo;Hello&rdquo; on WhatsApp to {connected.display_phone}.
      </p>
      <div className="mt-4 rounded-panel border border-line bg-surface p-5">
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
      <div className="mt-6 rounded-panel bg-sunken p-4 text-sm text-ink-muted">
        {connected.coexistence ? (
          <p>Keep chatting in the WhatsApp Business app as usual — messages appear in both places.</p>
        ) : (
          <p>This number now works through this app only. On your phone, open this website and add it to your home screen.</p>
        )}
        <p className="mt-2">Only message people who contacted you first. WhatsApp lowers the rating of numbers that send unwanted messages.</p>
      </div>
      <div className="mt-6 flex flex-wrap gap-3">
        <Link
          href={first ? `/inbox/${first.id}` : "/inbox"}
          className="inline-flex min-h-11 items-center rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover"
        >
          Open inbox
        </Link>
        <Link href="/channels" className="inline-flex min-h-11 items-center px-3 text-ink-muted hover:text-ink">
          {first ? "Done" : "Skip the test"}
        </Link>
      </div>
    </section>
  );
}

export function WhatsAppWizard() {
  const [mode, setMode] = useState<Mode>("new_number");
  const [attempt, setAttempt] = useState(0);
  const [step, setStep] = useState<Step>("choose");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [signup, setSignup] = useState<SignupResult | null>(null);
  const [connected, setConnected] = useState<WhatsAppConnected | null>(null);
  const [connectedAt, setConnectedAt] = useState(0);

  // A setup session per mode, plus Meta's SDK, ready before the click (pop-up blockers).
  const preparation = useQuery({
    queryKey: ["whatsapp-setup", mode, attempt],
    queryFn: async () => {
      const started = await api<SetupStarted>("tenant", "POST", "/api/v1/channels/setup-sessions", { provider: "whatsapp", mode });
      await loadFacebookSdk(started.app_id, started.graph_api_version);
      return started;
    },
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const setup = preparation.data ?? null;
  const prepareError = preparation.error ? errorMessage(preparation.error) : null;

  async function finish(setupSession: SetupStarted, result: SignupResult | null, code: string | null) {
    if (!result) return;
    setBusy(true);
    setError(null);
    setStep("finishing");
    try {
      const done = await api<WhatsAppConnected>("tenant", "POST", `/api/v1/channels/setup-sessions/${setupSession.id}/whatsapp`, {
        state: setupSession.state,
        waba_id: result.wabaId,
        phone_number_id: result.phoneNumberId,
        ...(code ? { code } : {}),
      });
      setConnected(done);
      setConnectedAt(Date.now());
      setStep("test");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function startSignup() {
    if (!setup) return;
    setError(null);
    let result: SignupResult;
    try {
      result = await whatsappSignup(setup.login_config_id, mode); // opens synchronously within the click
    } catch (err) {
      setError(errorMessage(err));
      if (err instanceof SignupStopped) {
        void api("tenant", "POST", `/api/v1/channels/setup-sessions/${setup.id}/cancel`, {
          step: err.step,
          error: err.detail,
        }).catch(() => undefined);
        setAttempt((n) => n + 1); // the cancelled session is closed; prepare a fresh one
      }
      return;
    }
    setSignup(result);
    await finish(setup, result, result.code);
  }

  function startOver() {
    setSignup(null);
    setError(null);
    setStep("choose");
    setAttempt((n) => n + 1);
  }

  const stepIndex = step === "choose" ? (busy ? 1 : 0) : step === "finishing" ? 2 : 3;

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-8 sm:py-8">
      <Link href="/channels" className="mb-6 inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Channels
      </Link>
      <Stepper current={stepIndex} />

      {step === "choose" && (
        <section>
          <h1 className="text-2xl font-semibold text-ink">Connect WhatsApp</h1>
          <p className="mt-2 text-ink-muted">Customers keep messaging your WhatsApp number as usual; their messages arrive in your inbox.</p>
          <fieldset className="mt-6 grid gap-3">
            <legend className="sr-only">How do you want to connect?</legend>
            {MODES.map((m) => {
              const Icon = m.icon;
              const selected = mode === m.key;
              return (
                <label
                  key={m.key}
                  className={cx(
                    "flex cursor-pointer gap-4 rounded-panel border p-4 transition-colors",
                    selected ? "border-primary bg-primary-soft/50" : "border-line bg-surface hover:border-line-strong",
                  )}
                >
                  <input type="radio" name="mode" className="mt-1 size-4 accent-[var(--sc-primary)]" checked={selected} onChange={() => setMode(m.key)} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 font-semibold text-ink">
                      <Icon className="size-5 text-primary" aria-hidden />
                      {m.title}
                    </span>
                    <span className="mt-1 block text-sm text-ink-muted">{m.body}</span>
                    {selected && (
                      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink">
                        {m.needs.map((n) => (
                          <li key={n}>{n}</li>
                        ))}
                      </ul>
                    )}
                  </span>
                </label>
              );
            })}
          </fieldset>
          <p className="mt-4 flex items-center gap-2 text-sm text-ink-muted">
            <ShieldCheck className="size-4 text-success" aria-hidden />
            The WhatsApp account stays yours. You can disconnect it any time.
          </p>
          {(error ?? prepareError) && (
            <div className="mt-6">
              <Alert tone="error">{error ?? prepareError}</Alert>
            </div>
          )}
          <Button className="mt-6 w-full sm:w-auto" onClick={startSignup} disabled={!preparation.isSuccess} loading={busy}>
            {preparation.isSuccess ? "Continue with Facebook" : preparation.isError ? "Not available right now" : "Getting ready…"}
          </Button>
          <p className="mt-3 text-sm text-ink-subtle">
            Meta&apos;s window asks for your business details, your WhatsApp display name and the number, then sends a code to it.
          </p>
        </section>
      )}

      {step === "finishing" && (
        <section>
          <h1 className="text-2xl font-semibold text-ink">{error ? "Almost there" : "Finishing setup…"}</h1>
          {error ? (
            <>
              <div className="mt-6">
                <Alert tone="error">{error}</Alert>
              </div>
              <div className="flex flex-wrap gap-3">
                {/* Retrying continues from the failed step; Meta's code is not needed again. */}
                <Button onClick={() => setup && finish(setup, signup, null)} loading={busy}>
                  Try again
                </Button>
                <Button variant="ghost" onClick={startOver}>
                  Start over
                </Button>
              </div>
            </>
          ) : (
            <ul className="mt-6 space-y-3">
              {["Saving secure access", "Connecting your number", "Activating the number for messages", "Subscribing to new messages"].map((c) => (
                <li key={c} className="flex items-center gap-3 text-ink">
                  <Loader2 className="size-5 animate-spin text-primary" aria-hidden />
                  {c}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {step === "test" && connected && <TestMessage connected={connected} since={connectedAt} />}
    </main>
  );
}
