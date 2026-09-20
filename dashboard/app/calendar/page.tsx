"use client";

import { useEffect, useState } from "react";
import CalendarGrid from "@/components/CalendarGrid";
import { getCalendarMonth } from "@/lib/api";
import type { CalendarResponse } from "@/lib/types";

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(month: string, delta: number): string {
  const [year, mon] = month.split("-").map(Number);
  const date = new Date(Date.UTC(year, mon - 1 + delta, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

export default function CalendarPage() {
  const [month, setMonth] = useState(currentMonth());
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    getCalendarMonth(month)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load calendar.");
      });
    return () => {
      cancelled = true;
    };
  }, [month]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Content Calendar</h1>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setMonth((m) => shiftMonth(m, -1))}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            &larr; Prev
          </button>
          <span className="text-sm font-medium">{month}</span>
          <button
            onClick={() => setMonth((m) => shiftMonth(m, 1))}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            Next &rarr;
          </button>
        </div>
      </div>
      {error && <p className="text-sm text-red-600">{error}</p>}
      {data && <CalendarGrid month={data.month} days={data.days} />}
    </div>
  );
}
