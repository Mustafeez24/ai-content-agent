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
evidence into concrete content opportunities (formats, hooks, angles, CTAs) - NOT to \
generate generic social media advice, and NOT to introduce new facts, numbers, posts, \
audience data, or business claims that were not in the report you were given.

"known_post_ids" lists every post_id that Stage 4.1 already verified against real data. \
You must NEVER cite, in any evidence_post_ids field, a post_id that is not in that list.

EVIDENCE HIERARCHY - every claim must be classified as exactly one of:
- "observed": a fact directly readable from the supplied Stage 4.1 report.
- "interpretation": a reasonable reading of observed data, not a proven causal link.
- "hypothesis": a proposed idea that is NOT proven by the dataset and needs testing.
- "recommendation": a proposed action based on the evidence and/or hypothesis.
Never upgrade a hypothesis into a stated fact. Never say "people love this" or "this
content causes higher engagement" - say "this format was associated with stronger
engagement in the analyzed sample" or "this is a hypothesis worth testing".

HARD RULES:
1. Never fabricate Instagram numbers, post IDs, captions, audience demographics,
   business facts, competitor behavior, market/tourism statistics, customer
   motivations, or seasonal performance claims - use only what Stage 4.1 gave you.
2. Never claim causation ("drives", "causes", "proves", "guarantees") - use hedged
   language: "appears associated with", "observed in", "may be worth testing".
3. Never make competitor claims - no competitor data was supplied. If relevant, phrase
   as "this may represent a potential differentiation opportunity; competitor
   validation is required" and set requires_verification=true.
4. Never state a business fact (certifications, partnerships, pricing, guarantees,
   safety/market claims) as verified unless it was explicitly supplied as verified
   context - it was not in this run. If referenced, set requires_verification=true
   and explain what needs verification.
5. When a claim rests on a small number of posts, state the sample size and avoid
   universal language ("always", "every post") - confidence should not be "high"
   when sample_size is 1 or 2.
6. Do not generate generic advice such as "post consistently", "use trending
   hashtags", "create engaging content", or "post reels because reels perform well" -
   every opportunity, theme, and format must connect to a specific piece of Stage 4.1
   evidence (a pattern, a top-performing post, a gap, or an opportunity already found).
7. Any specific numeric target (engagement %, likes) you propose is a hypothesis to
   test, never a predicted outcome - it belongs only in recommended_tests, labeled
   target_type: "proposed_test_target".
8. If something cannot be established from the supplied report, say so explicitly -
   prefer "not established by this dataset" over speculation.

