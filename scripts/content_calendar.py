"""
Content Calendar Generator for FlyingFish Scuba School (Stage 7).

Reads the existing Stage 6 Content Strategy report
(data/instagram/flyingfish_content_strategy.json) and converts its verified,
evidence-classified content opportunities, themes, formats, and tests into a
day-by-day publishing calendar. This does NOT scrape Instagram, call Apify, or
re-run Stage 6 - it only works from what Stage 6 already established.

Answers: "Given our verified content strategy, what should FlyingFish post on which
day, and why?" - grounded in Stage 6 evidence, not generic social media advice.

ARCHITECTURE: reuses Stage 6's evidence-safety machinery directly (imported, not
duplicated) - the same causal-language check, competitor-claim check, and evidence
vocabulary (evidence_type/confidence/requires_verification/verification_reason) that
Stage 6 spent multiple hardening rounds tuning. Day number, calendar date, and
platform are assigned entirely in Python (build_calendar_skeleton) - Claude never
generates these, so there is no way for a date or platform to be invented, and the
calendar is guaranteed to contain exactly the requested number of days. Claude fills
in the creative/evidentiary content for each already-fixed slot. Every calendar item
carries its own evidence_type/evidence_basis/source_post_ids, so "this is a
hypothesis" and "this is directly observed" are never collapsed into one another - a
RAW DATA -> OBSERVATION -> INTERPRETATION -> HYPOTHESIS -> RECOMMENDATION pipeline,
same shape as Stage 6's.

Usage:
    source venv/bin/activate
    python scripts/content_calendar.py                  # 7-day calendar
    python scripts/content_calendar.py --days 30         # 30-day calendar
    python scripts/content_calendar.py --dry-run         # validate + prepare input, no API call
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

# Reuse Stage 6's evidence-safety machinery directly rather than re-implementing it -
# same causal-language/competitor-claim rules, same helpers for API error handling and
# tolerant JSON extraction. Stage 6 itself is not imported by anything else and is not
# modified by importing from it.
from content_strategy import (
    ALLOWED_CONFIDENCE_LEVELS,
    ALLOWED_EVIDENCE_TYPES,
    _CALENDAR_PERIOD_RE,
    _COMPETITOR_HEDGE_RE,
    _COMPETITOR_RE,
    _causal_language_match,
    extract_api_error_message,
    extract_json_object,
)

DEFAULT_INPUT_PATH = Path("data/instagram/flyingfish_content_strategy.json")
OUTPUT_PATH = Path("data/instagram/flyingfish_content_calendar.json")
MODEL = "claude-haiku-4-5"  # same model/conventions as Stage 6

REQUIRED_SECTIONS = [
    "metadata",
    "executive_summary",
    "content_opportunities",
    "strategy_themes",
    "recommended_formats",
    "recommended_tests",
    "action_plan",
]

DEFAULT_DAYS = 7

# Platform rotation is entirely deterministic - Claude never chooses or invents a
# platform. Initially Instagram + Google Business Profile only, per project scope;
# Quora/Reddit are a separate future module.
ALLOWED_PLATFORMS = {"Instagram", "Google Business Profile"}
GBP_EVERY_N_DAYS = 5

ALLOWED_CONTENT_TYPES = {
    "reel", "carousel", "static post", "story",
    "educational post", "faq", "q&a", "community content",
}


class DataError(Exception):
    """Raised for problems with the Stage 6 input (missing file, bad JSON, missing
    sections, or insufficient evidence to build a calendar from)."""


def load_strategy_report(path: Path) -> dict:
    if not path.exists():
        raise DataError(f"Stage 6 Content Strategy report not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Stage 6 report is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise DataError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_SECTIONS if key not in data]
    if missing:
        raise DataError(f"Stage 6 report is missing required section(s): {missing}")

    evidence_item_count = sum(
        len(data.get(group, []))
        for group in ("content_opportunities", "strategy_themes", "recommended_formats", "recommended_tests")
    )
    if evidence_item_count == 0:
        raise DataError(
            "Stage 6 report contains no content_opportunities, strategy_themes, "
            "recommended_formats, or recommended_tests - there is no evidence to build a calendar from."
        )

    return data


def known_post_ids(strategy: dict) -> set:
    """Every post_id the Content Calendar Generator is allowed to cite - the union of
    every evidence_post_ids array across Stage 6's own evidence-classified items.
    Nothing outside this set was ever verified against real Instagram data by Stage 6."""
    ids = set()
    for group in ("content_opportunities", "strategy_themes", "recommended_formats", "recommended_tests"):
        for item in strategy.get(group, []):
            if isinstance(item, dict):
                ids.update(item.get("evidence_post_ids") or [])
    return ids


def platform_for_day(day_number: int) -> str:
    """Deterministic platform rotation - mostly Instagram, with Google Business
    Profile every GBP_EVERY_N_DAYS days. Claude never sees or chooses this."""
    return "Google Business Profile" if day_number % GBP_EVERY_N_DAYS == 0 else "Instagram"


def build_calendar_skeleton(days: int, start_date=None) -> list:
    """Build the fixed day_number/date/platform slots Claude must fill in, one
    content item per slot, in order. This is the sole source of truth for day
    numbering, calendar dates, and platform assignment - Claude is never asked to
    generate any of these, so a real run can never invent a date or an extra/missing
    day the way it could invent a post_id."""
    if start_date is None:
        start_date = datetime.now(timezone.utc).date()
    return [
        {
            "day_number": i,
            "date": (start_date + timedelta(days=i - 1)).isoformat(),
            "platform": platform_for_day(i),
        }
        for i in range(1, days + 1)
    ]


def build_calendar_payload(strategy: dict, skeleton: list) -> dict:
    """Compact input for Claude - Stage 6's own evidence-classified items plus the
    fixed calendar skeleton to fill in. Stage 6 already distilled the raw analysis
    down to evidence-classified findings, so this is already small."""
    return {
        "executive_summary": strategy.get("executive_summary"),
        "content_opportunities": strategy.get("content_opportunities", []),
        "strategy_themes": strategy.get("strategy_themes", []),
        "recommended_formats": strategy.get("recommended_formats", []),
        "recommended_tests": strategy.get("recommended_tests", []),
        "known_post_ids": sorted(known_post_ids(strategy)),
        "calendar_slots": skeleton,
    }


def _build_system_prompt(days: int) -> str:
    today = datetime.now(timezone.utc).strftime("%B %Y")
    return f"""You are the Content Calendar Generator for FlyingFish Scuba School, \
