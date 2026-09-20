import type { WorkflowStatus } from "@/lib/types";

const STATUS_STYLES: Record<WorkflowStatus, string> = {
  "AI Generated": "bg-slate-100 text-slate-700",
  "QA Passed": "bg-blue-100 text-blue-700",
  "Pending Review": "bg-amber-100 text-amber-800",
  "Changes Requested": "bg-red-100 text-red-700",
  Approved: "bg-emerald-100 text-emerald-700",
  Scheduled: "bg-purple-100 text-purple-700",
  Published: "bg-green-100 text-green-800",
};

export default function StatusBadge({ status }: { status: WorkflowStatus | string }) {
  const style = STATUS_STYLES[status as WorkflowStatus] ?? "bg-slate-100 text-slate-700";
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${style}`}>
      {status}
    </span>
  );
}
