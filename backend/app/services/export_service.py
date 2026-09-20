"""
Stage 11 export service - builds downloadable JSON/CSV/Markdown from the live
database, reusing Stage 10's own formatting functions directly (imported from
scripts/content_export.py) rather than re-implementing CSV/Markdown formatting a
second time. Only the "where the data comes from" (database rows instead of a
content.json file) differs; the formatting logic is identical.
"""

import csv
import io
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import content_export as ce  # noqa: E402  (path must be set up first)

SUPPORTED_FORMATS = ("json", "csv", "markdown")


def _item_to_dict(item) -> dict:
    """Reconstruct the exact 27-field shape content_export.py's formatting
    functions expect, from a database ContentItem row."""
    return {
        "day_number": item.day_number,
        "date": item.date.isoformat() if hasattr(item.date, "isoformat") else item.date,
        "platform": item.platform,
        "content_type": item.content_type,
        "package_type": item.package_type,
        "topic": item.topic,
        "objective": item.objective,
        "target_audience": item.target_audience,
        "content_angle": item.content_angle,
        "priority": item.priority,
        "hook": item.hook,
        "script_scenes": item.script_scenes,
        "slides": item.slides,
        "frames": item.frames,
        "interaction_suggestion": item.interaction_suggestion,
        "headline": item.headline,
        "body": item.body,
        "caption": item.caption,
        "cta": item.cta,
        "footage_note": item.footage_note,
        "evidence_basis": item.evidence_basis,
        "evidence_type": item.evidence_type,
        "source_post_ids": item.source_post_ids,
        "confidence": item.confidence,
        "requires_verification": item.requires_verification,
        "verification_reason": item.verification_reason,
        "status": item.ai_status,
    }


def _latest_pipeline_run(content_items):
    latest = None
    for item in content_items:
        run = item.pipeline_run
        if run is not None and (latest is None or run.imported_at > latest.imported_at):
            latest = run
    return latest


def build_export(content_items: list, export_format: str) -> tuple:
    """Returns (content, media_type, filename) for the requested format."""
    if export_format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported export format: {export_format!r}")

    ordered = sorted(content_items, key=lambda it: it.day_number)
    item_dicts = [_item_to_dict(it) for it in ordered]

    latest_run = _latest_pipeline_run(ordered)
    qa_report = {
        "status": latest_run.qa_status if latest_run else "PASS",
        "summary": {
            "hard_failure_count": 0,
            "warning_count": len(latest_run.qa_warnings) if latest_run else 0,
        },
        "warnings": latest_run.qa_warnings if latest_run else [],
    }

    if export_format == "json":
        data = ce.build_json_export(item_dicts, qa_report, "database", "database", [])
        return json.dumps(data, ensure_ascii=False, indent=2), "application/json", ce.JSON_OUTPUT_FILENAME

    if export_format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(ce.CSV_COLUMNS)
        for row in item_dicts:
            writer.writerow([ce._format_csv_value(field, row.get(field)) for field in ce.CSV_COLUMNS])
        return buf.getvalue(), "text/csv", ce.CSV_OUTPUT_FILENAME

    text = ce.build_markdown_export(item_dicts, qa_report, [])
    return text, "text/markdown", ce.MARKDOWN_OUTPUT_FILENAME
