"""
Content Scout Agent for FlyingFish Scuba School.

Reads the existing Stage 3 output (data/instagram/flyingfishscuba_content_analysis.json,
produced by analyze_instagram_content.py) and turns it into a structured, evidence-based
scout report. This does NOT scrape Instagram, call Apify, or re-analyze raw posts - it
builds on Stage 3's already-computed deterministic metrics and Claude-generated patterns.

Deterministic data (top/lowest performing posts, engagement scores) comes straight from
Stage 3's dataset_summary and is never recomputed or overridden by Claude here - Claude
only adds interpretation for the post_ids it is given.

Usage:
    source venv/bin/activate
    python scripts/content_scout.py
    python scripts/content_scout.py --dry-run   # validate + prepare input, no API call
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_INPUT_PATH = Path("data/instagram/flyingfishscuba_content_analysis.json")
OUTPUT_PATH = Path("data/instagram/flyingfish_content_scout.json")
MODEL = "claude-haiku-4-5"  # cheapest current model - synthesis over already-computed data

REQUIRED_SECTIONS = [
    "metadata",
    "dataset_summary",
    "content_patterns",
    "performance_patterns",
    "recommendations",
]


class DataError(Exception):
    """Raised for problems with the Stage 3 input (missing file, bad JSON, missing sections)."""


def load_stage3_analysis(path: Path) -> dict:
    if not path.exists():
        raise DataError(f"Stage 3 analysis file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Stage 3 analysis file is not valid JSON: {e}")

    if not isinstance(data, dict):
        raise DataError(f"Expected a JSON object at the top level, got {type(data).__name__}")

    missing = [key for key in REQUIRED_SECTIONS if key not in data]
    if missing:
        raise DataError(f"Stage 3 analysis is missing required section(s): {missing}")

    if not isinstance(data.get("dataset_summary"), dict) or not data["dataset_summary"]:
        raise DataError("Stage 3 analysis 'dataset_summary' is empty or malformed - nothing usable to build on")

    return data


def build_claude_payload(stage3: dict) -> dict:
    """Compact, already-summarized input for Claude - not the raw Instagram dataset."""
    dataset_summary = stage3["dataset_summary"]
    top_posts = dataset_summary.get("top_posts", [])
    lowest_posts = dataset_summary.get("lowest_posts", [])

    evidence_post_ids = {p["post_id"] for p in top_posts} | {p["post_id"] for p in lowest_posts}
    post_analyses = stage3.get("claude_analysis", {}).get("post_analyses", [])
    evidence_posts = [p for p in post_analyses if p.get("post_id") in evidence_post_ids]

    return {
        "posts_analyzed": stage3.get("metadata", {}).get("posts_analyzed"),
        "dataset_summary": {
            "total_posts": dataset_summary.get("total_posts"),
            "average_likes": dataset_summary.get("average_likes"),
            "average_comments": dataset_summary.get("average_comments"),
            "average_video_views": dataset_summary.get("average_video_views"),
            "date_range": dataset_summary.get("date_range"),
            "post_type_distribution": dataset_summary.get("post_type_distribution"),
            "top_hashtags": dataset_summary.get("top_hashtags"),
        },
        "top_posts": top_posts,
        "lowest_posts": lowest_posts,
        "evidence_post_details": evidence_posts,
        "content_patterns": stage3.get("content_patterns", {}),
        "performance_patterns": stage3.get("performance_patterns", {}),
        "stage3_recommendations": stage3.get("recommendations", []),
    }


CONTENT_SCOUT_SYSTEM_PROMPT = """You are the Content Scout Agent for FlyingFish Scuba School, \
a PADI/SSI scuba diving school at Novotel Resort & Spa, Candolim, Goa, India.

Analyze the provided Instagram content-performance analysis, which was already computed by \
a prior deterministic + Claude analysis pass. The top_posts and lowest_posts lists, and all \
numeric engagement figures, are already correct and final - you must NOT recompute, \
re-rank, contradict, or invent different engagement numbers or a different ranking.

Your job is NOT to invent facts. Base recommendations primarily on the supplied analysis. \
Separate observed patterns from recommendations. Do not claim that something is proven \
when the dataset only suggests it - this is a small dataset (typically ~20 posts), so most \
findings should be framed as low-to-medium confidence unless the evidence is unusually \
consistent. Do not fabricate engagement numbers, posts, topics, or audience behavior. If \
the dataset is insufficient to determine something, explicitly say so rather than guessing. \
Prioritize actionable, practical recommendations for a scuba-diving business in Goa.

