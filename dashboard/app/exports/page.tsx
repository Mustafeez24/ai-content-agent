import { exportUrl } from "@/lib/api";

export default function ExportsPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Exports</h1>
      <p className="text-sm text-slate-600">Download the current live content as a publishing-ready file.</p>
      <div className="flex gap-3">
        <a
          href={exportUrl("json")}
          className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Download JSON
        </a>
        <a
          href={exportUrl("csv")}
          className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Download CSV
        </a>
        <a
          href={exportUrl("markdown")}
          className="rounded border border-slate-300 bg-white px-3 py-2 text-sm font-medium hover:bg-slate-50"
        >
          Download Markdown
        </a>
      </div>
    </div>
  );
}
