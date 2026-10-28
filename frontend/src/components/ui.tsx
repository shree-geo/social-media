/**
 * Shared UI primitives. They only use semantic theme utilities (src/styles/theme.css),
 * so changing the theme there restyles the whole app.
 */

import { AlertCircle, CheckCircle2, Info, Loader2, type LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/* Buttons ---------------------------------------------------------------------------- */

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

const BUTTON_STYLES: Record<ButtonVariant, string> = {
  primary: "bg-primary text-on-primary hover:bg-primary-hover disabled:opacity-50",
  secondary: "border border-line-strong bg-surface text-ink hover:bg-sunken disabled:opacity-50",
  ghost: "text-ink-muted hover:bg-sunken hover:text-ink disabled:opacity-50",
  danger: "bg-danger text-white hover:opacity-90 disabled:opacity-50",
};

export function Button({
  children,
  variant = "primary",
  size = "md",
  icon: Icon,
  loading = false,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  icon?: LucideIcon;
  loading?: boolean;
}) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-control font-medium transition-colors disabled:cursor-not-allowed",
        size === "md" ? "min-h-11 px-4 text-base" : "min-h-9 px-3 text-sm",
        BUTTON_STYLES[variant],
        className,
      )}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? <Loader2 className="size-4 animate-spin" aria-hidden /> : Icon && <Icon className="size-4" aria-hidden />}
      {children}
    </button>
  );
}

/* Form fields ------------------------------------------------------------------------ */

const CONTROL =
  "w-full rounded-control border border-line-strong bg-surface px-3 py-2.5 text-base text-ink placeholder:text-ink-subtle transition-colors hover:border-ink-subtle focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/25 aria-[invalid=true]:border-danger";

function FieldShell({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="mb-5">
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 flex items-center gap-1.5 text-sm text-danger" role="alert">
          <AlertCircle className="size-4 shrink-0" aria-hidden />
          {error}
        </p>
      ) : (
        hint && (
          <p id={`${id}-hint`} className="mt-1.5 text-sm text-ink-muted">
            {hint}
          </p>
        )
      )}
    </div>
  );
}

function describedBy(id: string, error?: string, hint?: string): string | undefined {
  return error ? `${id}-error` : hint ? `${id}-hint` : undefined;
}

export function Field({
  label,
  error,
  hint,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }) {
  const id = props.id ?? props.name ?? label;
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <input
        id={id}
        className={CONTROL}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        {...props}
      />
    </FieldShell>
  );
}

export function SelectField({
  label,
  error,
  hint,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { label: string; error?: string; hint?: string }) {
  const id = props.id ?? props.name ?? label;
  return (
    <FieldShell id={id} label={label} hint={hint} error={error}>
      <select
        id={id}
        className={cx(CONTROL, "appearance-none bg-[length:1rem] bg-[right_0.75rem_center] bg-no-repeat pr-9")}
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%238a91ac' stroke-width='2'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E\")",
        }}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(id, error, hint)}
        {...props}
      >
        {children}
      </select>
    </FieldShell>
  );
}

export function TextArea({
  label,
  hint,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string; hint?: string }) {
  const id = props.id ?? props.name ?? label;
  return (
    <FieldShell id={id} label={label} hint={hint}>
      <textarea id={id} className={cx(CONTROL, "min-h-24")} aria-describedby={describedBy(id, undefined, hint)} {...props} />
    </FieldShell>
  );
}

export function Checkbox({ label, hint, ...props }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className="mb-4 flex cursor-pointer items-start gap-3">
      <input type="checkbox" className="mt-1 size-4 accent-[var(--sc-primary)]" {...props} />
      <span>
        <span className="block text-base text-ink">{label}</span>
        {hint && <span className="block text-sm text-ink-muted">{hint}</span>}
      </span>
    </label>
  );
}

/* Feedback --------------------------------------------------------------------------- */

const ALERT_STYLES = {
  error: { box: "border-danger/30 bg-danger-soft text-danger", icon: AlertCircle },
  warning: { box: "border-attention/40 bg-attention-soft text-attention-ink", icon: AlertCircle },
  info: { box: "border-primary/20 bg-primary-soft text-primary", icon: Info },
  success: { box: "border-success/30 bg-success-soft text-success", icon: CheckCircle2 },
} as const;

