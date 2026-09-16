"""
Content Strategy Agent for FlyingFish Scuba School.

Reads the existing Stage 4.1 Content Scout report (data/instagram/flyingfish_content_scout.json)
and converts its verified, evidence-classified intelligence into concrete content
opportunities, themes, formats, tests, and an action plan. This does NOT scrape
Instagram, call Apify, or re-analyze raw posts, and it does NOT use competitor data or
external business facts - it only works from what Stage 4.1 already established.

Answers: "Based on our actual Instagram performance data, what content should
FlyingFish consider creating next?" - grounded in Stage 4.1 evidence, not generic
social media advice.

ARCHITECTURE (redesigned - see git history for the earlier prose-policing approach):
every evidence-bearing claim is split into a short "observation" (a directly-citable
fact - a post_id and its number) and a short "interpretation" (a hedged association,
never a causal claim), instead of one long free-form "rationale"/"evidence" paragraph.
Proposed tests ("hypothesis") are validated structurally - they must start with an
explicit test verb (Test/Measure/Compare/Evaluate/Determine/Track/Assess) - rather
than by scanning for causal words, since the field's own required shape is what proves
it's a hypothesis, not a stated fact. Creative fields (content labels, hooks, CTAs,
audience descriptions, action-plan items) are not evidentiary claims and are never
checked for causal language at all - they still get the universal competitor-claim and
calendar-period checks, since those are unsafe in any field. This replaced an earlier
design that tried to police long free-form prose with an ever-growing causal-language
regex: the regex kept finding new false positives ("Generate a report" flagged as a
causal claim; "scarcity-driven" flagged as an unsupported claim) and false negatives,
because prose is unbounded and a regex cannot understand context. Constraining what
each field is allowed to contain removes most of that ambiguity structurally instead
of trying to out-regex natural language.

Usage:
    source venv/bin/activate
    python scripts/content_strategy.py
    python scripts/content_strategy.py --dry-run   # validate + prepare input, no API call
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_INPUT_PATH = Path("data/instagram/flyingfish_content_scout.json")
OUTPUT_PATH = Path("data/instagram/flyingfish_content_strategy.json")
MODEL = "claude-haiku-4-5"  # same model/conventions as Stage 4.1 - cost-conscious synthesis over already-evidenced data

REQUIRED_SECTIONS = [
    "metadata",
    "executive_summary",
    "top_content_patterns",
    "top_performing_content",
    "weak_content_patterns",
    "content_gaps",
    "opportunities",
    "recommended_tests",
    "action_plan",
]


class DataError(Exception):
    """Raised for problems with the Stage 4.1 input (missing file, bad JSON, missing sections)."""


def load_stage41_report(path: Path) -> dict:
    if not path.exists():
        raise DataError(f"Stage 4.1 Content Scout report not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Stage 4.1 report is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise DataError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_SECTIONS if key not in data]
    if missing:
        raise DataError(f"Stage 4.1 report is missing required section(s): {missing}")

    return data


def known_post_ids(stage41: dict) -> set:
    """Every post_id the Content Strategy Agent is allowed to cite - the union of
    Stage 4.1's deterministic top_performing_content and every evidence_post_ids
    array already validated by Stage 4.1's own hardening. Nothing outside this set
    was ever verified against real Instagram data."""
    ids = {p.get("post_id") for p in stage41.get("top_performing_content", []) if p.get("post_id")}
    for group in ("top_content_patterns", "weak_content_patterns", "content_gaps", "opportunities"):
        for item in stage41.get(group, []):
            if isinstance(item, dict):
                ids.update(item.get("evidence_post_ids") or [])
    return ids


def build_strategy_payload(stage41: dict) -> dict:
    """Compact input for Claude - Stage 4.1's own distilled report, not raw Instagram
    data. Stage 4.1 already stripped the raw scrape down to evidence-classified
    findings, so this is already small; we just pass its substance through."""
    return {
        "executive_summary": stage41.get("executive_summary"),
        "top_performing_content": stage41.get("top_performing_content", []),
        "top_content_patterns": stage41.get("top_content_patterns", []),
        "weak_content_patterns": stage41.get("weak_content_patterns", []),
        "content_gaps": stage41.get("content_gaps", []),
        "opportunities": stage41.get("opportunities", []),
        "recommended_tests": stage41.get("recommended_tests", []),
        "action_plan": stage41.get("action_plan", []),
        "known_post_ids": sorted(known_post_ids(stage41)),
    }


def _build_system_prompt() -> str:
    today = datetime.now(timezone.utc).strftime("%B %Y")
    return f"""You are the Content Strategy Agent for FlyingFish Scuba School, \
a scuba diving school at Novotel Resort & Spa, Candolim, Goa, India.

The current date is {today}. Never reference or invent a specific past or future calendar \
quarter (e.g. "Q4 2025") or a specific date you were not given - use relative planning \
language instead, such as "the next 1-2 weeks" or "the next 4 weeks".

You will receive the Stage 4.1 Content Scout report: verified, evidence-classified \
findings about FlyingFish's actual Instagram performance. Your job is to convert that \
evidence into concrete content opportunities - NOT generic social media advice, and NOT \
new facts, numbers, posts, audience data, or business claims not in the report you were given.

"known_post_ids" lists every post_id Stage 4.1 already verified against real data. \
NEVER cite, in any evidence_post_ids field, a post_id that is not in that list.

OUTPUT IS STRUCTURED, NOT PROSE. Every field has a narrow job. Keep every string SHORT \
- one sentence or a short phrase, never a paragraph. Do not repeat the same point \
across multiple fields.

