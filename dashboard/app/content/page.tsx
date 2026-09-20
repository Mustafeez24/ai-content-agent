"use client";

import { useEffect, useState } from "react";
import ContentTable from "@/components/ContentTable";
import FilterBar, { EMPTY_FILTERS, type Filters } from "@/components/FilterBar";
import { listContent } from "@/lib/api";
import type { ContentItem } from "@/lib/types";

export default function ContentListPage() {
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [items, setItems] = useState<ContentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listContent({ ...filters, limit: 100 })
      .then((res) => {
        if (!cancelled) {
          setItems(res.items);
          setTotal(res.total);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load content.");
      });
    return () => {
      cancelled = true;
    };
  }, [filters]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Content ({total})</h1>
      <FilterBar filters={filters} onChange={setFilters} />
      {error && <p className="text-sm text-red-600">{error}</p>}
      <ContentTable items={items} />
    </div>
  );
}