Respond with ONLY a single valid JSON object (no markdown code fences, no commentary before \
or after) matching exactly this shape:

{
  "executive_summary": "<3-5 sentence plain-language summary for a marketing team>",
  "top_content_patterns": [
    {"pattern": "...", "evidence": "...", "confidence": "high|medium|low", "recommendation": "..."}
  ],
  "top_performing_content_notes": [
    {"post_id": "<must be one of the given top_posts post_ids>", "likely_reason": "...", "evidence": "..."}
  ],
  "weak_content_patterns": [
    {"pattern": "...", "evidence": "...", "confidence": "high|medium|low"}
  ],
  "content_gaps": [
    {"gap": "...", "evidence": "...", "confidence": "high|medium|low"}
  ],
  "opportunities": [
    {"opportunity": "...", "rationale": "...", "confidence": "high|medium|low"}
  ],
  "recommended_tests": [
    {"test": "...", "hypothesis": "...", "expected_signal": "..."}
  ],
  "action_plan": ["<concrete next step, ordered by priority>"]
}

For "top_performing_content_notes", use ONLY the post_ids provided in top_posts - do not \
introduce any other post_id. Keep every string field concise and specific to scuba diving \
content in Goa, not generic social media advice."""

# Passed via output_config.format (json_schema) so the API constrains generation to
# schema-valid JSON directly - this closes off the whole class of "malformed JSON from
# unescaped quotes/newlines/unicode" failures, independent of the truncation fix below.
CONTENT_SCOUT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "top_content_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "recommendation": {"type": "string"},
                },
                "required": ["pattern", "evidence", "confidence", "recommendation"],
                "additionalProperties": False,
            },
        },
        "top_performing_content_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_id": {"type": "string"},
                    "likely_reason": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["post_id", "likely_reason", "evidence"],
                "additionalProperties": False,
            },
        },
        "weak_content_patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["pattern", "evidence", "confidence"],
                "additionalProperties": False,
            },
        },
        "content_gaps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "gap": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["gap", "evidence", "confidence"],
                "additionalProperties": False,
            },
        },
        "opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "opportunity": {"type": "string"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["opportunity", "rationale", "confidence"],
                "additionalProperties": False,
            },
        },
        "recommended_tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test": {"type": "string"},
                    "hypothesis": {"type": "string"},
                    "expected_signal": {"type": "string"},
                },
                "required": ["test", "hypothesis", "expected_signal"],
                "additionalProperties": False,
            },
        },
        "action_plan": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "executive_summary",
        "top_content_patterns",
        "top_performing_content_notes",
        "weak_content_patterns",
        "content_gaps",
        "opportunities",
        "recommended_tests",
        "action_plan",
    ],
    "additionalProperties": False,
}

# 4000 was measured too low against the real 20-post payload (truncated mid-string at
# ~3,900 tokens). 8000 gives real headroom; the truncation retry escalates further still.
BASE_MAX_TOKENS = 8000
RETRY_MAX_TOKENS = 12000


class TruncatedResponseError(Exception):
    """Raised when Claude's response was cut off by the token limit before completing."""


def call_claude(api_key: str, payload: dict, max_tokens: int = BASE_MAX_TOKENS) -> tuple:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        "Here is the Stage 3 content-performance analysis for FlyingFish Scuba School's "
        "Instagram account. Rankings and numbers are already final - interpret them, "
        "do not recompute.\n\n" + json.dumps(payload, ensure_ascii=False)
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=CONTENT_SCOUT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
        output_config={"format": {"type": "json_schema", "schema": CONTENT_SCOUT_RESPONSE_SCHEMA}},
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

    # Balanced-brace scan: find the first '{' and its matching '}', tolerating any
    # surrounding commentary text the model might have added around the JSON object.
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
                    return json.loads(candidate)  # let JSONDecodeError propagate if still bad

    # Nothing worked - raise the original error against the untouched text for a clear message.
    return json.loads(cleaned)


REQUIRED_RESPONSE_FIELDS = {
    "executive_summary": str,
    "top_content_patterns": list,
    "top_performing_content_notes": list,
    "weak_content_patterns": list,
    "content_gaps": list,
    "opportunities": list,
    "recommended_tests": list,
    "action_plan": list,
}


def validate_scout_response(data) -> None:
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


