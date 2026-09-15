"""
Content analysis of the raw FlyingFish Instagram dataset, using Claude.

Loads data/instagram/flyingfishscuba_posts_raw.json (produced by
scrape_instagram_flyingfish.py), discovers the actual schema present in the
file at runtime (fields vary by Apify actor/version - this does not assume
a fixed schema), computes deterministic engagement metrics locally, then
asks Claude for one interpretive analysis pass over the normalized data.

Triggers no Apify activity whatsoever - this only reads the existing local
JSON file.

Usage:
    source venv/bin/activate
    python scripts/analyze_instagram_content.py
    python scripts/analyze_instagram_content.py --dry-run   # skip the Claude
        call; useful for validating the pipeline without spending API credit
    python scripts/analyze_instagram_content.py --input path/to/file.json
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_INPUT_PATH = Path("data/instagram/flyingfishscuba_posts_raw.json")
OUTPUT_PATH = Path("data/instagram/flyingfishscuba_content_analysis.json")
MODEL = "claude-haiku-4-5"  # cheapest current model - structured classification task, cost-conscious project

# Candidate key names per logical field. Apify's instagram-scraper actor is
# the expected source, but this does not assume a single fixed key name -
# each logical field tries several known variants and falls back to None.
FIELD_CANDIDATES = {
    "shortcode": ["shortCode", "shortcode", "code"],
    "url": ["url", "inputUrl"],
    "caption": ["caption", "text"],
    "hashtags": ["hashtags"],
    "mentions": ["mentions"],
    "likes": ["likesCount", "likes"],
    "comments": ["commentsCount", "comments"],
    "video_views": ["videoViewCount", "videoPlayCount", "videoViewsCount"],
    "timestamp": ["timestamp"],
    "post_type": ["type"],
    "product_type": ["productType"],
    "owner_username": ["ownerUsername"],
    "child_posts": ["childPosts", "sidecarItems"],
}

EXPECTED_LOGICAL_FIELDS = list(FIELD_CANDIDATES.keys())


class DataError(Exception):
    """Raised for problems with the input data (missing file, bad JSON, wrong shape)."""


def load_posts(path: Path) -> list:
    if not path.exists():
        raise DataError(f"Input file not found: {path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise DataError(f"Input file is not valid JSON: {e}")

    if not isinstance(data, list):
        raise DataError(f"Expected a JSON list of posts, got {type(data).__name__}")
    if not data:
        raise DataError("Input file contains an empty list of posts")
    if not all(isinstance(item, dict) for item in data):
        raise DataError("Expected every item in the list to be a JSON object")

    return data


def first_present(post: dict, candidate_keys: list, field_found_counter: Counter, logical_name: str):
    for key in candidate_keys:
        if key in post and post[key] not in (None, ""):
            field_found_counter[logical_name] += 1
            return post[key]
    return None


def discover_schema(posts: list) -> dict:
    """Report the real fields present across the dataset - not assumed, observed."""
    all_keys = Counter()
    for post in posts:
        all_keys.update(post.keys())

    resolved_field_counts = Counter()
    for post in posts:
        for logical_name, candidates in FIELD_CANDIDATES.items():
            first_present(post, candidates, resolved_field_counts, logical_name)

    return {
        "post_count": len(posts),
        "raw_keys_seen": dict(sorted(all_keys.items(), key=lambda kv: -kv[1])),
        "logical_field_coverage": {
            name: f"{resolved_field_counts.get(name, 0)}/{len(posts)}"
            for name in EXPECTED_LOGICAL_FIELDS
        },
    }


def normalize_post(post: dict, index: int) -> dict:
    counter = Counter()  # throwaway - normalize_post doesn't need coverage stats
    shortcode = first_present(post, FIELD_CANDIDATES["shortcode"], counter, "shortcode")
    url = first_present(post, FIELD_CANDIDATES["url"], counter, "url")
    caption = first_present(post, FIELD_CANDIDATES["caption"], counter, "caption")
    hashtags = first_present(post, FIELD_CANDIDATES["hashtags"], counter, "hashtags")
    mentions = first_present(post, FIELD_CANDIDATES["mentions"], counter, "mentions")
    likes = first_present(post, FIELD_CANDIDATES["likes"], counter, "likes")
    comments = first_present(post, FIELD_CANDIDATES["comments"], counter, "comments")
    video_views = first_present(post, FIELD_CANDIDATES["video_views"], counter, "video_views")
    timestamp = first_present(post, FIELD_CANDIDATES["timestamp"], counter, "timestamp")
    post_type = first_present(post, FIELD_CANDIDATES["post_type"], counter, "post_type")
    product_type = first_present(post, FIELD_CANDIDATES["product_type"], counter, "product_type")
    owner_username = first_present(post, FIELD_CANDIDATES["owner_username"], counter, "owner_username")
    child_posts = first_present(post, FIELD_CANDIDATES["child_posts"], counter, "child_posts")

    likes = likes if isinstance(likes, (int, float)) else None
    comments = comments if isinstance(comments, (int, float)) else None
    video_views = video_views if isinstance(video_views, (int, float)) else None

    return {
        "post_id": shortcode or f"post_index_{index}",
        "post_url": url or "unknown",
        "caption": caption if isinstance(caption, str) else "",
        "hashtags": hashtags if isinstance(hashtags, list) else [],
        "mentions": mentions if isinstance(mentions, list) else [],
        "likes": likes,
        "comments": comments,
        "video_views": video_views,
        "timestamp": timestamp or None,
        "post_type": post_type or "unknown",
        "product_type": product_type or "unknown",
        "owner_username": owner_username or "unknown",
        "is_carousel": bool(child_posts) and isinstance(child_posts, list) and len(child_posts) > 0,
        "media_count": (len(child_posts) if isinstance(child_posts, list) and child_posts else 1),
    }


def compute_deterministic_metrics(normalized_posts: list) -> dict:
    likes_values = [p["likes"] for p in normalized_posts if p["likes"] is not None]
    comments_values = [p["comments"] for p in normalized_posts if p["comments"] is not None]
    video_view_values = [p["video_views"] for p in normalized_posts if p["video_views"] is not None]

    for p in normalized_posts:
        p["engagement_score"] = (p["likes"] or 0) + (p["comments"] or 0)

    ranked = sorted(normalized_posts, key=lambda p: p["engagement_score"], reverse=True)
    top_n = min(5, len(ranked))
    bottom_n = min(3, len(ranked))

    timestamps = [p["timestamp"] for p in normalized_posts if p["timestamp"]]
    date_range = {"earliest": min(timestamps), "latest": max(timestamps)} if timestamps else {
        "earliest": None,
        "latest": None,
    }

    hashtag_counter = Counter()
    for p in normalized_posts:
        hashtag_counter.update(h.lower() for h in p["hashtags"])

    post_type_counter = Counter(p["post_type"] for p in normalized_posts)

    return {
        "total_posts": len(normalized_posts),
        "posts_with_likes_data": len(likes_values),
        "posts_with_comments_data": len(comments_values),
        "posts_with_video_view_data": len(video_view_values),
        "total_likes": sum(likes_values) if likes_values else None,
        "total_comments": sum(comments_values) if comments_values else None,
        "total_video_views": sum(video_view_values) if video_view_values else None,
        "average_likes": round(sum(likes_values) / len(likes_values), 1) if likes_values else None,
        "average_comments": round(sum(comments_values) / len(comments_values), 1) if comments_values else None,
        "average_video_views": round(sum(video_view_values) / len(video_view_values), 1) if video_view_values else None,
        "date_range": date_range,
        "post_type_distribution": dict(post_type_counter),
        "top_hashtags": hashtag_counter.most_common(15),
        "top_posts": [
            {"post_id": p["post_id"], "engagement_score": p["engagement_score"], "likes": p["likes"], "comments": p["comments"]}
            for p in ranked[:top_n]
        ],
        "lowest_posts": [
            {"post_id": p["post_id"], "engagement_score": p["engagement_score"], "likes": p["likes"], "comments": p["comments"]}
            for p in ranked[-bottom_n:]
        ],
    }


def build_claude_payload(normalized_posts: list, metrics: dict) -> list:
    top_ids = {p["post_id"] for p in metrics["top_posts"]}
    low_ids = {p["post_id"] for p in metrics["lowest_posts"]}
    return [
        {
            "post_id": p["post_id"],
            "caption": p["caption"][:600],
            "hashtags": p["hashtags"],
            "mentions": p["mentions"],
            "post_type": p["post_type"],
            "product_type": p["product_type"],
            "is_carousel": p["is_carousel"],
            "likes": p["likes"],
            "comments": p["comments"],
            "video_views": p["video_views"],
            "engagement_score": p["engagement_score"],
            "is_top_performer": p["post_id"] in top_ids,
            "is_low_performer": p["post_id"] in low_ids,
        }
        for p in normalized_posts
    ]


CLAUDE_SYSTEM_PROMPT = """You are a social media content analyst for FlyingFish Scuba School, \
a PADI/SSI scuba diving school at Novotel Resort & Spa, Candolim, Goa, India. \
You will receive a compact JSON array of Instagram posts with real, already-computed \
engagement numbers and a performance flag (is_top_performer / is_low_performer) that was \
calculated deterministically from those numbers - you must NOT recompute, second-guess, \
or contradict which posts performed best. Your job is only to interpret WHY, based on \
each post's content characteristics (caption, hashtags, format), and to find patterns \
across the set.

