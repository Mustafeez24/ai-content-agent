"""
Content Generator for FlyingFish Scuba School (Stage 8).

Reads the existing Stage 7 Content Calendar (data/instagram/flyingfish_content_calendar.json)
and converts each already-planned calendar item into a production-ready content package -
a full Reel script, Carousel slide deck, Story frame sequence, Static/Educational Post copy,
or Google Business Profile post. This does NOT re-plan the calendar, choose a different
format/platform for any day, or re-run Stage 6/Stage 7 - it only expands what Stage 7 already
decided into something a content creator can shoot/write from.

ARCHITECTURE: reuses Stage 6/7's evidence-safety machinery directly (imported, not
duplicated) - the same causal-language check, competitor-claim check, calendar-period check,
and evidence vocabulary (evidence_type/confidence/requires_verification/verification_reason).
day_number/date/platform/content_type/topic/objective/target_audience/content_angle/priority
are carried forward from the Stage 7 calendar item exactly as Stage 7 produced them - Claude
never regenerates or overrides these here, so a content package can never drift from the plan
Stage 7 already validated. package_type (reel/carousel/story/static/gbp) is assigned
deterministically in Python from each item's platform/content_type, not chosen by Claude.
Every content package still carries its own evidence_basis/evidence_type/source_post_ids, so
new claims introduced while writing the actual script/caption text are checked for
evidence-safety independently of Stage 7's original (shorter) evidence_basis - a RAW DATA ->
OBSERVATION -> INTERPRETATION -> HYPOTHESIS -> RECOMMENDATION -> CONTENT pipeline, same shape
as Stage 6/7's.

FlyingFish shoots real footage (underwater, instructor, pool, boat, Goa, marine life,
customer). Nothing here may instruct AI-generated footage, and nothing may claim a specific
clip exists unless the input data says so - visual direction defaults to "use existing
FlyingFish footage if available."

Usage:
    source venv/bin/activate
    python scripts/content_generator.py                  # process the full available calendar
    python scripts/content_generator.py --days 7          # process only the first 7 planned days
    python scripts/content_generator.py --days 30         # process only the first 30 planned days
    python scripts/content_generator.py --dry-run         # validate + prepare input, no API call
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Reuse Stage 6's evidence-safety machinery and Stage 7's allowed-value vocabulary
# directly rather than re-implementing them - same causal-language/competitor-claim
# rules, same tolerant JSON extraction and API error handling, same content
# type/platform vocabulary Stage 7 already validated the calendar against.
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
from content_calendar import ALLOWED_CONTENT_TYPES, ALLOWED_PLATFORMS

DEFAULT_INPUT_PATH = Path("data/instagram/flyingfish_content_calendar.json")
OUTPUT_PATH = Path("data/instagram/flyingfish_content.json")
MODEL = "claude-haiku-4-5"  # same model/conventions as Stage 6/7

REQUIRED_CALENDAR_TOP_LEVEL = ["metadata", "calendar_summary", "calendar_items"]

# Every field Stage 7 guarantees on a calendar item - Stage 8 both requires these on
# load (a malformed/hand-edited calendar file fails clearly) and carries several of
# them straight through into the final content package untouched.
REQUIRED_CALENDAR_ITEM_FIELDS = [
    "day_number", "date", "platform", "content_type", "topic", "hook", "objective",
    "target_audience", "content_angle", "cta", "priority", "evidence_basis",
    "evidence_type", "source_post_ids", "confidence", "requires_verification",
    "verification_reason",
]

# Batches of ~5 calendar items per Claude call. Deliberately smaller than Stage 7's
# BATCH_SIZE=10: a calendar item is a few short evidence fields, but a content package
# is a full Reel script / Carousel slide deck - several times more output text per
# item - so the same real risk Stage 7 hit (an oversized single request tripping the
# Anthropic SDK's non-streaming 10-minute guard, or truncating output) reappears at a
# smaller item count here.
BATCH_SIZE = 5

ALLOWED_PACKAGE_TYPES = {"reel", "carousel", "story", "static", "gbp"}


class DataError(Exception):
    """Raised for problems with the Stage 7 input (missing file, bad JSON, missing
    sections, malformed calendar items, or no calendar items to generate content for)."""


def load_calendar(path: Path) -> dict:
    if not path.exists():
        raise DataError(f"Stage 7 Content Calendar not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Stage 7 calendar is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise DataError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_CALENDAR_TOP_LEVEL if key not in data]
    if missing:
        raise DataError(f"Stage 7 calendar is missing required section(s): {missing}")

    items = data.get("calendar_items")
    if not isinstance(items, list) or not items:
        raise DataError("Stage 7 calendar contains no calendar_items - there is nothing to generate content for.")

    day_numbers = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise DataError(f"calendar_items[{i}] is not an object.")
        missing_fields = [f for f in REQUIRED_CALENDAR_ITEM_FIELDS if f not in item]
        if missing_fields:
            raise DataError(f"calendar_items[{i}] is missing required field(s): {missing_fields}")
        if item["platform"] not in ALLOWED_PLATFORMS:
            raise DataError(f"calendar_items[{i}].platform is not one of {sorted(ALLOWED_PLATFORMS)}: {item['platform']!r}")
        if str(item["content_type"]).strip().lower() not in ALLOWED_CONTENT_TYPES:
            raise DataError(f"calendar_items[{i}].content_type is not a recognized Stage 7 format: {item['content_type']!r}")
        day_numbers.append(item["day_number"])

    if len(set(day_numbers)) != len(day_numbers):
        raise DataError(f"Stage 7 calendar has duplicate day_number values: {day_numbers}")

    return data


def known_post_ids(calendar: dict) -> set:
    """Every post_id Stage 8 is allowed to cite - the union of every source_post_ids
    array Stage 7 already validated against real Instagram data. Nothing outside this
    set was ever verified."""
    ids = set()
    for item in calendar.get("calendar_items", []):
        if isinstance(item, dict):
            ids.update(item.get("source_post_ids") or [])
    return ids


def package_type_for_item(item: dict) -> str:
    """Deterministic mapping from Stage 7's platform/content_type to the content
    package shape to generate - never chosen by Claude. Google Business Profile has no
    Reel/Carousel/Story equivalent, so platform always wins over content_type for GBP
    days; every other content_type maps onto one of the four Instagram package shapes
    without inventing a new taxonomy."""
    if item["platform"] == "Google Business Profile":
        return "gbp"
    content_type = str(item["content_type"]).strip().lower()
    if content_type == "reel":
        return "reel"
    if content_type == "carousel":
        return "carousel"
    if content_type == "story":
        return "story"
    # static post, educational post, faq, q&a, community content - all are body-copy
    # posts with a headline/body/caption/CTA shape, not a scene/slide/frame sequence.
    return "static"


def build_batches(items: list, batch_size: int = BATCH_SIZE) -> list:
    """Split the (already day_number-ordered) selected calendar items into batch_size
    chunks, in order."""
    return [items[i : i + batch_size] for i in range(0, len(items), batch_size)]


def build_content_payload(batch_items: list) -> dict:
    """Compact input for Claude - only what's needed to safely write each package: the
    Stage 7 plan for each slot in this batch (never the whole calendar), plus the
    post_ids actually cited by THIS batch's items (not the full calendar's pool)."""
    slots = []
    batch_post_ids = set()
    for item in batch_items:
        slots.append(
            {
                "day_number": item["day_number"],
                "platform": item["platform"],
                "content_type": item["content_type"],
                "package_type": package_type_for_item(item),
                "topic": item["topic"],
                "planned_hook": item["hook"],
                "objective": item["objective"],
                "target_audience": item["target_audience"],
                "content_angle": item["content_angle"],
                "planned_cta": item["cta"],
                "priority": item["priority"],
                "evidence_basis": item["evidence_basis"],
                "evidence_type": item["evidence_type"],
                "source_post_ids": item.get("source_post_ids") or [],
                "confidence": item["confidence"],
            }
        )
        batch_post_ids.update(item.get("source_post_ids") or [])
    return {"content_slots": slots, "known_post_ids": sorted(batch_post_ids)}


def _build_system_prompt(batch_size: int) -> str:
    return f"""You are the Content Generator for FlyingFish Scuba School, a scuba diving \