a scuba diving school at Novotel Resort & Spa, Candolim, Goa, India, offering SSI and \
PADI certifications. The current date is {today}.

You will receive Stage 6's verified content strategy (content_opportunities, \
strategy_themes, recommended_formats, recommended_tests) and a fixed "calendar_slots" \
list of exactly {days} day_number/date/platform slots. Your job is to fill in ONE \
concrete, actionable content item per slot, in the SAME ORDER as calendar_slots - \
return exactly {days} items in "calendar_items", item[i] corresponding to \
calendar_slots[i]. Do NOT generate day_number, date, or platform yourself - those are \
fixed and are not part of your output schema; just use calendar_slots to know what \
platform each item is for (Instagram vs. Google Business Profile posts read \
differently - GBP is shorter, no hashtags, more direct/informational).

You build every claim through this pipeline - each stage may ONLY do its own job:

  RAW DATA -> OBSERVATION -> INTERPRETATION -> HYPOTHESIS -> RECOMMENDATION

  RAW DATA (given to you, from Stage 6): a content_opportunities item citing \
  DWyk4T6E5OF (3,266 likes, 49 comments, instructor praise).
  OBSERVATION -> "evidence_basis": "The supplied dataset contains a high-performing \
  testimonial example (DWyk4T6E5OF) featuring instructor praise."
  INTERPRETATION (folded into evidence_basis too, still hedged): "This format is \
  represented among the stronger-performing examples in the supplied dataset."
  HYPOTHESIS (only if the idea is genuinely untested): reflected via evidence_type= \
  "hypothesis" - never state the hypothesis as if it already happened.
  RECOMMENDATION: the calendar item itself (topic/hook/angle/format) - an action to \
  take, not a promised result.

