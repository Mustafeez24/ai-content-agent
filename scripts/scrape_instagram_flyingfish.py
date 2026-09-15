"""
Small test scrape of the FlyingFish Instagram account via Apify.

Runs the `apify/instagram-scraper` Actor against a single public profile,
limited to 20 posts, with no Instagram login and no residential proxy
(datacenter/default Apify proxy only). Saves the raw dataset locally.
Never prints APIFY_API_TOKEN.

Usage:
    source venv/bin/activate
    python scripts/scrape_instagram_flyingfish.py
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from apify_client import ApifyClient

ACTOR_ID = "apify/instagram-scraper"
TARGET_URL = "https://www.instagram.com/flyingfishscuba/"
RESULTS_LIMIT = 20
OUTPUT_PATH = Path("data/instagram/flyingfishscuba_posts_raw.json")

RUN_INPUT = {
    "directUrls": [TARGET_URL],
    "resultsType": "posts",
    "resultsLimit": RESULTS_LIMIT,
    "addParentData": False,
    # Default Apify proxy only - no residential group (keeps cost predictable).
    "proxyConfiguration": {"useApifyProxy": True},
}


def main() -> int:
    load_dotenv()

    api_token = os.environ.get("APIFY_API_TOKEN")
    if not api_token:
        print("FAILED: APIFY_API_TOKEN is not set.")
        print("Add it to your local .env file (see .env.example) and try again.")
        return 1

    client = ApifyClient(api_token)

    print(f"Starting Actor run: {ACTOR_ID} (limit={RESULTS_LIMIT} posts, no residential proxy)...")
    try:
        run = client.actor(ACTOR_ID).call(run_input=RUN_INPUT)
    except Exception as e:
        print(f"FAILED: Actor run could not be started or did not finish: {e}")
        return 1

    status = run.get("status")
    if status != "SUCCEEDED":
        print(f"FAILED: Actor run finished with status '{status}'.")
        print(f"Run ID: {run.get('id')}")
        return 1

    dataset_id = run["defaultDatasetId"]
    items = list(client.dataset(dataset_id).iterate_items())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    # Cost reporting: Apify does not always expose a dollar figure on the run
    # object depending on account/plan - report whatever is available.
    usage_usd = run.get("usageTotalUsd")
    stats = run.get("stats", {})

    print("SUCCESS: Actor run completed.")
    print(f"Run ID: {run.get('id')}")
    print(f"Posts collected: {len(items)}")
    print(f"Fields in first item: {sorted(items[0].keys()) if items else 'N/A (no items returned)'}")
    if usage_usd is not None:
        print(f"Reported usage cost: ${usage_usd:.4f} USD")
    else:
        print("Reported usage cost: not available on the run object - check the Apify Console run details for the exact figure.")
    if stats:
        print(f"Run stats: {stats}")
    print(f"Saved raw results to: {OUTPUT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
