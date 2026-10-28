"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { PasswordInput } from "@/components/password-input";
import { Alert, Button, Field } from "@/components/ui";
import { ApiError, api, type Realm, type SessionResponse } from "@/lib/api";

const PATHS: Record<Realm, { login: string; changePassword: string; home: string; changePage: string; loginPage: string }> = {
  tenant: {
    login: "/api/v1/auth/login",
    changePassword: "/api/v1/auth/change-password",
    home: "/dashboard",
    changePage: "/change-password",
    loginPage: "/login",
  },
  platform: {
    login: "/api/v1/platform/auth/login",
    changePassword: "/api/v1/platform/auth/change-password",
    home: "/admin/tenants",
    changePage: "/admin/change-password",
    loginPage: "/admin/login",
  },
};

const OFFLINE = "Can't reach the server. Check your internet connection and try again.";

const loginSchema = z.object({
  email: z.email("Enter the email address you log in with"),
  password: z.string().min(1, "Enter your password"),
});

export function LoginForm({ realm, title, intro }: { realm: Realm; title: string; intro: string }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof loginSchema>>({ resolver: zodResolver(loginSchema) });

  const onSubmit = form.handleSubmit(async (values) => {
    setError(null);
    try {
      const session = await api<SessionResponse>(realm, "POST", PATHS[realm].login, values);
      router.replace(session.must_change_password ? PATHS[realm].changePage : PATHS[realm].home);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : OFFLINE);
    }
  });

  return (
    <>
      <h1 className="text-2xl font-semibold text-ink">{title}</h1>
      <p className="mt-1 mb-8 text-ink-muted">{intro}</p>
      <form onSubmit={onSubmit} noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          inputMode="email"
          error={form.formState.errors.email?.message}
          {...form.register("email")}
        />
        <PasswordInput
          label="Password"
          autoComplete="current-password"
          hint={realm === "tenant" ? "First time here? Use the temporary password we sent you." : undefined}
          error={form.formState.errors.password?.message}
          {...form.register("password")}
        />
        <Button type="submit" loading={form.formState.isSubmitting} className="mt-2 w-full">
          Log in
        </Button>
      </form>
    </>
  );
}

const changeSchema = z
  .object({
    current_password: z.string().min(1, "Enter your current password"),
    new_password: z.string().min(10, "Use at least 10 characters"),
    confirm: z.string(),
  })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "The two passwords don't match" });

export function ChangePasswordForm({ realm, firstLogin }: { realm: Realm; firstLogin: boolean }) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const form = useForm<z.infer<typeof changeSchema>>({ resolver: zodResolver(changeSchema) });
  const { errors } = form.formState;

  const onSubmit = form.handleSubmit(async ({ current_password, new_password }) => {
    setError(null);
    try {
      await api<SessionResponse>(realm, "POST", PATHS[realm].changePassword, { current_password, new_password });
      router.replace(PATHS[realm].home);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401 && err.code === "unauthorized") {
        router.replace(PATHS[realm].loginPage);
        return;
      }
      setError(err instanceof ApiError ? err.message : OFFLINE);
    }
  });

  return (
    <>
      <h1 className="text-2xl font-semibold text-ink">{firstLogin ? "Set your own password" : "Change password"}</h1>
      <p className="mt-1 mb-8 text-ink-muted">
        {firstLogin
          ? "Your temporary password works only once. Choose a password only you know."
          : "Choose a new password. You'll stay logged in on this device."}
      </p>
      <form onSubmit={onSubmit} noValidate>
        {error && <Alert tone="error">{error}</Alert>}
        <PasswordInput
          label={firstLogin ? "Temporary password" : "Current password"}
          autoComplete="current-password"
          error={errors.current_password?.message}
          {...form.register("current_password")}
        />
        <PasswordInput
          label="New password"
          autoComplete="new-password"
          hint="At least 10 characters. A short sentence is easy to remember and hard to guess."
          error={errors.new_password?.message}
          {...form.register("new_password")}
        />
        <PasswordInput
          label="Type the new password again"
          autoComplete="new-password"
          error={errors.confirm?.message}
          {...form.register("confirm")}
        />
        <Button type="submit" loading={form.formState.isSubmitting} className="mt-2 w-full">
          Save password
        </Button>
      </form>
    </>
  );
}