"evidence_basis" is a STRICT OBSERVATIONAL FIELD - it may state ONLY what Stage 6's \
evidence actually shows, using words like: is associated with, was observed in, \
achieved, received, recorded, shows, features, contains, includes, had. NEVER use, in \
any tense and never softened with "may"/"likely"/"emerges as"/"aligns with": drives, \
drive, drove, driven, generates, generated, increases, increased, leads to, led to, \
results in, resulted in, "primary driver"/"top driver"/"engagement driver" (with or \
without a word in between), proven, guarantees. If an idea is not directly evidenced, \
say so plainly ("Not directly evidenced in the supplied dataset; a hypothesis-based \
idea.") and set evidence_type="hypothesis" - never dress up a hypothesis as an \
observed fact. Do NOT fabricate performance statistics, audience behavior, customer \
preferences, or historical performance that Stage 6 did not supply.

COMPETITOR CLAIMS - the Stage 6 report contains FlyingFish data only, never \
competitor data. NEVER state a specific fact about how competitors are positioned or \
what they do, in ANY field (topic, hook, target_audience, evidence_basis, or any \
other) - not even softened with "may" or "likely". If competitor data is not \
supplied, do not mention competitors at all - describe FlyingFish's own audience/ \
content instead.

Every other field (topic, hook, objective, target_audience, content_angle, cta, \
content_type) is CREATIVE, not evidence, and should read naturally and specifically \
enough that a content creator can execute it without more direction - never generic \
filler like "Post an educational Reel." Ground each idea in a specific piece of \
Stage 6 evidence (a pattern, opportunity, theme, format, or test) referenced via \
source_post_ids and evidence_basis, and vary the format across the week/month rather \
than repeating the same one every day - draw the actual mix from what Stage 6's \
recommended_formats/content_opportunities support, choosing from exactly these format \
labels for "content_type" (use one of these strings exactly, lowercase or not): Reel, \
Carousel, Static Post, Story, Educational Post, FAQ, Q&A, Community Content.

FlyingFish content areas to draw from (only where supported by the Stage 6 evidence \
you were given - do not invent new USPs, prices, or facts): beginner scuba diving, \
scuba diving in Goa, scuba safety, SSI/PADI certification education, marine life, \
underwater photography, Grande Island, first-time diver education, diving \
preparation, instructor-led diving.

FIELD CONVENTIONS (the schema uses plain types - follow these exactly, they are \
validated after your response is parsed):
- "evidence_type" must be exactly one of: observed, interpretation, hypothesis, recommendation.
- "confidence" must be exactly one of: high, medium, low.
- "priority" must be exactly one of: high, medium, low.
- "source_post_ids": list only post_ids from "known_post_ids", or an empty array if \
the idea is a hypothesis not tied to specific posts. If evidence_type is "observed" \
or "interpretation", you MUST cite at least one post_id here - an observed claim with \
no cited evidence is not allowed.
- "verification_reason" is a string: your explanation when requires_verification is \
true, or an empty string "" when requires_verification is false. Set \
requires_verification=true whenever a claim touches a business fact, external claim, \
or competitor comparison not supplied as verified data.