school at Novotel Resort & Spa, Candolim, Goa, India, offering SSI and PADI certifications.

You will receive "content_slots" - exactly {batch_size} already-planned calendar days from \
Stage 7 (a longer run is generated as several smaller batches; you only ever see one \
batch's slots at a time). Each slot fixes platform, content_type, and package_type - these \
are NOT yours to change. Your job is to turn each slot's topic/planned_hook/objective/ \
target_audience/content_angle/planned_cta/evidence_basis into ONE production-ready content \
package, in the SAME ORDER as content_slots. Return EXACTLY {batch_size} content items - one \
per supplied slot, never more, never fewer. item[i] corresponds to content_slots[i]. Do NOT \
generate day_number, platform, content_type, or package_type yourself - those are not part \
of your output schema.

PACKAGE SHAPES (fill only the fields that apply to a slot's package_type; leave every other \
field an empty string or empty array - do not omit fields, the schema requires all of them):
- package_type="reel": "hook" (first 1-3 seconds, must earn attention), "script_scenes" \
(at least 2 entries, one string per scene, each stating the visual direction, an \
approximate duration, the on-screen text, and the point that scene makes), "caption" \
(concise, natural, few or no hashtags), "cta". Leave "slides"/"frames"/"headline"/"body"/ \
"interaction_suggestion" empty.
- package_type="carousel": "hook" (slide 1's hook), "slides" (at least 3 entries, one \
string per slide - slide 1 restates the hook, the middle slides each make ONE educational/ \
body point, the last slide is the CTA slide), "caption", "cta". Leave "script_scenes"/ \
"frames"/"headline"/"body"/"interaction_suggestion" empty.
- package_type="story": "frames" (at least 2 entries, one short conversational string per \
frame), "interaction_suggestion" (a poll/question ONLY if genuinely relevant to this frame \
sequence - leave it "" rather than forcing one), "cta". Leave "hook"/"script_scenes"/ \
"slides"/"headline"/"body"/"caption" empty.
- package_type="static": "headline" is MANDATORY - a specific, non-empty headline; NEVER leave \
it blank. "body" is MANDATORY - the post's main copy; NEVER leave it blank, and NEVER fill it \
with placeholder or filler text - it must contain useful, specific content a reader could act \
on, grounded in the slot's topic/content_angle/evidence_basis. "caption" is required, and "cta" \
is MANDATORY. A Static Post with an empty headline, an empty body, or a missing CTA is invalid \
and will be rejected - if you are unsure what to write, ground it in the slot data rather than \
leaving the field blank. Leave "hook"/"script_scenes"/"slides"/"frames"/"interaction_suggestion" \
empty.
- package_type="gbp": "headline" is MANDATORY (specific, non-empty - never blank). "body" is \
MANDATORY (useful local/business information, natural local relevance, no keyword stuffing - \
never blank and never placeholder/filler text). "cta" is MANDATORY. Google Business Profile \
posts read differently from Instagram - shorter, no hashtags, more direct/informational. A GBP \
post with an empty headline or body is invalid and will be rejected. Leave "hook"/ \
"script_scenes"/"slides"/"frames"/"interaction_suggestion"/"caption" empty.

"footage_note" applies to reel/carousel/story/static (leave it "" for gbp): describe the \
visual source in plain terms - existing FlyingFish underwater footage, instructor footage, \
pool training footage, boat footage, real Goa footage, real marine-life footage, customer \
footage, or existing brand assets. If you are not certain footage exists for an idea, say \
"Use existing FlyingFish footage if available." NEVER instruct AI-generated footage, an \
AI-generated video/clip, or any AI image/video generation tool, and never claim a specific \
clip exists unless the slot's evidence says so.

DO NOT INVENT FACTS. Never state, as if true, any of the following unless it is explicitly \
present in the slot data you were given: prices, discounts, offers, promotions, specific dive \
depths, specific dive durations, facility details, safety guarantees, customer/student \
counts, engagement or performance statistics, guarantees of any kind, or availability \
claims (e.g. "book now", "slots available today"). A CTA that invites someone to ask/DM/ \
message for pricing or availability is fine (it invents nothing); stating an actual price, \
percentage discount, or "available today" is not. If an idea genuinely needs information you \
were not given, write the content around what IS supported and set requires_verification=true \
with a verification_reason explaining exactly what needs checking - never silently fabricate \
the missing detail.

You build every claim through this pipeline - each stage may ONLY do its own job:

  RAW DATA -> OBSERVATION -> INTERPRETATION -> HYPOTHESIS -> RECOMMENDATION -> CONTENT

  Example - RAW DATA (given to you, from Stage 7): evidence_basis "The supplied dataset \
  contains a high-performing testimonial example (DWyk4T6E5OF) featuring instructor praise."
  BAD CONTENT: "Emotional testimonials drive engagement, so this Reel will get more comments."
  GOOD CONTENT: "The supplied dataset includes a high-performing post featuring an emotional \
  student testimonial." (stated as what was observed) - and if you want to propose testing \
  the idea further, phrase it as a hypothesis: "Test hypothesis: testimonial-led storytelling \
  may be useful to test again." Never present a hypothesis as an already-proven fact.

"evidence_basis" is a STRICT OBSERVATIONAL FIELD, exactly like Stage 6/7's - it may state \
ONLY what the supplied evidence actually shows, using words like: is associated with, was \
observed in, achieved, received, recorded, shows, features, contains, includes, had. NEVER \
use, in any tense: drive, drives, driving, drove, driven, boost, boosts, causes, caused, \
generates, generated, increases, increased, leads to, led to, results in, resulted in, \
"primary driver"/"engagement driver", proven, guarantees. If a content idea is not directly \
evidenced, say so plainly and set evidence_type="hypothesis" - never dress up a hypothesis as \
an observed fact.
  BAD: "This content uses marine-life interest to drive booking motivation."
  GOOD: "This content tests a static-post format using the documented marine-life interest pattern."
  GOOD (hypothesis framing): "Hypothesis: marine-life-focused static content may be useful to \
  test for booking interest."
  Only use hypothesis framing when appropriate - do not hedge every sentence into a hypothesis \
  just to avoid the causal-language check.

COMPETITOR CLAIMS - never state a specific fact about how competitors are positioned or what \
they do, in ANY field - not even softened with "may" or "likely". If no competitor data was \
supplied, do not mention competitors at all.

Creative fields (hook, script_scenes, slides, frames, interaction_suggestion, headline, body, \
caption, cta, footage_note) should read naturally, specifically, and usefully enough that a \
content creator can shoot/publish from them without more direction - never generic filler \
like "Create content about beginner scuba." Keep content educational, useful, beginner- \
friendly where appropriate, non-spammy, and brand-consistent; not every post is promotional. \
Never reference or invent a specific past or future calendar quarter or year - use the \
planning context you were given instead.

FIELD CONVENTIONS (validated after your response is parsed):
- "evidence_type" must be exactly one of: observed, interpretation, hypothesis, recommendation.
- "confidence" must be exactly one of: high, medium, low.
- "source_post_ids": list only post_ids from "known_post_ids", or an empty array if the \
content is a hypothesis not tied to specific posts. If evidence_type is "observed" or \
"interpretation", you MUST cite at least one post_id here.
- "verification_reason" is a string: your explanation when requires_verification is true, or \
an empty string "" when requires_verification is false.

Respond with ONLY a single valid JSON object (no markdown code fences, no commentary before \
or after) matching exactly the schema you are given."""


CONTENT_GENERATOR_SYSTEM_PROMPT_CACHE = {}


def build_system_prompt(batch_size: int) -> str:
    if batch_size not in CONTENT_GENERATOR_SYSTEM_PROMPT_CACHE:
        CONTENT_GENERATOR_SYSTEM_PROMPT_CACHE[batch_size] = _build_system_prompt(batch_size)
    return CONTENT_GENERATOR_SYSTEM_PROMPT_CACHE[batch_size]


# Deliberately flat and non-nested, same reasoning as Stage 6/7: 0 enums, 0 unions,
# every field a plain string/array/bool, additionalProperties=false. Allowed values
# (evidence_type/confidence) and package-shape requirements (which fields must be
# non-empty for which package_type) are enforced in Python by find_content_violations()
# instead of in the schema.
_CONTENT_EVIDENCE_FIELDS = {
    "evidence_basis": {"type": "string"},
    "evidence_type": {"type": "string"},
    "source_post_ids": {"type": "array", "items": {"type": "string"}},
    "confidence": {"type": "string"},
    "requires_verification": {"type": "boolean"},
    "verification_reason": {"type": "string"},
}
_CONTENT_EVIDENCE_FIELD_NAMES = list(_CONTENT_EVIDENCE_FIELDS.keys())

_CONTENT_ITEM_CREATIVE_FIELDS = (
    "hook", "script_scenes", "slides", "frames", "interaction_suggestion",
    "headline", "body", "caption", "cta", "footage_note",
)
# Text-only creative fields (excludes the two array fields, which are joined
# separately wherever combined text is needed for a regex scan).
_CONTENT_ITEM_TEXT_FIELDS = (
    "hook", "interaction_suggestion", "headline", "body", "caption", "cta", "footage_note",
)
_CONTENT_ITEM_ARRAY_FIELDS = ("script_scenes", "slides", "frames")

CONTENT_GENERATOR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "content_summary": {"type": "string"},
        "content_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hook": {"type": "string"},
                    "script_scenes": {"type": "array", "items": {"type": "string"}},
                    "slides": {"type": "array", "items": {"type": "string"}},
                    "frames": {"type": "array", "items": {"type": "string"}},
                    "interaction_suggestion": {"type": "string"},
                    "headline": {"type": "string"},
                    "body": {"type": "string"},
                    "caption": {"type": "string"},
                    "cta": {"type": "string"},
                    "footage_note": {"type": "string"},
                    **_CONTENT_EVIDENCE_FIELDS,
                },
                "required": [*_CONTENT_ITEM_CREATIVE_FIELDS, *_CONTENT_EVIDENCE_FIELD_NAMES],
                "additionalProperties": False,
            },
        },
    },
    "required": ["content_summary", "content_items"],
    "additionalProperties": False,
}

# Content packages are much larger than Stage 7's short calendar items (a full Reel
# script vs. a few evidence sentences), so the per-item budget is higher even though
# batches are smaller.
TOKENS_OVERHEAD_BASE = 2000
TOKENS_PER_ITEM_BASE = 1600
TOKENS_OVERHEAD_RETRY = 2500
TOKENS_PER_ITEM_RETRY = 2400


def token_budget_for_batch(batch_size: int) -> tuple:
    base = TOKENS_OVERHEAD_BASE + TOKENS_PER_ITEM_BASE * batch_size
    retry = TOKENS_OVERHEAD_RETRY + TOKENS_PER_ITEM_RETRY * batch_size
    return base, retry


class TruncatedResponseError(Exception):
    """Raised when Claude's response was cut off by the token limit before completing."""


def call_claude(api_key: str, payload: dict, batch_size: int, max_tokens: int, extra_note: str = None) -> tuple:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        "Here are the fixed Stage 7 calendar slots for FlyingFish Scuba School to turn into "
        f"production-ready content packages. Return exactly {batch_size} content items, one per "
        "supplied slot, never more. Build every package strictly from this evidence.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    if extra_note:
        user_message += f"\n\nCORRECTION REQUIRED: {extra_note}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=build_system_prompt(batch_size),
        messages=[{"role": "user", "content": user_message}],
        output_config={"format": {"type": "json_schema", "schema": CONTENT_GENERATOR_RESPONSE_SCHEMA}},
    )

    if response.stop_reason == "max_tokens":
        raise TruncatedResponseError(
            f"Response was cut off by the max_tokens limit ({max_tokens}) before it finished."
        )

    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response


REQUIRED_RESPONSE_FIELDS = {
    "content_summary": str,
    "content_items": list,
}


def validate_content_response(data) -> None:
    """Fail clearly and specifically rather than silently assembling an incomplete package set."""
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


# --- FlyingFish-fact-safety patterns (beyond causal-language/competitor/calendar-period,
# which are imported from Stage 6) -------------------------------------------------

# A numeric price/currency claim - hard violation unless explicitly verified, same
# escape valve as the competitor-claim check (requires_verification=true + a real
# verification_reason).
_PRICE_CLAIM_RE = re.compile(
    r"(?:₹|Rs\.?\s?|INR\s?|\$|USD\s?)\s?[\d][\d,]*(?:\.\d+)?"
    r"|\b[\d,]+(?:\.\d+)?\s?(?:rupees|dollars)\b",
    re.IGNORECASE,
)
# A specific offer/discount/promotion claim - same hard-unless-verified treatment.
_OFFER_CLAIM_RE = re.compile(
    r"\bspecial\s+offer\b|\blimited[- ]time\s+offer\b|\bpromo(?:tion)?s?\b|"
    r"\bdiscount(?:ed|s)?\b|\bvoucher[s]?\b|\bcoupon[s]?\b|\b\d+%\s*off\b|"
    r"\bearly[- ]bird\b|\bsale\b|\bfree\s+(?:dive|session|trial|course|consultation)\b",
    re.IGNORECASE,
)
# Other unsupported-fact categories (certifications/awards/experience claims, customer/
# performance counts, guarantees, availability claims, specific dive depths/durations) -
# soft: auto-flagged (requires_verification set) rather than rejected, mirroring Stage
# 6's treatment of business facts.
_UNSUPPORTED_FACT_RE = re.compile(
    r"\bcertified\s+instructors?\b|\baward[- ]winning\b|\byears?\s+of\s+experience\b|"
    r"\b\d+\+?\s*(?:divers?|students?|customers?)\s+(?:trained|certified)\b|"
    r"\b\d+%\s*(?:success|satisfaction|pass)\s*rate\b|"
    r"\bguarantee[sd]?\b|\b100%\s*safe\b|\bcompletely\s+safe\b|"
    r"\bavailable\s+(?:now|today|daily|year[- ]round)\b|\bbook\s+now\b|\blimited\s+slots?\b|"
    r"\b\d{1,3}\s?(?:m|meters|metres|feet|ft)\b|"
    r"\b\d{1,3}\s?(?:minutes?|mins?|hours?|hrs?)\b",
    re.IGNORECASE,
)
# Stage 6's imported _causal_language_match() does not cover "boost"/"boosts" - this
# supplements it for evidence_basis only, without modifying Stage 6. Same hard,
# no-escape-valve treatment as every other causal-language violation.
_BOOST_CAUSAL_RE = re.compile(r"\bboosts?\b", re.IGNORECASE)

# AI-generated footage/video is never allowed, in any field, with no escape valve -
# FlyingFish's content strategy uses real footage only.
_AI_FOOTAGE_RE = re.compile(
    r"\bAI[- ]generat\w*\s+(?:footage|video|clip|underwater|scene)\b"
    r"|\bgenerat(?:e|es|ed|ing)\s+(?:footage|video|clip)s?\s+(?:using|with|via)\s+AI\b"
    r"|\bsynthetic(?:ally)?\s+generat\w*\s+(?:footage|video|underwater)\b"
    r"|\b(?:midjourney|stable\s+diffusion|runway\s*ml|sora|dall-?e)\b",
    re.IGNORECASE,
)

_VAGUE_PHRASES = (
    "create content about", "post something educational", "write a caption",
    "make a reel about", "engaging content for instagram", "post content",
    "engage the audience", "post an educational reel",
)


def _contains_vague_phrase(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _VAGUE_PHRASES)


# Minimum lengths - loose thresholds meant to catch empty/placeholder content, not to
# police writing quality.
_MIN_HOOK_LENGTH = 10
_MIN_SCENE_LENGTH = 15
_MIN_SLIDE_LENGTH = 8
_MIN_FRAME_LENGTH = 8
_MIN_HEADLINE_LENGTH = 5
_MIN_BODY_LENGTH = 20
_MIN_CAPTION_LENGTH = 8
_MIN_CTA_LENGTH = 5
_MIN_FOOTAGE_NOTE_LENGTH = 10
_MIN_REEL_SCENES = 2
_MIN_CAROUSEL_SLIDES = 3
_MIN_STORY_FRAMES = 2

# Whether footage_note is required (non-empty) for a given package_type - static posts
# and stories/reels/carousels all need a real visual source; GBP posts don't.
_FOOTAGE_REQUIRED_PACKAGE_TYPES = {"reel", "carousel", "story", "static"}


def _item_combined_text(item: dict) -> str:
    parts = [str(item.get(f, "")) for f in _CONTENT_ITEM_TEXT_FIELDS if item.get(f)]
    for f in _CONTENT_ITEM_ARRAY_FIELDS:
        parts.extend(str(s) for s in (item.get(f) or []) if s)
    parts.append(str(item.get("evidence_basis", "")))
    return " ".join(parts)


def _visual_field_text(item: dict) -> str:
    """Only the fields describing actual visuals - what the AI-generated-footage check
    scans, since that rule is specifically about how footage is sourced/directed."""
    parts = [str(item.get("footage_note", ""))]
    for f in ("script_scenes", "slides", "frames"):
        parts.extend(str(s) for s in (item.get(f) or []) if s)
    return " ".join(parts)


def find_content_violations(data: dict, valid_post_ids: set, expected_count: int, package_types: list) -> dict:
    """Check content_items against the hardening rules, mirroring Stage 6/7's
    hard-vs-soft violation model. package_types[i] is the package_type Python assigned
    to slot i (never chosen by Claude) and drives which structural checks apply to
    content_items[i]. Returns {"hard": [...], "soft": [{"loc","type","detail"}, ...]}."""
    hard = []
    soft = []

    items = data.get("content_items", [])
    if len(items) != expected_count:
        hard.append(
            f"content_items must contain exactly {expected_count} item(s) (one per supplied "
            f"content slot), got {len(items)}"
        )

    for i, item in enumerate(items):
        loc = f"content_items[{i}]"
        if not isinstance(item, dict):
            hard.append(f"{loc}: expected an object, got {type(item).__name__}")
            continue

        package_type = package_types[i] if i < len(package_types) else None

        # --- structural checks per package_type ---
        if package_type == "reel":
            hook = str(item.get("hook", "")).strip()
            if len(hook) < _MIN_HOOK_LENGTH or _contains_vague_phrase(hook):
                hard.append(f"{loc}.hook: missing/too short/vague for a Reel: {hook!r}")
            scenes = item.get("script_scenes") or []
            if len(scenes) < _MIN_REEL_SCENES:
                hard.append(f"{loc}.script_scenes: a Reel needs at least {_MIN_REEL_SCENES} scenes, got {len(scenes)}")
            for j, scene in enumerate(scenes):
                if len(str(scene).strip()) < _MIN_SCENE_LENGTH:
                    hard.append(f"{loc}.script_scenes[{j}]: too short/empty to be actionable: {scene!r}")
            caption = str(item.get("caption", "")).strip()
            if len(caption) < _MIN_CAPTION_LENGTH:
                hard.append(f"{loc}.caption: missing/too short for a Reel: {caption!r}")
        elif package_type == "carousel":
            hook = str(item.get("hook", "")).strip()
            if len(hook) < _MIN_HOOK_LENGTH or _contains_vague_phrase(hook):
                hard.append(f"{loc}.hook: missing/too short/vague for a Carousel slide 1: {hook!r}")
            slides = item.get("slides") or []
            if len(slides) < _MIN_CAROUSEL_SLIDES:
                hard.append(f"{loc}.slides: a Carousel needs at least {_MIN_CAROUSEL_SLIDES} slides, got {len(slides)}")
            for j, slide in enumerate(slides):
                if len(str(slide).strip()) < _MIN_SLIDE_LENGTH:
                    hard.append(f"{loc}.slides[{j}]: too short/empty to be actionable: {slide!r}")
            caption = str(item.get("caption", "")).strip()
            if len(caption) < _MIN_CAPTION_LENGTH:
                hard.append(f"{loc}.caption: missing/too short for a Carousel: {caption!r}")
        elif package_type == "story":
            frames = item.get("frames") or []
            if len(frames) < _MIN_STORY_FRAMES:
                hard.append(f"{loc}.frames: a Story needs at least {_MIN_STORY_FRAMES} frames, got {len(frames)}")
            for j, frame in enumerate(frames):
                if len(str(frame).strip()) < _MIN_FRAME_LENGTH:
                    hard.append(f"{loc}.frames[{j}]: too short/empty to be actionable: {frame!r}")
        elif package_type == "static":
            headline = str(item.get("headline", "")).strip()
            if len(headline) < _MIN_HEADLINE_LENGTH or _contains_vague_phrase(headline):
                hard.append(f"{loc}.headline: missing/too short/vague for a Static Post: {headline!r}")
            body = str(item.get("body", "")).strip()
            if len(body) < _MIN_BODY_LENGTH or _contains_vague_phrase(body):
                hard.append(f"{loc}.body: missing/too short/vague for a Static Post: {body!r}")
            caption = str(item.get("caption", "")).strip()
            if len(caption) < _MIN_CAPTION_LENGTH:
                hard.append(f"{loc}.caption: missing/too short for a Static Post: {caption!r}")
        elif package_type == "gbp":
            headline = str(item.get("headline", "")).strip()
            if len(headline) < _MIN_HEADLINE_LENGTH or _contains_vague_phrase(headline):
                hard.append(f"{loc}.headline: missing/too short/vague for a Google Business Profile post: {headline!r}")
            body = str(item.get("body", "")).strip()
            if len(body) < _MIN_BODY_LENGTH or _contains_vague_phrase(body):
                hard.append(f"{loc}.body: missing/too short/vague for a Google Business Profile post: {body!r}")

        cta = str(item.get("cta", "")).strip()
        if len(cta) < _MIN_CTA_LENGTH:
            hard.append(f"{loc}.cta: missing/too short to be actionable: {cta!r}")

        if package_type in _FOOTAGE_REQUIRED_PACKAGE_TYPES:
            footage_note = str(item.get("footage_note", "")).strip()
            if len(footage_note) < _MIN_FOOTAGE_NOTE_LENGTH:
                hard.append(f"{loc}.footage_note: missing/too short - must state a real footage source: {footage_note!r}")

        # --- evidence-safety checks (same shape as Stage 6/7) ---
        evidence_type = item.get("evidence_type")
        if evidence_type not in ALLOWED_EVIDENCE_TYPES:
            hard.append(f"{loc}.evidence_type must be one of {sorted(ALLOWED_EVIDENCE_TYPES)}, got {evidence_type!r}")

        confidence = item.get("confidence")
        if confidence not in ALLOWED_CONFIDENCE_LEVELS:
            hard.append(f"{loc}.confidence must be one of {sorted(ALLOWED_CONFIDENCE_LEVELS)}, got {confidence!r}")

        source_post_ids = item.get("source_post_ids") or []
        invalid_ids = [pid for pid in source_post_ids if pid not in valid_post_ids]
        if invalid_ids:
            hard.append(f"{loc}: source_post_ids references post_id(s) not in the supplied Stage 7 evidence: {invalid_ids}")

        if evidence_type in ("observed", "interpretation") and not source_post_ids:
            hard.append(
                f"{loc}: evidence_type={evidence_type!r} but source_post_ids is empty - an observed/"
                "interpretation claim must cite at least one source_post_id"
            )

        evidence_basis = item.get("evidence_basis", "")
        if isinstance(evidence_basis, str):
            causal = _causal_language_match(evidence_basis)
            if causal:
                phrase, sentence = causal
                hard.append(
                    f"{loc}.evidence_basis: uses unsupported causal language ({phrase!r}) - state "
                    f"only what was observed, or mark evidence_type='hypothesis': {sentence!r}"
                )
            boost_match = _BOOST_CAUSAL_RE.search(evidence_basis)
            if boost_match:
                hard.append(
                    f"{loc}.evidence_basis: uses unsupported causal language ({boost_match.group(0)!r}) - state "
                    f"only what was observed, or mark evidence_type='hypothesis': {evidence_basis!r}"
                )

        combined_text = _item_combined_text(item)
        requires_verification = bool(item.get("requires_verification", False))
        verification_reason = str(item.get("verification_reason") or "").strip()
        verified = requires_verification and bool(verification_reason)

        if _COMPETITOR_RE.search(combined_text) and not _COMPETITOR_HEDGE_RE.search(combined_text) and not verified:
            hard.append(
                f"{loc}: makes a competitor claim without competitor data, without hedged 'validation "
                f"required' phrasing, and without requires_verification=true + a verification_reason"
            )
        if _CALENDAR_PERIOD_RE.search(combined_text):
            hard.append(f"{loc}: contains a hardcoded calendar quarter/year instead of a relative reference")
        if _PRICE_CLAIM_RE.search(combined_text) and not verified:
            hard.append(
                f"{loc}: states a specific price/currency amount without requires_verification=true + "
                "a verification_reason - prices are never supplied to this system and must never be invented"
            )
        if _OFFER_CLAIM_RE.search(combined_text) and not verified:
            hard.append(
                f"{loc}: states a specific offer/discount/promotion without requires_verification=true + "
                "a verification_reason - offers are never supplied to this system and must never be invented"
            )

        visual_text = _visual_field_text(item)
        if _AI_FOOTAGE_RE.search(visual_text):
            hard.append(
                f"{loc}: instructs AI-generated footage/video - FlyingFish's content strategy uses real "
                "footage only; use 'Use existing FlyingFish footage if available.' instead"
            )

        if not requires_verification and _UNSUPPORTED_FACT_RE.search(combined_text):
            soft.append(
                {
                    "loc": loc,
                    "type": "flag_verification",
                    "detail": "references a specific factual claim (certification/award/experience, "
                    "customer or performance count, guarantee, availability, or a specific dive depth/"
                    "duration) not supplied as verified context",
                }
            )

    return {"hard": hard, "soft": soft}


def apply_auto_corrections(content_items: list, violations: dict) -> int:
    """Apply soft-violation corrections in place (auto-flag requires_verification).
    Returns the number applied."""
    count = 0
    soft_by_loc = {}
    for v in violations["soft"]:
        soft_by_loc.setdefault(v["loc"], []).append(v)

    for i, item in enumerate(content_items):
        loc = f"content_items[{i}]"
        for v in soft_by_loc.get(loc, []):
            if v["type"] == "flag_verification" and not item.get("requires_verification"):
                item["requires_verification"] = True
                existing = item.get("verification_reason")
                note = f"auto-flagged: {v['detail']}"
                item["verification_reason"] = f"{existing}; {note}" if existing else note
                count += 1
    return count


def assemble_content_items(claude_items: list, calendar_items: list) -> list:
    """Merge Claude's per-slot content package with the deterministic planning fields
    carried forward from the Stage 7 calendar item - Claude's output schema does not
    even include day_number/platform/content_type/topic/etc, so there is nothing for
    it to get wrong here; this just zips the two positionally."""
    assembled = []
    for calendar_item, content_item in zip(calendar_items, claude_items):
        merged = {
            "day_number": calendar_item["day_number"],
            "date": calendar_item["date"],
            "platform": calendar_item["platform"],
            "content_type": calendar_item["content_type"],
            "package_type": package_type_for_item(calendar_item),
            "topic": calendar_item["topic"],
            "objective": calendar_item["objective"],
            "target_audience": calendar_item["target_audience"],
            "content_angle": calendar_item["content_angle"],
            "priority": calendar_item["priority"],
        }
        merged.update(content_item)
        merged["status"] = "drafted"
        if merged.get("verification_reason") == "":
            merged["verification_reason"] = None
        assembled.append(merged)
    return assembled


# --- package-specific retry feedback -----------------------------------------------
#
# find_content_violations() returns flat, precisely-worded strings (unchanged - so
# every existing check on violations["hard"] keeps working). build_retry_feedback()
# re-organizes those same strings into package-specific, actionable correction blocks
# for the retry prompt, instead of handing Claude one long "|"-joined dump of internal
# validator messages. Nothing here changes what is rejected - only how the correction
# is explained. Any violation that doesn't match a known category still appears
# verbatim, so a correction is never silently dropped.

_ITEM_LOC_RE = re.compile(r"content_items\[(\d+)\]")
_STATIC_FIELD_RE = re.compile(r"content_items\[(\d+)\]\.(?:headline|body)\b")
_REEL_HOOK_RE = re.compile(r"content_items\[(\d+)\]\.hook\b")
_SCRIPT_SCENES_RE = re.compile(r"content_items\[(\d+)\]\.script_scenes")
_SLIDES_RE = re.compile(r"content_items\[(\d+)\]\.slides")
_FRAMES_RE = re.compile(r"content_items\[(\d+)\]\.frames")
_CTA_FIELD_RE = re.compile(r"content_items\[(\d+)\]\.cta\b")
_FOOTAGE_FIELD_RE = re.compile(r"content_items\[(\d+)\]\.footage_note\b")
_EVIDENCE_BASIS_CAUSAL_VIOLATION_RE = re.compile(
    r"content_items\[(\d+)\]\.evidence_basis: uses unsupported causal language"
)
_COMPETITOR_VIOLATION_RE = re.compile(r"content_items\[(\d+)\]: makes a competitor claim")
_PRICE_VIOLATION_RE = re.compile(r"content_items\[(\d+)\]: states a specific price")
_OFFER_VIOLATION_RE = re.compile(r"content_items\[(\d+)\]: states a specific offer")
_AI_FOOTAGE_VIOLATION_RE = re.compile(r"content_items\[(\d+)\]: instructs AI-generated footage")
_POST_ID_VIOLATION_RE = re.compile(r"content_items\[(\d+)\]: source_post_ids references")

_EVIDENCE_BASIS_BANNED_WORDS = (
    "drive, drives, driving, boost, boosts, causes, caused, leads to, resulted in, "
    "engagement driver, primary driver"
)


def build_retry_feedback(hard_violations: list, package_types: list) -> str:
    """Turn find_content_violations()'s hard-violation strings into package-specific,
    structured correction instructions for the retry prompt (see module comment
    above). Each distinct (category, item index) is emitted once."""

    def _package_for(index):
        return package_types[index] if index is not None and index < len(package_types) else None

    blocks = []
    seen = set()

    def _emit(key, text):
        if key not in seen:
            seen.add(key)
            blocks.append(text)

    for v in hard_violations:
        m = _STATIC_FIELD_RE.search(v)
        if m and _package_for(int(m.group(1))) in ("static", "gbp"):
            index = int(m.group(1))
            package = _package_for(index)
            label = "STATIC POST" if package == "static" else "GOOGLE BUSINESS PROFILE POST"
            _emit(
                (package, index),
                f"{label} CORRECTION (content_items[{index}]):\n"
                f"The previous response contained an invalid {label.title()} with an empty or "
                "too-short headline/body.\nRegenerate that item with:\n"
                "- a specific, non-empty headline\n"
                "- useful body copy grounded in the slot's topic/content_angle/evidence_basis "
                "(never placeholder text)\n"
                "- a CTA\n"
                "Do not leave any required field empty.",
            )
            continue

        m = _EVIDENCE_BASIS_CAUSAL_VIOLATION_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("evidence_basis", index),
                f"evidence_basis CORRECTION (content_items[{index}]):\n"
                f"Remove unsupported causal wording such as:\n{_EVIDENCE_BASIS_BANNED_WORDS}.\n"
                "State only what the supplied evidence directly supports, or explicitly classify "
                "the reasoning as a hypothesis where appropriate.",
            )
            continue

        m = _REEL_HOOK_RE.search(v)
        if m and _package_for(int(m.group(1))) == "reel":
            index = int(m.group(1))
            _emit(
                ("reel_hook", index),
                f"REEL CORRECTION (content_items[{index}]): hook is empty - provide a specific first-second hook.",
            )
            continue

        m = _SCRIPT_SCENES_RE.search(v)
        if m and _package_for(int(m.group(1))) == "reel":
            index = int(m.group(1))
            _emit(
                ("reel_script", index),
                f"REEL CORRECTION (content_items[{index}]): script is missing or incomplete - provide "
                "at least 2 meaningful scenes.",
            )
            continue

        m = _SLIDES_RE.search(v)
        if m and _package_for(int(m.group(1))) == "carousel":
            index = int(m.group(1))
            _emit(
                ("carousel_slides", index),
                f"CAROUSEL CORRECTION (content_items[{index}]): slide count is invalid - provide the "
                "required number of meaningful slides.",
            )
            continue

        m = _FRAMES_RE.search(v)
        if m and _package_for(int(m.group(1))) == "story":
            index = int(m.group(1))
            _emit(
                ("story_frames", index),
                f"STORY CORRECTION (content_items[{index}]): frame content is missing - provide "
                "meaningful frame-by-frame content.",
            )
            continue

        m = _AI_FOOTAGE_VIOLATION_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("ai_footage", index),
                f"FOOTAGE CORRECTION (content_items[{index}]): never instruct AI-generated footage/video - "
                "use real FlyingFish footage, or 'Use existing FlyingFish footage if available.'.",
            )
            continue

        m = _COMPETITOR_VIOLATION_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("competitor", index),
                f"COMPETITOR CLAIM CORRECTION (content_items[{index}]): remove the unhedged competitor "
                "claim, or set requires_verification=true with a verification_reason.",
            )
            continue

        m = _PRICE_VIOLATION_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("price", index),
                f"PRICE CLAIM CORRECTION (content_items[{index}]): remove the invented price/currency "
                "amount, or set requires_verification=true with a verification_reason.",
            )
            continue

        m = _OFFER_VIOLATION_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("offer", index),
                f"OFFER/DISCOUNT CLAIM CORRECTION (content_items[{index}]): remove the invented offer/ "
                "discount, or set requires_verification=true with a verification_reason.",
            )
            continue

        m = _POST_ID_VIOLATION_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("post_id", index),
                f"SOURCE POST ID CORRECTION (content_items[{index}]): only cite post_ids from "
                "known_post_ids, or use an empty array for a hypothesis.",
            )
            continue

        m = _FOOTAGE_FIELD_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("footage_note", index),
                f"FOOTAGE CORRECTION (content_items[{index}]): footage_note is empty - state a real "
                "footage source, or 'Use existing FlyingFish footage if available.'.",
            )
            continue

        m = _CTA_FIELD_RE.search(v)
        if m:
            index = int(m.group(1))
            _emit(
                ("cta", index),
                f"CTA CORRECTION (content_items[{index}]): cta is empty - provide a complete, actionable CTA.",
            )
            continue

        # No specific template matched - surface the raw validator message verbatim so
        # nothing is silently dropped from the retry feedback.
        _emit(("other", v), f"OTHER CORRECTION: {v}")

    return "\n\n".join(blocks)