Respond with ONLY a single valid JSON object (no markdown code fences, no commentary \
before or after) matching exactly this shape:

{
  "post_analyses": [
    {
      "post_id": "<same post_id from input>",
      "main_topic": "<short phrase or 'unknown'>",
      "content_category": "<short phrase or 'unknown'>",
      "hook": "<short phrase describing the opening/hook, or 'unknown'>",
      "cta": "<short phrase describing the call to action, or 'unknown'>",
      "tone": "<short phrase, e.g. playful/educational/inspirational, or 'unknown'>",
      "target_audience": "<short phrase or 'unknown'>",
      "content_format": "<short phrase, e.g. photo/reel/carousel, or 'unknown'>",
      "diving_subject": "<short phrase, e.g. certification course/marine life/resort, or 'unknown'>",
      "content_intent": "<one of: promotional, educational, inspirational, unknown>",
      "key_themes": ["<short phrase>", "..."]
    }
  ],
  "content_patterns": {
    "strongest_themes": ["..."],
    "recurring_topics": ["..."],
    "common_hooks": ["..."],
    "common_ctas": ["..."],
    "content_formats_used": ["..."]
  },
  "performance_patterns": {
    "traits_of_top_performers": ["..."],
    "traits_of_low_performers": ["..."],
    "weak_or_underused_content_areas": ["..."]
  },
  "recommendations": [
    "<concrete, specific, actionable recommendation for future FlyingFish content>"
  ]
}

