"use client";

import { Eye, EyeOff } from "lucide-react";
import { forwardRef, useState, type InputHTMLAttributes } from "react";

import { cx } from "@/components/ui";

/** Password field with a show/hide toggle (typing temporary passwords on a phone is error-prone). */
export const PasswordInput = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: string }
>(function PasswordInput({ label, error, hint, ...props }, ref) {
  const [visible, setVisible] = useState(false);
  const id = props.id ?? props.name ?? label;
  return (
    <div className="mb-5">
      <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-ink">
        {label}
      </label>
      <div className="relative">
        <input
          ref={ref}
          id={id}
          type={visible ? "text" : "password"}
          className={cx(
            "w-full rounded-control border border-line-strong bg-surface py-2.5 pr-12 pl-3 text-base text-ink transition-colors hover:border-ink-subtle focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none",
            error && "border-danger",
          )}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${id}-error` : hint ? `${id}-hint` : undefined}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="absolute inset-y-0 right-0 grid w-11 place-items-center rounded-r-control text-ink-subtle hover:text-ink"
          aria-label={visible ? "Hide password" : "Show password"}
          aria-pressed={visible}
        >
          {visible ? <EyeOff className="size-5" aria-hidden /> : <Eye className="size-5" aria-hidden />}
        </button>
      </div>
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-sm text-danger" role="alert">
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
});
