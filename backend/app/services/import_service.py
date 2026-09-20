"""
Stage 11 import service.

Reads ONLY data/instagram/exports/flyingfish_publish_ready.json - Stage 10's own
QA-gated export. This is deliberate and non-negotiable: that file is the one
artifact in the whole pipeline that is guaranteed to have passed Stage 9's QA gate
(Stage 10 itself refuses to write it otherwise). Nothing here ever reads a raw
Stage 8 content.json, and nothing here re-implements or second-guesses Stage 9's
verdict - it is simply re-checked (qa_status must be "PASS") as a defensive
belt-and-suspenders measure before anything is written to the database.

Re-importing a newer export must never silently overwrite a content item a human
has already moved past "QA Passed" - see STATUSES_PROTECTED_FROM_REIMPORT below.
"""

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.content_item import ContentItem

REQUIRED_TOP_LEVEL = ["metadata", "qa_summary", "qa_warnings", "content_items"]

# The exact 27-field passthrough contract Stage 10 guarantees for every content item.
REQUIRED_ITEM_FIELDS = [
    "day_number", "date", "platform", "content_type", "package_type", "topic", "objective",
    "target_audience", "content_angle", "priority", "hook", "script_scenes", "slides",
    "frames", "interaction_suggestion", "headline", "body", "caption", "cta", "footage_note",
    "evidence_basis", "evidence_type", "source_post_ids", "confidence", "requires_verification",
    "verification_reason", "status",
]

# Any workflow_status beyond the automatic "QA Passed" a fresh import assigns means a
# human has already made a decision on that day's content - never silently clobbered
# by a later re-import.
STATUSES_PROTECTED_FROM_REIMPORT = {
    "Pending Review",
    "Changes Requested",
    "Approved",
    "Scheduled",
    "Published",
}


class ContentImportError(Exception):
    """Raised for any problem with the Stage 10 export that prevents a safe import."""


def load_publish_ready_export(path: Path) -> dict:
    if not path.exists():
        raise ContentImportError(f"Stage 10 export not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ContentImportError(f"Stage 10 export is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise ContentImportError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_TOP_LEVEL if key not in data]
    if missing:
        raise ContentImportError(f"Stage 10 export is missing required section(s): {missing}")

    qa_status = data.get("metadata", {}).get("qa_status")
    if qa_status != "PASS":
        raise ContentImportError(
            f"Stage 10 export's qa_status is {qa_status!r}, not 'PASS' - refusing to import. "
            "The QA gate must never be bypassed."
        )

    items = data.get("content_items")
    if not isinstance(items, list) or not items:
        raise ContentImportError("Stage 10 export contains no content_items - nothing to import.")

    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ContentImportError(f"content_items[{i}] is not an object.")
        missing_fields = [f for f in REQUIRED_ITEM_FIELDS if f not in item]
        if missing_fields:
            raise ContentImportError(f"content_items[{i}] is missing required field(s): {missing_fields}")

    day_numbers = [item["day_number"] for item in items]
    if len(set(day_numbers)) != len(day_numbers):
        raise ContentImportError(f"Stage 10 export has duplicate day_number values: {day_numbers}")

    return data


def _apply_fields(item: ContentItem, source: dict) -> None:
    item.date = source["date"]
    item.platform = source["platform"]
    item.content_type = source["content_type"]
    item.package_type = source["package_type"]
    item.topic = source["topic"]
    item.objective = source["objective"]
    item.target_audience = source["target_audience"]
    item.content_angle = source["content_angle"]
    item.priority = source["priority"]
    item.hook = source["hook"]
    item.script_scenes = source["script_scenes"]
    item.slides = source["slides"]
    item.frames = source["frames"]
    item.interaction_suggestion = source["interaction_suggestion"]
    item.headline = source["headline"]
    item.body = source["body"]
    item.caption = source["caption"]
    item.cta = source["cta"]
    item.footage_note = source["footage_note"]
    item.evidence_basis = source["evidence_basis"]
    item.evidence_type = source["evidence_type"]
    item.source_post_ids = source["source_post_ids"]
    item.confidence = source["confidence"]
    item.requires_verification = source["requires_verification"]
    item.verification_reason = source["verification_reason"]
    item.ai_status = source["status"]


def import_publish_ready_export(db: Session, path: Path) -> dict:
    """Import Stage 10's export into the database.

    For each day_number: if an existing row's workflow_status has already moved
    past "QA Passed" (a human decision), that row is left completely untouched and
    the day is reported under "skipped_protected". Otherwise the row is created (or
    updated in place if it already exists at "AI Generated"/"QA Passed") with
    workflow_status reset to "QA Passed" and repointed at the new pipeline_run.

    Returns a summary dict; never raises for a protected-day skip - that is normal,
    expected behavior, not an error.
    """
    from app.models.pipeline_run import PipelineRun  # local import avoids a circular import at module load time

    data = load_publish_ready_export(path)
    items = data["content_items"]
    metadata = data.get("metadata", {})

    run = PipelineRun(
        qa_status=metadata.get("qa_status", "PASS"),
        days_imported=len(items),
        qa_source_path=str(metadata.get("qa_source", "")),
        content_source_path=str(metadata.get("content_source", "")),
        qa_warnings=data.get("qa_warnings", []),
    )
    db.add(run)
    db.flush()  # assign run.id without committing yet

    imported_or_updated = 0
    skipped_protected = []

    for source in items:
        existing = db.query(ContentItem).filter(ContentItem.day_number == source["day_number"]).one_or_none()

        if existing is not None and existing.workflow_status in STATUSES_PROTECTED_FROM_REIMPORT:
            skipped_protected.append({"day_number": source["day_number"], "existing_status": existing.workflow_status})
            continue

        if existing is not None:
            existing.pipeline_run_id = run.id
            _apply_fields(existing, source)
            existing.workflow_status = "QA Passed"
        else:
            new_item = ContentItem(pipeline_run_id=run.id, day_number=source["day_number"], workflow_status="QA Passed")
            _apply_fields(new_item, source)
            db.add(new_item)

        imported_or_updated += 1

    db.commit()

    return {
        "pipeline_run_id": str(run.id),
        "days_in_export": len(items),
        "imported_or_updated": imported_or_updated,
        "skipped_protected": skipped_protected,
    }
