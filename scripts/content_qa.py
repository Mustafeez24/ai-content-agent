"""
Content QA / Final Quality Gate for FlyingFish Scuba School (Stage 9).

Reads the Stage 7 Content Calendar (data/instagram/flyingfish_content_calendar.json) and
the Stage 8 production content package (data/instagram/flyingfish_content.json) and
performs one last, fully deterministic check before either is considered publish-ready.
This makes NO Anthropic API calls and generates no new content - it only re-validates
what Stages 7 and 8 already produced, as an independent audit of the two files actually
on disk (not a re-run of the generation process itself).

ARCHITECTURE: reuses Stage 8's own validators directly (imported, not duplicated) -
find_content_violations(), package_type_for_item(), and known_post_ids() are the exact
same functions Stage 8 used while generating the content, run again here against the
final persisted files. This catches real drift (a hand-edited file, a bug in Stage 8's
own bookkeeping) that a self-report from the generation run alone cannot catch, without
re-inventing any of the safety-critical regex logic that Stage 6/7/8 already spent
multiple hardening rounds tuning.

Unlike Stage 6/7/8, Stage 9 NEVER auto-corrects anything - it only reports. Stage 8
auto-flags a set of "soft" unsupported-fact patterns with requires_verification=true;
if any such pattern is still present in the FINAL file without that flag, there is no
further retry step after this stage, so it is promoted to a hard QA failure here rather
than silently passing through as a warning.

Warnings (content-quality signals - repeated topics/hooks/CTAs, weak hooks, generic
CTAs, excessive promotional wording, missing brand/location context, a possible
unverified testimonial) are reported separately and never fail the QA gate - only
schema/coverage/evidence-safety/content-safety problems do.

Usage:
    source venv/bin/activate
    python scripts/content_qa.py
    python scripts/content_qa.py --calendar-input data/instagram/flyingfish_content_calendar.json \\
        --content-input data/instagram/flyingfish_content.json
    python scripts/content_qa.py --dry-run        # validate both input files, no report written
"""

import argparse
import difflib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Reuse Stage 8's own validators and loader directly rather than re-implementing them -
# the exact same evidence-safety/content-safety/package-structural checks Stage 8 used
# while generating the content, re-run here against the final persisted files.
from content_generator import (
    ALLOWED_PACKAGE_TYPES,
    DataError,
    find_content_violations,
    known_post_ids,
    load_calendar as load_stage7_calendar,
    package_type_for_item,
)
from content_calendar import ALLOWED_CONTENT_TYPES, ALLOWED_PLATFORMS

DEFAULT_CALENDAR_INPUT_PATH = Path("data/instagram/flyingfish_content_calendar.json")
DEFAULT_CONTENT_INPUT_PATH = Path("data/instagram/flyingfish_content.json")
OUTPUT_PATH = Path("data/instagram/flyingfish_content_qa.json")

REQUIRED_CONTENT_TOP_LEVEL = ["metadata", "content_summary", "content_items"]

# Every field Stage 8 guarantees on a content item - a malformed/hand-edited content
# file fails to load cleanly rather than being silently partially checked.
REQUIRED_CONTENT_ITEM_FIELDS = [
    "day_number", "date", "platform", "content_type", "package_type", "topic", "objective",
    "target_audience", "content_angle", "priority", "hook", "script_scenes", "slides",
    "frames", "interaction_suggestion", "headline", "body", "caption", "cta", "footage_note",
    "evidence_basis", "evidence_type", "source_post_ids", "confidence", "requires_verification",
    "verification_reason", "status",
]

CONSISTENCY_FIELDS = ("date", "platform", "content_type")


