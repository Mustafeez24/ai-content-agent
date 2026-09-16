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
        "rationale": "Top post used testimonial framing",
        "evidence": "Observed in POST_TOP1",
        "recommended_format": "reel",
        "target_audience": "prospective divers",
        "content_angle": "instructor trust",
        "suggested_hook": "Meet the instructor who got me certified",
        "core_message": "Structured, supportive learning",
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


def make_test_item(**overrides):
    base = {
        "test_name": "Testimonial reel test",
        "hypothesis": "May be associated with higher engagement",
        "target_type": "proposed_test_target",
        "variable_to_test": "testimonial framing",
        "format": "reel",
        "audience": "prospective divers",
        "success_metric": "likes above dataset average",
        "suggested_duration": "next 4 weeks",
        "evidence_basis": "POST_TOP1 performance",
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
        "strategy_themes": [
            {
                "theme": "Instructor trust",
                "evidence": "Present in the top-performing post",
                "evidence_type": "interpretation",
                "evidence_post_ids": ["POST_TOP1"],
                "sample_size": 1,
                "confidence": "low",
                "requires_verification": False,
                "verification_reason": "",
            }
        ],
        "recommended_formats": [
            {
                "format": "reel",
                "rationale": "Associated with the strongest observed performer",
                "evidence_type": "interpretation",
                "evidence_post_ids": ["POST_TOP1"],
                "sample_size": 1,
                "confidence": "low",
                "requires_verification": False,
                "verification_reason": "",
            }
        ],
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


# --- Regression: the simplified schema must stay meaningfully below the complexity
# that produced the real "compiled grammar is too large" 400 error, and must not have
# silently dropped any required output section in the process of simplifying it. ---
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
        # The real 400 was "compiled grammar too large" from Anthropic's structured-
        # output compiler; enum/union branching are the most plausible contributors.
        # The fix removes all enums entirely - allowed values are enforced in Python.
        enums, _ = self._count_enums_and_unions(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA)
        self.assertEqual(enums, 0, "schema should contain zero JSON-schema enums after simplification")

    def test_schema_has_no_nullable_type_unions(self):
        _, unions = self._count_enums_and_unions(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA)
        self.assertEqual(unions, 0, "schema should contain zero [type, null] unions after simplification")

    def test_schema_size_below_reasonable_threshold(self):
        size = len(json.dumps(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA))
        # Generous ceiling - well above the pre-simplification ~4KB that failed, this
        # just guards against future regrowth without being a brittle exact-size check.
        self.assertLess(size, 6000, f"schema grew to {size} chars - re-check grammar complexity")

    def test_action_plan_is_flat_not_nested_object(self):
        # One fewer distinct object shape for the grammar compiler than the original
        # {immediate, next, later} nested object.
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["action_plan"]
        self.assertEqual(schema, {"type": "array", "items": {"type": "string"}})


class TestSchemaContainsRequiredSections(unittest.TestCase):
    def test_all_critical_output_sections_present(self):
        top_level_props = set(strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"].keys())
        # top_performing_content and metadata are assembled in Python from Stage 4.1's
        # deterministic data (see main()), not requested from Claude - they are not part
        # of the API-facing schema by design (Claude never touches those numbers), but
        # must appear in the final written output. Check both surfaces.
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
        # names (content_opportunities/strategy_themes/recommended_formats) since it is a
        # new artifact, not a copy of Stage 4.1's report. Confirm Stage 6 still reads
        # every one of these from its input.
        self.assertEqual(set(strat.REQUIRED_SECTIONS), expected)


# --- 6/7: malformed / truncated response handling (pure function) ---
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


# --- 8: missing required output field ---
class TestValidation(unittest.TestCase):
    def test_missing_top_level_field_rejected(self):
        resp = make_strategy_response()
        del resp["executive_summary"]
        with self.assertRaises(strat.DataError):
            strat.validate_strategy_response(resp)

    def test_action_plan_wrong_type_rejected(self):
        # action_plan is a flat array of strings (schema-simplified) - a dict is wrong.
        resp = make_strategy_response()
        resp["action_plan"] = {"immediate": ["x"], "next": [], "later": []}
        with self.assertRaises(strat.DataError):
            strat.validate_strategy_response(resp)

    def test_action_plan_valid_flat_list_accepted(self):
        resp = make_strategy_response()
        strat.validate_strategy_response(resp)  # should not raise


# --- 9: invented post ID ---
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


# --- 13: Claude cannot change/fabricate evidence numbers (structural) ---
class TestNoNumericFabricationSurface(unittest.TestCase):
    def test_content_opportunities_schema_has_no_engagement_number_fields(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["content_opportunities"]["items"]
        for forbidden in ("likes", "comments", "engagement_score", "views"):
            self.assertNotIn(forbidden, schema["properties"])
        self.assertFalse(schema.get("additionalProperties", True))

    def test_schema_rejects_additional_properties_everywhere(self):
        for key in ("content_opportunities", "strategy_themes", "recommended_formats", "recommended_tests"):
            schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"][key]["items"]
            self.assertFalse(schema.get("additionalProperties", True), f"{key} should not allow additionalProperties")


# --- 14/17: unsupported performance claims / experimental targets must be labeled ---
class TestPerformanceClaimsAndTargets(unittest.TestCase):
    def test_causal_claim_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "Testimonial framing drives higher engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_hedged_claim_is_allowed(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "Testimonial framing appears associated with higher engagement."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_recommended_test_missing_target_type_is_hard_violation(self):
        resp = make_strategy_response()
        del resp["recommended_tests"][0]["target_type"]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("proposed_test_target" in v for v in violations["hard"]))

    def test_recommended_test_with_target_type_passes(self):
        resp = make_strategy_response()
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_schema_requires_target_type_field(self):
        # Schema-simplified: target_type is a plain required string (not a JSON-schema
        # enum, to keep the compiled grammar small) - the literal value is enforced by
        # find_evidence_violations() instead, tested above.
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["recommended_tests"]["items"]
        self.assertIn("target_type", schema["required"])
        self.assertEqual(schema["properties"]["target_type"], {"type": "string"})
        self.assertNotIn("enum", schema["properties"]["target_type"])

    def test_invalid_confidence_value_is_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["confidence"] = "extremely high"
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("confidence" in v for v in violations["hard"]))


# --- 15: hypothesis correctly labeled (structural + pass-through) ---
class TestEvidenceTypeLabeling(unittest.TestCase):
    def test_evidence_type_is_plain_string_in_schema(self):
        # Schema-simplified: evidence_type is a plain required string, not a JSON-schema
        # enum - the allowed-value set is enforced by find_evidence_violations() instead.
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
        self.assertEqual(resp["content_opportunities"][0]["evidence_type"], "hypothesis")

    def test_invalid_evidence_type_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"evidence_type": "definitely-true-fact"})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("evidence_type" in v for v in violations["hard"]))