EXECUTIVE_SUMMARY, "observation", "interpretation", and recommended_tests' \
"evidence_basis" are ALL OBSERVATIONAL FIELDS - they may state ONLY what the dataset \
actually shows, using words like: is associated with, co-occurs with, was observed \
in, achieved, received, recorded, shows, features, contains, was used in, had, was \
associated with. This includes a post's own derived numbers (ratios, rates, \
percentages) - a comment ratio or engagement rate is just another number Stage 4.1 \
already gave you, so cite it with "recorded"/"had"/"achieved", never "generated"/
"drove". NEVER use, in these fields, in any tense and never softened with "may" or \
"likely": drives, drive, drove, driven, generates, generated, increases, increased, \
leads to, led to, results in, resulted in, "primary driver", "engagement driver", \
proven, guarantees. If you cannot state something using only these observational \
words, it does not belong in an observational field - put it in "hypothesis" instead.
  Bad (executive_summary): "...educational course breakdowns also drive strong engagement."
  Good (executive_summary): "...educational course breakdowns were among the posts \
  with strong observed engagement."
  Bad (observation): "...used countdown messaging and generated a notably high \
  comment ratio (5.5% engagement rate)."
  Good (observation): "...used countdown messaging and recorded 366 likes, 20 \
  comments, and a 5.5% engagement rate."
  Bad (evidence_basis / recommended_formats.observation): "Emotional reaction and \
  instructor praise drove exceptional performance." / "...personal connection drive \
  exceptional engagement."
  Good: "DWyk4T6E5OF featured an emotional reaction and explicit instructor praise \
  and received 3,266 likes and 49 comments, compared with the account average."

EVIDENCE FIELDS (content_opportunities, strategy_themes, recommended_formats):
- "observation": ONE short factual sentence citing a specific post_id and its actual \
number(s) from the data you were given, e.g. "DH3VdAmCS5g had 1,119 likes." State the \
number and stop - never interpret, never explain why, never use a verb like drives/ \
generates/increases/causes here.
- "interpretation": ONE short sentence using association language only (see the \
OBSERVATIONAL FIELDS rules above). If you cannot state something as a plain \
association, put it in "hypothesis" instead.

content_opportunities also has:
- "pattern": a short label for what was observed (e.g. "time-limited discount CTA", \
"scarcity-driven booking window") - a phrase, not a sentence. Compound adjectives like \
"scarcity-driven"/"narrative-driven"/"weather-driven"/"data-driven" are fine here and \
anywhere else - they describe content characteristics, not a causal claim.
- "hypothesis": a proposed FUTURE test - see HYPOTHESIS FORMAT below.