Include one entry in post_analyses for every post in the input, in the same order. \
Do not invent facts not supported by the caption/hashtags/metrics provided - use "unknown" \
where you cannot determine something. Keep every string field concise (under ~20 words)."""


def call_claude(api_key: str, payload: list) -> tuple:
    import anthropic  # imported lazily so --dry-run doesn't require the package to be importable-clean

    client = anthropic.Anthropic(api_key=api_key)

    user_message = (
        "Analyze these Instagram posts for FlyingFish Scuba School. "
        "Engagement numbers and top/low performer flags are already computed - interpret, don't recompute.\n\n"
        + json.dumps(payload, ensure_ascii=False)
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=6000,
        system=CLAUDE_SYSTEM_PROMPT,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="Path to the raw Instagram JSON.")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to write the analysis JSON.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip the Claude API call (validates loading/normalization/metrics/output only).",
    )
    args = parser.parse_args()

    load_dotenv()

    try:
        raw_posts = load_posts(args.input)
    except DataError as e:
        print(f"FAILED: {e}")
        return 1

    schema_report = discover_schema(raw_posts)
    print("=== Schema discovered in input file (not assumed) ===")
    print(f"Post count: {schema_report['post_count']}")
    print(f"Raw keys seen across posts: {list(schema_report['raw_keys_seen'].keys())}")
    print("Logical field coverage (found/total posts):")
    for name, coverage in schema_report["logical_field_coverage"].items():
        print(f"  {name}: {coverage}")
    print()

    normalized_posts = [normalize_post(p, i) for i, p in enumerate(raw_posts)]
    metrics = compute_deterministic_metrics(normalized_posts)
    payload = build_claude_payload(normalized_posts, metrics)

    claude_result = None
    usage_info = None

    if args.dry_run:
        print("DRY RUN: skipping Claude API call.")
        claude_result = {
            "post_analyses": [],
            "content_patterns": {},
            "performance_patterns": {},
            "recommendations": [],
            "note": "dry run - no Claude call was made",
        }
    else:
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
                text2, response2 = call_claude(
                    api_key,
                    payload + [{"_reminder": "Respond with ONLY the JSON object, no other text."}],
                )
                claude_result = parse_claude_json(text2)
                response = response2
            except (json.JSONDecodeError, Exception) as e:
                print(f"FAILED: Claude did not return valid JSON: {e}")
                return 1

        usage_info = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

    output = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source_file": str(args.input),
            "model_used": MODEL if not args.dry_run else "none (dry run)",
            "posts_analyzed": len(normalized_posts),
            "dry_run": args.dry_run,
        },
        "dataset_summary": metrics,
        "top_posts": metrics["top_posts"],
        "content_patterns": claude_result.get("content_patterns", {}),
        "performance_patterns": claude_result.get("performance_patterns", {}),
        "claude_analysis": {"post_analyses": claude_result.get("post_analyses", [])},
        "recommendations": claude_result.get("recommendations", []),
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print("SUCCESS: Analysis complete.")
    print(f"Posts analyzed: {len(normalized_posts)}")
    print(f"Model used: {output['metadata']['model_used']}")
    if usage_info:
        input_cost = usage_info["input_tokens"] / 1_000_000 * 1.00
        output_cost = usage_info["output_tokens"] / 1_000_000 * 5.00
        print(f"Token usage: {usage_info['input_tokens']} in / {usage_info['output_tokens']} out")
        print(f"Approx. cost (Haiku 4.5 list pricing): ${input_cost + output_cost:.4f} USD")
    print(f"Saved analysis to: {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
