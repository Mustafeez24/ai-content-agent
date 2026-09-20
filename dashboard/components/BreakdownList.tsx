export default function BreakdownList({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...entries.map(([, count]) => count));

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="mb-3 text-sm font-medium text-slate-700">{title}</h3>
      <div className="space-y-2">
        {entries.length === 0 && <p className="text-sm text-slate-400">No data yet.</p>}
        {entries.map(([label, count]) => (
          <div key={label} className="flex items-center gap-2 text-sm">
            <span className="w-36 shrink-0 truncate text-slate-600">{label}</span>
            <div className="h-2 flex-1 rounded bg-slate-100">
              <div className="h-2 rounded bg-sky-500" style={{ width: `${(count / max) * 100}%` }} />
            </div>
            <span className="w-8 text-right font-medium text-slate-700">{count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