HYPOTHESIS FORMAT (content_opportunities.hypothesis and recommended_tests.hypothesis): \
must start with one of these exact words: Test, Measure, Compare, Evaluate, Determine, \
Track, Assess (e.g. "Test whether...", "Compare A against B and measure whether..."). \
That required opening is what proves the sentence is a proposed test rather than a \
stated fact, so once it's there you do not need to hedge every verb inside the \
sentence too. Never phrase a past-tense word as the sentence's main claim (never "DM \
inquiries increased" / "this drove engagement" / "engagement was generated" - those \
assert something already happened, which this dataset does not establish for a test \
that hasn't run). A past-tense word used adjectivally to name a target state right \
after "with"/"of"/"for"/"about"/"versus"/"compared to" is fine, since it describes \
what you're testing FOR, not a claim it already occurred - "...and correlate with \
increased DM inquiries about certifications..." is a valid target description. \
"Track increased DM inquiries" is NOT fine - phrase it as "Track DM inquiries" or \
"Track whether DM inquiries increase" instead.

RECOMMENDED_TESTS also replaces one long "success metric" paragraph with three short \
structural fields instead of a sentence:
- "metric": what is measured, e.g. "click-through rate to booking page" or "DM inquiry volume".
- "target": the target value/direction, e.g. "15% increase" or "at least 10 more inquiries".
- "comparison": what it's measured against, e.g. "baseline" or "the account average".
"evidence_basis" is the one recommended_tests field that follows the observation/ \
interpretation rules above (short, factual, no drives/generates/increases/driver-as- \
noun) - it must justify the test using only already-observed evidence, never a \
comparative target (that's what metric/target/comparison are for).

CREATIVE FIELDS are not evidence and are NEVER checked for causal language - write \
them naturally: opportunity, pattern, recommended_format, target_audience, \
suggested_cta, theme, format, test_name, variable_to_test, audience, \
suggested_duration, metric, target, comparison. They still may never state an \
unverified competitor fact or reference a specific calendar quarter (see below).

ACTION PLAN: action_plan items describe an action to take, not a claim about evidence \
- they are never checked for causal language either. Normal action verbs (generate, \
create, publish, monitor, compare, review, test, measure, track, document, schedule) \
are expected and fine, e.g. "Generate a weekly report comparing results to test \
hypotheses" is an instruction, not a claim. Prefix EVERY item with exactly one of \
"[IMMEDIATE] ", "[NEXT] ", or "[LATER] " (including the brackets and trailing space).

COMPETITOR CLAIMS - the Stage 4.1 report contains FlyingFish data only, never actual \
competitor data. Never state a specific fact about how competitors are positioned or \
what they do, in ANY field - not even softened with "may" or "likely". If \
differentiation is worth raising, phrase it as "Potential differentiation; competitor \
validation required." or "Requires competitor research before making a comparative \
claim." and set requires_verification=true with a verification_reason explaining that \
competitor data is needed. An unhedged competitor mention with requires_verification \
left false is always rejected, in every field including target_audience and action_plan.

BUSINESS OUTCOME CLAIMS - the dataset contains Instagram engagement observations only. \
It does NOT establish bookings, booking conversions, revenue, leads, customer \
acquisition, enrollment, inquiry quality, conversion rate, or ROI as historical facts. \
A test's "target"/"metric"/"comparison" may reference these as a FUTURE measurement \
target - that is exactly what those fields are for - but "observation"/ \
"interpretation"/"evidence_basis" must never state them as an already-established outcome.

EVIDENCE HIERARCHY: classify every content_opportunities/strategy_themes/ \
recommended_formats item via evidence_type as exactly one of observed (directly \
supported by Stage 4.1 evidence), interpretation (a reasonable reading of observed \
data), hypothesis (a proposed, untested idea), or recommendation (a proposed action). \
Match evidence_type to whichever of observation/interpretation/hypothesis actually \
carries the claim.

OTHER HARD RULES:
1. Never fabricate Instagram numbers, post IDs, captions, audience demographics, \
business facts, competitor behavior, market/tourism statistics, or seasonal \
performance claims - use only what Stage 4.1 gave you.
2. When a claim rests on a small number of posts, state the sample size and avoid \
universal language ("always", "every post") - confidence should not be "high" when \
sample_size is 1 or 2.
3. Do not generate generic advice such as "post consistently", "use trending \
hashtags", or "create engaging content" - every opportunity/theme/format must connect \
to a specific piece of Stage 4.1 evidence.
4. Any specific numeric target you propose belongs only in recommended_tests \
(metric/target/comparison), labeled target_type: "proposed_test_target" - never \
presented as a predicted outcome elsewhere.
5. If something cannot be established from the supplied report, say so explicitly.

FIELD CONVENTIONS (the schema uses plain types for these - follow these conventions \
exactly, they are validated after your response is parsed):
- "evidence_type" must be exactly one of: observed, interpretation, hypothesis, recommendation.
- "confidence" must be exactly one of: high, medium, low.
- "target_type" on every recommended_tests item must be exactly: proposed_test_target.
- "sample_size" is an integer: the number of posts the claim is based on, or 0 if the \
claim is not tied to a specific count of posts.
- "verification_reason" is a string: your explanation when requires_verification is \
true, or an empty string "" when requires_verification is false.

Respond with ONLY a single valid JSON object (no markdown code fences, no commentary \
before or after) matching exactly the schema you are given. For every evidence_post_ids \
field, list only post_ids from "known_post_ids", or an empty array if not tied to \
specific posts. Set requires_verification=true whenever a claim touches a business \
fact, external claim, or competitor comparison not supplied as verified data, and \
explain what needs verification in verification_reason (otherwise "")."""


CONTENT_STRATEGY_SYSTEM_PROMPT = _build_system_prompt()

# Evidence fields shared by every claim-bearing item - structurally required, mirroring
# Stage 4.1's hardening so Claude cannot omit evidence classification or the
# verification flag.
# Deliberately NOT enums and NOT nullable unions - a real API call against the original
# (enum + [type,null]-union) version of this schema failed with "The compiled grammar is
# too large" from Anthropic's structured-output compiler. Every field here is a single
# plain type, structurally guaranteed to be present by output_config.format, but the
# *allowed values* (evidence_type, confidence) and the *null convention* (sample_size=0,
# verification_reason="") are enforced in Python by find_evidence_violations() /
# main() below instead of in the schema.
_EVIDENCE_FIELDS = {
    "evidence_type": {"type": "string"},
    "evidence_post_ids": {"type": "array", "items": {"type": "string"}},
    "sample_size": {"type": "integer"},
    "confidence": {"type": "string"},
    "requires_verification": {"type": "boolean"},
    "verification_reason": {"type": "string"},
}
_EVIDENCE_FIELD_NAMES = list(_EVIDENCE_FIELDS.keys())

ALLOWED_EVIDENCE_TYPES = {"observed", "interpretation", "hypothesis", "recommendation"}
ALLOWED_CONFIDENCE_LEVELS = {"high", "medium", "low"}

CONTENT_STRATEGY_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "content_opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "opportunity": {"type": "string"},
                    "observation": {"type": "string"},
                    "pattern": {"type": "string"},
                    "interpretation": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "recommended_format": {"type": "string"},
                    "target_audience": {"type": "string"},
                    "suggested_cta": {"type": "string"},
                    **_EVIDENCE_FIELDS,
                },
                "required": [
                    "opportunity", "observation", "pattern", "interpretation", "hypothesis",
                    "recommended_format", "target_audience", "suggested_cta", *_EVIDENCE_FIELD_NAMES,
                ],
                "additionalProperties": False,
            },
        },
        "strategy_themes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "theme": {"type": "string"},
                    "observation": {"type": "string"},
                    "interpretation": {"type": "string"},
                    **_EVIDENCE_FIELDS,
                },
                "required": ["theme", "observation", "interpretation", *_EVIDENCE_FIELD_NAMES],
                "additionalProperties": False,
            },
        },
        "recommended_formats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "format": {"type": "string"},
                    "observation": {"type": "string"},
                    "interpretation": {"type": "string"},
                    **_EVIDENCE_FIELDS,
                },
                "required": ["format", "observation", "interpretation", *_EVIDENCE_FIELD_NAMES],
                "additionalProperties": False,
            },
        },
        "recommended_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "target_type": {"type": "string"},
                    "variable_to_test": {"type": "string"},
                    "format": {"type": "string"},
                    "audience": {"type": "string"},
                    "metric": {"type": "string"},
                    "target": {"type": "string"},
                    "comparison": {"type": "string"},
                    "suggested_duration": {"type": "string"},
                    "evidence_basis": {"type": "string"},
                    "evidence_post_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string"},
                    "requires_verification": {"type": "boolean"},
                    "verification_reason": {"type": "string"},
                },
                "required": [
                    "test_name", "hypothesis", "target_type", "variable_to_test", "format",
                    "audience", "metric", "target", "comparison", "suggested_duration",
                    "evidence_basis", "evidence_post_ids", "confidence",
                    "requires_verification", "verification_reason",
                ],
                "additionalProperties": False,
            },
        },
        # Flat array (like Stage 4.1's action_plan), not a nested {immediate,next,later}
        # object - one less distinct object shape for the grammar compiler. Each string
        # is prefixed "[IMMEDIATE]"/"[NEXT]"/"[LATER]" by convention (see system prompt)
        # and parsed back into the immediate/next/later buckets in Python before the
        # output file is written - the persisted contract is unchanged.
        "action_plan": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "executive_summary", "content_opportunities", "strategy_themes",
        "recommended_formats", "recommended_tests", "action_plan",
    ],
    "additionalProperties": False,
}

# 8000/12000 mirrors Stage 4.1's measured-safe budget for a similarly-shaped,
# similarly-sized evidence-classified response.
BASE_MAX_TOKENS = 8000
RETRY_MAX_TOKENS = 12000


class TruncatedResponseError(Exception):
    """Raised when Claude's response was cut off by the token limit before completing."""


_CREDENTIAL_LIKE_RE = re.compile(r"sk-ant-[A-Za-z0-9\-_]+")


def extract_api_error_message(e) -> str:
    """Best-effort extraction of the real Anthropic error message (e.g. the
    invalid_request_error detail for a 400) so failures are diagnosable instead of a
    bare status code. Anthropic's error responses never echo the API key/auth header -
    the redaction below is defense-in-depth, not a response to an observed leak."""
    message = None
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            message = err.get("message")
        elif isinstance(err, str):
            message = err
    if not message:
        message = getattr(e, "message", None)
    if not message:
        message = str(e)
    return _CREDENTIAL_LIKE_RE.sub("[REDACTED]", str(message))


def call_claude(api_key: str, payload: dict, max_tokens: int = BASE_MAX_TOKENS, extra_note: str = None) -> tuple:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        "Here is the Stage 4.1 Content Scout report for FlyingFish Scuba School's "
        "Instagram account. Build content strategy strictly from this evidence.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    if extra_note:
        user_message += f"\n\nCORRECTION REQUIRED: {extra_note}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=CONTENT_STRATEGY_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        output_config={"format": {"type": "json_schema", "schema": CONTENT_STRATEGY_RESPONSE_SCHEMA}},
    )

    if response.stop_reason == "max_tokens":
        raise TruncatedResponseError(
            f"Response was cut off by the max_tokens limit ({max_tokens}) before it finished."
        )

    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response


def extract_json_object(text: str) -> dict:
    """Parse Claude's response as JSON, tolerating markdown fences or minor surrounding
    text. With output_config.format this should already be clean JSON - these are
    defense-in-depth fallbacks, not the primary correctness mechanism."""
    cleaned = text.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    fenced = cleaned
    if fenced.startswith("```"):
        fenced = fenced.strip("`")
        if fenced.lower().startswith("json"):
            fenced = fenced[4:]
        try:
            return json.loads(fenced.strip())
        except json.JSONDecodeError:
            pass

    start = cleaned.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start : i + 1]
                    return json.loads(candidate)

    return json.loads(cleaned)