export function Alert({
  tone = "error",
  title,
  children,
}: {
  tone?: keyof typeof ALERT_STYLES;
  title?: string;
  children?: ReactNode;
}) {
  const { box, icon: Icon } = ALERT_STYLES[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cx("mb-5 flex gap-3 rounded-control border px-4 py-3", box)}>
      <Icon className="mt-0.5 size-5 shrink-0" aria-hidden />
      <div className="min-w-0 text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? "mt-0.5" : undefined}>{children}</div>}
      </div>
    </div>
  );
}

export function ErrorBanner({ message }: { message: string | null }) {
  return message ? <Alert tone="error">{message}</Alert> : null;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-ink-muted" role="status">
      <Loader2 className="size-5 animate-spin" aria-hidden />
      <span>{label}…</span>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span className="mb-4 grid size-12 place-items-center rounded-full bg-primary-soft text-primary">
        <Icon className="size-6" aria-hidden />
      </span>
      <p className="text-lg font-semibold text-ink">{title}</p>
      {children && <div className="mt-1 max-w-sm text-ink-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

/* Layout ----------------------------------------------------------------------------- */

export function Panel({ title, description, actions, children, className }: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cx("rounded-panel border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            {title && <h2 className="text-lg font-semibold text-ink">{title}</h2>}
            {description && <p className="mt-0.5 text-sm text-ink-muted">{description}</p>}
          </div>
          {actions}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold text-ink sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 gap-2">{actions}</div>}
    </header>
  );
}

/* People and channels ---------------------------------------------------------------- */

export type Channel = "whatsapp" | "messenger";

export const CHANNEL_LABEL: Record<string, string> = { whatsapp: "WhatsApp", messenger: "Messenger" };

const CHANNEL_DOT: Record<string, string> = { whatsapp: "bg-whatsapp", messenger: "bg-messenger" };

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

export function Avatar({ name, channel, size = "md" }: { name: string; channel?: string; size?: "sm" | "md" | "lg" }) {
  const box = { sm: "size-8 text-xs", md: "size-10 text-sm", lg: "size-14 text-lg" }[size];
  return (
    <span className={cx("relative inline-grid shrink-0 place-items-center rounded-full bg-primary-soft font-semibold text-primary", box)}>
      {initials(name)}
      {channel && (
        <span
          className={cx("absolute -right-0.5 -bottom-0.5 size-3.5 rounded-full ring-2 ring-surface", CHANNEL_DOT[channel] ?? "bg-ink-subtle")}
          title={CHANNEL_LABEL[channel]}
          aria-label={CHANNEL_LABEL[channel]}
        />
      )}
    </span>
  );
}

export function ChannelTag({ channel }: { channel: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-ink-muted">
      <span className={cx("size-2 rounded-full", CHANNEL_DOT[channel] ?? "bg-ink-subtle")} aria-hidden />
      {CHANNEL_LABEL[channel] ?? channel}
    </span>
  );
}

const PILL = {
  neutral: "bg-sunken text-ink-muted",
  primary: "bg-primary-soft text-primary",
  attention: "bg-attention-soft text-attention-ink",
  success: "bg-success-soft text-success",
  danger: "bg-danger-soft text-danger",
} as const;

export function Pill({ tone = "neutral", children }: { tone?: keyof typeof PILL; children: ReactNode }) {
  return <span className={cx("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium", PILL[tone])}>{children}</span>;
}

const SUBSCRIPTION_TONE: Record<string, keyof typeof PILL> = {
  TRIAL: "primary",
  ACTIVE: "success",
  GRACE: "attention",
  EXPIRED: "danger",
  SUSPENDED: "danger",
  CANCELLED: "neutral",
};

const SUBSCRIPTION_LABEL: Record<string, string> = {
  TRIAL: "Trial",
  ACTIVE: "Active",
  GRACE: "Grace period",
  EXPIRED: "Expired",
  SUSPENDED: "Suspended",
  CANCELLED: "Cancelled",
};

export function SubscriptionPill({ status }: { status: string | null }) {
  if (!status) return <Pill>No subscription</Pill>;
  return <Pill tone={SUBSCRIPTION_TONE[status] ?? "neutral"}>{SUBSCRIPTION_LABEL[status] ?? status}</Pill>;
}

export { cx };