def assemble_top_performing_content(top_posts: list, claude_notes: list) -> list:
    """Merge Stage 3's deterministic top_posts with Claude's interpretation, keyed by
    post_id. Deterministic fields always come from Stage 3 - never from Claude."""
    notes_by_id = {n.get("post_id"): n for n in claude_notes if isinstance(n, dict)}
    result = []
    for post in top_posts:
        note = notes_by_id.get(post["post_id"], {})
        result.append(
            {
                "post_id": post["post_id"],
                "engagement_score": post.get("engagement_score"),
                "likes": post.get("likes"),
                "comments": post.get("comments"),
                "likely_reason": note.get("likely_reason", "unknown"),
                "evidence": note.get("evidence", "unknown"),
            }
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to the Stage 3 analysis JSON.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to write the scout report JSON.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load/validate Stage 3 data and prepare the Claude input, but skip the API call and output write.",
    )
    args = parser.parse_args()

    load_dotenv()

    try:
        stage3 = load_stage3_analysis(args.input)
    except DataError as e:
        print(f"FAILED: {e}")
        return 1

    print("=== Stage 3 analysis inspected (real top-level keys) ===")
    print(f"Top-level keys: {sorted(stage3.keys())}")
    print(f"dataset_summary keys: {sorted(stage3['dataset_summary'].keys())}")
    print(f"content_patterns keys: {sorted(stage3.get('content_patterns', {}).keys())}")
    print(f"performance_patterns keys: {sorted(stage3.get('performance_patterns', {}).keys())}")
    print(f"posts_analyzed (metadata): {stage3.get('metadata', {}).get('posts_analyzed')}")
    print(f"recommendations count: {len(stage3.get('recommendations', []))}")
    print()

    payload = build_claude_payload(stage3)
    print("=== Compact Claude input prepared ===")
    print(f"top_posts included: {len(payload['top_posts'])}")
    print(f"lowest_posts included: {len(payload['lowest_posts'])}")
    print(f"evidence_post_details included: {len(payload['evidence_post_details'])}")
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

    # At most two Claude calls total: one normal attempt, one retry only if the first
    # was truncated (higher max_tokens) or returned unparseable/invalid JSON.
    for attempt, max_tokens in enumerate([BASE_MAX_TOKENS, RETRY_MAX_TOKENS], start=1):
        try:
            text, response = call_claude(api_key, payload, max_tokens=max_tokens)
        except TruncatedResponseError as e:
            last_error = str(e)
            if attempt == 1:
                print(f"{e} Retrying once with max_tokens={RETRY_MAX_TOKENS}...")
                continue
            print(f"FAILED: Response was truncated even at max_tokens={RETRY_MAX_TOKENS}. "
                  "The payload or requested output is too large for this budget - reduce "
                  "the payload (e.g. fewer evidence posts) rather than raising the limit further.")
            return 1
        except api_errors as e:
            print(f"FAILED: {describe_api_error(e)}")
            return 1

        try:
            claude_result = extract_json_object(text)
            validate_scout_response(claude_result)
            break
        except (json.JSONDecodeError, DataError) as e:
            last_error = str(e)
            if attempt == 1:
                print(f"Claude's response was invalid ({e}) - retrying once with max_tokens={RETRY_MAX_TOKENS}...")
                continue
            print(f"FAILED: Claude did not return a valid, complete response after retry: {last_error}")
            return 1

    if claude_result is None:
        print(f"FAILED: Could not obtain a valid response from Claude: {last_error}")
        return 1

    top_performing_content = assemble_top_performing_content(
        payload["top_posts"], claude_result.get("top_performing_content_notes", [])
    )

    output = {
        "metadata": {
            "agent": "content_scout",
            "source": str(args.input),
            "posts_analyzed": stage3.get("metadata", {}).get("posts_analyzed"),
            "model": MODEL,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        "executive_summary": claude_result.get("executive_summary", "unknown"),
        "top_content_patterns": claude_result.get("top_content_patterns", []),
        "top_performing_content": top_performing_content,
        "weak_content_patterns": claude_result.get("weak_content_patterns", []),
        "content_gaps": claude_result.get("content_gaps", []),
        "opportunities": claude_result.get("opportunities", []),
        "recommended_tests": claude_result.get("recommended_tests", []),
        "action_plan": claude_result.get("action_plan", []),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("SUCCESS: Content Scout analysis complete.")
    print(f"Posts analyzed: {output['metadata']['posts_analyzed']}")
    print(f"Model used: {MODEL}")
    print(f"Token usage: {response.usage.input_tokens} in / {response.usage.output_tokens} out")
    input_cost = response.usage.input_tokens / 1_000_000 * 1.00
    output_cost = response.usage.output_tokens / 1_000_000 * 5.00
    print(f"Approx. cost (Haiku 4.5 list pricing): ${input_cost + output_cost:.4f} USD")
    print(f"Saved scout report to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