REQUIRED_RESPONSE_FIELDS = {
    "executive_summary": str,
    "content_opportunities": list,
    "strategy_themes": list,
    "recommended_formats": list,
    "recommended_tests": list,
    "action_plan": list,
}

_ACTION_BUCKET_RE = re.compile(r"^\[(IMMEDIATE|NEXT|LATER)\]\s*(.*)$", re.IGNORECASE)


def validate_strategy_response(data) -> None:
    """Fail clearly and specifically rather than silently assembling an incomplete report."""
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


def parse_action_plan(items: list) -> dict:
    """Parse the flat '[IMMEDIATE]'/'[NEXT]'/'[LATER]'-prefixed action_plan list into
    the {immediate, next, later} structure for the output file. Untagged items default
    to 'next' rather than being dropped."""
    buckets = {"immediate": [], "next": [], "later": []}
    for item in items:
        if not isinstance(item, str):
            continue
        m = _ACTION_BUCKET_RE.match(item.strip())
        if m:
            buckets[m.group(1).lower()].append(m.group(2).strip())
        else:
            buckets["next"].append(item.strip())
    return buckets


# --- Evidence-safety validation ---------------------------------------------------
#
# Every free-text field is assigned exactly one ROLE, and only that role's rules
# apply to it - this is the core of the redesign: instead of one causal-language
# regex trying to police every field the same way (and constantly getting the wrong
# false positive/negative for whichever field it was actually applied to), each
# field's role tells us up front what kind of content is even possible there.
#
#   "strict"     - observation/interpretation/evidence_basis: a claim about what the
#                   dataset already shows. Never allowed to use causal/trend language
#                   in any tense - there is no hedge that makes a causal claim safe in
#                   a field whose whole job is to state only what was observed. (The
#                   separate "hypothesis" field exists precisely for proposed tests.)
#   "hypothesis" - content_opportunities.hypothesis / recommended_tests.hypothesis: a
#                   proposed, not-yet-run test. Validated structurally (must start with
#                   an explicit test verb) instead of by scanning for causal words -
#                   past-tense claims of an already-observed result are still rejected.
#   "creative"   - content/label fields (opportunity, pattern, recommended_format,
#                   target_audience, suggested_cta, theme, format, test_name,
#                   variable_to_test, audience, metric, target, comparison,
#                   suggested_duration) and action_plan items: not evidentiary claims,
#                   never causal-language-checked. Still checked for competitor claims
#                   and hardcoded calendar periods, which are unsafe in any field.
#
# "Hard" violations mean the claim itself is unsafe as worded; "soft" violations are
# missing metadata that can be safely auto-corrected without discarding the claim.

