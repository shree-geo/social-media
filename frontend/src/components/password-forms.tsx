"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ApiError, api, type Realm, type SessionResponse } from "@/lib/api";
import { Button, Card, ErrorBanner, Field } from "@/components/ui";

const PATHS: Record<Realm, { login: string; changePassword: string; home: string; changePage: string }> = {
  tenant: {
    login: "/api/v1/auth/login",
    changePassword: "/api/v1/auth/change-password",
    home: "/dashboard",
    changePage: "/change-password",
  },
  platform: {
    login: "/api/v1/platform/auth/login",
    changePassword: "/api/v1/platform/auth/change-password",
    home: "/admin/tenants",
    changePage: "/admin/change-password",
  },
};

const loginSchema = z.object({
  email: z.email("Enter a valid email address"),
  password: z.string().min(1, "Enter your password"),
});

export function LoginForm({ realm, title }: { realm: Realm; title: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const session = await api<SessionResponse>(realm, "POST", PATHS[realm].login, values);
      router.replace(session.must_change_password ? PATHS[realm].changePage : PATHS[realm].home);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Check your connection.");
    }
  });

  return (
    <Card title={title}>
      <form onSubmit={onSubmit} noValidate>
        <ErrorBanner message={error} />
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          inputMode="email"
          error={form.formState.errors.email?.message}
          {...form.register("email")}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          hint="First time? Use the temporary password we sent you."
          error={form.formState.errors.password?.message}
          {...form.register("password")}
        />
        <Button type="submit" disabled={form.formState.isSubmitting} className="w-full">
          {form.formState.isSubmitting ? "Logging in…" : "Log in"}
        </Button>
      </form>
    </Card>
  );
}

const changeSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current or temporary password"),
    new_password: z.string().min(10, "Use at least 10 characters"),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });

export function ChangePasswordForm({ realm, firstLogin }: { realm: Realm; firstLogin: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof changeSchema>>({ resolver: zodResolver(changeSchema) });

  const onSubmit = form.handleSubmit(async ({ current_password, new_password }) => {
    setError(null);
    try {
      await api<SessionResponse>(realm, "POST", PATHS[realm].changePassword, { current_password, new_password });
      router.replace(PATHS[realm].home);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401 && err.code === "unauthorized") {
        router.replace(realm === "tenant" ? "/login" : "/admin/login");
        return;
      }
      setError(err instanceof ApiError ? err.message : "Could not reach the server. Check your connection.");
    }
  });

  return (
    <Card title={firstLogin ? "Welcome! Please set your own password" : "Change password"}>
      <form onSubmit={onSubmit} noValidate>
        <ErrorBanner message={error} />
        <Field
          label={firstLogin ? "Temporary password" : "Current password"}
          type="password"
          autoComplete="current-password"
          error={form.formState.errors.current_password?.message}
          {...form.register("current_password")}
        />
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters. A short sentence is easy to remember."
          error={form.formState.errors.new_password?.message}
          {...form.register("new_password")}
        />
        <Field
          label="Confirm new password"
          type="password"
          autoComplete="new-password"
          error={form.formState.errors.confirm?.message}
          {...form.register("confirm")}
        />
        <Button type="submit" disabled={form.formState.isSubmitting} className="w-full">
          {form.formState.isSubmitting ? "Saving…" : "Set password"}
        </Button>
      </form>
    </Card>
  );
}
