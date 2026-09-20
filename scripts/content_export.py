"""
Content Export / Publishing-Ready Delivery Layer for FlyingFish Scuba School (Stage 10).

Reads the Stage 9 QA report (data/instagram/flyingfish_content_qa.json) and the Stage 8
content production package (data/instagram/flyingfish_content.json) and produces clean,
publishing-ready exports - JSON, CSV, and Markdown - for a human content team (or another
tool) to work from. This makes NO Anthropic API calls, writes to NO source files, and
performs NO content correction, paraphrasing, or fact generation of any kind - it only
reformats already-validated data for delivery.

THE QA GATE IS NEVER BYPASSED: export is refused entirely unless the Stage 9 QA report's
status is exactly "PASS" AND its hard_failures list is empty. On any other outcome (FAIL,
missing report, malformed report, or an internally inconsistent one), Stage 10 writes no
export files at all and returns a non-zero exit code with a clear explanation.

Stage 9 already performed the authoritative calendar<->content cross-validation - Stage 10
does not repeat that job. An OPTIONAL Stage 7 calendar file may be supplied purely for a
best-effort, informational spot-check (day coverage / package_type agreement); any mismatch
it finds is reported as a note, never a failure - it can never override the Stage 9 verdict.

Usage:
    source venv/bin/activate
    python scripts/content_export.py
    python scripts/content_export.py --formats json,csv
    python scripts/content_export.py --dry-run     # validate + report, no files written
"""

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse Stage 8/9's own loaders and vocabulary directly rather than re-implementing them -
# the same structural validation Stage 9 already applies to the content package, and the
# same DataError type both stages already raise.
from content_qa import DataError, REQUIRED_CONTENT_ITEM_FIELDS, load_content_package
from content_generator import load_calendar as load_stage7_calendar, package_type_for_item

DEFAULT_QA_INPUT_PATH = Path("data/instagram/flyingfish_content_qa.json")
DEFAULT_CONTENT_INPUT_PATH = Path("data/instagram/flyingfish_content.json")
DEFAULT_CALENDAR_INPUT_PATH = Path("data/instagram/flyingfish_content_calendar.json")
DEFAULT_OUTPUT_DIR = Path("data/instagram/exports")

JSON_OUTPUT_FILENAME = "flyingfish_publish_ready.json"
CSV_OUTPUT_FILENAME = "flyingfish_content_calendar.csv"
MARKDOWN_OUTPUT_FILENAME = "flyingfish_content_calendar.md"

SUPPORTED_FORMATS = ("json", "csv", "markdown")

# The exact 27 fields the content team asked to preserve - imported from content_qa.py's
# own REQUIRED_CONTENT_ITEM_FIELDS (schema order) so this list can never silently drift
# from what Stage 9 already treats as the content item's required shape.
CONTENT_ITEM_FIELDS = REQUIRED_CONTENT_ITEM_FIELDS

# CSV column order is deliberately different from CONTENT_ITEM_FIELDS - optimized for a
# content team scanning a spreadsheet (date/platform/type/priority/copy/CTA/footage up
# front) rather than the JSON schema's field order. Every field is still included -
# nothing is dropped, only reordered for presentation.
CSV_COLUMNS = [
    "day_number", "date", "platform", "content_type", "package_type", "priority", "topic",
    "hook", "headline", "body", "caption", "cta", "script_scenes", "slides", "frames",
    "interaction_suggestion", "footage_note", "evidence_type", "confidence", "source_post_ids",
    "requires_verification", "verification_reason", "evidence_basis", "objective",
    "target_audience", "content_angle", "status",
]

REQUIRED_QA_TOP_LEVEL = ["metadata", "status", "summary", "hard_failures", "warnings"]