_TREND_PRESENT_RE = re.compile(
    r"\b(drives?|driving)\b"
    r"|\b(increas(?:e|es|ing))\b"
    r"|\b(decreas(?:e|es|ing))\b"
    r"|\b(convert(?:s|ing)?)\b"
    r"|\b(generat(?:e|es|ing))\b"
    r"|\bresults?\s+in\b|\bresulting\s+in\b"
    r"|\bleads?\s+to\b|\bleading\s+to\b",
    re.IGNORECASE,
)
_TREND_PAST_RE = re.compile(
    r"\b(drove|driven)\b"
    r"|\bincreased\b|\bdecreased\b|\bconverted\b|\bgenerated\b"
    r"|\bresulted\s+in\b|\bled\s+to\b",
    re.IGNORECASE,
)
_STRONG_CLAIM_RE = re.compile(
    r"\b(causes?|causing|caused)\b"
    r"|\b(proves?|proving|proved|proven)\b"
    r"|\b(guarantees?|guaranteeing|guaranteed)\b"
    r"|\bprimary\s+(?:engagement\s+)?drivers?\b"
    r"|\bengagement\s+drivers?\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# A trend word immediately preceded by a hyphen is a compound adjective describing
# content characteristics ("scarcity-driven booking windows", "narrative-driven
# reels", "weather-driven dive conditions", "urgency-driven CTAs"), not a claim that
# the dataset showed causation - it should never be flagged on its own.
def _is_compound_adjective(sentence: str, start: int) -> bool:
    return start > 0 and sentence[start - 1] == "-"


# A trend word describing a post's OWN already-observed engagement numbers
# ("generating 3,266 likes and 49 comments") is a grammatical participle, not a claim
# that the format/content caused an external outcome - the number itself is exactly
# what Stage 4.1 already verified. Deliberately scoped to engagement-metric nouns only
# (likes/comments/shares/saves/views/followers/reactions), NOT bookings/inquiries/
# conversions/revenue - "generated bookings" or "increased inquiries" must still be
# flagged, since those business outcomes are never established by this dataset.
_METRIC_DESCRIPTION_RE = re.compile(
    r"\b(?:generat(?:e|es|ed|ing)|driv(?:e|es|ing)|drove|result(?:s|ed|ing)?\s+in)\s+"
    r"[\d,]+(?:\.\d+)?%?\s+(?:likes?|comments?|shares?|saves?|views?|followers?|reactions?)\b",
    re.IGNORECASE,
)


def _is_metric_description(sentence: str, start: int, end: int) -> bool:
    for m in _METRIC_DESCRIPTION_RE.finditer(sentence):
        if m.start() <= start and end <= m.end():
            return True
    return False


def _first_real_match(pattern, sentence: str):
    """Like pattern.search(), but skips matches that are compound adjectives or part
    of an observed-metric description (see the two helpers above) - neither is a
    causal claim, so continue scanning the rest of the sentence for a real one."""
    for m in pattern.finditer(sentence):
        if _is_compound_adjective(sentence, m.start()):
            continue
        if _is_metric_description(sentence, m.start(), m.end()):
            continue
        return m
    return None


_COMPETITOR_RE = re.compile(r"\bcompetitors?\b", re.IGNORECASE)
_COMPETITOR_HEDGE_RE = re.compile(
    r"\b(competitor\s+validation(?:\s+is)?\s+required|requires?\s+competitor\s+(?:validation|research)|"
    r"validation\s+is\s+required|potential\s+differentiation|"
    r"cannot\s+be\s+concluded\s+from\s+(?:the\s+)?current\s+data)\b",
    re.IGNORECASE,
)
_CALENDAR_PERIOD_RE = re.compile(r"\bQ[1-4]\s*20\d{2}\b|\b20\d{2}\s*Q[1-4]\b", re.IGNORECASE)
_BUSINESS_FACT_RE = re.compile(
    r"\b(PADI|SSI|certifi\w*|award\w*|partnership\w*|licens\w*|guarantee\w*|scam\w*|"
    r"safety\s+concern\w*|tourist\s+market\w*|"
    r"bookings?|booking\s+conversions?|revenue|leads?(?!\s+to\b)|customer\s+acquisition|"
    r"enrollment\w*|inquiry\s+quality|conversion\s+rates?|ROI)\b",
    re.IGNORECASE,
)
_UNIVERSAL_LANGUAGE_RE = re.compile(
    r"\b(always|every\s+post|all\s+posts|consistently\s+performs?|guaranteed|people\s+love)\b", re.IGNORECASE
)
_HYPOTHESIS_ALLOWED_START_RE = re.compile(
    r"^(test|measure|compare|evaluate|determine|track|assess)\b", re.IGNORECASE
)
# A past-tense trend word immediately preceded by a preposition/comparative
# (with/of/for/about/versus/than/compared to) can only be functioning as an adjective
# describing a FUTURE TARGET state ("correlate WITH increased DM inquiries" = a target
# to test for), never as the main verb of a completed-action claim - a preposition
# can never be followed by a finite verb in English, only by a noun phrase. This is
# deliberately narrow: a bare verb immediately before the word ("track increased
# inquiries") is NOT exempted, since that phrasing is genuinely ambiguous and still
# reads as asserting the increase already happened unless reframed with "whether" or
# a preposition. Scoped to the hypothesis field only - observation/interpretation/
# evidence_basis never get this exemption, per _causal_language_match above.
_HYPOTHESIS_TARGET_PRECEDING_RE = re.compile(
    r"\b(with|of|for|about|versus|vs\.?|than|compared(?:\s+(?:to|with))?|relative\s+to)\s*$",
    re.IGNORECASE,
)


def _is_hypothesis_target_descriptor(sentence: str, start: int) -> bool:
    return bool(_HYPOTHESIS_TARGET_PRECEDING_RE.search(sentence[:start]))


def _first_hypothesis_past_tense_match(sentence: str):
    """Like _first_real_match(_TREND_PAST_RE, ...), plus the target-descriptor
    exemption above, which applies only to the hypothesis field."""
    for m in _TREND_PAST_RE.finditer(sentence):
        if _is_compound_adjective(sentence, m.start()):
            continue
        if _is_metric_description(sentence, m.start(), m.end()):
            continue
        if _is_hypothesis_target_descriptor(sentence, m.start()):
            continue
        return m
    return None


def _sentences(text: str) -> list:
    text = (text or "").strip()
    if not text:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return parts or [text]


def _causal_language_match(text: str):
    """Unconditional causal-language check for STRICT evidentiary fields (observation/
    interpretation/evidence_basis). These fields never propose a test - that's what
    the separate, structurally-validated "hypothesis" field is for - so there is no
    hedge/framing that makes a causal claim acceptable here: any trend or strong-claim
    word is a violation, in any tense, except a compound adjective ("scarcity-driven")
    or a post's own observed-metric description ("generating 3,266 likes"), neither of
    which is a causal claim to begin with."""
    for sentence in _sentences(text):
        m = _first_real_match(_TREND_PAST_RE, sentence)
        if m:
            return m.group(0), sentence
        m = _first_real_match(_TREND_PRESENT_RE, sentence)
        if m:
            return m.group(0), sentence
        m = _STRONG_CLAIM_RE.search(sentence)
        if m:
            return m.group(0), sentence
    return None


def _hypothesis_violation(text: str) -> str:
    """Return a violation reason, or "" if the hypothesis is structurally valid. Valid
    means (a) it starts with an explicit test/measurement verb - this required shape,
    not a causal-language regex, is what proves it's a proposed test and not a stated
    fact - and (b) it contains no past-tense claim of an already-observed result (a
    proposed test's hypothesis describes a FUTURE measurement, so a past-tense verb
    there is still an unsupported claim that it already happened)."""
    stripped = (text or "").strip()
    if not _HYPOTHESIS_ALLOWED_START_RE.match(stripped):
        return (
            "must start with an explicit test verb (Test/Measure/Compare/Evaluate/"
            f"Determine/Track/Assess) to prove it is a proposed test, not a stated fact: {text!r}"
        )
    for sentence in _sentences(text):
        m = _first_hypothesis_past_tense_match(sentence)
        if m:
            return f"uses a past-tense claim ({m.group(0)!r}) of an already-observed result: {sentence!r}"
    return ""


_EVIDENCE_GROUPS = ("content_opportunities", "strategy_themes", "recommended_formats")

# Field-role tables per group - see the module-level comment above for what each role
# means. Used both to scan for unsafe language (field-aware, not a hardcoded list of
# array indexes) and to build combined_text for the soft business-fact/competitor
# checks below.
_CONTENT_OPPORTUNITIES_STRICT_FIELDS = ("observation", "interpretation")
_CONTENT_OPPORTUNITIES_HYPOTHESIS_FIELDS = ("hypothesis",)
_CONTENT_OPPORTUNITIES_CREATIVE_FIELDS = (
    "opportunity", "pattern", "recommended_format", "target_audience", "suggested_cta",
)
_CONTENT_OPPORTUNITIES_ALL_FIELDS = (
    _CONTENT_OPPORTUNITIES_CREATIVE_FIELDS
    + _CONTENT_OPPORTUNITIES_STRICT_FIELDS
    + _CONTENT_OPPORTUNITIES_HYPOTHESIS_FIELDS
)

_STRATEGY_THEMES_STRICT_FIELDS = ("observation", "interpretation")
_STRATEGY_THEMES_CREATIVE_FIELDS = ("theme",)
_STRATEGY_THEMES_ALL_FIELDS = _STRATEGY_THEMES_CREATIVE_FIELDS + _STRATEGY_THEMES_STRICT_FIELDS

_RECOMMENDED_FORMATS_STRICT_FIELDS = ("observation", "interpretation")
_RECOMMENDED_FORMATS_CREATIVE_FIELDS = ("format",)
_RECOMMENDED_FORMATS_ALL_FIELDS = _RECOMMENDED_FORMATS_CREATIVE_FIELDS + _RECOMMENDED_FORMATS_STRICT_FIELDS

_RECOMMENDED_TESTS_STRICT_FIELDS = ("evidence_basis",)
_RECOMMENDED_TESTS_HYPOTHESIS_FIELDS = ("hypothesis",)
_RECOMMENDED_TESTS_CREATIVE_FIELDS = (
    "test_name", "variable_to_test", "format", "audience", "metric", "target", "comparison", "suggested_duration",
)
_RECOMMENDED_TESTS_ALL_FIELDS = (
    _RECOMMENDED_TESTS_CREATIVE_FIELDS + _RECOMMENDED_TESTS_STRICT_FIELDS + _RECOMMENDED_TESTS_HYPOTHESIS_FIELDS
)

_GROUP_TEXT_FIELDS = {
    "content_opportunities": _CONTENT_OPPORTUNITIES_ALL_FIELDS,
    "strategy_themes": _STRATEGY_THEMES_ALL_FIELDS,
    "recommended_formats": _RECOMMENDED_FORMATS_ALL_FIELDS,
}


def _iter_text_fields(data: dict):
    """Yield (location, text, role, item) for every free-text string field in a
    response - every claim-bearing field across every item, not a hardcoded list of
    specific indexes. role is "strict"/"hypothesis"/"creative" (see the module-level
    comment above _TREND_PRESENT_RE). item is the owning dict (for the competitor-
    claim requires_verification escape valve), or None for executive_summary/
    action_plan, which aren't part of an item and so can't carry that flag."""
    yield "executive_summary", data.get("executive_summary", ""), "strict", None

    for i, item in enumerate(data.get("content_opportunities", [])):
        for field in _CONTENT_OPPORTUNITIES_CREATIVE_FIELDS:
            yield f"content_opportunities[{i}].{field}", item.get(field, ""), "creative", item
        for field in _CONTENT_OPPORTUNITIES_STRICT_FIELDS:
            yield f"content_opportunities[{i}].{field}", item.get(field, ""), "strict", item
        for field in _CONTENT_OPPORTUNITIES_HYPOTHESIS_FIELDS:
            yield f"content_opportunities[{i}].{field}", item.get(field, ""), "hypothesis", item
    for i, item in enumerate(data.get("strategy_themes", [])):
        for field in _STRATEGY_THEMES_CREATIVE_FIELDS:
            yield f"strategy_themes[{i}].{field}", item.get(field, ""), "creative", item
        for field in _STRATEGY_THEMES_STRICT_FIELDS:
            yield f"strategy_themes[{i}].{field}", item.get(field, ""), "strict", item
    for i, item in enumerate(data.get("recommended_formats", [])):
        for field in _RECOMMENDED_FORMATS_CREATIVE_FIELDS:
            yield f"recommended_formats[{i}].{field}", item.get(field, ""), "creative", item
        for field in _RECOMMENDED_FORMATS_STRICT_FIELDS:
            yield f"recommended_formats[{i}].{field}", item.get(field, ""), "strict", item
    for i, item in enumerate(data.get("recommended_tests", [])):
        for field in _RECOMMENDED_TESTS_CREATIVE_FIELDS:
            yield f"recommended_tests[{i}].{field}", item.get(field, ""), "creative", item
        for field in _RECOMMENDED_TESTS_STRICT_FIELDS:
            yield f"recommended_tests[{i}].{field}", item.get(field, ""), "strict", item
        for field in _RECOMMENDED_TESTS_HYPOTHESIS_FIELDS:
            yield f"recommended_tests[{i}].{field}", item.get(field, ""), "hypothesis", item
    for i, text in enumerate(data.get("action_plan", [])):
        yield f"action_plan[{i}]", text, "creative", None


def _competitor_claim_is_verified(item) -> bool:
    """True when the item has explicitly flagged its competitor mention for human
    verification (requires_verification=true with a real explanation) - the "auto-set
    requires_verification=true with a clear verification_reason" alternative to
    rewriting. executive_summary/action_plan have no item to carry this flag, so they
    can never use this escape valve - a competitor mention there must be hedged in the
    text itself."""
    if not isinstance(item, dict):
        return False
    return bool(item.get("requires_verification")) and bool(str(item.get("verification_reason") or "").strip())


def find_evidence_violations(data: dict, valid_post_ids: set) -> dict:
    """Check response content against the hardening rules.
    Returns {"hard": [str, ...], "soft": [{"loc", "type", "detail"}, ...]}."""
    hard = []
    soft = []

    for location, text, role, item in _iter_text_fields(data):
        if not isinstance(text, str):
            continue

        if role == "strict":
            causal = _causal_language_match(text)
            if causal:
                phrase, sentence = causal
                hard.append(
                    f"{location}: uses unsupported causal language ({phrase!r}) - state "
                    f"only what was observed, or move this into 'hypothesis': {sentence!r}"
                )
        elif role == "hypothesis":
            violation = _hypothesis_violation(text)
            if violation:
                hard.append(f"{location}: {violation}")

        if (
            _COMPETITOR_RE.search(text)
            and not _COMPETITOR_HEDGE_RE.search(text)
            and not _competitor_claim_is_verified(item)
        ):
            hard.append(
                f"{location}: makes a competitor claim without competitor data, without hedged "
                f"'validation required' phrasing, and without requires_verification=true + a "
                f"verification_reason: {text!r}"
            )
        if _CALENDAR_PERIOD_RE.search(text):
            hard.append(
                f"{location}: contains a hardcoded calendar quarter/year instead of relative "
                f"planning language: {text!r}"
            )

    for group_name in _EVIDENCE_GROUPS:
        for i, item in enumerate(data.get(group_name, [])):
            if not isinstance(item, dict):
                continue
            loc = f"{group_name}[{i}]"

            evidence_post_ids = item.get("evidence_post_ids") or []
            invalid_ids = [pid for pid in evidence_post_ids if pid not in valid_post_ids]
            if invalid_ids:
                hard.append(f"{loc}: evidence_post_ids references post_id(s) not in the supplied dataset: {invalid_ids}")

            evidence_type = item.get("evidence_type")
            if evidence_type not in ALLOWED_EVIDENCE_TYPES:
                hard.append(f"{loc}: evidence_type must be one of {sorted(ALLOWED_EVIDENCE_TYPES)}, got {evidence_type!r}")

            confidence = item.get("confidence")
            if confidence not in ALLOWED_CONFIDENCE_LEVELS:
                hard.append(f"{loc}: confidence must be one of {sorted(ALLOWED_CONFIDENCE_LEVELS)}, got {confidence!r}")

            # sample_size=0 is the "not applicable" sentinel (schema requires a plain
            # integer, not a nullable one - see _EVIDENCE_FIELDS comment).
            sample_size = item.get("sample_size")
            requires_verification = bool(item.get("requires_verification", False))
            combined_text = " ".join(
                str(item.get(f, "")) for f in _GROUP_TEXT_FIELDS[group_name] if item.get(f)
            )

            if sample_size and sample_size <= 2 and confidence == "high":
                soft.append(
                    {
                        "loc": loc,
                        "type": "confidence_downgrade",
                        "detail": f"confidence 'high' with sample_size={sample_size} is not justified - downgraded to 'medium'",
                    }
                )

            if sample_size and sample_size <= 2 and not requires_verification and _UNIVERSAL_LANGUAGE_RE.search(combined_text):
                soft.append(
                    {
                        "loc": loc,
                        "type": "flag_verification",
                        "detail": f"uses universal/absolute language with a small sample_size={sample_size}",
                    }
                )

            if not requires_verification and _BUSINESS_FACT_RE.search(combined_text):
                soft.append(
                    {
                        "loc": loc,
                        "type": "flag_verification",
                        "detail": "references a business/external fact or unestablished business outcome "
                        "(certification, award, safety/market claim, bookings, revenue, leads, etc.) "
                        "not supplied as verified context",
                    }
                )

            # An unhedged competitor mention is already a hard violation (caught above via
            # _iter_text_fields); a properly hedged one ("competitor validation required")
            # still needs requires_verification=true rather than silently passing through.
            if not requires_verification and _COMPETITOR_RE.search(combined_text):
                soft.append(
                    {
                        "loc": loc,
                        "type": "flag_verification",
                        "detail": "mentions competitors - requires_verification should be set since no competitor data was supplied",
                    }
                )

    # recommended_tests: separate schema shape (no evidence_type field) - check
    # evidence_post_ids, confidence, and the proposed_test_target label.
    for i, item in enumerate(data.get("recommended_tests", [])):
        if not isinstance(item, dict):
            continue
        loc = f"recommended_tests[{i}]"
        evidence_post_ids = item.get("evidence_post_ids") or []
        invalid_ids = [pid for pid in evidence_post_ids if pid not in valid_post_ids]
        if invalid_ids:
            hard.append(f"{loc}: evidence_post_ids references post_id(s) not in the supplied dataset: {invalid_ids}")
        if item.get("target_type") != "proposed_test_target":
            hard.append(f"{loc}: numeric/target test is missing the required 'proposed_test_target' label")
        test_confidence = item.get("confidence")
        if test_confidence not in ALLOWED_CONFIDENCE_LEVELS:
            hard.append(f"{loc}: confidence must be one of {sorted(ALLOWED_CONFIDENCE_LEVELS)}, got {test_confidence!r}")

        requires_verification = bool(item.get("requires_verification", False))
        combined_text = " ".join(str(item.get(f, "")) for f in _RECOMMENDED_TESTS_ALL_FIELDS if item.get(f))
        if not requires_verification and _BUSINESS_FACT_RE.search(combined_text):
            soft.append(
                {
                    "loc": loc,
                    "type": "flag_verification",
                    "detail": "references a business/external fact or unestablished business outcome "
                    "(certification, award, safety/market claim, bookings, revenue, leads, etc.) "
                    "not supplied as verified context",
                }
            )
        if not requires_verification and _COMPETITOR_RE.search(combined_text):
            soft.append(
                {
                    "loc": loc,
                    "type": "flag_verification",
                    "detail": "mentions competitors - requires_verification should be set since no competitor data was supplied",
                }
            )

    return {"hard": hard, "soft": soft}


def apply_auto_corrections(data: dict, violations: dict) -> int:
    """Apply soft-violation corrections in place. Returns the number applied."""
    count = 0
    soft_by_loc = {}
    for v in violations["soft"]:
        soft_by_loc.setdefault(v["loc"], []).append(v)

    for group_name in _EVIDENCE_GROUPS:
        for i, item in enumerate(data.get(group_name, [])):
            loc = f"{group_name}[{i}]"
            for v in soft_by_loc.get(loc, []):
                if v["type"] == "confidence_downgrade" and item.get("confidence") == "high":
                    item["confidence"] = "medium"
                    count += 1
                elif v["type"] == "flag_verification" and not item.get("requires_verification"):
                    item["requires_verification"] = True
                    existing = item.get("verification_reason")
                    note = f"auto-flagged: {v['detail']}"
                    item["verification_reason"] = f"{existing}; {note}" if existing else note
                    count += 1

    for i, item in enumerate(data.get("recommended_tests", [])):
        loc = f"recommended_tests[{i}]"
        for v in soft_by_loc.get(loc, []):
            if v["type"] == "flag_verification" and not item.get("requires_verification"):
                item["requires_verification"] = True
                existing = item.get("verification_reason")
                note = f"auto-flagged: {v['detail']}"
                item["verification_reason"] = f"{existing}; {note}" if existing else note
                count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to the Stage 4.1 Content Scout report.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to write the strategy report JSON.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load/validate Stage 4.1 data and prepare the Claude input, but skip the API call and output write.",
    )
    args = parser.parse_args()

    load_dotenv()

    try:
        stage41 = load_stage41_report(args.input)
    except DataError as e:
        print(f"FAILED: {e}")
        return 1

    print("=== Stage 4.1 input inspected ===")
    print(f"Top-level keys: {sorted(stage41.keys())}")
    print(f"content_opportunities-relevant sections present: top_content_patterns={len(stage41.get('top_content_patterns', []))}, "
          f"weak_content_patterns={len(stage41.get('weak_content_patterns', []))}, "
          f"content_gaps={len(stage41.get('content_gaps', []))}, "
          f"opportunities={len(stage41.get('opportunities', []))}")
    print(f"top_performing_content count: {len(stage41.get('top_performing_content', []))}")
    print(f"recommended_tests count: {len(stage41.get('recommended_tests', []))}")
    print(f"known post_ids available as evidence: {len(known_post_ids(stage41))}")
    print()

    payload = build_strategy_payload(stage41)
    evidence_item_count = (
        len(payload["top_performing_content"])
        + len(payload["top_content_patterns"])
        + len(payload["weak_content_patterns"])
        + len(payload["content_gaps"])
        + len(payload["opportunities"])
    )
    print("=== Compact Strategy input prepared ===")
    print(f"Evidence items included: {evidence_item_count}")
    payload_json = json.dumps(payload, ensure_ascii=False)
    print(f"Approx payload size: {len(payload_json)} chars")
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

    claude_result = None
    response = None
    last_error = None
    extra_note = None
    valid_post_ids = known_post_ids(stage41)

    # At most two Claude calls total: one normal attempt, one retry only if the first
    # was truncated (higher max_tokens), returned unparseable/invalid JSON, or violated
    # an evidence-safety rule (fabricated post_id, causal claim, unhedged competitor
    # claim, hardcoded calendar period, unlabeled numeric target).
    for attempt, max_tokens in enumerate([BASE_MAX_TOKENS, RETRY_MAX_TOKENS], start=1):
        try:
            text, response = call_claude(api_key, payload, max_tokens=max_tokens, extra_note=extra_note)
        except TruncatedResponseError as e:
            last_error = str(e)
            if attempt == 1:
                print(f"{e} Retrying once with max_tokens={RETRY_MAX_TOKENS}...")
                continue
            print(f"FAILED: Response was truncated even at max_tokens={RETRY_MAX_TOKENS}. "
                  "The payload or requested output is too large for this budget.")
            return 1
        except api_errors as e:
            print(f"FAILED: {describe_api_error(e)}")
            return 1

        try:
            claude_result = extract_json_object(text)
            validate_strategy_response(claude_result)
        except (json.JSONDecodeError, DataError) as e:
            last_error = str(e)
            claude_result = None
            if attempt == 1:
                print(f"Claude's response was invalid ({e}) - retrying once with max_tokens={RETRY_MAX_TOKENS}...")
                extra_note = f"Your previous response was invalid ({e}). Return ONLY the corrected JSON object."
                continue
            print(f"FAILED: Claude did not return a valid, complete response after retry: {last_error}")
            return 1

        violations = find_evidence_violations(claude_result, valid_post_ids)
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

        applied = apply_auto_corrections(claude_result, violations)
        if applied:
            print(
                f"Applied {applied} automatic evidence-safety correction(s) "
                "(flagged unverified claims and/or downgraded overconfident small-sample findings)."
            )
        break

    if claude_result is None:
        print(f"FAILED: Could not obtain a valid, safe response from Claude: {last_error}")
        return 1

    # Restore the null convention in the persisted file (0 -> null, "" -> null) even
    # though the API schema used plain non-nullable types to keep the request simple -
    # the on-disk contract is unchanged from before the schema simplification.
    for group in ("content_opportunities", "strategy_themes", "recommended_formats", "recommended_tests"):
        for item in claude_result.get(group, []):
            if isinstance(item, dict):
                if item.get("sample_size") == 0:
                    item["sample_size"] = None
                if item.get("verification_reason") == "":
                    item["verification_reason"] = None

    output = {
        "metadata": {
            "agent": "content_strategy",
            "source": str(args.input),
            "model": MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "evidence_items_considered": evidence_item_count,
        },
        "executive_summary": claude_result.get("executive_summary", "unknown"),
        "content_opportunities": claude_result.get("content_opportunities", []),
        "strategy_themes": claude_result.get("strategy_themes", []),
        "recommended_formats": claude_result.get("recommended_formats", []),
        "recommended_tests": claude_result.get("recommended_tests", []),
        "action_plan": parse_action_plan(claude_result.get("action_plan", [])),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("SUCCESS: Content Strategy analysis complete.")
    print(f"Evidence items considered: {evidence_item_count}")
    print(f"Model used: {MODEL}")
    print(f"Token usage: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
    input_cost = response.usage.input_tokens / 1_000_000 * 1.00
    output_cost = response.usage.output_tokens / 1_000_000 * 5.00
    print(f"Approx. cost (Haiku 4.5 list pricing): ${input_cost + output_cost:.4f} USD")
    print(f"Saved strategy report to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
