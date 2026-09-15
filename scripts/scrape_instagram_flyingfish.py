"""
Small test scrape of the FlyingFish Instagram account via Apify.

Runs the `apify/instagram-scraper` Actor against a single public profile,
limited to 20 posts, with no Instagram login and no residential proxy
(datacenter/default Apify proxy only). Saves the raw dataset locally.
Never prints APIFY_API_TOKEN.

The Apify Python SDK (apify-client 3.x) returns typed objects (e.g. `Run`),
not plain dicts - fields are accessed as attributes (`run.status`,
`run.default_dataset_id`), not `run.get(...)` / `run["..."]`.

Usage:
    source venv/bin/activate
    python scripts/scrape_instagram_flyingfish.py
        # starts a new Actor run

    python scripts/scrape_instagram_flyingfish.py --run-id <existing run ID>
        # reuses an existing completed run instead of starting a new one
"""

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-id",
        help="Reuse an existing completed Actor run instead of starting a new one.",
    )
    args = parser.parse_args()

    load_dotenv()

    api_token = os.environ.get("APIFY_API_TOKEN")
    if not api_token:
        print("FAILED: APIFY_API_TOKEN is not set.")
        print("Add it to your local .env file (see .env.example) and try again.")
        return 1

    client = ApifyClient(api_token)

    if args.run_id:
        print(f"Reusing existing Actor run: {args.run_id} (no new run will be started)...")
        try:
            run = client.run(args.run_id).get()
        except Exception as e:
            print(f"FAILED: Could not retrieve run {args.run_id}: {e}")
            return 1
        if run is None:
            print(f"FAILED: Run {args.run_id} was not found.")
            return 1
    else:
        print(f"Starting Actor run: {ACTOR_ID} (limit={RESULTS_LIMIT} posts, no residential proxy)...")
        try:
            run = client.actor(ACTOR_ID).call(run_input=RUN_INPUT)
        except Exception as e:
            print(f"FAILED: Actor run could not be started or did not finish: {e}")
            return 1

    # apify-client 3.x returns a typed `Run` object - use attributes, not
    # dict-style .get()/["..."] access.
    if run.status != "SUCCEEDED":
        print(f"FAILED: Actor run finished with status '{run.status}'.")
        print(f"Run ID: {run.id}")
        return 1

    items = list(client.dataset(run.default_dataset_id).iterate_items())

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print("SUCCESS: Actor run completed.")
    print(f"Run ID: {run.id}")
    print(f"Posts collected: {len(items)}")
    print(f"Fields in first item: {sorted(items[0].keys()) if items else 'N/A (no items returned)'}")
    if run.usage_total_usd is not None:
        print(f"Reported usage cost: ${run.usage_total_usd:.4f} USD")
    else:
        print("Reported usage cost: not available on the run object - check the Apify Console run details for the exact figure.")
    if run.stats is not None:
        print(f"Run stats: {run.stats.model_dump(exclude_none=True)}")
    print(f"Saved raw results to: {OUTPUT_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
