"use client";

import { WORKFLOW_STATUSES } from "@/lib/types";

export interface Filters {
  platform: string;
  content_type: string;
  status: string;
  priority: string;
  q: string;
}

export const EMPTY_FILTERS: Filters = { platform: "", content_type: "", status: "", priority: "", q: "" };

export default function FilterBar({
  filters,
  onChange,
}: {
  filters: Filters;
  onChange: (filters: Filters) => void;
}) {
  function update<K extends keyof Filters>(key: K, value: Filters[K]) {
    onChange({ ...filters, [key]: value });
  }

  return (
    <div className="mb-4 flex flex-wrap gap-3 rounded-lg border border-slate-200 bg-white p-3">
      <input
        type="text"
        placeholder="Search topic..."
        aria-label="Search topic"
        value={filters.q}
        onChange={(e) => update("q", e.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      />
      <select
        aria-label="Platform"
        value={filters.platform}
        onChange={(e) => update("platform", e.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">All platforms</option>
        <option value="Instagram">Instagram</option>
        <option value="Google Business Profile">Google Business Profile</option>
      </select>
      <select
        aria-label="Content type"
        value={filters.content_type}
        onChange={(e) => update("content_type", e.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">All content types</option>
        <option value="Reel">Reel</option>
        <option value="Carousel">Carousel</option>
        <option value="Story">Story</option>
        <option value="Static Post">Static Post</option>
      </select>
      <select
        aria-label="Status"
        value={filters.status}
        onChange={(e) => update("status", e.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">All statuses</option>
        {WORKFLOW_STATUSES.map((status) => (
          <option key={status} value={status}>
            {status}
          </option>
        ))}
      </select>
      <select
        aria-label="Priority"
        value={filters.priority}
        onChange={(e) => update("priority", e.target.value)}
        className="rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="">All priorities</option>
        <option value="high">High</option>
        <option value="medium">Medium</option>
        <option value="low">Low</option>
      </select>
    </div>
  );
}
