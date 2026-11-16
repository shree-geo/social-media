"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";

import { useMe } from "@/components/tenant-shell";
import { Alert, Checkbox, EmptyState, PageHeader, Panel, Spinner } from "@/components/ui";
import { ApiError, api } from "@/lib/api";

type BusinessSettings = { orders_need_lead: boolean };

/** Business rules an owner or admin can change. */
export function SettingsView() {
  const me = useMe();
  const queryClient = useQueryClient();
  const allowed = me.data?.permissions.includes("settings.manage") ?? false;
  const settings = useQuery({
    queryKey: ["business-settings"],
    queryFn: () => api<BusinessSettings>("tenant", "GET", "/api/v1/settings"),
    enabled: allowed,
  });
  const save = useMutation({
    mutationFn: (patch: Partial<BusinessSettings>) => api<BusinessSettings>("tenant", "PATCH", "/api/v1/settings", patch),
    onSuccess: (updated) => {
      queryClient.setQueryData(["business-settings"], updated);
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  if (me.data && !allowed) {
    return (
      <main className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-8 sm:py-8">
        <EmptyState icon={Lock} title="Only the owner or an admin can change settings" />
      </main>
    );
  }
  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader title="Settings" description="Rules for how your team works." />
      {!settings.data ? (
        settings.isError ? <Alert tone="error">Couldn&apos;t load settings. Try again.</Alert> : <Spinner />
      ) : (
        <Panel title="Orders from chats">
          <Checkbox
            label="WhatsApp and Messenger orders start as a lead"
            hint="Staff mark the chat as a lead, talk to the customer, then convert the lead to an order once it's confirmed. Turn off to allow creating an order straight from a chat. Phone and walk-in orders are not affected."
            checked={settings.data.orders_need_lead}
            disabled={save.isPending}
            onChange={(e) => save.mutate({ orders_need_lead: e.target.checked })}
          />
          {save.isError && (
            <Alert tone="error">{save.error instanceof ApiError ? save.error.message : "Couldn't save. Try again."}</Alert>
          )}
        </Panel>
      )}
    </main>
  );
}
