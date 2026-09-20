import type { CalendarResponse, ContentItem, ContentListResponse, DashboardSummary, Note } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`Request to ${path} failed with status ${res.status}`);
  }
  return (await res.json()) as T;
}

export function getDashboardSummary(): Promise<DashboardSummary> {
  return getJson<DashboardSummary>("/api/dashboard/summary");
}

export interface ContentListParams {
  date_from?: string;
  date_to?: string;
  platform?: string;
  content_type?: string;
  status?: string;
  priority?: string;
  q?: string;
  page?: number;
  limit?: number;
}

export function listContent(params: ContentListParams = {}): Promise<ContentListResponse> {
  const search = new URLSearchParams();
  (Object.entries(params) as [string, string | number | undefined][]).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  const query = search.toString();
  return getJson<ContentListResponse>(`/api/content${query ? `?${query}` : ""}`);
}

export function getContent(id: string): Promise<ContentItem> {
  return getJson<ContentItem>(`/api/content/${id}`);
}

export function listNotes(id: string): Promise<Note[]> {
  return getJson<Note[]>(`/api/content/${id}/notes`);
}

export function getCalendarMonth(month: string): Promise<CalendarResponse> {
  return getJson<CalendarResponse>(`/api/calendar?month=${month}`);
}

export function exportUrl(format: "json" | "csv" | "markdown"): string {
  return `${API_BASE_URL}/api/exports/${format}`;
}

// --- Writes go through this app's own server-side proxy routes (app/api/proxy/**),
// which are the only place the shared secret is ever read. The browser never sees
// CONTENT_AGENT_API_SECRET - see .env.local.example. ---

async function postOrPatchJson<T>(path: string, method: "PATCH" | "POST", body: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `Request failed with status ${res.status}`);
  }
  return (await res.json()) as T;
}

export function updateStatus(id: string, status: string, reason?: string): Promise<ContentItem> {
  return postOrPatchJson<ContentItem>(`/api/proxy/content/${id}/status`, "PATCH", { status, reason });
}

export function addNote(id: string, note: string, author?: string): Promise<Note> {
  return postOrPatchJson<Note>(`/api/proxy/content/${id}/notes`, "POST", { note, author });
}