def generate_batch(
    api_key: str,
    batch_items: list,
    valid_post_ids: set,
    api_errors: tuple,
    describe_api_error,
) -> tuple:
    """Generate and validate ONE batch (at most BATCH_SIZE calendar slots), using the
    same bounded 2-call retry architecture as Stage 6/7: one normal attempt, one retry
    only if the first was truncated, unparseable/invalid, or violated a hardening rule
    - never silently accepted. Returns (content_items, content_summary, response,
    error_message): on failure, content_items and content_summary are None and
    error_message is set; on success error_message is None."""
    batch_size = len(batch_items)
    package_types = [package_type_for_item(item) for item in batch_items]
    payload = build_content_payload(batch_items)
    base_tokens, retry_tokens = token_budget_for_batch(batch_size)
    claude_result = None
    response = None
    last_error = None
    extra_note = None

    for attempt, max_tokens in enumerate([base_tokens, retry_tokens], start=1):
        try:
            text, response = call_claude(api_key, payload, batch_size, max_tokens=max_tokens, extra_note=extra_note)
        except TruncatedResponseError as e:
            last_error = str(e)
            if attempt == 1:
                print(f"{e} Retrying once with max_tokens={retry_tokens}...")
                continue
            return None, None, response, (
                f"Response was truncated even at max_tokens={retry_tokens}. "
                "The batch or requested output is too large for this budget."
            )
        except api_errors as e:
            return None, None, None, describe_api_error(e)

        try:
            claude_result = extract_json_object(text)
            validate_content_response(claude_result)
        except (json.JSONDecodeError, DataError) as e:
            last_error = str(e)
            claude_result = None
            if attempt == 1:
                print(f"Batch response was invalid ({e}) - retrying once with max_tokens={retry_tokens}...")
                extra_note = f"Your previous response was invalid ({e}). Return ONLY the corrected JSON object."
                continue
            return None, None, response, f"Claude did not return a valid, complete batch response after retry: {last_error}"

        violations = find_content_violations(claude_result, valid_post_ids, batch_size, package_types)
        if violations["hard"]:
            last_error = "; ".join(violations["hard"])
            if attempt == 1:
                print("Batch response violated evidence-safety/content rules - retrying once:")
                for v in violations["hard"]:
                    print(f"  - {v}")
                extra_note = (
                    "Your previous response violated the content-safety rules and cannot be published "
                    "as-is. Fix EXACTLY these issues:\n\n" + build_retry_feedback(violations["hard"], package_types)
                )
                claude_result = None
                continue
            return None, None, response, "Batch response still violates content-safety rules after retry: " + "; ".join(
                violations["hard"]
            )

        applied = apply_auto_corrections(claude_result.get("content_items", []), violations)
        if applied:
            print(f"Applied {applied} automatic verification-flag correction(s) to this batch.")
        break

    if claude_result is None:
        return None, None, response, last_error

    return claude_result.get("content_items", []), claude_result.get("content_summary", ""), response, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to the Stage 7 Content Calendar.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to write the content production package JSON.")
    parser.add_argument(
        "--days", type=int, default=None,
        help="Process only the first N planned days from the calendar (default: the full available calendar).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load/validate the Stage 7 calendar and prepare the Claude input, but skip the API call and output write.",
    )
    args = parser.parse_args()

    if args.days is not None and args.days < 1:
        print("FAILED: --days must be a positive integer.")
        return 1

    load_dotenv()

    try:
        calendar = load_calendar(args.input)
    except DataError as e:
        print(f"FAILED: {e}")
        return 1

    all_items = sorted(calendar["calendar_items"], key=lambda it: it["day_number"])
    if args.days is not None:
        max_day = max(it["day_number"] for it in all_items)
        if args.days > max_day:
            print(f"FAILED: --days {args.days} was requested, but the calendar only has {max_day} day(s).")
            return 1
        selected_items = [it for it in all_items if it["day_number"] <= args.days]
    else:
        selected_items = all_items

    print("=== Stage 7 calendar inspected ===")
    print(f"Top-level keys: {sorted(calendar.keys())}")
    print(f"Total calendar days available: {len(all_items)}")
    print(f"Days selected for content generation: {len(selected_items)}")
    print(f"known post_ids available as evidence: {len(known_post_ids(calendar))}")
    print()

    batches = build_batches(selected_items)
    print(f"=== Content generation batching ===")
    print(f"Batches: {len(batches)} (sizes: {[len(b) for b in batches]})")
    for i, b in enumerate(batches, start=1):
        package_counts = {}
        for item in b:
            pt = package_type_for_item(item)
            package_counts[pt] = package_counts.get(pt, 0) + 1
        payload_json = json.dumps(build_content_payload(b), ensure_ascii=False)
        print(
            f"  Batch {i}: days {b[0]['day_number']}-{b[-1]['day_number']}, "
            f"package mix {package_counts}, approx payload size {len(payload_json)} chars"
        )
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

    valid_post_ids = known_post_ids(calendar)
    all_claude_items = []
    responses = []
    content_summaries = []

    # Each batch runs its own bounded 2-call retry (see generate_batch). If a batch's
    # second attempt still fails, the entire multi-day generation fails cleanly here -
    # no partial content package set is ever written.
    for i, batch_items in enumerate(batches, start=1):
        print(f"=== Generating batch {i}/{len(batches)} (days {batch_items[0]['day_number']}-{batch_items[-1]['day_number']}) ===")
        items, summary, response, error = generate_batch(api_key, batch_items, valid_post_ids, api_errors, describe_api_error)
        if error is not None:
            print(f"FAILED: Batch {i}/{len(batches)} could not be generated: {error}")
            print("No output file written - content generation was not completed.")
            return 1

        all_claude_items.extend(items)
        responses.append(response)
        content_summaries.append(summary)
        print(f"Batch {i}/{len(batches)} succeeded ({len(items)} items).")
        print()

    # Final validation across the FULL merged output, not just each batch in isolation.
    package_types = [package_type_for_item(item) for item in selected_items]
    merged = {
        "content_summary": " ".join(s for s in content_summaries if s),
        "content_items": all_claude_items,
    }
    violations = find_content_violations(merged, valid_post_ids, len(selected_items), package_types)
    if violations["hard"]:
        print("FAILED: Merged content package set failed final validation:")
        for v in violations["hard"]:
            print(f"  - {v}")
        print("No output file written.")
        return 1

    if len(all_claude_items) != len(selected_items):
        print("FAILED: Internal error - merged content items do not match the selected calendar days 1:1.")
        return 1

    content_items = assemble_content_items(all_claude_items, selected_items)

    output = {
        "metadata": {
            "agent": "content_generator",
            "source": str(args.input),
            "model": MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "days_generated": len(selected_items),
            "batches": len(batches),
        },
        "content_summary": merged["content_summary"] or "unknown",
        "content_items": content_items,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    total_input_tokens = sum(r.usage.input_tokens for r in responses)
    total_output_tokens = sum(r.usage.output_tokens for r in responses)

    print("SUCCESS: Content Generator run complete.")
    print(f"Days generated: {len(selected_items)}")
    print(f"Batches used: {len(batches)}")
    print(f"Model used: {MODEL}")
    print(
        f"Token usage: {total_input_tokens} in / {total_output_tokens} out "
        f"(summed across {len(responses)} batch call(s))"
    )
    input_cost = total_input_tokens / 1_000_000 * 1.00
    output_cost = total_output_tokens / 1_000_000 * 5.00
    print(f"Approx. cost (Haiku 4.5 list pricing): ${input_cost + output_cost:.4f} USD")
    print(f"Saved content production package to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
