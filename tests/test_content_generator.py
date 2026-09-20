"""
Tests for scripts/content_generator.py (Stage 8 - Content Generator).

Pure-function tests exercise validation/violation logic directly with hand-built
synthetic dicts (never real FlyingFish data). End-to-end tests mock anthropic.Anthropic
entirely, so no real API calls are made by running this file.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-fake-key-never-used-in-mocked-tests")

import content_generator as cg

VALID_POST_IDS = {"POST_TOP1", "POST_TOP2"}


def make_calendar_item(day_number, content_type="Static Post", platform="Instagram", **overrides):
    base = {
        "day_number": day_number,
        "date": f"2026-01-{day_number:02d}",
        "platform": platform,
        "content_type": content_type,
        "topic": f"Topic for day {day_number}",
        "hook": f"Hook for day {day_number}",
        "objective": "Educational",
        "target_audience": "First-time divers researching certification",
        "content_angle": "Simple beginner education",
        "cta": "DM us to learn more",
        "priority": "medium",
        "evidence_basis": "POST_TOP1 had 3,200 likes and included instructor praise.",
        "evidence_type": "interpretation",
        "source_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": None,
        "status": "planned",
    }
    base.update(overrides)
    return base


# Content-type/platform rotation used to build realistic multi-day calendar fixtures -
# every 5th day forced to Google Business Profile, mirroring Stage 7's real rotation.
_ROTATION = ["Reel", "Carousel", "Static Post", "Story", "Educational Post"]


def make_calendar(days=7):
    items = []
    for i in range(1, days + 1):
        content_type = _ROTATION[(i - 1) % len(_ROTATION)]
        platform = "Google Business Profile" if i % 5 == 0 else "Instagram"
        items.append(make_calendar_item(i, content_type=content_type, platform=platform))
    return {
        "metadata": {"agent": "content_calendar", "model": "claude-haiku-4-5"},
        "calendar_summary": "SYNTHETIC calendar for testing - not real FlyingFish data.",
        "calendar_items": items,
    }


def make_content_item(package_type, index=0, **overrides):
    base = {
        "hook": "", "script_scenes": [], "slides": [], "frames": [],
        "interaction_suggestion": "", "headline": "", "body": "", "caption": "",
        "cta": f"DM us to book your first dive. ({index})",
        "footage_note": "",
        "evidence_basis": "POST_TOP1 had 3,200 likes and included instructor praise.",
        "evidence_type": "interpretation",
        "source_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": "",
    }
    if package_type == "reel":
        base.update({
            "hook": f"Never dived before? Here's what actually happens before you enter the water. ({index})",
            "script_scenes": [
                f"Scene 1 (~3s) - Visual: existing FlyingFish boat footage. On-screen text: 'First dive?' ({index})",
                f"Scene 2 (~5s) - Visual: instructor briefing footage. Point: safety briefing basics. ({index})",
            ],
            "caption": f"What actually happens before your first dive. ({index})",
            "footage_note": "Use existing FlyingFish boat and instructor footage if available.",
        })
    elif package_type == "carousel":
        base.update({
            "hook": f"What SSI certification actually involves. ({index})",
            "slides": [
                f"Slide 1: What SSI certification actually involves. ({index})",
                f"Slide 2: Step one is the classroom sessions. ({index})",
                f"Slide 3: Ready to start? DM us to learn more. ({index})",
            ],
            "caption": f"A quick breakdown of the certification path. ({index})",
            "footage_note": "Use existing FlyingFish classroom and pool training footage if available.",
        })
    elif package_type == "story":
        base.update({
            "frames": [
                f"Frame 1: Ever wondered what marine life looks like near Goa? ({index})",
                f"Frame 2: Real footage from our recent dives. ({index})",
            ],
            "footage_note": "Use existing FlyingFish marine-life footage if available.",
        })
    elif package_type == "static":
        base.update({
            "headline": f"Beginner scuba preparation checklist ({index})",
            "body": f"Here is what first-time divers should know before their first session with FlyingFish. ({index})",
            "caption": f"Save this before your first dive. ({index})",
            "footage_note": "Use existing FlyingFish pool training footage if available.",
        })
    elif package_type == "gbp":
        base.update({
            "headline": f"Learn to dive at FlyingFish Scuba School ({index})",
            "body": f"FlyingFish offers SSI and PADI certifications at Novotel Resort and Spa, Candolim, Goa. ({index})",
        })
    base.update(overrides)
    return base


def make_content_batch_response(package_types, summary=None, start_index=0):
    return {
        "content_summary": summary or "A mix of educational and testimonial content.",
        "content_items": [make_content_item(pt, index=start_index + i) for i, pt in enumerate(package_types)],
    }


def package_types_for(calendar_items):
    return [cg.package_type_for_item(it) for it in calendar_items]


# --- input loading ---
class TestInputLoading(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(cg.DataError):
            cg.load_calendar(Path("/tmp/does_not_exist_calendar.json"))

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_missing_top_level_section(self):
        incomplete = {"metadata": {}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(incomplete, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_empty_calendar_items_rejected(self):
        empty = {"metadata": {}, "calendar_summary": "x", "calendar_items": []}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(empty, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_item_missing_required_field_rejected(self):
        calendar = make_calendar(1)
        del calendar["calendar_items"][0]["evidence_basis"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(calendar, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_invalid_platform_rejected(self):
        calendar = make_calendar(1)
        calendar["calendar_items"][0]["platform"] = "TikTok"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(calendar, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_invalid_content_type_rejected(self):
        calendar = make_calendar(1)
        calendar["calendar_items"][0]["content_type"] = "TikTok Dance Challenge"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(calendar, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_duplicate_day_number_rejected(self):
        calendar = make_calendar(2)
        calendar["calendar_items"][1]["day_number"] = 1
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(calendar, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cg.DataError):
                cg.load_calendar(path)
        finally:
            path.unlink()

    def test_valid_calendar_loads(self):
        calendar = make_calendar(7)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(calendar, f)
            path = Path(f.name)
        try:
            data = cg.load_calendar(path)
            self.assertEqual(len(data["calendar_items"]), 7)
        finally:
            path.unlink()


class TestKnownPostIds(unittest.TestCase):
    def test_known_post_ids_union(self):
        calendar = make_calendar(2)
        calendar["calendar_items"][1]["source_post_ids"] = ["POST_TOP2"]
        ids = cg.known_post_ids(calendar)
        self.assertEqual(ids, {"POST_TOP1", "POST_TOP2"})


# --- package_type routing (Scenarios 6, 7) ---
class TestPackageTypeRouting(unittest.TestCase):
    def test_reel_content_type_routes_to_reel(self):
        item = make_calendar_item(1, content_type="Reel", platform="Instagram")
        self.assertEqual(cg.package_type_for_item(item), "reel")

    def test_carousel_content_type_routes_to_carousel(self):
        item = make_calendar_item(1, content_type="Carousel", platform="Instagram")
        self.assertEqual(cg.package_type_for_item(item), "carousel")

    def test_story_content_type_routes_to_story(self):
        item = make_calendar_item(1, content_type="Story", platform="Instagram")
        self.assertEqual(cg.package_type_for_item(item), "story")

    def test_static_and_educational_variants_route_to_static(self):
        for ct in ("Static Post", "Educational Post", "FAQ", "Q&A", "Community Content"):
            with self.subTest(content_type=ct):
                item = make_calendar_item(1, content_type=ct, platform="Instagram")
                self.assertEqual(cg.package_type_for_item(item), "static")

    def test_google_business_profile_platform_always_routes_to_gbp(self):
        # Scenario 7: platform overrides content_type - GBP has no Reel equivalent.
        item = make_calendar_item(1, content_type="Reel", platform="Google Business Profile")
        self.assertEqual(cg.package_type_for_item(item), "gbp")


class TestBuildBatches(unittest.TestCase):
    def test_thirty_items_split_into_six_batches_of_five(self):
        calendar = make_calendar(30)
        batches = cg.build_batches(calendar["calendar_items"])
        self.assertEqual(len(batches), 6)
        self.assertEqual([len(b) for b in batches], [5] * 6)

    def test_seven_items_split_into_five_and_two(self):
        calendar = make_calendar(7)
        batches = cg.build_batches(calendar["calendar_items"])
        self.assertEqual([len(b) for b in batches], [5, 2])


class TestTokenBudgetForBatch(unittest.TestCase):
    def test_budget_scales_with_batch_size(self):
        base_small, retry_small = cg.token_budget_for_batch(2)
        base_large, retry_large = cg.token_budget_for_batch(5)
        self.assertLess(base_small, base_large)
        self.assertGreater(retry_large, base_large)


# --- schema complexity regression (same lessons as Stage 6/7) ---
class TestSchemaComplexityRegression(unittest.TestCase):
    def _count_enums_and_unions(self, schema):
        enums = unions = 0
        if isinstance(schema, dict):
            if "enum" in schema:
                enums += 1
            if isinstance(schema.get("type"), list):
                unions += 1
            for v in schema.get("properties", {}).values():
                e, u = self._count_enums_and_unions(v)
                enums += e
                unions += u
            if "items" in schema:
                e, u = self._count_enums_and_unions(schema["items"])
                enums += e
                unions += u
        return enums, unions

    def test_schema_has_no_enum_fields(self):
        enums, _ = self._count_enums_and_unions(cg.CONTENT_GENERATOR_RESPONSE_SCHEMA)
        self.assertEqual(enums, 0)

    def test_schema_has_no_nullable_type_unions(self):
        _, unions = self._count_enums_and_unions(cg.CONTENT_GENERATOR_RESPONSE_SCHEMA)
        self.assertEqual(unions, 0)

    def test_schema_size_below_reasonable_threshold(self):
        size = len(json.dumps(cg.CONTENT_GENERATOR_RESPONSE_SCHEMA))
        self.assertLess(size, 4000, f"schema grew to {size} chars - re-check grammar complexity")

    def test_additional_properties_false(self):
        top = cg.CONTENT_GENERATOR_RESPONSE_SCHEMA
        self.assertFalse(top.get("additionalProperties", True))
        item_schema = top["properties"]["content_items"]["items"]
        self.assertFalse(item_schema.get("additionalProperties", True))

    def test_schema_does_not_include_planning_fields(self):
        # day_number/date/platform/content_type/package_type are assigned entirely in
        # Python - Claude's schema must not even offer a place to put them.
        props = cg.CONTENT_GENERATOR_RESPONSE_SCHEMA["properties"]["content_items"]["items"]["properties"]
        for forbidden in ("day_number", "date", "platform", "content_type", "package_type", "topic", "status"):
            self.assertNotIn(forbidden, props)


# --- response validation ---
class TestValidation(unittest.TestCase):
    def test_missing_top_level_field_rejected(self):
        resp = make_content_batch_response(["static"])
        del resp["content_summary"]
        with self.assertRaises(cg.DataError):
            cg.validate_content_response(resp)

    def test_content_items_wrong_type_rejected(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"] = "not a list"
        with self.assertRaises(cg.DataError):
            cg.validate_content_response(resp)

    def test_valid_response_accepted(self):
        resp = make_content_batch_response(["static"])
        cg.validate_content_response(resp)  # should not raise


# --- content/evidence-safety violations ---
class TestContentViolations(unittest.TestCase):
    # Scenarios 1-5: each valid package type has no violations.
    def test_valid_reel_has_no_violations(self):
        resp = make_content_batch_response(["reel"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["reel"])
        self.assertEqual(violations["hard"], [])

    def test_valid_carousel_has_no_violations(self):
        resp = make_content_batch_response(["carousel"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["carousel"])
        self.assertEqual(violations["hard"], [])

    def test_valid_story_has_no_violations(self):
        resp = make_content_batch_response(["story"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["story"])
        self.assertEqual(violations["hard"], [])

    def test_valid_static_has_no_violations(self):
        resp = make_content_batch_response(["static"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])

    def test_valid_gbp_has_no_violations(self):
        resp = make_content_batch_response(["gbp"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["gbp"])
        self.assertEqual(violations["hard"], [])

    # Scenario 6: content shaped for the wrong package type is rejected.
    def test_reel_shaped_content_rejected_for_carousel_slot(self):
        resp = make_content_batch_response(["reel"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["carousel"])
        self.assertTrue(any("slides" in v for v in violations["hard"]))

    # Scenario 7: platform (GBP) forces gbp requirements even if content is reel-shaped.
    def test_reel_shaped_content_rejected_for_gbp_slot(self):
        resp = make_content_batch_response(["reel"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["gbp"])
        self.assertTrue(any("headline" in v for v in violations["hard"]))

    # Scenarios 8/9: wrong item count (missing/extra).
    def test_wrong_item_count_is_hard_violation(self):
        resp = make_content_batch_response(["static", "static"])
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 3, ["static", "static", "static"])
        self.assertTrue(any("exactly 3" in v for v in violations["hard"]))

    # Scenario 11: invented post_id.
    def test_invented_post_id_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["source_post_ids"] = ["POST_DOES_NOT_EXIST"]
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("POST_DOES_NOT_EXIST" in v for v in violations["hard"]))

    def test_real_post_id_accepted(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["source_post_ids"] = ["POST_TOP1", "POST_TOP2"]
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])

    # Scenario 12: unsupported factual claim (soft - flagged, not rejected).
    def test_unsupported_factual_claim_is_soft_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["body"] = "Our certified instructors have years of experience diving in Goa."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])
        self.assertTrue(any(v["loc"] == "content_items[0]" for v in violations["soft"]))

    # Scenario 13: unsupported causal claim (hard).
    def test_causal_language_in_evidence_basis_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = "Instructor praise is the primary engagement driver."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    # Scenario 14: unsupported competitor claim.
    def test_unhedged_competitor_claim_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["body"] = "Unlike our competitors, we focus on safety."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_competitor_claim_with_verification_allowed(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["body"] = "Unlike our competitors, we focus on safety."
        resp["content_items"][0]["requires_verification"] = True
        resp["content_items"][0]["verification_reason"] = "Competitor validation required; no competitor data supplied."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])

    # Scenario 15: unsupported price claim.
    def test_price_claim_without_verification_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["cta"] = "Book now for just ₹5000!"
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("price" in v.lower() for v in violations["hard"]))

    def test_price_claim_with_verification_allowed(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["cta"] = "Book now for just ₹5000!"
        resp["content_items"][0]["requires_verification"] = True
        resp["content_items"][0]["verification_reason"] = "Price not supplied by Stage 6/7 - must be confirmed before publishing."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])

    # Scenario 16: unsupported offer/discount claim.
    def test_offer_claim_without_verification_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["body"] = "Enjoy our limited-time offer this week only."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("offer" in v.lower() for v in violations["hard"]))

    # Scenario 17: requires_verification behavior (consolidated).
    def test_requires_verification_true_without_reason_still_rejected(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["cta"] = "Book now for just ₹5000!"
        resp["content_items"][0]["requires_verification"] = True
        resp["content_items"][0]["verification_reason"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("price" in v.lower() for v in violations["hard"]))

    # Scenario 18: empty hook.
    def test_empty_hook_is_hard_violation_for_reel(self):
        resp = make_content_batch_response(["reel"])
        resp["content_items"][0]["hook"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["reel"])
        self.assertTrue(any(".hook" in v for v in violations["hard"]))

    # Scenario 19: empty script.
    def test_empty_script_scenes_is_hard_violation_for_reel(self):
        resp = make_content_batch_response(["reel"])
        resp["content_items"][0]["script_scenes"] = []
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["reel"])
        self.assertTrue(any("script_scenes" in v for v in violations["hard"]))

    # Scenario 20: invalid carousel structure.
    def test_too_few_slides_is_hard_violation_for_carousel(self):
        resp = make_content_batch_response(["carousel"])
        resp["content_items"][0]["slides"] = ["Only one slide"]
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["carousel"])
        self.assertTrue(any("slides" in v for v in violations["hard"]))

    # Scenario 21: invalid story structure.
    def test_too_few_frames_is_hard_violation_for_story(self):
        resp = make_content_batch_response(["story"])
        resp["content_items"][0]["frames"] = []
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["story"])
        self.assertTrue(any("frames" in v for v in violations["hard"]))

    def test_gbp_missing_body_is_hard_violation(self):
        resp = make_content_batch_response(["gbp"])
        resp["content_items"][0]["body"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["gbp"])
        self.assertTrue(any(".body" in v for v in violations["hard"]))

    def test_missing_cta_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["cta"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any(".cta" in v for v in violations["hard"]))

    def test_hardcoded_calendar_quarter_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["headline"] = "Get certified before Q4 2025!"
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("calendar" in v.lower() for v in violations["hard"]))

    def test_ai_generated_footage_instruction_is_hard_violation(self):
        resp = make_content_batch_response(["reel"])
        resp["content_items"][0]["footage_note"] = "Generate footage using AI for the underwater scene."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["reel"])
        self.assertTrue(any("ai-generated" in v.lower() for v in violations["hard"]))

    def test_missing_footage_note_is_hard_violation_for_reel(self):
        resp = make_content_batch_response(["reel"])
        resp["content_items"][0]["footage_note"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["reel"])
        self.assertTrue(any("footage_note" in v for v in violations["hard"]))

    def test_vague_headline_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["headline"] = "Post content"
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any(".headline" in v for v in violations["hard"]))

    def test_observed_evidence_without_source_post_ids_is_hard_violation(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_type"] = "observed"
        resp["content_items"][0]["source_post_ids"] = []
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("must cite at least one" in v for v in violations["hard"]))

    def test_hypothesis_without_source_post_ids_is_allowed(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_type"] = "hypothesis"
        resp["content_items"][0]["source_post_ids"] = []
        resp["content_items"][0]["evidence_basis"] = "Not directly evidenced in the supplied dataset; a hypothesis-based idea."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])


# --- Hardening pass: regression tests for the real Batch 4/6 failure (Static Post
# with empty headline/body, then a causal "drive" in evidence_basis on retry) ---
class TestHardeningRegression(unittest.TestCase):
    # Scenario 1: Static Post with empty headline fails.
    def test_static_post_empty_headline_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["headline"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any(".headline" in v for v in violations["hard"]))

    # Scenario 2: Static Post with empty body fails.
    def test_static_post_empty_body_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["body"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any(".body" in v for v in violations["hard"]))

    # Scenario 3: Static Post with both empty fails (the exact real-run shape).
    def test_static_post_empty_headline_and_body_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["headline"] = ""
        resp["content_items"][0]["body"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any(".headline" in v for v in violations["hard"]))
        self.assertTrue(any(".body" in v for v in violations["hard"]))

    # Scenario 4: retry feedback contains a Static Post-specific correction.
    def test_retry_feedback_contains_static_post_correction(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["headline"] = ""
        resp["content_items"][0]["body"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        feedback = cg.build_retry_feedback(violations["hard"], ["static"])
        self.assertIn("STATIC POST CORRECTION", feedback)
        self.assertIn("content_items[0]", feedback)
        self.assertIn("headline", feedback)
        self.assertIn("Do not leave any required field empty", feedback)

    def test_retry_feedback_contains_gbp_specific_correction(self):
        resp = make_content_batch_response(["gbp"])
        resp["content_items"][0]["headline"] = ""
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["gbp"])
        feedback = cg.build_retry_feedback(violations["hard"], ["gbp"])
        self.assertIn("GOOGLE BUSINESS PROFILE POST CORRECTION", feedback)

    # Scenarios 5-7: each individual causal word rejected in evidence_basis.
    def test_causal_drive_in_evidence_basis_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = "This content will drive interest in diving."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("causal" in v.lower() and "evidence_basis" in v for v in violations["hard"]))

    def test_causal_drives_in_evidence_basis_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = "Marine-life interest drives booking motivation."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("causal" in v.lower() and "evidence_basis" in v for v in violations["hard"]))

    def test_causal_driving_in_evidence_basis_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = "This is driving strong interest in the format."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("causal" in v.lower() and "evidence_basis" in v for v in violations["hard"]))

    def test_causal_boost_in_evidence_basis_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = "This content will boost booking motivation."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("causal" in v.lower() and "boost" in v.lower() for v in violations["hard"]))

    def test_causal_boosts_in_evidence_basis_fails(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = "This format boosts booking motivation."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertTrue(any("causal" in v.lower() and "boost" in v.lower() for v in violations["hard"]))

    # Scenario 8: corrected, non-causal evidence_basis passes.
    def test_corrected_non_causal_evidence_basis_passes(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_basis"] = (
            "This content tests a static-post format using the documented marine-life interest pattern."
        )
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])

    # Scenario 9: hypothesis wording passes where appropriate.
    def test_hypothesis_framed_evidence_basis_passes(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["evidence_type"] = "hypothesis"
        resp["content_items"][0]["source_post_ids"] = []
        resp["content_items"][0]["evidence_basis"] = (
            "Hypothesis: marine-life-focused static content may be useful to test for booking interest."
        )
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        self.assertEqual(violations["hard"], [])


class TestApplyAutoCorrections(unittest.TestCase):
    def test_soft_violation_sets_requires_verification(self):
        resp = make_content_batch_response(["static"])
        resp["content_items"][0]["body"] = "Our certified instructors have years of experience."
        violations = cg.find_content_violations(resp, VALID_POST_IDS, 1, ["static"])
        applied = cg.apply_auto_corrections(resp["content_items"], violations)
        self.assertEqual(applied, 1)
        self.assertTrue(resp["content_items"][0]["requires_verification"])
        self.assertIn("auto-flagged", resp["content_items"][0]["verification_reason"])


# --- deterministic assembly ---
class TestAssembleContentItems(unittest.TestCase):
    def test_merges_calendar_planning_fields_and_claude_output(self):
        calendar = make_calendar(1)
        calendar_items = calendar["calendar_items"]
        package_types = package_types_for(calendar_items)
        claude_items = [make_content_item(package_types[0])]
        assembled = cg.assemble_content_items(claude_items, calendar_items)
        self.assertEqual(assembled[0]["day_number"], 1)
        self.assertEqual(assembled[0]["platform"], calendar_items[0]["platform"])
        self.assertEqual(assembled[0]["content_type"], calendar_items[0]["content_type"])
        self.assertEqual(assembled[0]["package_type"], package_types[0])
        self.assertEqual(assembled[0]["topic"], calendar_items[0]["topic"])
        self.assertEqual(assembled[0]["hook"], claude_items[0]["hook"])

    def test_status_is_always_drafted(self):
        calendar = make_calendar(1)
        claude_items = [make_content_item("static")]
        assembled = cg.assemble_content_items(claude_items, calendar["calendar_items"])
        self.assertEqual(assembled[0]["status"], "drafted")

    def test_empty_verification_reason_becomes_null(self):
        calendar = make_calendar(1)
        claude_items = [make_content_item("static", verification_reason="")]
        assembled = cg.assemble_content_items(claude_items, calendar["calendar_items"])
        self.assertIsNone(assembled[0]["verification_reason"])


def make_completed_stream(stop_reason, payload_dict):
    resp = MagicMock()
    resp.stop_reason = stop_reason
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload_dict)
    resp.content = [block]
    resp.usage.input_tokens = 1000
    resp.usage.output_tokens = 500
    return resp


class MainEndToEndMixin:
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.calendar_path = Path(self.tmpdir.name) / "calendar.json"
        self.output_path = Path(self.tmpdir.name) / "content.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_calendar(self, days=7):
        calendar = make_calendar(days)
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        return calendar

    def run_main(self, responses, extra_args=None):
        call_count = {"n": 0}

        def fake_create(**kwargs):
            r = responses[call_count["n"]]
            call_count["n"] += 1
            return r

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = fake_create

        with patch("anthropic.Anthropic", return_value=mock_client):
            argv_backup = sys.argv
            sys.argv = ["content_generator.py", "--input", str(self.calendar_path), "--output", str(self.output_path)]
            sys.argv += extra_args or []
            try:
                exit_code = cg.main()
            finally:
                sys.argv = argv_backup
        return exit_code, mock_client.messages.create.call_args_list


class TestDryRun(MainEndToEndMixin, unittest.TestCase):
    def test_dry_run_makes_no_api_call(self):
        self.write_calendar(7)
        with patch("anthropic.Anthropic") as mock_client_cls:
            argv_backup = sys.argv
            sys.argv = ["content_generator.py", "--input", str(self.calendar_path), "--output", str(self.output_path), "--dry-run"]
            try:
                exit_code = cg.main()
            finally:
                sys.argv = argv_backup
        self.assertEqual(exit_code, 0)
        mock_client_cls.assert_not_called()
        self.assertFalse(self.output_path.exists())


class TestValidResponseEndToEnd(MainEndToEndMixin, unittest.TestCase):
    def test_seven_day_calendar_uses_two_batches(self):
        # Scenario 24 (batch generation), Scenario 27 (7-day real-calendar-shaped fixture).
        calendar = self.write_calendar(7)
        package_types = package_types_for(calendar["calendar_items"])
        responses = [
            make_completed_stream("end_turn", make_content_batch_response(package_types[0:5])),
            make_completed_stream("end_turn", make_content_batch_response(package_types[5:7])),
        ]
        exit_code, calls = self.run_main(responses)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.output_path.exists())
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertEqual(output["metadata"]["days_generated"], 7)
        self.assertEqual(output["metadata"]["batches"], 2)
        self.assertEqual(len(output["content_items"]), 7)

    def test_thirty_day_calendar_uses_six_batches(self):
        # Scenario 28 (30-day calendar-shaped fixture), Scenario 25 (final merge).
        calendar = self.write_calendar(30)
        package_types = package_types_for(calendar["calendar_items"])
        responses = [
            make_completed_stream("end_turn", make_content_batch_response(package_types[i : i + 5], start_index=i))
            for i in range(0, 30, 5)
        ]
        exit_code, calls = self.run_main(responses)
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 6)
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertEqual(len(output["content_items"]), 30)
        day_numbers = [item["day_number"] for item in output["content_items"]]
        self.assertEqual(sorted(day_numbers), list(range(1, 31)))
        self.assertEqual(len(set(day_numbers)), 30)
        for item, expected_pt in zip(output["content_items"], package_types):
            self.assertEqual(item["package_type"], expected_pt)

    def test_days_argument_limits_processed_calendar(self):
        calendar = self.write_calendar(30)
        package_types = package_types_for(calendar["calendar_items"][:7])
        responses = [
            make_completed_stream("end_turn", make_content_batch_response(package_types[0:5])),
            make_completed_stream("end_turn", make_content_batch_response(package_types[5:7])),
        ]
        exit_code, calls = self.run_main(responses, extra_args=["--days", "7"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertEqual(len(output["content_items"]), 7)
        self.assertEqual(output["metadata"]["days_generated"], 7)

    def test_days_argument_beyond_calendar_length_rejected(self):
        self.write_calendar(7)
        exit_code, calls = self.run_main([], extra_args=["--days", "30"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 0)

    def test_invalid_days_argument_rejected(self):
        self.write_calendar(7)
        exit_code, calls = self.run_main([], extra_args=["--days", "0"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 0)


class TestTruncation(MainEndToEndMixin, unittest.TestCase):
    def test_truncation_then_success(self):
        calendar = self.write_calendar(2)
        package_types = package_types_for(calendar["calendar_items"])
        exit_code, calls = self.run_main(
            [make_completed_stream("max_tokens", {}), make_completed_stream("end_turn", make_content_batch_response(package_types))]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.output_path.exists())

    def test_truncation_twice_fails_no_output(self):
        self.write_calendar(2)
        exit_code, calls = self.run_main([make_completed_stream("max_tokens", {}), make_completed_stream("max_tokens", {})])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())


class TestRetryAndFailure(MainEndToEndMixin, unittest.TestCase):
    def test_hard_violation_then_clean_retry_succeeds(self):
        # Scenario 22: retry after validation failure.
        calendar = self.write_calendar(2)
        package_types = package_types_for(calendar["calendar_items"])
        bad = make_content_batch_response(package_types)
        bad["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        good = make_content_batch_response(package_types)
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", good)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        second_call_messages = calls[1].kwargs["messages"]
        self.assertIn("CORRECTION REQUIRED", second_call_messages[0]["content"])
        self.assertTrue(self.output_path.exists())

    def test_hard_violation_persists_fails_cleanly(self):
        # Scenario 23: failure after second invalid response.
        calendar = self.write_calendar(2)
        package_types = package_types_for(calendar["calendar_items"])
        bad = make_content_batch_response(package_types)
        bad["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())

    def test_retry_count_bounded_at_two_calls(self):
        calendar = self.write_calendar(2)
        package_types = package_types_for(calendar["calendar_items"])
        bad = make_content_batch_response(package_types)
        bad["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        exit_code, calls = self.run_main(
            [make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)

    def test_batch_failure_after_earlier_batch_success_writes_no_output(self):
        # Scenario 26: no partial output after failure (batch 2 of 2 fails).
        calendar = self.write_calendar(7)
        package_types = package_types_for(calendar["calendar_items"])
        good_batch1 = make_content_batch_response(package_types[0:5])
        bad_batch2 = make_content_batch_response(package_types[5:7])
        bad_batch2["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        responses = [
            make_completed_stream("end_turn", good_batch1),
            make_completed_stream("end_turn", bad_batch2),
            make_completed_stream("end_turn", bad_batch2),
        ]
        exit_code, calls = self.run_main(responses)
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 3)
        self.assertFalse(self.output_path.exists())

    # Scenario 10: Static Post retry succeeds after an invalid first response - the
    # real Batch 4/6 shape (empty headline/body first attempt), but the retry is clean.
    def test_static_post_empty_fields_then_clean_retry_succeeds(self):
        calendar = self.write_calendar(3)
        package_types = package_types_for(calendar["calendar_items"])
        bad = make_content_batch_response(package_types)
        static_index = package_types.index("static")
        bad["content_items"][static_index]["headline"] = ""
        bad["content_items"][static_index]["body"] = ""
        good = make_content_batch_response(package_types)
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", good)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        second_call_messages = calls[1].kwargs["messages"]
        self.assertIn("STATIC POST CORRECTION", second_call_messages[0]["content"])
        self.assertTrue(self.output_path.exists())

    # Scenarios 11 & 12: the exact real failure - first attempt has an empty Static
    # Post headline/body, the retry response instead introduces causal "drive" wording
    # in evidence_basis. Both attempts are invalid, so the whole batch (and run) must
    # fail cleanly with no output written.
    def test_static_post_empty_fields_then_causal_retry_still_fails(self):
        calendar = self.write_calendar(3)
        package_types = package_types_for(calendar["calendar_items"])
        static_index = package_types.index("static")

        first_attempt = make_content_batch_response(package_types)
        first_attempt["content_items"][static_index]["headline"] = ""
        first_attempt["content_items"][static_index]["body"] = ""

        retry_attempt = make_content_batch_response(package_types)
        retry_attempt["content_items"][static_index]["evidence_basis"] = (
            "This content will drive strong interest in booking a dive."
        )

        exit_code, calls = self.run_main(
            [make_completed_stream("end_turn", first_attempt), make_completed_stream("end_turn", retry_attempt)]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())


class TestApiErrorSurfacesRealMessage(MainEndToEndMixin, unittest.TestCase):
    def test_400_with_body_message_is_printed(self):
        import httpx2
        import anthropic

        self.write_calendar(2)
        response = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
        error = anthropic.APIStatusError(
            "bad request",
            response=response,
            body={"error": {"type": "invalid_request_error", "message": "schema validation failed: unexpected token"}},
        )

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = error

        with patch("anthropic.Anthropic", return_value=mock_client):
            argv_backup = sys.argv
            sys.argv = ["content_generator.py", "--input", str(self.calendar_path), "--output", str(self.output_path)]
            try:
                import io
                import contextlib

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    exit_code = cg.main()
            finally:
                sys.argv = argv_backup

        self.assertEqual(exit_code, 1)
        output = buf.getvalue()
        self.assertIn("schema validation failed: unexpected token", output)
        self.assertIn("400", output)
        self.assertFalse(self.output_path.exists())


class TestCalendarFileUntouched(MainEndToEndMixin, unittest.TestCase):
    def test_calendar_file_unchanged_after_run(self):
        self.write_calendar(2)
        before = self.calendar_path.read_text()
        calendar = json.loads(before)
        package_types = package_types_for(calendar["calendar_items"])
        self.run_main([make_completed_stream("end_turn", make_content_batch_response(package_types))])
        after = self.calendar_path.read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