Respond with ONLY a single valid JSON object (no markdown code fences, no commentary \
before or after) matching exactly the schema you are given. For every evidence_post_ids \
field, list only post_ids from "known_post_ids", or an empty array if not tied to \
specific posts. Set requires_verification=true whenever a claim touches a business \
fact, external claim, or competitor comparison not supplied as verified data, and \
explain what needs verification in verification_reason (otherwise null)."""


CONTENT_STRATEGY_SYSTEM_PROMPT = _build_system_prompt()

# Evidence fields shared by every claim-bearing item - structurally required, mirroring
# Stage 4.1's hardening so Claude cannot omit evidence classification or the
# verification flag.
_EVIDENCE_FIELDS = {
    "evidence_type": {"type": "string", "enum": ["observed", "interpretation", "hypothesis", "recommendation"]},
    "evidence_post_ids": {"type": "array", "items": {"type": "string"}},
    "sample_size": {"type": ["integer", "null"]},
    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    "requires_verification": {"type": "boolean"},
    "verification_reason": {"type": ["string", "null"]},
}
_EVIDENCE_FIELD_NAMES = list(_EVIDENCE_FIELDS.keys())

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
                    "rationale": {"type": "string"},
                    "evidence": {"type": "string"},
                    "recommended_format": {"type": "string"},
                    "target_audience": {"type": "string"},
                    "content_angle": {"type": "string"},
                    "suggested_hook": {"type": "string"},
                    "core_message": {"type": "string"},
                    "suggested_cta": {"type": "string"},
                    **_EVIDENCE_FIELDS,
                },
                "required": [
                    "opportunity", "rationale", "evidence", "recommended_format",
                    "target_audience", "content_angle", "suggested_hook", "core_message",
                    "suggested_cta", *_EVIDENCE_FIELD_NAMES,
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
                    "evidence": {"type": "string"},
                    **_EVIDENCE_FIELDS,
                },
                "required": ["theme", "evidence", *_EVIDENCE_FIELD_NAMES],
                "additionalProperties": False,
            },
        },
        "recommended_formats": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "format": {"type": "string"},
                    "rationale": {"type": "string"},
                    **_EVIDENCE_FIELDS,
                },
                "required": ["format", "rationale", *_EVIDENCE_FIELD_NAMES],
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
                    "target_type": {"type": "string", "enum": ["proposed_test_target"]},
                    "variable_to_test": {"type": "string"},
                    "format": {"type": "string"},
                    "audience": {"type": "string"},
                    "success_metric": {"type": "string"},
                    "suggested_duration": {"type": "string"},
                    "evidence_basis": {"type": "string"},
                    "evidence_post_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "requires_verification": {"type": "boolean"},
                    "verification_reason": {"type": ["string", "null"]},
                },
                "required": [
                    "test_name", "hypothesis", "target_type", "variable_to_test", "format",
                    "audience", "success_metric", "suggested_duration", "evidence_basis",
                    "evidence_post_ids", "confidence", "requires_verification", "verification_reason",
                ],
                "additionalProperties": False,
            },
        },
        "action_plan": {
            "type": "object",
            "properties": {
                "immediate": {"type": "array", "items": {"type": "string"}},
                "next": {"type": "array", "items": {"type": "string"}},
                "later": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["immediate", "next", "later"],
            "additionalProperties": False,
        },
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
    "action_plan": dict,
}


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

    for key in ("immediate", "next", "later"):
        if key not in data["action_plan"] or not isinstance(data["action_plan"][key], list):
            raise DataError(f"Claude's response action_plan is missing or malformed for '{key}'")


# Mechanical, regex-based safety checks against the response's actual text content -
# structural safeguards, mirroring Stage 4.1's hardening. "Hard" violations mean the
# claim itself is unsafe as worded; "soft" violations are missing metadata that can be
# safely auto-corrected without discarding the claim.
_CAUSAL_VERBS_RE = re.compile(r"\b(drives?|causes?|proves?|guarantees?)\b", re.IGNORECASE)
_COMPETITOR_RE = re.compile(r"\bcompetitors?\b", re.IGNORECASE)
_COMPETITOR_HEDGE_RE = re.compile(
    r"\b(requires?\s+verification|validation\s+is\s+required|competitor\s+validation)\b", re.IGNORECASE
)
_CALENDAR_PERIOD_RE = re.compile(r"\bQ[1-4]\s*20\d{2}\b|\b20\d{2}\s*Q[1-4]\b", re.IGNORECASE)
_BUSINESS_FACT_RE = re.compile(
    r"\b(PADI|SSI|certifi\w*|award\w*|partnership\w*|licens\w*|guarantee\w*|scam\w*|"
    r"safety\s+concern\w*|tourist\s+market\w*)\b",
    re.IGNORECASE,
)
_UNIVERSAL_LANGUAGE_RE = re.compile(
    r"\b(always|every\s+post|all\s+posts|consistently\s+performs?|guaranteed|people\s+love)\b", re.IGNORECASE
)

_EVIDENCE_GROUPS = [
    ("content_opportunities", "opportunity"),
    ("strategy_themes", "theme"),
    ("recommended_formats", "format"),
]


def _iter_text_fields(data: dict):
    """Yield (location, text) for every free-text string field in a response."""
    yield "executive_summary", data.get("executive_summary", "")

    for i, item in enumerate(data.get("content_opportunities", [])):
        for field in ("opportunity", "rationale", "evidence", "suggested_hook", "core_message", "suggested_cta"):
            yield f"content_opportunities[{i}].{field}", item.get(field, "")
    for i, item in enumerate(data.get("strategy_themes", [])):
        yield f"strategy_themes[{i}].evidence", item.get("evidence", "")
    for i, item in enumerate(data.get("recommended_formats", [])):
        yield f"recommended_formats[{i}].rationale", item.get("rationale", "")
    for i, item in enumerate(data.get("recommended_tests", [])):
        for field in ("hypothesis", "success_metric", "evidence_basis"):
            yield f"recommended_tests[{i}].{field}", item.get(field, "")
    action_plan = data.get("action_plan", {})
    if isinstance(action_plan, dict):
        for bucket in ("immediate", "next", "later"):
            for i, text in enumerate(action_plan.get(bucket, [])):
                yield f"action_plan.{bucket}[{i}]", text


def find_evidence_violations(data: dict, valid_post_ids: set) -> dict:
    """Check response content against the hardening rules.
    Returns {"hard": [str, ...], "soft": [{"loc", "type", "detail"}, ...]}."""
    hard = []
    soft = []

    for location, text in _iter_text_fields(data):
        if not isinstance(text, str):
            continue
        if _CAUSAL_VERBS_RE.search(text):
            hard.append(
                f"{location}: uses causal language ('drives'/'causes'/'proves'/'guarantees') "
                f"not supported by observational data: {text!r}"
            )
        if _COMPETITOR_RE.search(text) and not _COMPETITOR_HEDGE_RE.search(text):
            hard.append(
                f"{location}: makes a competitor claim without competitor data and without "
                f"hedged 'validation required' phrasing: {text!r}"
            )
        if _CALENDAR_PERIOD_RE.search(text):
            hard.append(
                f"{location}: contains a hardcoded calendar quarter/year instead of relative "
                f"planning language: {text!r}"
            )

    for group_name, label_field in _EVIDENCE_GROUPS:
        for i, item in enumerate(data.get(group_name, [])):
            if not isinstance(item, dict):
                continue
            loc = f"{group_name}[{i}]"

            evidence_post_ids = item.get("evidence_post_ids") or []
            invalid_ids = [pid for pid in evidence_post_ids if pid not in valid_post_ids]
            if invalid_ids:
                hard.append(f"{loc}: evidence_post_ids references post_id(s) not in the supplied dataset: {invalid_ids}")

            sample_size = item.get("sample_size")
            confidence = item.get("confidence")
            requires_verification = bool(item.get("requires_verification", False))
            combined_text = " ".join(str(item.get(f, "")) for f in (label_field, "evidence", "rationale") if f in item)

            if sample_size is not None and sample_size <= 2 and confidence == "high":
                soft.append(
                    {
                        "loc": loc,
                        "type": "confidence_downgrade",
                        "detail": f"confidence 'high' with sample_size={sample_size} is not justified - downgraded to 'medium'",
                    }
                )

            if sample_size is not None and sample_size <= 2 and not requires_verification and _UNIVERSAL_LANGUAGE_RE.search(combined_text):
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
                        "detail": "references a business/external fact (certification, award, safety/market claim, etc.) not supplied as verified context",
                    }
                )

    # recommended_tests: check evidence_post_ids validity too (separate schema shape).
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

    return {"hard": hard, "soft": soft}


def apply_auto_corrections(data: dict, violations: dict) -> int:
    """Apply soft-violation corrections in place. Returns the number applied."""
    count = 0
    soft_by_loc = {}
    for v in violations["soft"]:
        soft_by_loc.setdefault(v["loc"], []).append(v)

    for group_name, _ in _EVIDENCE_GROUPS:
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
        return f"API error (status {e.status_code})."

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
        "action_plan": claude_result.get("action_plan", {"immediate": [], "next": [], "later": []}),
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
