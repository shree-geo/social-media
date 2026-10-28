"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, Plug, Unplug } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, Avatar, Button, ChannelTag, EmptyState, PageHeader, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import type { ChannelCard, ChannelsResponse } from "@/lib/channels";
import { formatTime } from "@/lib/inbox";

const HEALTH = {
  healthy: { label: "Working", icon: CheckCircle2, className: "text-success" },
  pending: { label: "Waiting for Meta", icon: Clock, className: "text-attention-ink" },
  action_needed: { label: "Needs your attention", icon: AlertTriangle, className: "text-danger" },
  disconnected: { label: "Disconnected", icon: Unplug, className: "text-ink-subtle" },
} as const;

function DisconnectDialog({ channel, onClose }: { channel: ChannelCard; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const name = channel.name ?? "this channel";
  const disconnect = useMutation({
    mutationFn: () => api("tenant", "POST", `/api/v1/channels/${channel.id}/disconnect`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channels"] });
      onClose();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : "Couldn't disconnect. Try again."),
  });
  return (
    <div className="fixed inset-0 z-30 grid place-items-center bg-ink/40 p-4" role="dialog" aria-modal="true" aria-labelledby="disconnect-title">
      <div className="w-full max-w-md rounded-panel bg-surface p-6 shadow-xl">
        <h2 id="disconnect-title" className="text-lg font-semibold text-ink">
          Disconnect {name}?
        </h2>
        <p className="mt-2 text-sm text-ink-muted">
          New messages from this Page will stop arriving here. Your existing chats, customers and orders stay. You can
          connect it again any time.
        </p>
        {error && (
          <div className="mt-4">
            <Alert tone="error">{error}</Alert>
          </div>
        )}
        <label htmlFor="confirm-name" className="mt-4 mb-1.5 block text-sm font-medium text-ink">
          Type <strong>{name}</strong> to confirm
        </label>
        <input
          id="confirm-name"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          autoComplete="off"
          className="w-full rounded-control border border-line-strong bg-surface px-3 py-2.5 text-base text-ink focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
        />
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Keep connected
          </Button>
          <Button variant="danger" disabled={typed.trim() !== name} loading={disconnect.isPending} onClick={() => disconnect.mutate()}>
            Disconnect
          </Button>
        </div>
      </div>
    </div>
  );
}

function ChannelRow({ channel, onDisconnect }: { channel: ChannelCard; onDisconnect: () => void }) {
  const health = HEALTH[channel.health_status] ?? HEALTH.healthy;
  const Icon = health.icon;
  const connected = channel.status === "connected";
  return (
    <li className="flex flex-wrap items-center gap-4 border-b border-line px-5 py-4 last:border-b-0">
      <Avatar name={channel.name ?? "?"} channel={channel.provider} size="lg" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-semibold text-ink">{channel.name ?? channel.display_phone}</p>
        <ChannelTag channel={channel.provider} />
        <p className={cx("mt-1 flex items-center gap-1.5 text-sm", health.className)}>
          <Icon className="size-4" aria-hidden />
          {health.label}
        </p>
        {channel.health_reason && channel.health_status !== "healthy" && (
          <p className="mt-0.5 text-sm text-ink-muted">{channel.health_reason}</p>
        )}
      </div>
      {connected && (
        <dl className="tabular grid grid-cols-2 gap-x-6 text-sm">
          <dt className="text-ink-subtle">Messages today</dt>
          <dt className="text-ink-subtle">Last message</dt>
          <dd className="font-medium text-ink">{channel.messages_today}</dd>
          <dd className="font-medium text-ink">{channel.last_webhook_at ? formatTime(channel.last_webhook_at) : "None yet"}</dd>
        </dl>
      )}
      <div className="flex gap-2">
        {(channel.health_status === "action_needed" || !connected) && channel.provider === "messenger" && (
          <Link
            href="/channels/connect/messenger"
            className="inline-flex min-h-9 items-center rounded-control bg-primary px-3 text-sm font-medium text-on-primary hover:bg-primary-hover"
          >
            Reconnect
          </Link>
        )}
        {connected && (
          <Button size="sm" variant="ghost" onClick={onDisconnect}>
            Disconnect
          </Button>
        )}
      </div>
    </li>
  );
}

export function ChannelsView() {
  const [disconnecting, setDisconnecting] = useState<ChannelCard | null>(null);
  const channels = useQuery({
    queryKey: ["channels"],
    queryFn: () => api<ChannelsResponse>("tenant", "GET", "/api/v1/channels"),
  });
  const data = channels.data;
  const atLimit = data?.messenger_limit != null && data.messenger_used >= data.messenger_limit;

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-6 sm:px-8 sm:py-8">
      <PageHeader title="Channels" description="Where your customers can message you. Messages from every channel arrive in one inbox." />

      {channels.error && <Alert tone="error">We couldn&apos;t load your channels. Refresh the page to try again.</Alert>}

      {data && (
        <>
          {data.items.length === 0 ? (
            <div className="mb-6 rounded-panel border border-line bg-surface">
              <EmptyState icon={Plug} title="No channels connected yet">
                Connect your Facebook Page so customer messages arrive here. WhatsApp is coming next.
              </EmptyState>
            </div>
          ) : (
            <ul className="mb-6 overflow-hidden rounded-panel border border-line bg-surface">
              {data.items.map((c) => (
                <ChannelRow key={c.id} channel={c} onDisconnect={() => setDisconnecting(c)} />
              ))}
            </ul>
          )}

          <h2 className="mb-3 text-lg font-semibold text-ink">Add a channel</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-panel border border-line bg-surface p-5">
              <ChannelTag channel="messenger" />
              <p className="mt-1 font-semibold text-ink">Facebook Page</p>
              <p className="mt-1 text-sm text-ink-muted">About 5 minutes. You need the Facebook account that has full control of your Page.</p>
              {!data.messenger_available ? (
                <p className="mt-4 text-sm text-ink-subtle">Available once our Facebook app is approved.</p>
              ) : atLimit ? (
                <p className="mt-4 text-sm text-attention-ink">Your package allows {data.messenger_limit} Facebook Page(s). Ask us about upgrading.</p>
              ) : (
                <Link
                  href="/channels/connect/messenger"
                  className="mt-4 inline-flex min-h-11 items-center rounded-control bg-primary px-4 font-medium text-on-primary hover:bg-primary-hover"
                >
                  Connect Facebook Page
                </Link>
              )}
            </div>
            <div className="rounded-panel border border-dashed border-line-strong p-5">
              <ChannelTag channel="whatsapp" />
              <p className="mt-1 font-semibold text-ink">WhatsApp</p>
              <p className="mt-1 text-sm text-ink-muted">Use a new number or keep your WhatsApp Business app.</p>
              <p className="mt-4 text-sm text-ink-subtle">Coming next.</p>
            </div>
          </div>
        </>
      )}

      {disconnecting && <DisconnectDialog channel={disconnecting} onClose={() => setDisconnecting(null)} />}
    </main>
  );
}
