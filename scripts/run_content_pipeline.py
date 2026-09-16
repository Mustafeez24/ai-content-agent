"""
Content Pipeline Orchestrator for FlyingFish Scuba School.

Coordinates the existing, independently-tested stages in order:

    Stage 2: scripts/scrape_instagram_flyingfish.py  (Instagram scrape via Apify)
        -> data/instagram/flyingfishscuba_posts_raw.json
    Stage 3: scripts/analyze_instagram_content.py     (Claude content analysis)
        -> data/instagram/flyingfishscuba_content_analysis.json
    Stage 4: scripts/content_scout.py                 (Claude Content Scout)
        -> data/instagram/flyingfish_content_scout.json

This file does NOT reimplement Apify, Claude, or analysis logic - it invokes
the three existing scripts as subprocesses (same interpreter, `sys.executable`)
and checks their exit codes. Each stage's own script keeps full responsibility
for its API calls, error handling, and secret handling; this orchestrator does
not read or forward API keys itself.

Usage:
    # Validate everything without calling Apify or Anthropic, or writing data:
    python scripts/run_content_pipeline.py --dry-run

    # Reuse an existing completed Apify run (no new scrape triggered):
    python scripts/run_content_pipeline.py --run-id <existing run ID>

    # Explicitly start a brand new (billable) Apify scrape:
    python scripts/run_content_pipeline.py --new-scrape

A real run always requires exactly one of --run-id / --new-scrape - there is
no silent default that could trigger an unwanted paid scrape.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

STAGE2_SCRIPT = Path("scripts/scrape_instagram_flyingfish.py")
STAGE3_SCRIPT = Path("scripts/analyze_instagram_content.py")
STAGE4_SCRIPT = Path("scripts/content_scout.py")

RAW_PATH = Path("data/instagram/flyingfishscuba_posts_raw.json")
ANALYSIS_PATH = Path("data/instagram/flyingfishscuba_content_analysis.json")
SCOUT_PATH = Path("data/instagram/flyingfish_content_scout.json")

ALL_OUTPUT_PATHS = [RAW_PATH, ANALYSIS_PATH, SCOUT_PATH]


def get_stage_scripts() -> list:
    """Read the three path constants fresh on every call (not a frozen snapshot),
    so reassigning e.g. STAGE2_SCRIPT - as tests do - is always reflected."""
    return [STAGE2_SCRIPT, STAGE3_SCRIPT, STAGE4_SCRIPT]


def check_missing_scripts() -> list:
    return [str(p) for p in get_stage_scripts() if not p.exists()]


def check_gitignored(paths: list) -> dict:
    """Best-effort check via `git check-ignore` - never fatal if git is unavailable."""
    result = {}
    for path in paths:
        try:
            proc = subprocess.run(
                ["git", "check-ignore", str(path)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            result[str(path)] = "ignored" if proc.returncode == 0 else "NOT ignored"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            result[str(path)] = "unknown (git not available)"
    return result


def run_stage(script_path: Path, args: list) -> int:
    """Run one existing stage script as a subprocess. Its stdout/stderr are
    inherited directly (not captured) so its own progress/error output shows
    through unchanged."""
    cmd = [sys.executable, str(script_path)] + args
    proc = subprocess.run(cmd)
    return proc.returncode


def read_posts_analyzed() -> str:
    try:
        with open(ANALYSIS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return str(data.get("metadata", {}).get("posts_analyzed", "unknown"))
    except (FileNotFoundError, json.JSONDecodeError, AttributeError):
        return "unknown"


def print_dry_run_report(args) -> None:
    print("=== DRY RUN: Content Pipeline Orchestrator ===")
    print("No Apify or Anthropic calls will be made. No data files will be written.")
    print()

    missing = check_missing_scripts()
    print("Stage scripts:")
    for script in get_stage_scripts():
        status = "MISSING" if str(script) in missing else "found"
        print(f"  {script}: {status}")
    print()

    print("Environment (presence only - values are never printed):")
    import os

    print(f"  APIFY_API_TOKEN: {'set' if os.environ.get('APIFY_API_TOKEN') else 'NOT set'}")
    print(f"  ANTHROPIC_API_KEY: {'set' if os.environ.get('ANTHROPIC_API_KEY') else 'NOT set'}")
    print()

    print("Output paths and gitignore status:")
    ignore_status = check_gitignored(ALL_OUTPUT_PATHS)
    for path in ALL_OUTPUT_PATHS:
        exists = "exists" if path.exists() else "does not exist yet"
        print(f"  {path}: {exists}, gitignore: {ignore_status.get(str(path), 'unknown')}")
    print()

    if args.run_id and args.new_scrape:
        mode_desc = "INVALID: both --run-id and --new-scrape given (ambiguous - a real run would refuse)"
    elif args.run_id:
        mode_desc = f"reuse existing Apify run '{args.run_id}' - no new Actor run"
    elif args.new_scrape:
        mode_desc = "start a brand NEW Apify Actor run (billable)"
    else:
        mode_desc = "NOT SELECTED - a real run would require --run-id or --new-scrape"

    print(f"Scrape mode: {mode_desc}")
    print()

    print("Stages that WOULD execute, in order:")
    stage2_args = ["--run-id", args.run_id] if args.run_id else []
    print(f"  [1/3] Instagram scrape: python {STAGE2_SCRIPT} {' '.join(stage2_args)}".rstrip())
    print(f"  [2/3] Content analysis: python {STAGE3_SCRIPT}")
    print(f"  [3/3] Content Scout:    python {STAGE4_SCRIPT}")
    print()

    if missing:
        print(f"DRY RUN RESULT: FAILED - missing stage script(s): {missing}")
    else:
        print("DRY RUN RESULT: OK - all stage scripts present, ready to run for real.")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-id", help="Reuse an existing completed Apify Actor run (no new scrape).")
    parser.add_argument("--new-scrape", action="store_true", help="Explicitly start a new (billable) Apify Actor run.")
    parser.add_argument("--dry-run", action="store_true", help="Validate everything; make no API calls or writes.")
    args = parser.parse_args(argv)

    load_dotenv()

    missing = check_missing_scripts()
    if missing:
        print(f"FAILED: Missing required stage script(s): {missing}")
        return 1

    if args.dry_run:
        print_dry_run_report(args)
        return 0

    if args.run_id and args.new_scrape:
        print("FAILED: --run-id and --new-scrape are mutually exclusive - choose one.")
        return 1
    if not args.run_id and not args.new_scrape:
        print("FAILED: A real run requires an explicit scrape mode.")
        print("Use --run-id <existing run ID> to reuse a prior Apify run, or")
        print("--new-scrape to explicitly start a new (billable) Apify Actor run.")
        return 1

    # --- Stage 2: Instagram scrape ---
    print("[1/3] Instagram scrape")
    stage2_args = ["--run-id", args.run_id] if args.run_id else []
    rc = run_stage(STAGE2_SCRIPT, stage2_args)
    if rc != 0:
        print(f"PIPELINE FAILED at Stage 2 (Instagram scrape) - exit code {rc}")
        return rc or 1
    print()

    # --- Stage 3: Content analysis ---
    print("[2/3] Content analysis")
    rc = run_stage(STAGE3_SCRIPT, [])
    if rc != 0:
        print(f"PIPELINE FAILED at Stage 3 (Content analysis) - exit code {rc}")
        return rc or 1
    print()

    # --- Stage 4: Content Scout ---
    print("[3/3] Content Scout")
    rc = run_stage(STAGE4_SCRIPT, [])
    if rc != 0:
        print(f"PIPELINE FAILED at Stage 4 (Content Scout) - exit code {rc}")
        return rc or 1
    print()

    print("PIPELINE SUCCESS")
    print(f"Posts processed: {read_posts_analyzed()}")
    print("Analysis: completed")
    print("Content Scout: completed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