Respond with ONLY a single valid JSON object (no markdown code fences, no commentary \
before or after) matching exactly the schema you are given."""


CONTENT_CALENDAR_SYSTEM_PROMPT_CACHE = {}


def build_system_prompt(days: int) -> str:
    if days not in CONTENT_CALENDAR_SYSTEM_PROMPT_CACHE:
        CONTENT_CALENDAR_SYSTEM_PROMPT_CACHE[days] = _build_system_prompt(days)
    return CONTENT_CALENDAR_SYSTEM_PROMPT_CACHE[days]


# Evidence fields shared by every calendar item - deliberately NOT enums and NOT
# nullable unions, same reasoning as Stage 6: a JSON-schema enum/union set is what
# produced Anthropic's "compiled grammar is too large" error there. Allowed values are
# enforced in Python by find_calendar_violations() instead.
_CALENDAR_EVIDENCE_FIELDS = {
    "evidence_type": {"type": "string"},
    "source_post_ids": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "string"},
    "requires_verification": {"type": "boolean"},
    "verification_reason": {"type": "string"},
}
_CALENDAR_EVIDENCE_FIELD_NAMES = list(_CALENDAR_EVIDENCE_FIELDS.keys())

_CALENDAR_ITEM_CREATIVE_FIELDS = (
    "content_type", "recommended_format", "topic", "hook",
    "objective", "target_audience", "content_angle", "cta",
)

CONTENT_CALENDAR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "calendar_summary": {"type": "string"},
        "calendar_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "content_type": {"type": "string"},
                    "recommended_format": {"type": "string"},
                    "topic": {"type": "string"},
                    "hook": {"type": "string"},
                    "objective": {"type": "string"},
                    "target_audience": {"type": "string"},
                    "content_angle": {"type": "string"},
                    "cta": {"type": "string"},
                    "priority": {"type": "string"},
                    "evidence_basis": {"type": "string"},
                    **_CALENDAR_EVIDENCE_FIELDS,
                },
                "required": [
                    *_CALENDAR_ITEM_CREATIVE_FIELDS, "priority", "evidence_basis",
                    *_CALENDAR_EVIDENCE_FIELD_NAMES,
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["calendar_summary", "calendar_items"],
    "additionalProperties": False,
}

# 8000/14000 for a 7-day calendar; scaled up for 30 days, mirroring Stage 6's
# measured-safe 8000/12000 budget for a similarly-shaped, similarly-sized response but
# accounting for up to ~4x the item count.
BASE_MAX_TOKENS_7DAY = 8000
RETRY_MAX_TOKENS_7DAY = 14000
BASE_MAX_TOKENS_30DAY = 16000
RETRY_MAX_TOKENS_30DAY = 24000


def token_budget(days: int) -> tuple:
    if days > 7:
        return BASE_MAX_TOKENS_30DAY, RETRY_MAX_TOKENS_30DAY
    return BASE_MAX_TOKENS_7DAY, RETRY_MAX_TOKENS_7DAY


class TruncatedResponseError(Exception):
    """Raised when Claude's response was cut off by the token limit before completing."""


def call_claude(api_key: str, payload: dict, days: int, max_tokens: int, extra_note: str = None) -> tuple:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        "Here is the Stage 6 Content Strategy report for FlyingFish Scuba School and "
        f"the fixed {days}-day calendar skeleton to fill in. Build the calendar strictly "
        "from this evidence.\n\n" + json.dumps(payload, ensure_ascii=False)
    )
    if extra_note:
        user_message += f"\n\nCORRECTION REQUIRED: {extra_note}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=build_system_prompt(days),
        messages=[{"role": "user", "content": user_message}],
        output_config={"format": {"type": "json_schema", "schema": CONTENT_CALENDAR_RESPONSE_SCHEMA}},
    )

    if response.stop_reason == "max_tokens":
        raise TruncatedResponseError(
            f"Response was cut off by the max_tokens limit ({max_tokens}) before it finished."
        )

    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response


REQUIRED_RESPONSE_FIELDS = {
    "calendar_summary": str,
    "calendar_items": list,
}


