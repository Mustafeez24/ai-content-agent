"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import ContentDetailPanel from "@/components/ContentDetailPanel";
import NotesThread from "@/components/NotesThread";
import StatusBadge from "@/components/StatusBadge";
import WorkflowActionBar from "@/components/WorkflowActionBar";
import { getContent, listNotes } from "@/lib/api";
import type { ContentItem, Note } from "@/lib/types";

export default function ContentDetailPage() {
  const params = useParams<{ id: string }>();
  const [item, setItem] = useState<ContentItem | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getContent(params.id), listNotes(params.id)])
      .then(([contentItem, noteList]) => {
        if (!cancelled) {
          setItem(contentItem);
          setNotes(noteList);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load content.");
      });
    return () => {
      cancelled = true;
    };
  }, [params.id]);

  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!item) return <p className="text-sm text-slate-500">Loading...</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">
            Day {item.day_number}: {item.topic}
          </h1>
          <p className="text-sm text-slate-500">
            {item.date} · {item.platform} · {item.content_type}
          </p>
        </div>
        <StatusBadge status={item.workflow_status} />
      </div>

      <WorkflowActionBar item={item} onUpdated={setItem} />
      <ContentDetailPanel item={item} />

      <div>
        <h2 className="mb-2 text-sm font-semibold text-slate-700">Internal notes</h2>
        <NotesThread contentId={item.id} initialNotes={notes} />
      </div>
    </div>
  );
}
