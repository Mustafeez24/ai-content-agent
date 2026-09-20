"use client";

import { useState } from "react";
import { updateStatus } from "@/lib/api";
import type { ContentItem } from "@/lib/types";

// "Reject" has no dedicated workflow_status of its own (the approved status list is
// AI Generated / QA Passed / Pending Review / Changes Requested / Approved /
// Scheduled / Published) - both "Request changes" and "Reject" transition to
// "Changes Requested", distinguished only by the recorded reason.
export default function WorkflowActionBar({
  item,
  onUpdated,
}: {
  item: ContentItem;
  onUpdated: (item: ContentItem) => void;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function act(status: string, reason?: string) {
    setPending(status + (reason ?? ""));
    setError(null);
    try {
      const updated = await updateStatus(item.id, status, reason);
      onUpdated(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status.");
    } finally {
      setPending(null);
    }
  }

  const buttonClass = "rounded border px-3 py-1.5 text-sm font-medium disabled:opacity-50";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        <button
          className={`${buttonClass} border-emerald-300 bg-emerald-50 text-emerald-700`}
          disabled={pending !== null}
          onClick={() => act("Approved")}
        >
          Approve
        </button>
        <button
          className={`${buttonClass} border-amber-300 bg-amber-50 text-amber-700`}
          disabled={pending !== null}
          onClick={() => act("Changes Requested", "Changes requested by reviewer.")}
        >
          Request changes
        </button>
        <button
          className={`${buttonClass} border-red-300 bg-red-50 text-red-700`}
          disabled={pending !== null}
          onClick={() => act("Changes Requested", "Rejected by reviewer.")}
        >
          Reject
        </button>
        <button
          className={`${buttonClass} border-purple-300 bg-purple-50 text-purple-700`}
          disabled={pending !== null}
          onClick={() => act("Scheduled")}
        >
          Mark scheduled
        </button>
        <button
          className={`${buttonClass} border-green-300 bg-green-50 text-green-800`}
          disabled={pending !== null}
          onClick={() => act("Published")}
        >
          Mark published
        </button>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
    </div>
  );
}
