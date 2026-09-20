import type { ContentItem } from "@/lib/types";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="text-slate-800">{value}</div>
    </div>
  );
}

function Section({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <p className="whitespace-pre-wrap text-slate-800">{text}</p>
    </div>
  );
}

function ListSection({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div className="mb-1 text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <ol className="list-decimal space-y-1 pl-5 text-slate-800">
        {items.map((entry, index) => (
          <li key={index}>{entry}</li>
        ))}
      </ol>
    </div>
  );
}

export default function ContentDetailPanel({ item }: { item: ContentItem }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
        <Field label="Date" value={item.date} />
        <Field label="Platform" value={item.platform} />
        <Field label="Content type" value={item.content_type} />
        <Field label="Priority" value={item.priority} />
        <Field label="Objective" value={item.objective} />
        <Field label="Target audience" value={item.target_audience} />
      </div>

      {item.package_type === "reel" && (
        <>
          <Section label="Hook" text={item.hook} />
          <ListSection label="Script / Scenes" items={item.script_scenes} />
          <Section label="Caption" text={item.caption} />
        </>
      )}
      {item.package_type === "carousel" && (
        <>
          <Section label="Hook (Slide 1)" text={item.hook} />
          <ListSection label="Slides" items={item.slides} />
          <Section label="Caption" text={item.caption} />
        </>
      )}
      {item.package_type === "story" && (
        <>
          <ListSection label="Frames" items={item.frames} />
          {item.interaction_suggestion && <Section label="Interaction suggestion" text={item.interaction_suggestion} />}
        </>
      )}
      {(item.package_type === "static" || item.package_type === "gbp") && (
        <>
          <Section label="Headline" text={item.headline} />
          <Section label="Body" text={item.body} />
          {item.package_type === "static" && item.caption && <Section label="Caption" text={item.caption} />}
        </>
      )}

      <Section label="CTA" text={item.cta} />
      {item.footage_note && <Section label="Footage note" text={item.footage_note} />}

      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
        <div className="mb-1 font-medium text-slate-700">Evidence & verification</div>
        <p className="text-slate-600">{item.evidence_basis}</p>
        <p className="mt-1 text-slate-500">
          Type: {item.evidence_type} · Confidence: {item.confidence} · Sources:{" "}
          {item.source_post_ids.join(", ") || "none"}
        </p>
        <p className="mt-1 font-medium text-slate-700">
          Requires verification: {item.requires_verification ? "Yes" : "No"}
          {item.verification_reason ? ` — ${item.verification_reason}` : ""}
        </p>
      </div>
    </div>
  );
}