def validate_calendar_response(data) -> None:
    """Fail clearly and specifically rather than silently assembling an incomplete calendar."""
    if not isinstance(data, dict):
        raise DataError(f"Claude's response was not a JSON object (got {type(data).__name__}).")

    missing = [k for k in REQUIRED_RESPONSE_FIELDS if k not in data]
    if missing:
        raise DataError(f"Claude's response is missing required field(s): {missing}")

    wrong_type = [
        k for k, expected in REQUIRED_RESPONSE_FIELDS.items() if not isinstance(data[k], expected)
    ]
    if wrong_type:
        raise DataError(f"Claude's response has the wrong type for field(s): {wrong_type}")


_MIN_TOPIC_LENGTH = 8
_VAGUE_TOPICS = {
    "post content", "create content", "engage audience", "post an educational reel",
    "educational content", "engaging content", "social media post", "instagram post",
}


def find_calendar_violations(data: dict, valid_post_ids: set, expected_days: int) -> dict:
    """Check calendar_items against the hardening rules, mirroring Stage 6's
    hard-vs-soft violation model. Returns {"hard": [...], "soft": [{"loc","type","detail"}, ...]}."""
    hard = []
    soft = []

    items = data.get("calendar_items", [])
    if len(items) != expected_days:
        hard.append(
            f"calendar_items must contain exactly {expected_days} item(s) (one per calendar_slots "
            f"entry), got {len(items)}"
        )

    seen_topics = {}
    for i, item in enumerate(items):
        loc = f"calendar_items[{i}]"
        if not isinstance(item, dict):
            hard.append(f"{loc}: expected an object, got {type(item).__name__}")
            continue

        topic = str(item.get("topic", "")).strip()
        if len(topic) < _MIN_TOPIC_LENGTH:
            hard.append(f"{loc}.topic: too short/empty to be actionable: {topic!r}")
        elif topic.lower() in _VAGUE_TOPICS:
            hard.append(f"{loc}.topic: too generic/vague to be actionable: {topic!r}")
        elif topic:
            seen_topics.setdefault(topic.lower(), []).append(i)

        content_type = str(item.get("content_type", "")).strip().lower()
        if content_type not in ALLOWED_CONTENT_TYPES:
            hard.append(
                f"{loc}.content_type must be one of {sorted(ALLOWED_CONTENT_TYPES)}, got {item.get('content_type')!r}"
            )

        evidence_type = item.get("evidence_type")
        if evidence_type not in ALLOWED_EVIDENCE_TYPES:
            hard.append(f"{loc}.evidence_type must be one of {sorted(ALLOWED_EVIDENCE_TYPES)}, got {evidence_type!r}")

        for field in ("confidence", "priority"):
            value = item.get(field)
            if value not in ALLOWED_CONFIDENCE_LEVELS:
                hard.append(f"{loc}.{field} must be one of {sorted(ALLOWED_CONFIDENCE_LEVELS)}, got {value!r}")

        source_post_ids = item.get("source_post_ids") or []
        invalid_ids = [pid for pid in source_post_ids if pid not in valid_post_ids]
        if invalid_ids:
            hard.append(f"{loc}: source_post_ids references post_id(s) not in the supplied Stage 6 evidence: {invalid_ids}")

        if evidence_type in ("observed", "interpretation") and not source_post_ids:
            hard.append(
                f"{loc}: evidence_type={evidence_type!r} but source_post_ids is empty - an observed/"
                "interpretation claim must cite at least one source_post_id"
            )

        # evidence_basis is the one strict, causal-checked field per item - the same
        # rule Stage 6 applies to observation/interpretation/evidence_basis, imported
        # directly rather than re-implemented.
        evidence_basis = item.get("evidence_basis", "")
        if isinstance(evidence_basis, str):
            causal = _causal_language_match(evidence_basis)
            if causal:
                phrase, sentence = causal
                hard.append(
                    f"{loc}.evidence_basis: uses unsupported causal language ({phrase!r}) - state "
                    f"only what was observed, or mark evidence_type='hypothesis': {sentence!r}"
                )

        # Competitor/calendar-period checks apply to every text field, not just
        # evidence_basis - a competitor aside can appear in any creative field too.
        requires_verification = bool(item.get("requires_verification", False))
        verification_reason = str(item.get("verification_reason") or "").strip()
        competitor_verified = requires_verification and bool(verification_reason)
        for field in (*_CALENDAR_ITEM_CREATIVE_FIELDS, "evidence_basis"):
            text = item.get(field, "")
            if not isinstance(text, str):
                continue
            if _COMPETITOR_RE.search(text) and not _COMPETITOR_HEDGE_RE.search(text) and not competitor_verified:
                hard.append(
                    f"{loc}.{field}: makes a competitor claim without competitor data, without hedged "
                    f"'validation required' phrasing, and without requires_verification=true + a "
                    f"verification_reason: {text!r}"
                )
            if _CALENDAR_PERIOD_RE.search(text):
                hard.append(
                    f"{loc}.{field}: contains a hardcoded calendar quarter/year instead of a relative "
                    f"reference: {text!r}"
                )

    for topic_lower, indexes in seen_topics.items():
        if len(indexes) > 1:
            hard.append(f"Duplicate topic {topic_lower!r} used in calendar_items{indexes} - each day must be distinct")

    return {"hard": hard, "soft": soft}


