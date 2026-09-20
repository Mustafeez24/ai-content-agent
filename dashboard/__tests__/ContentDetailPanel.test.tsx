import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ContentDetailPanel from "@/components/ContentDetailPanel";
import type { ContentItem } from "@/lib/types";

function makeItem(overrides: Partial<ContentItem> = {}): ContentItem {
  return {
    id: "1",
    day_number: 1,
    date: "2026-01-01",
    platform: "Instagram",
    content_type: "Reel",
    package_type: "reel",
    topic: "A topic",
    objective: "Educational",
    target_audience: "Beginners",
    content_angle: "Simple",
    priority: "medium",
    hook: "A hook",
    script_scenes: ["Scene one"],
    slides: [],
    frames: [],
    interaction_suggestion: "",
    headline: "",
    body: "",
    caption: "A caption",
    cta: "A CTA",
    footage_note: "Use existing footage",
    evidence_basis: "Evidence text",
    evidence_type: "interpretation",
    source_post_ids: ["POST_1"],
    confidence: "low",
    requires_verification: false,
    verification_reason: null,
    ai_status: "drafted",
    workflow_status: "QA Passed",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("ContentDetailPanel", () => {
  it("renders Reel fields (hook + scenes)", () => {
    render(<ContentDetailPanel item={makeItem()} />);
    expect(screen.getByText("A hook")).toBeInTheDocument();
    expect(screen.getByText("Scene one")).toBeInTheDocument();
  });

  it("renders Carousel fields (slides)", () => {
    render(<ContentDetailPanel item={makeItem({ package_type: "carousel", slides: ["Slide one", "Slide two"] })} />);
    expect(screen.getByText("Slide one")).toBeInTheDocument();
    expect(screen.getByText("Slide two")).toBeInTheDocument();
  });

  it("renders Story fields (frames)", () => {
    render(<ContentDetailPanel item={makeItem({ package_type: "story", frames: ["Frame one"] })} />);
    expect(screen.getByText("Frame one")).toBeInTheDocument();
  });

  it("renders Static/GBP fields (headline + body)", () => {
    render(
      <ContentDetailPanel item={makeItem({ package_type: "static", headline: "A headline", body: "Body copy" })} />
    );
    expect(screen.getByText("A headline")).toBeInTheDocument();
    expect(screen.getByText("Body copy")).toBeInTheDocument();
  });

  it("shows verification status and reason", () => {
    render(<ContentDetailPanel item={makeItem({ requires_verification: true, verification_reason: "Needs check" })} />);
    expect(screen.getByText(/Requires verification: Yes/)).toBeInTheDocument();
    expect(screen.getByText(/Needs check/)).toBeInTheDocument();
  });

  it("shows source post ids", () => {
    render(<ContentDetailPanel item={makeItem({ source_post_ids: ["POST_1", "POST_2"] })} />);
    expect(screen.getByText(/POST_1, POST_2/)).toBeInTheDocument();
  });
});
