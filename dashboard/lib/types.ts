export type WorkflowStatus =
  | "AI Generated"
  | "QA Passed"
  | "Pending Review"
  | "Changes Requested"
  | "Approved"
  | "Scheduled"
  | "Published";

export const WORKFLOW_STATUSES: WorkflowStatus[] = [
  "AI Generated",
  "QA Passed",
  "Pending Review",
  "Changes Requested",
  "Approved",
  "Scheduled",
  "Published",
];

export type PackageType = "reel" | "carousel" | "story" | "static" | "gbp";

export interface ContentItem {
  id: string;
  day_number: number;
  date: string;
  platform: string;
  content_type: string;
  package_type: PackageType;
  topic: string;
  objective: string;
  target_audience: string;
  content_angle: string;
  priority: string;
  hook: string;
  script_scenes: string[];
  slides: string[];
  frames: string[];
  interaction_suggestion: string;
  headline: string;
  body: string;
  caption: string;
  cta: string;
  footage_note: string;
  evidence_basis: string;
  evidence_type: string;
  source_post_ids: string[];
  confidence: string;
  requires_verification: boolean;
  verification_reason: string | null;
  ai_status: string;
  workflow_status: WorkflowStatus;
  created_at: string;
  updated_at: string;
}

export interface ContentListResponse {
  items: ContentItem[];
  total: number;
  page: number;
  limit: number;
}

export interface DashboardSummary {
  total_content_items: number;
  ai_generated: number;
  qa_passed: number;
  pending_review: number;
  changes_requested: number;
  approved: number;
  scheduled: number;
  published: number;
  qa_warnings: number;
  platform_breakdown: Record<string, number>;
  content_type_breakdown: Record<string, number>;
  latest_pipeline_run_id: string | null;
}

export interface CalendarDayEntry {
  id: string;
  day_number: number;
  platform: string;
  content_type: string;
  package_type: string;
  topic: string;
  priority: string;
  workflow_status: WorkflowStatus;
}

export interface CalendarResponse {
  month: string;
  days: Record<string, CalendarDayEntry[]>;
}

export interface Note {
  id: string;
  content_item_id: string;
  author: string;
  note: string;
  created_at: string;
}