# --- Calendar period hardening ---
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


# --- 16: external/business claim requires verification ---
class TestBusinessFactClaims(unittest.TestCase):
    def test_unverified_business_fact_soft_flagged(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "The post mentions PADI certification.", "requires_verification": False})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])
        self.assertTrue(any(v["type"] == "flag_verification" for v in violations["soft"]))

    def test_auto_correction_sets_requires_verification(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "References a scam concern in the tourist market.", "requires_verification": False})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        applied = strat.apply_auto_corrections(resp, violations)
        self.assertGreater(applied, 0)
        item = resp["content_opportunities"][0]
        self.assertTrue(item["requires_verification"])
        self.assertIsNotNone(item["verification_reason"])

    def test_unhedged_competitor_claim_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"rationale": "No competitor addresses this angle."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_hedged_competitor_mention_without_flag_is_auto_corrected(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "evidence": "A potential differentiation angle; competitor validation required.",
                "requires_verification": False,
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        applied = strat.apply_auto_corrections(resp, violations)
        self.assertGreater(applied, 0)
        self.assertTrue(resp["content_opportunities"][0]["requires_verification"])


# --- Stage 6.1: real-run hardening - causal-language/competitor/business-outcome
# language must be caught (or allowed) regardless of which field it appears in, not
# just a fixed list of array indexes. Covers the actual phrases from the real
# production failure ("primary engagement driver", "drives", "proves") plus the
# explicit allow/deny matrix requested for this hardening pass.
class TestCausalAndCompetitorLanguageHardening(unittest.TestCase):
    def test_drives_bookings_is_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "This will drive measurable booking conversions."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_increases_bookings_as_factual_claim_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"rationale": "This format increases bookings."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_test_whether_bookings_increase_is_allowed(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Test whether bookings increase after this change."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_measure_whether_engagement_increases_is_allowed(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["success_metric"] = "Measure whether engagement increases week over week."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_proves_more_resonant_is_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "This proves more resonant with the audience."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_primary_engagement_driver_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"rationale": "Instructor quality is the primary engagement driver."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_differentiating_from_competitors_without_data_is_hard_violation(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "Differentiating from unstructured competitors."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_competitor_validation_required_is_allowed(self):
        resp = make_strategy_response(
            opportunity_overrides={"evidence": "A potential differentiation angle; competitor validation required."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_may_be_associated_with_bookings_is_allowed(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "This may be associated with bookings."})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_action_plan_causal_language_is_hard_violation(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["[NEXT] These formats drive highest-intent inquiries."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_action_plan_measurement_language_is_allowed(self):
        resp = make_strategy_response()
        resp["action_plan"] = [
            "[NEXT] Track inquiry source and content theme to measure which formats "
            "are associated with higher-intent inquiries."
        ]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_recommended_test_framed_as_hypothesis_is_allowed(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Test whether named instructor spotlights receive different engagement "
            "than comparable testimonials without an instructor focus."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_unsupported_business_outcome_claim_flagged(self):
        resp = make_strategy_response(
            opportunity_overrides={"evidence": "This is associated with higher booking conversions."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])
        self.assertTrue(any(v["type"] == "flag_verification" for v in violations["soft"]))


# --- Stage 6.2: real-run failure regression. The real Stage 4.1-driven run rejected a
# response for causal language in fields like "primary driver"/"driven" (rationale,
# theme, evidence, evidence_basis) and "increase"/"drive"/"generate" in hypothesis/
# success_metric - even when those hypothesis/success_metric uses were legitimate test
# framing ("will drive higher engagement than..."). This class locks in the fix:
# observational fields (rationale/evidence/theme/evidence_basis) stay strict in every
# tense; hypothesis/success_metric/variable_to_test/test_name accept a wider set of
# comparison framings ("than", "compared to", "relative to", "target:", "success if")
# without needing the literal word "whether"; and a PAST-TENSE claim of an already-
# observed result is a hard violation everywhere, even inside a test-design field.
class TestRealRunFailureRegression(unittest.TestCase):
    def test_primary_driver_in_rationale_is_still_hard_violation(self):
        resp = make_strategy_response(
            opportunity_overrides={"rationale": "Instructor quality is the primary driver of engagement."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_past_tense_driven_in_rationale_is_still_hard_violation(self):
        resp = make_strategy_response(
            opportunity_overrides={"rationale": "Engagement was driven by testimonials in this sample."}
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_drive_in_theme_label_is_still_hard_violation(self):
        resp = make_strategy_response()
        resp["strategy_themes"][0]["theme"] = "Content that drives engagement"
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_driving_in_theme_evidence_is_still_hard_violation(self):
        resp = make_strategy_response()
        resp["strategy_themes"][0]["evidence"] = "Named-instructor posts are driving stronger comment activity."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_driven_in_format_rationale_is_still_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_formats"][0]["rationale"] = "This format has driven stronger saves in the sample."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_evidence_basis_stays_strict_for_unhedged_drive(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_basis"] = "This pattern appears to drive stronger saves across the sample."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_evidence_basis_stays_strict_for_past_tense_driven(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["evidence_basis"] = "Top posts were driven primarily by testimonial framing."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_hypothesis_drive_allowed_with_comparison(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = (
            "Named instructor spotlights will drive higher engagement than comparable "
            "generic testimonials."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_success_metric_increase_allowed_with_compared_to(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["success_metric"] = "Engagement increases by 15% compared to the baseline average."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_success_metric_increase_allowed_with_relative_to(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["success_metric"] = "Booking inquiries increase by 20% relative to the control period."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_success_metric_generate_allowed_with_than(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["success_metric"] = "This format will generate more inquiries than the comparison group."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_success_metric_increase_without_comparison_is_still_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["success_metric"] = "Engagement will increase."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_past_tense_result_claim_in_success_metric_always_hard_violation(self):
        # Example E: a claimed *already observed* result is never allowed, even inside
        # a test-design field with comparison language.
        resp = make_strategy_response()
        resp["recommended_tests"][0]["success_metric"] = (
            "The discount increased booking inquiries by 20% compared to baseline."
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_past_tense_generated_in_hypothesis_always_hard_violation(self):
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "This format generated more bookings than the comparison group."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_unsupported_recommendation_stated_as_fact_in_hypothesis_is_hard_violation(self):
        # Example G: a bare, unhedged directional claim in a hypothesis field is still a
        # violation - test-design fields widen the accepted hedge *phrases*, they do not
        # exempt directional verbs entirely.
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Instructor-focused content increases engagement."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_proposed_experiment_in_hypothesis_is_allowed(self):
        # Example F: the same claim, properly framed as a proposed test.
        resp = make_strategy_response()
        resp["recommended_tests"][0]["hypothesis"] = "Test whether instructor-focused content increases engagement."
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- Stage 6.3: false-positive reduction. The real Stage 4.1-driven run rejected
# grammatically safe wording - compound adjectives ("scarcity-driven booking
# windows"), a post's own already-observed metrics ("generating 3,266 likes"), a
# verb-tense gap in the hedge regex ("tests whether" vs. only "test whether"), and a
# test-design field using "Track..." without the literal word "whether"
# ("Track DM inquiry volume for increase week-over-week"). This class locks in the 20
# explicit cases from that hardening pass, using find_evidence_violations() directly
# on minimal fixtures so each case tests exactly one thing.
class TestFalsePositiveReduction(unittest.TestCase):
    def _opportunity_violation(self, text):
        resp = make_strategy_response(opportunity_overrides={"evidence": text})
        return strat.find_evidence_violations(resp, VALID_POST_IDS)["hard"]

    def _test_field_violation(self, field, text):
        resp = make_strategy_response()
        resp["recommended_tests"][0][field] = text
        return strat.find_evidence_violations(resp, VALID_POST_IDS)["hard"]

    # 1-5: observational claims must remain violations
    def test_1_drives_engagement_is_violation(self):
        self.assertTrue(any("causal" in v.lower() for v in self._opportunity_violation("This drives engagement.")))

    def test_2_primary_driver_of_engagement_is_violation(self):
        self.assertTrue(any("causal" in v.lower() for v in self._opportunity_violation("This is the primary driver of engagement.")))

    def test_3_drove_engagement_is_violation(self):
        self.assertTrue(any("causal" in v.lower() for v in self._opportunity_violation("This drove engagement.")))

    def test_4_generated_bookings_is_violation(self):
        self.assertTrue(any("causal" in v.lower() for v in self._opportunity_violation("This generated bookings.")))

    def test_5_increased_bookings_is_violation(self):
        self.assertTrue(any("causal" in v.lower() for v in self._opportunity_violation("This increased bookings.")))

    # 6-9: compound adjectives must not be flagged
    def test_6_scarcity_driven_booking_windows_allowed(self):
        self.assertEqual(self._opportunity_violation("Scarcity-driven booking windows aligned with the season."), [])

    def test_7_narrative_driven_reels_allowed(self):
        self.assertEqual(self._opportunity_violation("Narrative-driven reels featuring career transformation."), [])

    def test_8_weather_driven_dive_conditions_allowed(self):
        self.assertEqual(self._opportunity_violation("Weather-driven dive conditions are mentioned in captions."), [])

    def test_9_urgency_driven_cta_allowed(self):
        self.assertEqual(self._opportunity_violation("Urgency-driven CTAs appear in the top post."), [])

    # 10-13: test-design/success-metric framings must be allowed
    def test_10_test_whether_bookings_increase_allowed(self):
        self.assertEqual(self._test_field_violation("hypothesis", "Test whether bookings increase after this change."), [])

    def test_11_measure_whether_inquiries_increase_compared_to_baseline_allowed(self):
        self.assertEqual(
            self._test_field_violation("success_metric", "Measure whether inquiries increase compared to baseline."), []
        )

    def test_12_track_dm_inquiry_volume_for_increase_week_over_week_allowed(self):
        self.assertEqual(
            self._test_field_violation("success_metric", "Track DM inquiry volume for increase week-over-week during test."),
            [],
        )

    def test_13_target_20_percent_increase_vs_baseline_allowed(self):
        self.assertEqual(self._test_field_violation("success_metric", "Target: 20% increase vs baseline"), [])

    # 14-16: retrospective/proven claims must remain violations even in test-design fields
    def test_14_campaign_increased_bookings_is_violation(self):
        self.assertTrue(
            any("causal" in v.lower() for v in self._test_field_violation("success_metric", "The campaign increased bookings."))
        )

    def test_15_campaign_generated_bookings_is_violation(self):
        self.assertTrue(
            any("causal" in v.lower() for v in self._test_field_violation("hypothesis", "The campaign generated bookings."))
        )

    def test_16_test_proved_an_increase_is_violation(self):
        self.assertTrue(
            any("causal" in v.lower() for v in self._test_field_violation("evidence_basis", "The test proved an increase in bookings."))
        )

    # 17-18: describing a post's own already-observed metrics must be allowed
    def test_17_has_likes_and_comments_allowed(self):
        self.assertEqual(self._opportunity_violation("DWyk4T6E5OF has 3,266 likes and 49 comments."), [])

    def test_18_generating_likes_and_comments_allowed(self):
        self.assertEqual(
            self._opportunity_violation("DWyk4T6E5OF, generating 3,266 likes and 49 comments, shows strong engagement."), []
        )

    # 19-20: competitor claim protection stays, but requires_verification=true + a
    # real verification_reason is now an accepted alternative to rewriting the text.
    def test_19_competitor_statement_without_verification_is_protected(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "rationale": "No competitor addresses this angle.",
                "requires_verification": False,
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_20_competitor_statement_with_verification_is_allowed(self):
        resp = make_strategy_response(
            opportunity_overrides={
                "rationale": "No competitor addresses this angle.",
                "requires_verification": True,
                "verification_reason": "No competitor dataset was supplied; needs manual research.",
            }
        )
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    # Real production failures, verbatim, as an end-to-end sanity check beyond the
    # word-level cases above.
    def test_real_failure_tests_whether_verb_form_is_allowed(self):
        text = (
            "This format tests whether dedicating content to specific instructors "
            "strengthens trust signals and drives repeat-viewer familiarity with the "
            "FlyingFish team."
        )
        self.assertEqual(self._opportunity_violation(text), [])

    def test_real_failure_driving_advance_bookings_remains_violation(self):
        # This one is a genuine unsupported claim (bookings, not an engagement metric,
        # with no test framing) and must still be rejected - not every real-run
        # failure was a false positive.
        text = (
            "Seasonal countdown messaging is associated with notably high comment "
            "engagement and community anticipation, driving advance bookings during "
            "seasonal transitions."
        )
        self.assertTrue(any("causal" in v.lower() for v in self._opportunity_violation(text)))


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


# --- 4: dry-run makes no API call ---
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


# --- 5: valid Claude response end-to-end ---
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


# --- 7: truncated response ---
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


# --- 10/11/12: retry after invalid response, second failure, no partial output ---
class TestRetryAndFailure(MainEndToEndMixin, unittest.TestCase):
    def test_hard_violation_then_clean_retry_succeeds(self):
        bad = make_strategy_response(opportunity_overrides={"evidence": "No competitor addresses this."})
        good = make_strategy_response()
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", good)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        second_call_messages = calls[1].kwargs["messages"]
        self.assertIn("CORRECTION REQUIRED", second_call_messages[0]["content"])
        self.assertTrue(self.output_path.exists())

    def test_hard_violation_persists_fails_cleanly(self):
        bad = make_strategy_response(opportunity_overrides={"evidence": "No competitor addresses this."})
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())

    def test_no_partial_output_on_any_failure(self):
        exit_code, calls = self.run_main([make_completed_stream("max_tokens", {}), make_completed_stream("max_tokens", {})])
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())
        self.assertEqual(list(Path(self.tmpdir.name).glob("strategy*")), [])


# --- Soft violation auto-corrected without wasting a retry ---
class TestSoftViolationAutoCorrection(MainEndToEndMixin, unittest.TestCase):
    def test_soft_violation_succeeds_on_first_call(self):
        resp = make_strategy_response(opportunity_overrides={"evidence": "Mentions PADI certification.", "requires_verification": False})
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


# --- 18: existing Stage 4.1 output remains untouched ---
class TestStage41Untouched(MainEndToEndMixin, unittest.TestCase):
    def test_stage41_file_unchanged_after_run(self):
        before = self.stage41_path.read_text()
        self.run_main([make_completed_stream("end_turn", make_strategy_response())])
        after = self.stage41_path.read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