def load_content_package(path: Path) -> dict:
    """Load and structurally validate the Stage 8 output file - no such loader exists
    yet since Stage 8 only ever wrote this file, never read it back."""
    if not path.exists():
        raise DataError(f"Stage 8 content package not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Stage 8 content package is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise DataError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_CONTENT_TOP_LEVEL if key not in data]
    if missing:
        raise DataError(f"Stage 8 content package is missing required section(s): {missing}")

    items = data.get("content_items")
    if not isinstance(items, list) or not items:
        raise DataError("Stage 8 content package contains no content_items - nothing to QA.")

    day_numbers = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise DataError(f"content_items[{i}] is not an object.")
        missing_fields = [f for f in REQUIRED_CONTENT_ITEM_FIELDS if f not in item]
        if missing_fields:
            raise DataError(f"content_items[{i}] is missing required field(s): {missing_fields}")
        if item["package_type"] not in ALLOWED_PACKAGE_TYPES:
            raise DataError(f"content_items[{i}].package_type is not recognized: {item['package_type']!r}")
        if item["platform"] not in ALLOWED_PLATFORMS:
            raise DataError(f"content_items[{i}].platform is not one of {sorted(ALLOWED_PLATFORMS)}: {item['platform']!r}")
        if str(item["content_type"]).strip().lower() not in ALLOWED_CONTENT_TYPES:
            raise DataError(f"content_items[{i}].content_type is not a recognized Stage 7 format: {item['content_type']!r}")
        day_numbers.append(item["day_number"])

    if len(set(day_numbers)) != len(day_numbers):
        raise DataError(f"Stage 8 content package has duplicate day_number values: {day_numbers}")

    return data


def check_calendar_consistency(calendar_items: list, content_items: list) -> dict:
    """Every Stage 7 calendar day must have exactly one Stage 8 content package, with
    matching date/platform/content_type/package_type - a field-by-field cross-check of
    the two persisted files, independent of whatever Stage 8's own generation run
    reported about itself. Returns {"hard": [str, ...], "coverage": {...}}."""
    hard = []
    calendar_by_day = {item["day_number"]: item for item in calendar_items}
    content_by_day = {item["day_number"]: item for item in content_items}

    calendar_days = set(calendar_by_day)
    content_days = set(content_by_day)
    missing_days = sorted(calendar_days - content_days)
    extra_days = sorted(content_days - calendar_days)
    mismatched_days = []

    for day in sorted(calendar_days & content_days):
        cal_item = calendar_by_day[day]
        con_item = content_by_day[day]

        for field in CONSISTENCY_FIELDS:
            if cal_item.get(field) != con_item.get(field):
                mismatched_days.append(
                    {"day_number": day, "field": field, "expected": cal_item.get(field), "actual": con_item.get(field)}
                )
                hard.append(
                    f"day {day}: {field} mismatch between calendar and content package - "
                    f"expected {cal_item.get(field)!r}, got {con_item.get(field)!r}"
                )

        expected_package_type = package_type_for_item(cal_item)
        actual_package_type = con_item.get("package_type")
        if expected_package_type != actual_package_type:
            mismatched_days.append(
                {"day_number": day, "field": "package_type", "expected": expected_package_type, "actual": actual_package_type}
            )
            hard.append(
                f"day {day}: package_type mismatch - expected {expected_package_type!r} (derived from the "
                f"calendar's own platform/content_type), got {actual_package_type!r}"
            )

    for day in missing_days:
        hard.append(f"day {day}: present in the Stage 7 calendar but has no matching Stage 8 content package")
    for day in extra_days:
        hard.append(f"day {day}: a content package exists but has no matching Stage 7 calendar day")

    return {
        "hard": hard,
        "coverage": {"missing_days": missing_days, "extra_days": extra_days, "mismatched_days": mismatched_days},
    }


def promote_soft_to_hard(soft_violations: list) -> list:
    """Stage 8 auto-flags these with requires_verification=true when it finds them
    (soft, not hard, there). Stage 9 never auto-corrects and has no further retry step,
    so a soft violation still present in the FINAL file means an unflagged, unsupported
    factual claim reached the last gate before publishing - promoted to a hard failure."""
    return [
        f"{v['loc']}: {v['detail']} - not auto-flagged with requires_verification=true in the final file"
        for v in soft_violations
    ]


# New check beyond Stage 8's own validators: specific partnership/sponsorship claims and
# specific course inclusions are exactly the kind of unsupported fact the project's brand/
# fact-QA rules forbid inventing, but Stage 8 has no dedicated check for them. Same
# hard-unless-verified treatment as Stage 8's price/offer/competitor checks.
_PARTNERSHIP_INCLUSION_RE = re.compile(
    r"\bofficial\s+partner\b|\bin\s+partnership\s+with\b|\bsponsored\s+by\b|\bpartnered\s+with\b|"
    r"\ball[- ]inclusive\b|\bincludes?\s+(?:equipment|gear|lunch|transport|pickup|hotel)\b",
    re.IGNORECASE,
)

_VIOLATION_TEXT_FIELDS = ("hook", "headline", "body", "caption", "cta", "footage_note", "evidence_basis")
_VIOLATION_ARRAY_FIELDS = ("script_scenes", "slides", "frames")


def _combined_item_text(item: dict) -> str:
    parts = [str(item.get(f, "")) for f in _VIOLATION_TEXT_FIELDS if item.get(f)]
    for f in _VIOLATION_ARRAY_FIELDS:
        parts.extend(str(s) for s in (item.get(f) or []) if s)
    return " ".join(parts)


def find_partnership_inclusion_violations(content_items: list) -> list:
    hard = []
    for i, item in enumerate(content_items):
        requires_verification = bool(item.get("requires_verification", False))
        verification_reason = str(item.get("verification_reason") or "").strip()
        verified = requires_verification and bool(verification_reason)
        if not verified and _PARTNERSHIP_INCLUSION_RE.search(_combined_item_text(item)):
            hard.append(
                f"content_items[{i}] (day {item.get('day_number')}): references a partnership/sponsorship "
                "or a specific course inclusion without requires_verification=true + a verification_reason"
            )
    return hard


def classify_violation(v: str) -> str:
    """Bucket a hard-failure string into a report section, purely by matching the
    fixed wording find_content_violations()/promote_soft_to_hard()/the consistency
    check already use - no separate source of truth for what a violation "is"."""
    lowered = v.lower()
    if "source_post_ids references" in lowered:
        return "invalid_source_post_ids"
    if "must cite at least one" in lowered:
        return "missing_citations"
    if "unsupported causal language" in lowered:
        return "causal_language"
    if "makes a competitor claim" in lowered:
        return "competitor_claims"
    if "specific price" in lowered:
        return "price_claims"
    if "specific offer" in lowered:
        return "offer_claims"
    if "ai-generated footage" in lowered:
        return "ai_footage"
    if "not auto-flagged" in lowered or "partnership/sponsorship" in lowered:
        return "unflagged_facts"
    return "structural_issues"


# --- quality signals (warnings only - never fail the QA gate) ----------------------

_GENERIC_CTA_PHRASES = {"click here", "learn more", "follow us", "check it out", "see more", "swipe up"}
_GENERIC_HOOK_OPENERS = ("discover", "learn about", "check out", "did you know")
_PROMOTIONAL_WORDS = (
    "book", "dm us", "message us", "sign up", "join now", "limited", "hurry",
    "don't miss", "act now", "call now", "book now",
)
_BRAND_CONTEXT_WORDS = (
    "flyingfish", "flying fish", "goa", "scuba", "dive", "diving", "padi", "ssi", "novotel", "candolim",
)
_TESTIMONIAL_RE = re.compile(
    r'"[^"]{10,}"'
    r"|\b(?:a\s+)?(?:customer|student|diver|guest)s?\s+(?:told\s+us|said|shared|wrote)\b"
    r"|\bone\s+of\s+our\s+(?:students?|customers?|divers?)\s+(?:said|told\s+us|shared)\b",
    re.IGNORECASE,
)
_MIN_HOOK_LENGTH_FOR_WARNING = 25  # above Stage 8's hard minimum (10) - a "weak but valid" hook
_TOPIC_SIMILARITY_WINDOW_DAYS = 3
_TOPIC_SIMILARITY_THRESHOLD = 0.8


def _per_item_quality_signals(item: dict) -> list:
    signals = []
    day = item.get("day_number")

    cta = str(item.get("cta", "")).strip()
    if cta.lower() in _GENERIC_CTA_PHRASES:
        signals.append({"category": "generic_cta", "day_number": day, "detail": f"CTA is generic/non-specific: {cta!r}"})

    hook = str(item.get("hook", "")).strip()
    if hook and (len(hook) < _MIN_HOOK_LENGTH_FOR_WARNING or hook.lower().startswith(_GENERIC_HOOK_OPENERS)):
        signals.append({"category": "weak_hook", "day_number": day, "detail": f"Hook is short or generically phrased: {hook!r}"})

    combined = _combined_item_text(item)
    lowered = combined.lower()

    promo_count = sum(1 for w in _PROMOTIONAL_WORDS if w in lowered)
    if promo_count >= 3:
        signals.append(
            {
                "category": "excessive_promotional_wording",
                "day_number": day,
                "detail": f"{promo_count} promotional trigger phrases found - content may read as overly salesy",
            }
        )

    if combined.strip() and not any(w in lowered for w in _BRAND_CONTEXT_WORDS):
        signals.append(
            {
                "category": "missing_brand_context",
                "day_number": day,
                "detail": "No FlyingFish/Goa/diving-related keyword found anywhere in this item",
            }
        )

    if _TESTIMONIAL_RE.search(combined):
        evidence_type = item.get("evidence_type")
        source_post_ids = item.get("source_post_ids") or []
        if evidence_type not in ("observed", "interpretation") or not source_post_ids:
            signals.append(
                {
                    "category": "possible_fabricated_testimonial",
                    "day_number": day,
                    "detail": "Content includes a quoted/attributed customer statement not tied to cited evidence",
                }
            )

    return signals


def _find_repeated_fields(content_items: list, field: str, category: str) -> list:
    """Exact-duplicate hook/CTA text anywhere across the batch - neither Stage 7 nor
    Stage 8 guarantees these are unique (only topic uniqueness is enforced), so a
    repeated CTA/hook is a legitimate, new content-quality signal."""
    signals = []
    seen = {}
    for item in sorted(content_items, key=lambda it: it.get("day_number", 0)):
        value = str(item.get(field, "")).strip().lower()
        if not value:
            continue
        if value in seen:
            signals.append(
                {
                    "category": category,
                    "day_number": item.get("day_number"),
                    "detail": f"{field} on day {item.get('day_number')} duplicates day {seen[value]}: {item.get(field)!r}",
                }
            )
        else:
            seen[value] = item.get("day_number")
    return signals


def _find_repeated_topics(content_items: list) -> list:
    """Near-duplicate topics within a nearby-day window - Stage 7 already forbids exact
    duplicate topics across the whole calendar, so this catches the softer case of two
    different-but-very-similar topics landing close together."""
    signals = []
    ordered = sorted(content_items, key=lambda it: it.get("day_number", 0))
    for i, item in enumerate(ordered):
        t1 = str(item.get("topic", "")).strip().lower()
        if not t1:
            continue
        for other in ordered[i + 1 :]:
            gap = (other.get("day_number", 0) or 0) - (item.get("day_number", 0) or 0)
            if gap <= 0:
                continue
            if gap > _TOPIC_SIMILARITY_WINDOW_DAYS:
                break
            t2 = str(other.get("topic", "")).strip().lower()
            if not t2:
                continue
            ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
            if ratio >= _TOPIC_SIMILARITY_THRESHOLD:
                signals.append(
                    {
                        "category": "repetitive_topic_near_days",
                        "day_number": other.get("day_number"),
                        "detail": (
                            f"Day {other.get('day_number')} topic is very similar to day {item.get('day_number')} "
                            f"(similarity {ratio:.2f}): {other.get('topic')!r} vs {item.get('topic')!r}"
                        ),
                    }
                )
    return signals


def find_quality_signals(content_items: list) -> list:
    signals = []
    for item in content_items:
        signals.extend(_per_item_quality_signals(item))
    signals.extend(_find_repeated_fields(content_items, "cta", "repeated_cta"))
    signals.extend(_find_repeated_fields(content_items, "hook", "repeated_hook"))
    signals.extend(_find_repeated_topics(content_items))
    return signals


def build_report(calendar: dict, content: dict, calendar_path: Path, content_path: Path) -> dict:
    calendar_items = calendar["calendar_items"]
    content_items = content["content_items"]

    consistency = check_calendar_consistency(calendar_items, content_items)

    valid_post_ids = known_post_ids(calendar)
    package_types = [item.get("package_type") for item in content_items]
    violations = find_content_violations(
        {"content_summary": content.get("content_summary", ""), "content_items": content_items},
        valid_post_ids,
        len(content_items),
        package_types,
    )

    unflagged_fact_failures = promote_soft_to_hard(violations["soft"])
    partnership_failures = find_partnership_inclusion_violations(content_items)

    all_hard = list(consistency["hard"]) + list(violations["hard"]) + unflagged_fact_failures + partnership_failures

    quality_signals = find_quality_signals(content_items)
    warnings = [f"[{s['category']}] day {s['day_number']}: {s['detail']}" for s in quality_signals]

    buckets = {
        "invalid_source_post_ids": [],
        "missing_citations": [],
        "causal_language": [],
        "competitor_claims": [],
        "price_claims": [],
        "offer_claims": [],
        "ai_footage": [],
        "unflagged_facts": [],
        "structural_issues": [],
    }
    for v in all_hard:
        buckets[classify_violation(v)].append(v)

    status = "FAIL" if all_hard else "PASS"

    return {
        "metadata": {
            "agent": "content_qa",
            "calendar_source": str(calendar_path),
            "content_source": str(content_path),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_expected": len(calendar_items),
            "days_checked": len(content_items),
        },
        "status": status,
        "summary": {
            "hard_failure_count": len(all_hard),
            "warning_count": len(warnings),
            "days_expected": len(calendar_items),
            "days_covered": len(content_items),
        },
        "hard_failures": all_hard,
        "warnings": warnings,
        "coverage": consistency["coverage"],
        "evidence_validation": {
            "invalid_source_post_ids": buckets["invalid_source_post_ids"],
            "missing_citations": buckets["missing_citations"],
        },
        "safety_validation": {
            "causal_language": buckets["causal_language"],
            "competitor_claims": buckets["competitor_claims"],
            "price_claims": buckets["price_claims"],
            "offer_claims": buckets["offer_claims"],
            "ai_footage": buckets["ai_footage"],
            "unflagged_facts": buckets["unflagged_facts"],
        },
        "package_validation": {"structural_issues": buckets["structural_issues"]},
        "quality_signals": quality_signals,
    }


def print_terminal_summary(report: dict) -> None:
    print(f"Status: {report['status']}")
    print(f"Days expected: {report['summary']['days_expected']}, days covered: {report['summary']['days_covered']}")
    print(f"Hard failures: {report['summary']['hard_failure_count']}")
    print(f"Warnings: {report['summary']['warning_count']}")

    if report["coverage"]["missing_days"]:
        print(f"Missing days: {report['coverage']['missing_days']}")
    if report["coverage"]["extra_days"]:
        print(f"Extra days: {report['coverage']['extra_days']}")

    if report["hard_failures"]:
        print("\nHard failures:")
        for v in report["hard_failures"]:
            print(f"  - {v}")

    if report["warnings"]:
        print("\nWarnings (non-blocking):")
        for w in report["warnings"]:
            print(f"  - {w}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calendar-input", type=Path, default=DEFAULT_CALENDAR_INPUT_PATH, help="Path to the Stage 7 Content Calendar.")
    parser.add_argument("--content-input", type=Path, default=DEFAULT_CONTENT_INPUT_PATH, help="Path to the Stage 8 content production package.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to write the QA report JSON.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load/validate both input files, but skip running the full QA gate and writing the report.",
    )
    args = parser.parse_args()

    try:
        calendar = load_stage7_calendar(args.calendar_input)
    except DataError as e:
        print(f"FAILED: could not load Stage 7 calendar ({args.calendar_input}): {e}")
        return 1

    try:
        content = load_content_package(args.content_input)
    except DataError as e:
        print(f"FAILED: could not load Stage 8 content package ({args.content_input}): {e}")
        return 1

    print("=== Stage 9 Content QA ===")
    print(f"Calendar: {args.calendar_input} ({len(calendar['calendar_items'])} day(s))")
    print(f"Content package: {args.content_input} ({len(content['content_items'])} item(s))")
    print()

    if args.dry_run:
        print("DRY RUN: both files loaded and are structurally valid. No QA report written.")
        return 0

    report = build_report(calendar, content, args.calendar_input, args.content_input)
    print_terminal_summary(report)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\nQA report saved to: {args.output}")

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
