"use client";

/** Stage changes shared by the chat's lead strip, the lead page and the board. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Modal } from "@/components/fulfilment";
import { INPUT } from "@/components/pickers";
import { Alert, Button, cx } from "@/components/ui";
import { ApiError, api } from "@/lib/api";
import { LOST_REASON_LABEL, OPEN_STAGES, STAGE_LABEL, type Lead } from "@/lib/leads";

export const leadErrorText = (err: unknown) =>
  err instanceof ApiError ? err.message : "That didn't work. Check your connection and try again.";

/** Invalidate everything that shows leads after a change. */
export function useLeadRefresh() {
  const queryClient = useQueryClient();
  return (lead?: { id: string; conversation_id: string | null }) => {
    void queryClient.invalidateQueries({ queryKey: ["leads"] });
    void queryClient.invalidateQueries({ queryKey: ["lead-followups"] });
    if (lead) {
      void queryClient.invalidateQueries({ queryKey: ["lead", lead.id] });
      if (lead.conversation_id) void queryClient.invalidateQueries({ queryKey: ["conversation", lead.conversation_id] });
    }
    void queryClient.invalidateQueries({ queryKey: ["conversations"] });
  };
}

export function useStageChange(lead: { id: string; version: number; conversation_id: string | null }) {
  const refresh = useLeadRefresh();
  return useMutation({
    mutationFn: (body: { stage: string; lost_reason?: string; lost_note?: string | null }) =>
      api<Lead>("tenant", "POST", `/api/v1/leads/${lead.id}/stage`, { ...body, version: lead.version }),
    onSettled: () => refresh(lead),
  });
}

export function LostDialog({
  lead,
  onClose,
  onDone,
}: {
  lead: { id: string; lead_number: string; version: number; conversation_id: string | null };
  onClose: () => void;
  onDone?: () => void;
}) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const change = useStageChange(lead);
  return (
    <Modal title={`Why was ${lead.lead_number} lost?`} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (reason) change.mutate({ stage: "LOST", lost_reason: reason, lost_note: note.trim() || null }, { onSuccess: () => { onDone?.(); onClose(); } });
        }}
      >
        {change.isError && <Alert tone="error">{leadErrorText(change.error)}</Alert>}
        <div className="mb-4 grid grid-cols-2 gap-2">
          {Object.entries(LOST_REASON_LABEL).map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setReason(value)}
              aria-pressed={reason === value}
              className={cx(
                "rounded-control border px-3 py-2 text-left text-sm",
                reason === value ? "border-primary bg-primary-soft font-medium text-primary" : "border-line text-ink hover:border-line-strong",
              )}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="text-sm">
          <span className="mb-1 block font-medium text-ink">Note (optional)</span>
          <input className={INPUT} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Found it Rs. 500 cheaper" />
        </label>
        <div className="mt-4 flex justify-end gap-3">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="danger" loading={change.isPending} disabled={!reason}>
            Mark lost
          </Button>
        </div>
      </form>
    </Modal>
  );
}

/** Compact stage picker for open leads; "Lost…" opens the reason dialog. */
export function StageSelect({ lead, className }: { lead: Lead; className?: string }) {
  const change = useStageChange(lead);
  const [lost, setLost] = useState(false);
  return (
    <>
      <select
        className={cx("rounded-control border border-line-strong bg-surface py-1.5 pr-8 pl-2.5 text-sm font-medium text-ink focus:border-primary focus:outline-none", className)}
        value={lead.stage}
        disabled={change.isPending}
        aria-label="Stage"
        onChange={(e) => (e.target.value === "LOST" ? setLost(true) : change.mutate({ stage: e.target.value }))}
      >
        {OPEN_STAGES.map((s) => (
          <option key={s} value={s}>
            {STAGE_LABEL[s]}
          </option>
        ))}
        <option value="LOST">Lost…</option>
      </select>
      {change.isError && <span className="text-sm text-danger">{leadErrorText(change.error)}</span>}
      {lost && <LostDialog lead={lead} onClose={() => setLost(false)} />}
    </>
  );
}
