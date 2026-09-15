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


def call_claude(api_key: str, payload: dict) -> tuple:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    user_message = (
        "Here is the Stage 3 content-performance analysis for FlyingFish Scuba School's "
        "Instagram account. Rankings and numbers are already final - interpret them, "
        "do not recompute.\n\n" + json.dumps(payload, ensure_ascii=False)
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=CONTENT_SCOUT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    text = "".join(block.text for block in response.content if block.type == "text")
    return text, response


def parse_claude_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:]
    return json.loads(cleaned.strip())


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

    try:
        text, response = call_claude(api_key, payload)
    except anthropic.AuthenticationError:
        print("FAILED: Authentication error - the API key was rejected.")
        return 1
    except anthropic.PermissionDeniedError:
        print("FAILED: Permission denied - the API key lacks access to this model.")
        return 1
    except anthropic.NotFoundError:
        print(f"FAILED: Model not found ({MODEL}).")
        return 1
    except anthropic.RateLimitError:
        print("FAILED: Rate limited. Try again in a moment.")
        return 1
    except anthropic.APIConnectionError:
        print("FAILED: Network error - could not reach the Anthropic API.")
        return 1
    except anthropic.APIStatusError as e:
        print(f"FAILED: API error (status {e.status_code}).")
        return 1

    try:
        claude_result = parse_claude_json(text)
    except json.JSONDecodeError:
        print("Claude's response was not valid JSON on first attempt - retrying once with a stricter reminder...")
        try:
            retry_payload = dict(payload)
            retry_payload["_reminder"] = "Respond with ONLY the JSON object, no other text."
            text2, response2 = call_claude(api_key, retry_payload)
            claude_result = parse_claude_json(text2)
            response = response2
        except json.JSONDecodeError as e:
            print(f"FAILED: Claude did not return valid JSON: {e}")
            return 1

    if not isinstance(claude_result, dict):
        print("FAILED: Claude's parsed response was not a JSON object.")
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
