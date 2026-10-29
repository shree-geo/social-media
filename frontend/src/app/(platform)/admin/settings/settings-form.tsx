"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, Button, Field, PageHeader } from "@/components/ui";
import { ApiError, api, type PlatformMe } from "@/lib/api";
import type { SiteContact } from "@/lib/site-contact";

const schema = z.object({
  support_phone: z.union([
    z
      .string()
      .trim()
      .regex(/^\+?[0-9 ()-]{6,30}$/, "Enter a phone number like +977 9851234567"),
    z.literal(""),
  ]),
  support_email: z.union([z.email("Enter a valid email"), z.literal("")]),
});
type Values = z.infer<typeof schema>;

export function SettingsForm() {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["platform-me"], queryFn: () => api<PlatformMe>("platform", "GET", "/api/v1/platform/auth/me") });
  const settings = useQuery({
    queryKey: ["platform-settings"],
    queryFn: () => api<SiteContact>("platform", "GET", "/api/v1/platform/settings"),
  });
  const canEdit = me.data?.role === "PLATFORM_SUPER_ADMIN";
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: { support_phone: "", support_email: "" } });
  const { errors, isSubmitting } = form.formState;

  useEffect(() => {
    if (settings.data) form.reset({ support_phone: settings.data.support_phone ?? "", support_email: settings.data.support_email ?? "" });
  }, [settings.data, form]);

  const onSubmit = form.handleSubmit(async (v) => {
    setError(null);
    setSaved(false);
    try {
      const result = await api<SiteContact>("platform", "PATCH", "/api/v1/platform/settings", {
        support_phone: v.support_phone.trim() || null,
        support_email: v.support_email || null,
      });
      queryClient.setQueryData(["platform-settings"], result);
      void queryClient.invalidateQueries({ queryKey: ["site-contact"] });
      setSaved(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Check your connection and try again.");
    }
  });

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader title="Settings" description="Platform-wide details. Changes show on the website and login screens straight away." />
      {error && <Alert>{error}</Alert>}
      {saved && <Alert tone="success">Saved. The website now shows the new contact details.</Alert>}
      {me.data && !canEdit && <Alert tone="warning">Only a super admin can change these settings.</Alert>}
      <form onSubmit={onSubmit} noValidate className="rounded-panel border border-line bg-surface px-5 py-8 sm:px-8">
        <h2 className="text-lg font-semibold text-ink">Support contact</h2>
        <p className="mt-1 mb-6 text-sm text-ink-muted">
          Shown on the Contact us page, in the footer, the privacy policy and on the login screens. The phone number is also used for the
          WhatsApp button. Leave a field empty to hide it.
        </p>
        <fieldset disabled={!canEdit} className="grid gap-x-4 sm:grid-cols-2">
          <Field
            label="Support phone"
            inputMode="tel"
            placeholder="+977 9851234567"
            error={errors.support_phone?.message}
            {...form.register("support_phone")}
          />
          <Field
            label="Support email"
            type="email"
            placeholder="support@myleadtoday.cloud"
            error={errors.support_email?.message}
            {...form.register("support_email")}
          />
        </fieldset>
        {canEdit && (
          <div className="flex justify-end pt-2">
            <Button type="submit" loading={isSubmitting}>
              Save
            </Button>
          </div>
        )}
      </form>
    </div>
  );
}
