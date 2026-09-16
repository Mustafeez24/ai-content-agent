"""
Tests for scripts/content_strategy.py (Stage 6 - Content Strategy Agent).

Pure-function tests exercise validation/violation logic directly with hand-built
synthetic dicts (never real FlyingFish data). End-to-end tests mock anthropic.Anthropic
entirely, so no real API calls are made by running this file.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-fake-key-never-used-in-mocked-tests")

import content_strategy as strat

VALID_POST_IDS = {"POST_TOP1", "POST_TOP2"}

STAGE41_FIXTURE = {
    "metadata": {"agent": "content_scout", "posts_analyzed": 20, "model": "claude-haiku-4-5"},
    "executive_summary": "SYNTHETIC - a small set of posts show above-average engagement.",
    "top_performing_content": [
        {"post_id": "POST_TOP1", "engagement_score": 3315, "likes": 3200, "comments": 115, "likely_reason": "x", "evidence": "y"},
        {"post_id": "POST_TOP2", "engagement_score": 500, "likes": 480, "comments": 20, "likely_reason": "x", "evidence": "y"},
    ],
    "top_content_patterns": [
        {
            "pattern": "SYNTHETIC testimonial framing",
            "evidence": "Observed in the top post's caption",
            "recommendation": "Test more testimonial content",
            "evidence_type": "interpretation",
            "evidence_post_ids": ["POST_TOP1"],
            "sample_size": 1,
            "confidence": "low",
            "requires_verification": False,
            "verification_reason": None,
        }
    ],
    "weak_content_patterns": [],
    "content_gaps": [],
    "opportunities": [],
    "recommended_tests": [],
    "action_plan": ["SYNTHETIC: post more reels"],
}


def make_opportunity(**overrides):
    base = {
        "opportunity": "More testimonial-style reels",
        "observation": "POST_TOP1 had 3,200 likes and 115 comments.",
        "pattern": "testimonial framing",
        "interpretation": "This format is associated with stronger engagement in the observed sample.",
        "hypothesis": "Test whether dedicated testimonial reels receive higher engagement than generic posts.",
        "recommended_format": "reel",
        "target_audience": "prospective divers",
        "suggested_cta": "DM us to book a trial dive",
        "evidence_type": "hypothesis",
        "evidence_post_ids": ["POST_TOP1"],
        "sample_size": 1,
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": "",
    }
    base.update(overrides)
    return base


def make_theme(**overrides):
    base = {
        "theme": "Instructor trust",
        "observation": "POST_TOP1 had 3,200 likes.",
        "interpretation": "Instructor praise is associated with strong engagement in the observed sample.",
        "evidence_type": "interpretation",
        "evidence_post_ids": ["POST_TOP1"],
        "sample_size": 1,
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": "",
    }
    base.update(overrides)
    return base


def make_format(**overrides):
    base = {
        "format": "reel",
        "observation": "POST_TOP1 had 3,200 likes.",
        "interpretation": "This format is associated with the strongest observed performer.",
        "evidence_type": "interpretation",
        "evidence_post_ids": ["POST_TOP1"],
        "sample_size": 1,
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": "",
    }
    base.update(overrides)
    return base


def make_test_item(**overrides):
    base = {
        "test_name": "Testimonial reel test",
        "hypothesis": "Test whether testimonial framing is associated with higher engagement than baseline.",
        "target_type": "proposed_test_target",
        "variable_to_test": "testimonial framing",
        "format": "reel",
        "audience": "prospective divers",
        "metric": "likes",
        "target": "15% above dataset average",
        "comparison": "dataset average",
        "suggested_duration": "next 4 weeks",
        "evidence_basis": "POST_TOP1 had 3,200 likes.",
        "evidence_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": "",
    }
    base.update(overrides)
    return base


def make_strategy_response(opportunity_overrides=None, **top_overrides):
    resp = {
        "executive_summary": "A small set of evidence items suggest testimonial framing is worth testing further.",
        "content_opportunities": [make_opportunity(**(opportunity_overrides or {}))],
        "strategy_themes": [make_theme()],
        "recommended_formats": [make_format()],
        "recommended_tests": [make_test_item()],
        "action_plan": [
            "[IMMEDIATE] Draft one testimonial-style reel in the next 1-2 weeks",
            "[NEXT] Review engagement after the next 4 weeks",
        ],
    }
    resp.update(top_overrides)
    return resp


# --- 1/2/3: input loading failures ---
class TestInputLoading(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(strat.DataError):
            strat.load_stage41_report(Path("/tmp/does_not_exist_stage41.json"))

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = Path(f.name)
        try:
            with self.assertRaises(strat.DataError):
                strat.load_stage41_report(path)
        finally:
            path.unlink()

    def test_missing_required_section(self):
        incomplete = {"metadata": {}, "executive_summary": "x"}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(incomplete, f)
            path = Path(f.name)
        try:
            with self.assertRaises(strat.DataError):
                strat.load_stage41_report(path)
        finally:
            path.unlink()

    def test_valid_fixture_loads(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(STAGE41_FIXTURE, f)
            path = Path(f.name)
        try:
            data = strat.load_stage41_report(path)
            self.assertEqual(sorted(data.keys()), sorted(STAGE41_FIXTURE.keys()))
        finally:
            path.unlink()


class TestKnownPostIds(unittest.TestCase):
    def test_known_post_ids_from_fixture(self):
        ids = strat.known_post_ids(STAGE41_FIXTURE)
        self.assertEqual(ids, {"POST_TOP1", "POST_TOP2"})


# --- Regression: schema complexity must stay meaningfully below the level that
# produced the real "compiled grammar is too large" 400 error. ---
class TestSchemaComplexityRegression(unittest.TestCase):
    def _count_enums_and_unions(self, schema):
        enums = 0
        unions = 0
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
        enums, _ = self._count_enums_and_unions(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA)
        self.assertEqual(enums, 0, "schema should contain zero JSON-schema enums")

    def test_schema_has_no_nullable_type_unions(self):
        _, unions = self._count_enums_and_unions(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA)
        self.assertEqual(unions, 0, "schema should contain zero [type, null] unions")

    def test_schema_size_below_reasonable_threshold(self):
        size = len(json.dumps(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA))
        # Generous ceiling - well above the pre-simplification ~4KB that failed, this
        # just guards against future regrowth without being a brittle exact-size check.
        self.assertLess(size, 6000, f"schema grew to {size} chars - re-check grammar complexity")

    def test_action_plan_is_flat_not_nested_object(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["action_plan"]
        self.assertEqual(schema, {"type": "array", "items": {"type": "string"}})

    def test_additional_properties_false_everywhere(self):
        top = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA
        self.assertFalse(top.get("additionalProperties", True))
        for key in ("content_opportunities", "strategy_themes", "recommended_formats", "recommended_tests"):
            item_schema = top["properties"][key]["items"]
            self.assertFalse(item_schema.get("additionalProperties", True), f"{key} should not allow additionalProperties")


class TestSchemaContainsRequiredSections(unittest.TestCase):
    def test_all_critical_output_sections_present(self):
        top_level_props = set(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"].keys())
        api_schema_sections = {
            "executive_summary", "content_opportunities", "strategy_themes",
            "recommended_formats", "recommended_tests", "action_plan",
        }
        self.assertEqual(top_level_props, api_schema_sections)
        self.assertEqual(set(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["required"]), api_schema_sections)

    def test_final_output_file_contains_all_critical_sections(self):
        expected = {
            "metadata", "executive_summary", "top_content_patterns", "weak_content_patterns",
            "content_gaps", "opportunities", "recommended_tests", "action_plan", "top_performing_content",
        }
        # These are Stage 4.1's own section names (its INPUT contract, re-verified here
        # against REQUIRED_SECTIONS) - Stage 6's own OUTPUT uses different, purpose-built
        # names, since it is a new artifact, not a copy of Stage 4.1's report.
        self.assertEqual(set(strat.REQUIRED_SECTIONS), expected)


# --- malformed / truncated response handling (pure function) ---
class TestJsonExtraction(unittest.TestCase):
    def test_valid_json_parses(self):
        resp = make_strategy_response()
        parsed = strat.extract_json_object(json.dumps(resp))
        strat.validate_strategy_response(parsed)

    def test_fenced_json_parses(self):
        resp = make_strategy_response()
        text = "```json\n" + json.dumps(resp) + "\n```"
        parsed = strat.extract_json_object(text)
        strat.validate_strategy_response(parsed)

    def test_truncated_json_raises(self):
        full = json.dumps(make_strategy_response())
        truncated = full[: full.index('"executive_summary"') + 40]
        with self.assertRaises(json.JSONDecodeError):
            strat.extract_json_object(truncated)


# --- missing required output field ---
class TestValidation(unittest.TestCase):
    def test_missing_top_level_field_rejected(self):
        resp = make_strategy_response()
        del resp["executive_summary"]
        with self.assertRaises(strat.DataError):
            strat.validate_strategy_response(resp)

    def test_action_plan_wrong_type_rejected(self):
        resp = make_strategy_response()
        resp["action_plan"] = {"immediate": ["x"], "next": [], "later": []}
        with self.assertRaises(strat.DataError):
            strat.validate_strategy_response(resp)

    def test_action_plan_valid_flat_list_accepted(self):
        resp = make_strategy_response()
        strat.validate_strategy_response(resp)  # should not raise


# --- invented post ID ---
class TestInventedPostIds(unittest.TestCase):
    def test_invented_post_id_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"evidence_post_ids": ["POST_DOES_NOT_EXIST"]})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("POST_DOES_NOT_EXIST" in v for v in violations["hard"]))

    def test_real_post_ids_accepted(self):
        resp = make_strategy_response(opportunity_overrides={"evidence_post_ids": ["POST_TOP1", "POST_TOP2"]})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_invented_post_id_in_recommended_test_is_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_post_ids"] = ["FAKE_POST"]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("FAKE_POST" in v for v in violations["hard"]))


# --- Claude cannot change/fabricate evidence numbers (structural) ---
class TestNoNumericFabricationSurface(unittest.TestCase):
    def test_content_opportunities_schema_has_no_engagement_number_fields(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["content_opportunities"]["items"]
        for forbidden in ("likes", "comments", "engagement_score", "views"):
            self.assertNotIn(forbidden, schema["properties"])
        self.assertFalse(schema.get("additionalProperties", True))


# --- Missing evidence metadata is invalid ---
class TestMissingEvidenceMetadata(unittest.TestCase):
    def test_missing_evidence_type_is_hard_violation(self):
        resp = make_strategy_response()
        del resp["content_opportunities"][0]["evidence_type"]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("evidence_type" in v for v in violations["hard"]))

    def test_missing_confidence_is_hard_violation(self):
        resp = make_strategy_response()
        del resp["content_opportunities"][0]["confidence"]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("confidence" in v for v in violations["hard"]))

    def test_recommended_test_missing_target_type_is_hard_violation(self):
        resp = make_strategy_response()
        del resp["recommended_tests"][0]["target_type"]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("proposed_test_target" in v for v in violations["hard"]))

    def test_recommended_test_with_target_type_passes(self):
        resp = make_strategy_response()
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_schema_requires_target_type_plain_string_not_enum(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["recommended_tests"]["items"]
        self.assertIn("target_type", schema["required"])
        self.assertEqual(schema["properties"]["target_type"], {"type": "string"})
        self.assertNotIn("enum", schema["properties"]["target_type"])

    def test_invalid_confidence_value_is_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["confidence"] = "extremely high"
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("confidence" in v for v in violations["hard"]))


class TestEvidenceTypeLabeling(unittest.TestCase):
    def test_evidence_type_is_plain_string_in_schema(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["content_opportunities"]["items"]
        self.assertEqual(schema["properties"]["evidence_type"], {"type": "string"})
        self.assertEqual(
            strat.ALLOWED_EVIDENCE_TYPES,
            {"observed", "interpretation", "hypothesis", "recommendation"},
        )

    def test_hypothesis_label_survives_violation_check(self):
        resp = make_strategy_response(opportunity_overrides={"evidence_type": "hypothesis"})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_invalid_evidence_type_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"evidence_type": "definitely-true-fact"})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("evidence_type" in v for v in violations["hard"]))


class TestCalendarPeriods(unittest.TestCase):
    def test_hardcoded_quarter_in_action_plan_is_hard_violation(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["[IMMEDIATE] Launch a Q4 2025 campaign."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("calendar" in v.lower() for v in violations["hard"]))

    def test_relative_timeframe_allowed(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["[IMMEDIATE] Launch a campaign in the next 4 weeks."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


class TestActionPlanParsing(unittest.TestCase):
    def test_parse_action_plan_buckets_by_prefix(self):
        items = [
            "[IMMEDIATE] Do this now",
            "[NEXT] Do this soon",
            "[LATER] Do this eventually",
            "[immediate] lowercase tag also works",
        ]
        result = strat.parse_action_plan(items)
        self.assertEqual(result["immediate"], ["Do this now", "lowercase tag also works"])
        self.assertEqual(result["next"], ["Do this soon"])
        self.assertEqual(result["later"], ["Do this eventually"])

    def test_untagged_item_defaults_to_next_not_dropped(self):
        result = strat.parse_action_plan(["No bracket tag here"])
        self.assertEqual(result["next"], ["No bracket tag here"])
        self.assertEqual(result["immediate"], [])
        self.assertEqual(result["later"], [])


# --- STRICT fields (observation/interpretation/evidence_basis): unconditional causal
# check, no hedge exemption of any kind - these fields never propose a test.
class TestStrictFieldCausalLanguage(unittest.TestCase):
    def test_drives_in_interpretation_is_violation(self):
        resp = make_strategy_response(opportunity_overrides={"interpretation": "This drives higher engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_primary_driver_in_interpretation_is_violation(self):
        resp = make_strategy_response(opportunity_overrides={"interpretation": "Instructor quality is the primary driver of engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_generates_in_evidence_basis_is_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_basis"] = "This messaging generates high comment engagement."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_past_tense_increased_in_observation_is_violation(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "Engagement increased after this post."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_test_whether_inside_interpretation_does_not_exempt_it(self):
        # Strict fields have no hedge exemption at all - even a "test whether" phrase
        # embedded in interpretation does not excuse a causal claim there. The
        # separate "hypothesis" field exists precisely so this never needs to happen.
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "This drives engagement; test whether it holds up."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_hedged_association_interpretation_is_allowed(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "This format is associated with higher engagement in this sample."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_scarcity_driven_compound_adjective_allowed_in_interpretation(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "Scarcity-driven CTAs are associated with strong engagement in this sample."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_narrative_driven_compound_adjective_allowed(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "Narrative-driven reels appear among the top posts."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_observed_metric_generating_likes_allowed_in_observation(self):
        resp = make_strategy_response(
            opportunity_overrides={"observation": "POST_TOP1, generating 3,266 likes and 49 comments, is the top performer."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_generating_bookings_is_not_automatically_allowed(self):
        # The observed-metric exemption is scoped to engagement metrics only
        # (likes/comments/shares/saves/views/followers/reactions) - "bookings" is a
        # business outcome never established by this dataset, so it is not exempt.
        resp = make_strategy_response(opportunity_overrides={"observation": "This format is generating 40 bookings this month."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))


# --- CREATIVE fields: never causal-checked, regardless of content ---
class TestCreativeFieldsNotCausalChecked(unittest.TestCase):
    def test_drive_in_pattern_field_not_flagged(self):
        resp = make_strategy_response(opportunity_overrides={"pattern": "urgency-driven CTAs that drive clicks"})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_guarantee_in_recommended_format_field_not_flagged(self):
        resp = make_strategy_response(
            opportunity_overrides={"recommended_format": "Carousel, which guarantees brand-controlled sequencing"}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_action_plan_generate_allowed(self):
        resp = make_strategy_response()
        resp["action_plan"] = [
            "[NEXT] Generate weekly performance report to marketing team comparing actual results to test hypotheses."
        ]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_action_plan_drive_treated_as_action_not_evidence(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["[NEXT] Drive traffic to the new booking page by pinning the top testimonial reel."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_metric_field_not_causal_checked(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["metric"] = "Click-through rate to booking page increases 15%+."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_target_and_comparison_fields_not_causal_checked(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["target"] = "Booking form submissions show increased mentions of safety reassurance."
        resp["recommended_tests"][0]["comparison"] = "the current baseline, which generates fewer mentions"
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- HYPOTHESIS fields: structural validation, not a causal-language scan ---
class TestHypothesisStructuralValidation(unittest.TestCase):
    def test_hypothesis_without_test_verb_is_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Click-through rate to booking page increases 15%+."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("test verb" in v for v in violations["hard"]))

    def test_hypothesis_with_test_whether_is_allowed(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Test whether click-through rate to booking page increases 15%+."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_hypothesis_starting_with_compare_is_allowed(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Compare generic testimonials against named-instructor content and measure "
            "whether specific-instructor inquiries differ between the two."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_hypothesis_past_tense_is_violation_even_with_correct_prefix(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Test whether named-instructor content drove higher engagement."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("past-tense" in v for v in violations["hard"]))

    def test_content_opportunities_hypothesis_also_structurally_checked(self):
        resp = make_strategy_response(opportunity_overrides={"hypothesis": "Instructor content increases engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("test verb" in v for v in violations["hard"]))


# --- competitor claims ---
class TestCompetitorClaims(unittest.TestCase):
    def test_unhedged_competitor_claim_in_interpretation_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"interpretation": "No competitor addresses this angle."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_hedged_competitor_claim_allowed(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "A potential differentiation angle; competitor validation required."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_competitor_claim_with_verification_allowed(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "interpretation": "This may differentiate FlyingFish from competitors.",
                "requires_verification": True,
                "verification_reason": "No competitor dataset was supplied; needs manual research.",
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_competitor_claim_in_target_audience_is_hard_violation(self):
        # target_audience is a CREATIVE field (not causal-checked) but competitor
        # claims are unsafe in every field, so it's still checked for those.
        resp = make_strategy_response(
            opportunity_overrides={"target_audience": "Potential bookers evaluating FlyingFish against competitors."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_unverified_competitor_claim_in_action_plan_is_hard_violation(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["[NEXT] Research how competitors position their certification content."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))


class TestBusinessFactClaims(unittest.TestCase):
    def test_unverified_business_fact_soft_flagged(self):
        resp = make_strategy_response(
            opportunity_overrides={"observation": "The post mentions PADI certification.", "requires_verification": False}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])
        self.assertTrue(any(v["type"] == "flag_verification" for v in violations["soft"]))

    def test_auto_correction_sets_requires_verification(self):
        resp = make_strategy_response(
            opportunity_overrides={"observation": "References a scam concern in the tourist market.", "requires_verification": False}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        applied = strat.apply_auto_corrections(resp, violations)
        self.assertGreater(applied, 0)
        item = resp["content_opportunities"][0]
        self.assertTrue(item["requires_verification"])
        self.assertIsNotNone(item["verification_reason"])


# --- Regression tests for the exact latest real-run failures from this hardening pass ---
class TestLatestRealRunFailureRegression(unittest.TestCase):
    def test_ctas_drive_strong_engagement_is_violation_in_interpretation(self):
        # content_opportunities[2].evidence (old field name) -> interpretation (new)
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "DH3VdAmCS5g demonstrates that time-limited discount CTAs drive strong engagement."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_proven_educational_format_is_violation_in_interpretation(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "A dedicated transparency series would pair well with the proven educational format."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_proven_to_drive_engagement_is_violation(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "Educational format is proven to drive engagement."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_carousel_cannot_guarantee_allowed_in_creative_format_field(self):
        # recommended_formats[2].rationale (old) -> "format" is now a creative label,
        # this kind of format-mechanics reasoning belongs there, not in interpretation.
        resp = make_strategy_response()
        resp["recommended_formats"][0]["format"] = (
            "Carousel format, which allows brand-controlled layout that reels' algorithm cannot guarantee"
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_carousel_cannot_guarantee_still_violation_if_placed_in_interpretation(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["interpretation"] = (
            "Carousel format allows brand-controlled layout that reels' algorithm cannot guarantee."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_appears_to_drive_community_response_is_violation(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["interpretation"] = "This format appears to drive community response and intent signaling."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_click_through_rate_increases_without_test_verb_is_hypothesis_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Click-through rate to booking page increases 15%+."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("test verb" in v for v in violations["hard"]))

    def test_documented_top_engagement_driver_in_evidence_basis_is_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_basis"] = (
            "No current dedicated instructor-spotlight content exists in the dataset, despite "
            "instructor quality being a documented top engagement driver."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_increased_mentions_target_field_allowed(self):
        # recommended_tests[4].success_metric (old, free prose) -> target (new,
        # structural, creative field) - not causal-checked.
        resp = make_strategy_response()
        resp["recommended_tests"][0]["target"] = (
            "Increased mentions of safety/certification reassurance as decision factors in inquiry text"
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_generate_weekly_report_action_item_allowed(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["[NEXT] Generate weekly performance report to marketing team comparing actual results to test hypotheses."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- Regression tests for the exact 5 real-run failures reported after the
# structured-field redesign (commit f52f85d). All 5 were the validator working
# correctly (4 were genuine unsupported causal claims Claude kept generating in
# observational fields) except one real bug: the hypothesis field's past-tense check
# flagged "increased" when used adjectivally as a target descriptor ("correlate with
# increased DM inquiries") the same way it flags a genuine completed-action assertion
# ("DM inquiries increased") - see _is_hypothesis_target_descriptor.
class TestThirdRealRunFailureRegression(unittest.TestCase):
    def test_1_executive_summary_drive_is_violation(self):
        resp = make_strategy_response(
            executive_summary=(
                "Promotional carousel posts with discount urgency (DH3VdAmCS5g, 1,119 likes) and "
                "educational course breakdowns (DIgZ3GuC0mo, 1,112 likes; DHvnI6ViEAb, 1,158 likes) "
                "also drive strong engagement."
            )
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() and "executive_summary" in v for v in violations["hard"]))

    def test_2_evidence_basis_personal_connection_drive_is_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_basis"] = (
            "DWyk4T6E5OF testimonial with explicit instructor praise achieved 3,266 likes (49 comments, "
            "10x account average comment rate), indicating instructor credibility and personal "
            "connection drive exceptional engagement."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_3_observation_generated_comment_ratio_is_violation(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "observation": (
                    "DYGc47zo4Tr (366 likes, 20 comments) used countdown messaging for seasonal "
                    "reopening and generated notably high comment ratio (5.5% engagement rate)."
                )
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_4_recommended_formats_observation_drove_is_violation(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["observation"] = "Emotional reaction and instructor praise drove exceptional performance."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_5_hypothesis_correlate_with_increased_dm_inquiries_allowed(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Test whether 2-4 educational reels addressing PADI/SSI certification standards, safety "
            "protocols, and 'How to Identify Unqualified Operators' generate 800+ likes, 25+ comments "
            "(indicating reassurance-seeking engagement), and correlate with increased DM inquiries "
            "about certifications and booking form submissions from safety-focused prospects."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- Additional coverage required for this hardening pass ---
class TestObservationalVsHypothesisWordChoice(unittest.TestCase):
    def test_observational_fields_reject_drive_driven_drove_generated_increased(self):
        for word, text in [
            ("drive", "This format continues to drive strong engagement."),
            ("driven", "Engagement here was driven by instructor praise."),
            ("drove", "Instructor praise drove exceptional performance."),
            ("generated", "This post generated a strong comment ratio."),
            ("increased", "Comment volume increased after this post."),
        ]:
            with self.subTest(word=word):
                resp = make_strategy_response(opportunity_overrides={"interpretation": text})
                violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
                self.assertTrue(
                    any("causal" in v.lower() for v in violations["hard"]),
                    f"expected {word!r} to be rejected in an observational field: {text!r}",
                )

    def test_observed_metric_received_likes_passes(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "POST_TOP1 received 3,266 likes and 49 comments."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_compound_adjective_narrative_driven_passes(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "Narrative-driven reels are associated with strong engagement in this sample."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_hypothesis_can_use_future_test_framing(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Measure whether testimonial reels achieve higher engagement than educational reels over the next 4 weeks."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_hypothesis_cannot_claim_past_observed_outcome(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Test whether testimonial reels performed better after engagement increased last month."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("past-tense" in v for v in violations["hard"]))

    def test_track_dm_inquiries_passes(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Track DM inquiries during the test period."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_track_increased_dm_inquiries_rejected_as_already_observed_increase(self):
        # Contrast with test_5 above: "with increased DM inquiries" (preposition
        # before the participle) names a future target; "Track increased DM
        # inquiries" (bare verb before the participle) reads as asserting the
        # increase already happened, and stays rejected.
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Track increased DM inquiries during the test period."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("past-tense" in v for v in violations["hard"]))


# --- Regression tests for the exact 8 real-run failures reported after commit
# 85c3c5f. All 8 were the validator correctly rejecting genuine unsupported causal/
# competitor claims Claude kept generating in observational fields - confirmed by
# hand-checking each one against find_evidence_violations before writing these tests.
# The one code change this round was closing a real gap in _STRONG_CLAIM_RE: "primary
# X driver" only recognized "engagement" as the intervening word, so a variant like
# "primary top-post driver" (failure #6) would have slipped through if that exact
# sentence hadn't also contained a second, already-covered "primary engagement
# driver" phrase earlier in it. The fix and the rest of this hardening pass are prompt
# tightening (a RAW DATA -> OBSERVATION -> INTERPRETATION -> HYPOTHESIS ->
# RECOMMENDATION -> TEST pipeline framing with a worked example, plus BAD/GOOD pairs
# matching each failure verbatim) so Claude generates fewer of these on the first
# attempt - it does not change what the validator accepts or rejects.
class TestFourthRealRunFailureRegression(unittest.TestCase):
    def test_1_observation_proves_transformation_narratives_drive_engagement(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "observation": (
                    "Report identifies absence of dedicated 'Non-Swimmer to Diver' transformation content "
                    "despite strong evidence this resonates; DWyk4T6E5OF's emotional resonance proves "
                    "transformation narratives drive engagement."
                )
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_2_observation_educational_format_has_proven_engagement_value(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "observation": (
                    "Report identifies marine life discovery as documented strong theme and dive site content "
                    "as completely absent; educational format has proven engagement value across DIgZ3GuC0mo "
                    "(1,112 likes) and DHvnI6ViEAb (1,158 likes)."
                )
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_3_strategy_themes_observation_primary_engagement_driver(self):
        resp = make_strategy_response()
        resp["strategy_themes"][0]["observation"] = (
            "DWyk4T6E5OF recorded 3,266 likes with explicit instructor praise as primary engagement driver; "
            "report notes instructor quality is discussed implicitly in top posts but no dedicated instructor "
            "profile content exists."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_4_recommended_formats_observation_primary_engagement_driver(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["observation"] = (
            "Report identifies explicit instructor praise in DWyk4T6E5OF as primary engagement driver "
            "(3,266 likes, 49 comments); no existing content dedicates full spotlight to named instructor."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_5_recommended_formats_interpretation_aligns_with_proven_format(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["interpretation"] = (
            "Educational video format shows strong engagement; location-specific dive site education is "
            "absent but aligns with proven educational format performance."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_6_evidence_basis_primary_top_post_driver_variant(self):
        # This is the exact string that exposed the _STRONG_CLAIM_RE gap - even
        # isolating just the "primary top-post driver" half (with the earlier
        # "primary engagement driver" phrase removed) must still be caught.
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_basis"] = (
            "Report notes instructor quality emerges as primary top-post driver but no dedicated "
            "instructor spotlight content exists."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_7_recommended_formats_interpretation_demonstrated_engagement_drivers(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["interpretation"] = (
            "Instructor praise in top posts suggests named instructor content would be aligned with "
            "demonstrated engagement drivers, though dedicated spotlight format is untested."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_8_recommended_tests_audience_competitor_comparison_unverified(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["audience"] = (
            "Certification-seekers researching 'how to get certified' and course structure; high-intent "
            "audience reducing booking friction via transparent pathway; students comparing FlyingFish "
            "structure vs. competitors"
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))


class TestFieldSemanticContractRequirements(unittest.TestCase):
    def test_1_observation_rejects_primary_engagement_driver(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "This is the primary engagement driver."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_2_observation_rejects_proven_engagement_value(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "This format has proven engagement value."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_3_observation_rejects_transformation_narratives_drive_engagement(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "Transformation narratives drive engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_4_observation_accepts_recorded_likes_and_comments(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "DWyk4T6E5OF recorded 3,266 likes and 49 comments."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_5_observation_accepts_includes_explicit_instructor_praise(self):
        resp = make_strategy_response(opportunity_overrides={"observation": "DWyk4T6E5OF includes explicit instructor praise."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_6_interpretation_accepts_associated_with_strong_observed_engagement(self):
        resp = make_strategy_response(
            opportunity_overrides={"interpretation": "These posts are associated with strong observed engagement."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_7_interpretation_rejects_these_posts_drive_engagement(self):
        resp = make_strategy_response(opportunity_overrides={"interpretation": "These posts drive engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_8_hypothesis_accepts_test_whether_named_instructor(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Test whether named instructor content receives higher engagement than generic testimonials."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_9_hypothesis_accepts_measure_whether_educational_reels(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Measure whether educational reels perform differently from testimonial reels."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_10_audience_rejects_competitor_comparison_without_verification(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["audience"] = "Students comparing FlyingFish structure vs. competitors."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_10b_audience_accepts_competitor_comparison_with_verification(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["audience"] = "Students comparing FlyingFish structure vs. competitors."
        resp["recommended_tests"][0]["requires_verification"] = True
        resp["recommended_tests"][0]["verification_reason"] = (
            "Competitor validation required; competitor data is not present in the supplied dataset."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_11_audience_accepts_certification_seekers_without_competitors(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["audience"] = "Certification-seekers researching how to get certified and understand course structure."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_12_compound_adjectives_continue_to_work(self):
        for word in ("narrative-driven", "urgency-driven", "weather-driven", "scarcity-driven"):
            with self.subTest(word=word):
                resp = make_strategy_response(
                    opportunity_overrides={"interpretation": f"{word.capitalize()} content is associated with strong engagement."}
                )
                violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
                self.assertEqual(violations["hard"], [], f"{word!r} should not be treated as a causal claim")


# --- error message extraction (Step 2 fix: real Anthropic error, never a bare status) ---
class TestApiErrorMessageExtraction(unittest.TestCase):
    def test_extracts_message_from_body_error_dict(self):
        e = MagicMock()
        e.body = {"error": {"type": "invalid_request_error", "message": "schema is invalid: bad enum"}}
        e.message = None
        self.assertEqual(strat.extract_api_error_message(e), "schema is invalid: bad enum")

    def test_falls_back_to_message_attribute(self):
        e = MagicMock()
        e.body = None
        e.message = "some SDK-level message"
        self.assertEqual(strat.extract_api_error_message(e), "some SDK-level message")

    def test_falls_back_to_str_when_nothing_else_available(self):
        class Fake(Exception):
            body = None
            message = None

        e = Fake("plain fallback text")
        self.assertEqual(strat.extract_api_error_message(e), "plain fallback text")

    def test_redacts_credential_like_strings(self):
        e = MagicMock()
        e.body = {"error": {"message": "bad key sk-ant-abc123XYZ_-9 was used"}}
        e.message = None
        result = strat.extract_api_error_message(e)
        self.assertNotIn("sk-ant-abc123XYZ_-9", result)
        self.assertIn("[REDACTED]", result)


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
        self.stage41_path = Path(self.tmpdir.name) / "stage41.json"
        self.output_path = Path(self.tmpdir.name) / "strategy.json"
        with open(self.stage41_path, "w") as f:
            json.dump(STAGE41_FIXTURE, f)

    def tearDown(self):
        self.tmpdir.cleanup()

    def run_main(self, responses):
        call_count = {"n": 0}

        def fake_create(**kwargs):
            r = responses[call_count["n"]]
            call_count["n"] += 1
            return r

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = fake_create

        with patch("anthropic.Anthropic", return_value=mock_client):
            argv_backup = sys.argv
            sys.argv = ["content_strategy.py", "--input", str(self.stage41_path), "--output", str(self.output_path)]
            try:
                exit_code = strat.main()
            finally:
                sys.argv = argv_backup
        return exit_code, mock_client.messages.create.call_args_list


# --- dry-run makes no API call ---
class TestDryRun(MainEndToEndMixin, unittest.TestCase):
    def test_dry_run_makes_no_api_call(self):
        with patch("anthropic.Anthropic") as mock_client_cls:
            argv_backup = sys.argv
            sys.argv = ["content_strategy.py", "--input", str(self.stage41_path), "--output", str(self.output_path), "--dry-run"]
            try:
                exit_code = strat.main()
            finally:
                sys.argv = argv_backup
        self.assertEqual(exit_code, 0)
        mock_client_cls.assert_not_called()
        self.assertFalse(self.output_path.exists())


# --- valid Claude response end-to-end ---
class TestValidResponseEndToEnd(MainEndToEndMixin, unittest.TestCase):
    def test_valid_response_succeeds_with_one_call(self):
        exit_code, calls = self.run_main([make_completed_stream("end_turn", make_strategy_response())])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.output_path.exists())
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertEqual(output["metadata"]["agent"], "content_strategy")
        self.assertIn("content_opportunities", output)


# --- truncated response ---
class TestTruncation(MainEndToEndMixin, unittest.TestCase):
    def test_truncation_then_success(self):
        exit_code, calls = self.run_main(
            [make_completed_stream("max_tokens", {}), make_completed_stream("end_turn", make_strategy_response())]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.output_path.exists())

    def test_truncation_twice_fails_no_output(self):
        exit_code, calls = self.run_main([make_completed_stream("max_tokens", {}), make_completed_stream("max_tokens", {})])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())


# --- retry after invalid response, second failure, no partial output ---
class TestRetryAndFailure(MainEndToEndMixin, unittest.TestCase):
    def test_hard_violation_then_clean_retry_succeeds(self):
        bad = make_strategy_response(opportunity_overrides={"interpretation": "No competitor addresses this."})
        good = make_strategy_response()
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", good)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        second_call_messages = calls[1].kwargs["messages"]
        self.assertIn("CORRECTION REQUIRED", second_call_messages[0]["content"])
        self.assertTrue(self.output_path.exists())

    def test_hard_violation_persists_fails_cleanly(self):
        bad = make_strategy_response(opportunity_overrides={"interpretation": "No competitor addresses this."})
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())

    def test_no_partial_output_on_any_failure(self):
        exit_code, calls = self.run_main([make_completed_stream("max_tokens", {}), make_completed_stream("max_tokens", {})])
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())
        self.assertEqual(list(Path(self.tmpdir.name).glob("strategy*")), [])

    def test_retry_count_bounded_at_two_calls(self):
        # Even three consecutive hard violations must never trigger a third API call.
        bad = make_strategy_response(opportunity_overrides={"interpretation": "No competitor addresses this."})
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)


# --- soft violation auto-corrected without wasting a retry ---
class TestSoftViolationAutoCorrection(MainEndToEndMixin, unittest.TestCase):
    def test_soft_violation_succeeds_on_first_call(self):
        resp = make_strategy_response(
            opportunity_overrides={"observation": "Mentions PADI certification.", "requires_verification": False}
        )
        exit_code, calls = self.run_main([make_completed_stream("end_turn", resp)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertTrue(output["content_opportunities"][0]["requires_verification"])


# --- end-to-end: a real 400 surfaces its actual server message, not a bare status code ---
class TestApiErrorSurfacesRealMessage(MainEndToEndMixin, unittest.TestCase):
    def test_400_with_body_message_is_printed(self):
        import httpx2
        import anthropic

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
            sys.argv = ["content_strategy.py", "--input", str(self.stage41_path), "--output", str(self.output_path)]
            try:
                import io
                import contextlib

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    exit_code = strat.main()
            finally:
                sys.argv = argv_backup

        self.assertEqual(exit_code, 1)
        output = buf.getvalue()
        self.assertIn("schema validation failed: unexpected token", output)
        self.assertIn("400", output)
        self.assertFalse(self.output_path.exists())


# --- existing Stage 4.1 output remains untouched ---
class TestStage41Untouched(MainEndToEndMixin, unittest.TestCase):
    def test_stage41_file_unchanged_after_run(self):
        before = self.stage41_path.read_text()
        self.run_main([make_completed_stream("end_turn", make_strategy_response())])
        after = self.stage41_path.read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
