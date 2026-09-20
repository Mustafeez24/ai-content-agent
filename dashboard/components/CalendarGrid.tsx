import Link from "next/link";
import type { CalendarDayEntry } from "@/lib/types";

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export default function CalendarGrid({ month, days }: { month: string; days: Record<string, CalendarDayEntry[]> }) {
  const [year, mon] = month.split("-").map(Number);
  const firstOfMonth = new Date(Date.UTC(year, mon - 1, 1));
  const daysInMonth = new Date(Date.UTC(year, mon, 0)).getUTCDate();
  const startWeekday = firstOfMonth.getUTCDay();

  const cells: (number | null)[] = [
    ...Array(startWeekday).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];

  return (
    <div className="grid grid-cols-7 gap-2">
      {WEEKDAY_LABELS.map((label) => (
        <div key={label} className="text-center text-xs font-medium text-slate-500">
          {label}
        </div>
      ))}
      {cells.map((day, index) => {
        if (day === null) return <div key={`empty-${index}`} />;
        const dateKey = `${month}-${String(day).padStart(2, "0")}`;
        const entries = days[dateKey] ?? [];
        return (
          <div key={dateKey} className="min-h-[90px] rounded border border-slate-200 bg-white p-1.5 text-xs">
            <div className="mb-1 font-medium text-slate-500">{day}</div>
            <div className="space-y-1">
              {entries.map((entry) => (
                <Link
                  key={entry.id}
                  href={`/content/${entry.id}`}
                  className="block truncate rounded bg-sky-50 px-1 py-0.5 text-sky-700 hover:bg-sky-100"
                  title={entry.topic}
                >
                  {entry.content_type}: {entry.topic}
                </Link>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