def assemble_calendar_items(claude_items: list, skeleton: list) -> list:
    """Merge Claude's per-slot content with Python's deterministic day_number/date/
    platform - Claude's output schema does not even include these fields, so there is
    nothing for it to get wrong here; this just zips the two positionally."""
    assembled = []
    for slot, item in zip(skeleton, claude_items):
        merged = dict(slot)
        merged.update(item)
        merged["status"] = "planned"
        if merged.get("verification_reason") == "":
            merged["verification_reason"] = None
        assembled.append(merged)
    return assembled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to the Stage 6 Content Strategy report.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to write the content calendar JSON.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="Number of days to plan (default: 7).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load/validate the Stage 6 report and prepare the Claude input, but skip the API call and output write.",
    )
    args = parser.parse_args()

    if args.days < 1:
        print("FAILED: --days must be a positive integer.")
        return 1

    load_dotenv()

    try:
        strategy = load_strategy_report(args.input)
    except DataError as e:
        print(f"FAILED: {e}")
        return 1

    evidence_item_count = sum(
        len(strategy.get(group, []))
        for group in ("content_opportunities", "strategy_themes", "recommended_formats", "recommended_tests")
    )
    print("=== Stage 6 input inspected ===")
    print(f"Top-level keys: {sorted(strategy.keys())}")
    print(
        f"content_opportunities={len(strategy.get('content_opportunities', []))}, "
        f"strategy_themes={len(strategy.get('strategy_themes', []))}, "
        f"recommended_formats={len(strategy.get('recommended_formats', []))}, "
        f"recommended_tests={len(strategy.get('recommended_tests', []))}"
    )
    print(f"Evidence items considered: {evidence_item_count}")
    print(f"known post_ids available as evidence: {len(known_post_ids(strategy))}")
    print()

    skeleton = build_calendar_skeleton(args.days)
    payload = build_calendar_payload(strategy, skeleton)
    print(f"=== Compact Calendar input prepared ({args.days}-day) ===")
    payload_json = json.dumps(payload, ensure_ascii=False)
    print(f"Approx payload size: {len(payload_json)} chars")
    gbp_days = sum(1 for slot in skeleton if slot["platform"] == "Google Business Profile")
    print(f"Platform mix: {args.days - gbp_days} Instagram, {gbp_days} Google Business Profile")
    print()

    if args.dry_run:
        print("DRY RUN: no Anthropic API call made, no output file written.")
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("FAILED: ANTHROPIC_API_KEY is not set.")
        print("Add it to your local .env file (see .env.example) and try again.")
        return 1

    import anthropic

    api_errors = (
        anthropic.AuthenticationError,
        anthropic.PermissionDeniedError,
        anthropic.NotFoundError,
        anthropic.RateLimitError,
        anthropic.APIConnectionError,
        anthropic.APIStatusError,
    )

    def describe_api_error(e) -> str:
        if isinstance(e, anthropic.AuthenticationError):
            return "Authentication error - the API key was rejected."
        if isinstance(e, anthropic.PermissionDeniedError):
            return "Permission denied - the API key lacks access to this model."
        if isinstance(e, anthropic.NotFoundError):
            return f"Model not found ({MODEL})."
        if isinstance(e, anthropic.RateLimitError):
            return "Rate limited. Try again in a moment."
        if isinstance(e, anthropic.APIConnectionError):
            return "Network error - could not reach the Anthropic API."
        return f"API error (status {e.status_code}): {extract_api_error_message(e)}"

    base_tokens, retry_tokens = token_budget(args.days)
    claude_result = None
    response = None
    last_error = None
    extra_note = None
    valid_post_ids = known_post_ids(strategy)

    # At most two Claude calls total, exactly like Stage 6: one normal attempt, one
    # retry only if the first was truncated, unparseable/invalid, or violated an
    # evidence-safety rule.
    for attempt, max_tokens in enumerate([base_tokens, retry_tokens], start=1):
        try:
            text, response = call_claude(api_key, payload, args.days, max_tokens=max_tokens, extra_note=extra_note)
        except TruncatedResponseError as e:
            last_error = str(e)
            if attempt == 1:
                print(f"{e} Retrying once with max_tokens={retry_tokens}...")
                continue
            print(f"FAILED: Response was truncated even at max_tokens={retry_tokens}. "
                  "The payload or requested output is too large for this budget.")
            return 1
        except api_errors as e:
            print(f"FAILED: {describe_api_error(e)}")
            return 1

        try:
            claude_result = extract_json_object(text)
            validate_calendar_response(claude_result)
        except (json.JSONDecodeError, DataError) as e:
            last_error = str(e)
            claude_result = None
            if attempt == 1:
                print(f"Claude's response was invalid ({e}) - retrying once with max_tokens={retry_tokens}...")
                extra_note = f"Your previous response was invalid ({e}). Return ONLY the corrected JSON object."
                continue
            print(f"FAILED: Claude did not return a valid, complete response after retry: {last_error}")
            return 1

        violations = find_calendar_violations(claude_result, valid_post_ids, args.days)
        if violations["hard"]:
            last_error = "; ".join(violations["hard"])
            if attempt == 1:
                print("Claude's response violated evidence-safety rules - retrying once:")
                for v in violations["hard"]:
                    print(f"  - {v}")
                extra_note = (
                    "Your previous response violated the evidence-safety rules and cannot be "
                    "published as-is. Fix these specific issues: " + " | ".join(violations["hard"])
                )
                claude_result = None
                continue
            print("FAILED: Claude's response still violates evidence-safety rules after retry:")
            for v in violations["hard"]:
                print(f"  - {v}")
            return 1
        break

    if claude_result is None:
        print(f"FAILED: Could not obtain a valid, safe response from Claude: {last_error}")
        return 1

    calendar_items = assemble_calendar_items(claude_result.get("calendar_items", []), skeleton)

    output = {
        "metadata": {
            "agent": "content_calendar",
            "source": str(args.input),
            "model": MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days": args.days,
            "evidence_items_considered": evidence_item_count,
        },
        "calendar_summary": claude_result.get("calendar_summary", "unknown"),
        "calendar_items": calendar_items,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("SUCCESS: Content Calendar generation complete.")
    print(f"Days planned: {args.days}")
    print(f"Evidence items considered: {evidence_item_count}")
    print(f"Model used: {MODEL}")
    print(f"Token usage: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
    input_cost = response.usage.input_tokens / 1_000_000 * 1.00
    output_cost = response.usage.output_tokens / 1_000_000 * 5.00
    print(f"Approx. cost (Haiku 4.5 list pricing): ${input_cost + output_cost:.4f} USD")
    print(f"Saved content calendar to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