def load_qa_report(path: Path) -> dict:
    """Load and structurally validate the Stage 9 QA report - no loader exists yet since
    Stage 9 only ever wrote this file, never read it back."""
    if not path.exists():
        raise DataError(f"Stage 9 QA report not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Stage 9 QA report is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise DataError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_QA_TOP_LEVEL if key not in data]
    if missing:
        raise DataError(f"Stage 9 QA report is missing required field(s): {missing}")

    if data["status"] not in ("PASS", "FAIL"):
        raise DataError(f"Stage 9 QA report has an unrecognized status: {data['status']!r} (expected 'PASS' or 'FAIL')")
    if not isinstance(data["hard_failures"], list) or not isinstance(data["warnings"], list):
        raise DataError("Stage 9 QA report's hard_failures/warnings fields must both be lists.")

    return data


def verify_qa_gate(qa_report: dict) -> None:
    """The publishing gate: status must be exactly PASS AND hard_failures must be empty.
    Checking both (rather than trusting the status string alone) defends against a
    corrupted or hand-edited QA report where the two disagree."""
    status = qa_report.get("status")
    hard_failures = qa_report.get("hard_failures") or []
    if status != "PASS" or hard_failures:
        raise DataError(
            f"QA gate did not pass - status={status!r}, hard_failure_count={len(hard_failures)}. "
            "Publishing export refused. Resolve the Stage 9 QA failures and re-run Stage 9 before exporting."
        )


def spot_check_calendar(calendar_path, explicit: bool, content_items: list) -> list:
    """Best-effort, informational only - NEVER raises, NEVER blocks export, and never
    overrides the Stage 9 verdict (which already performed the authoritative calendar<->
    content cross-validation). Returns a list of note strings, possibly empty."""
    if not calendar_path.exists():
        if explicit:
            return [f"Calendar spot-check skipped: {calendar_path} not found."]
        return []

    try:
        calendar = load_stage7_calendar(calendar_path)
    except DataError as e:
        return [f"Calendar spot-check skipped: could not load {calendar_path}: {e}"]

    notes = []
    calendar_by_day = {item["day_number"]: item for item in calendar["calendar_items"]}
    content_by_day = {item["day_number"]: item for item in content_items}
    calendar_days = set(calendar_by_day)
    content_days = set(content_by_day)

    if calendar_days != content_days:
        missing = sorted(calendar_days - content_days)
        extra = sorted(content_days - calendar_days)
        notes.append(
            f"Calendar spot-check: day coverage differs from the content package (missing from "
            f"content: {missing}, not in calendar: {extra}). Stage 9's QA PASS remains "
            "authoritative; this is informational only."
        )

    mismatched_package_types = []
    for day in sorted(calendar_days & content_days):
        expected_pt = package_type_for_item(calendar_by_day[day])
        actual_pt = content_by_day[day].get("package_type")
        if expected_pt != actual_pt:
            mismatched_package_types.append(day)
    if mismatched_package_types:
        notes.append(
            f"Calendar spot-check: package_type differs from the calendar on day(s) "
            f"{mismatched_package_types}. Stage 9's QA PASS remains authoritative; this is "
            "informational only."
        )

    return notes


def _export_item(item: dict) -> dict:
    """Exact passthrough of the 27 preserved fields, in schema order, as a new dict - never
    mutates the source item and never adds/drops/renames a field."""
    return {field: item.get(field) for field in CONTENT_ITEM_FIELDS}


def build_json_export(content_items: list, qa_report: dict, content_source, qa_source, export_notes: list) -> dict:
    """QA information lives entirely in metadata/qa_summary/qa_warnings/export_notes -
    content_items itself is a pure, unmodified passthrough of the 27 content fields."""
    return {
        "metadata": {
            "agent": "content_export",
            "qa_source": str(qa_source),
            "content_source": str(content_source),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "qa_status": qa_report.get("status"),
            "days_exported": len(content_items),
        },
        "qa_summary": qa_report.get("summary", {}),
        "qa_warnings": list(qa_report.get("warnings", [])),
        "export_notes": list(export_notes),
        "content_items": [_export_item(item) for item in content_items],
    }


def _format_csv_value(field: str, value) -> str:
    """Formatting is presentation-only - this never touches the underlying JSON source,
    only how a value is rendered as one CSV cell."""
    if field in ("script_scenes", "slides", "frames"):
        return "\n".join(f"{i}. {v}" for i, v in enumerate(value or [], start=1))
    if field == "source_post_ids":
        return ", ".join(value or [])
    if value is None:
        return ""
    return str(value)


def write_csv_export(content_items: list, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for item in content_items:
            writer.writerow([_format_csv_value(field, item.get(field)) for field in CSV_COLUMNS])


_PACKAGE_TYPE_LABELS = {
    "reel": "Reel", "carousel": "Carousel", "story": "Story", "static": "Static Post", "gbp": "Google Business Profile",
}


def _markdown_item_section(item: dict) -> list:
    lines = [f"## Day {item['day_number']} — {item['date']} — {item['platform']} ({item['content_type']})", ""]
    lines.append(f"**Topic:** {item['topic']}  ")
    lines.append(f"**Priority:** {item['priority']}  ")
    lines.append(f"**Package type:** {_PACKAGE_TYPE_LABELS.get(item['package_type'], item['package_type'])}")
    lines.append("")

    package_type = item.get("package_type")
    if package_type == "reel":
        lines.append(f"**Hook:** {item['hook']}")
        lines.append("")
        lines.append("**Script:**")
        for i, scene in enumerate(item.get("script_scenes") or [], start=1):
            lines.append(f"{i}. {scene}")
        lines.append("")
        lines.append(f"**Caption:** {item['caption']}")
    elif package_type == "carousel":
        lines.append(f"**Hook (Slide 1):** {item['hook']}")
        lines.append("")
        lines.append("**Slides:**")
        for i, slide in enumerate(item.get("slides") or [], start=1):
            lines.append(f"{i}. {slide}")
        lines.append("")
        lines.append(f"**Caption:** {item['caption']}")
    elif package_type == "story":
        lines.append("**Frames:**")
        for i, frame in enumerate(item.get("frames") or [], start=1):
            lines.append(f"{i}. {frame}")
        if item.get("interaction_suggestion"):
            lines.append("")
            lines.append(f"**Interaction suggestion:** {item['interaction_suggestion']}")
    elif package_type in ("static", "gbp"):
        lines.append(f"**Headline:** {item['headline']}")
        lines.append("")
        lines.append(f"**Body:** {item['body']}")
        if package_type == "static" and item.get("caption"):
            lines.append("")
            lines.append(f"**Caption:** {item['caption']}")

    lines.append("")
    lines.append(f"**CTA:** {item['cta']}")
    if item.get("footage_note"):
        lines.append("")
        lines.append(f"**Footage note:** {item['footage_note']}")

    lines.append("")
    source_ids = ", ".join(item.get("source_post_ids") or []) or "none"
    lines.append(f"**Evidence:** {item['evidence_type']} (confidence: {item['confidence']}) — sources: {source_ids}")
    verification_line = f"**Requires verification:** {'Yes' if item.get('requires_verification') else 'No'}"
    if item.get("verification_reason"):
        verification_line += f" — {item['verification_reason']}"
    lines.append(verification_line)
    lines.append("")
    lines.append("---")
    return lines


def build_markdown_export(content_items: list, qa_report: dict, export_notes: list) -> str:
    summary = qa_report.get("summary", {})
    lines = [
        "# FlyingFish Content Calendar — Publishing-Ready Export",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        f"QA status: {qa_report.get('status')} ({len(content_items)} day(s), "
        f"{summary.get('hard_failure_count', 0)} hard failure(s), {summary.get('warning_count', 0)} warning(s))",
    ]

    qa_warnings = qa_report.get("warnings") or []
    if qa_warnings:
        lines.append("")
        lines.append("**QA warnings (non-blocking):**")
        for w in qa_warnings:
            lines.append(f"- {w}")

    if export_notes:
        lines.append("")
        lines.append("**Export notes (informational, do not override Stage 9's QA PASS):**")
        for n in export_notes:
            lines.append(f"- {n}")

    lines.append("")
    lines.append("---")

    for item in content_items:
        lines.append("")
        lines.extend(_markdown_item_section(item))

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--qa-input", type=Path, default=DEFAULT_QA_INPUT_PATH, help="Path to the Stage 9 QA report.")
    parser.add_argument("--content-input", type=Path, default=DEFAULT_CONTENT_INPUT_PATH, help="Path to the Stage 8 content production package.")
    parser.add_argument(
        "--calendar-input", type=Path, default=None,
        help="Optional Stage 7 calendar, used only for a best-effort informational spot-check - "
        "never overrides the Stage 9 QA verdict. Defaults to the standard calendar path if present.",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory to write publishing-ready exports into.")
    parser.add_argument("--formats", default="json,csv,markdown", help="Comma-separated export formats to generate: json, csv, markdown.")
    parser.add_argument("--dry-run", action="store_true", help="Validate the QA gate and inputs, but write no export files.")
    args = parser.parse_args()

    try:
        qa_report = load_qa_report(args.qa_input)
    except DataError as e:
        print(f"FAILED: could not load Stage 9 QA report ({args.qa_input}): {e}")
        return 1

    try:
        verify_qa_gate(qa_report)
    except DataError as e:
        print(f"FAILED: {e}")
        hard_failures = qa_report.get("hard_failures") or []
        if hard_failures:
            print("Hard failures reported by Stage 9:")
            for v in hard_failures:
                print(f"  - {v}")
        return 1

    try:
        content = load_content_package(args.content_input)
    except DataError as e:
        print(f"FAILED: could not load Stage 8 content package ({args.content_input}): {e}")
        return 1

    formats = [f.strip().lower() for f in args.formats.split(",") if f.strip()]
    unknown = sorted(set(formats) - set(SUPPORTED_FORMATS))
    if unknown:
        print(f"FAILED: unknown export format(s): {unknown}. Supported: {list(SUPPORTED_FORMATS)}.")
        return 1

    content_items = sorted(content["content_items"], key=lambda it: it["day_number"])
    qa_warnings = list(qa_report.get("warnings") or [])

    calendar_path = args.calendar_input if args.calendar_input is not None else DEFAULT_CALENDAR_INPUT_PATH
    export_notes = spot_check_calendar(calendar_path, args.calendar_input is not None, content_items)

    print("=== Stage 10 Content Export ===")
    print(f"QA status: {qa_report.get('status')}")
    print(f"Days exported: {len(content_items)}")

    if args.dry_run:
        print(f"Exports that would be generated: {formats}")
        print(f"Warnings carried forward: {len(qa_warnings)}")
        print("DRY RUN: no export files written.")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    generated = []

    if "json" in formats:
        json_path = args.output_dir / JSON_OUTPUT_FILENAME
        json_data = build_json_export(content_items, qa_report, args.content_input, args.qa_input, export_notes)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
        generated.append(json_path)

    if "csv" in formats:
        csv_path = args.output_dir / CSV_OUTPUT_FILENAME
        write_csv_export(content_items, csv_path)
        generated.append(csv_path)

    if "markdown" in formats:
        md_path = args.output_dir / MARKDOWN_OUTPUT_FILENAME
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(build_markdown_export(content_items, qa_report, export_notes))
        generated.append(md_path)

    print(f"Exports generated: {len(generated)}")
    for p in generated:
        print(f"  - {p}")
    print(f"Warnings carried forward: {len(qa_warnings)}")
    for w in qa_warnings:
        print(f"  - {w}")
    if export_notes:
        print(f"Export notes: {len(export_notes)}")
        for n in export_notes:
            print(f"  - {n}")
    print("Status: SUCCESS")

    return 0


if __name__ == "__main__":
    sys.exit(main())
