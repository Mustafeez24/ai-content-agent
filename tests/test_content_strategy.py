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
        "verification_reason": None,
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
        "verification_reason": None,
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
                "verification_reason": None,
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
                "verification_reason": None,
            }
        ],
        "recommended_tests": [make_test_item()],
        "action_plan": {
            "immediate": ["Draft one testimonial-style reel in the next 1-2 weeks"],
            "next": ["Review engagement after the next 4 weeks"],
            "later": [],
        },
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

    def test_malformed_action_plan_rejected(self):
        resp = make_strategy_response()
        resp["action_plan"] = {"immediate": ["x"]}  # missing next/later
        with self.assertRaises(strat.DataError):
            strat.validate_strategy_response(resp)

    def test_action_plan_wrong_type_rejected(self):
        resp = make_strategy_response()
        resp["action_plan"] = ["flat", "list", "not", "allowed"]
        with self.assertRaises(strat.DataError):
            strat.validate_strategy_response(resp)


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

    def test_schema_requires_target_type_enum(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["recommended_tests"]["items"]
        self.assertIn("target_type", schema["required"])
        self.assertEqual(schema["properties"]["target_type"]["enum"], ["proposed_test_target"])


# --- 15: hypothesis correctly labeled (structural + pass-through) ---
class TestEvidenceTypeLabeling(unittest.TestCase):
    def test_evidence_type_enum_in_schema(self):
        schema = strat.CONTENT_STRATEGY_RESPONSE_SCHEMA["properties"]["content_opportunities"]["items"]
        self.assertEqual(
            sorted(schema["properties"]["evidence_type"]["enum"]),
            sorted(["observed", "interpretation", "hypothesis", "recommendation"]),
        )

    def test_hypothesis_label_survives_violation_check(self):
        resp = make_strategy_response(opportunity_overrides={"evidence_type": "hypothesis"})
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])
        self.assertEqual(resp["content_opportunities"][0]["evidence_type"], "hypothesis")


# --- Calendar period hardening ---
class TestCalendarPeriods(unittest.TestCase):
    def test_hardcoded_quarter_in_action_plan_is_hard_violation(self):
        resp = make_strategy_response()
        resp["action_plan"]["immediate"] = ["Launch a Q4 2025 campaign."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("calendar" in v.lower() for v in violations["hard"]))

    def test_relative_timeframe_allowed(self):
        resp = make_strategy_response()
        resp["action_plan"]["immediate"] = ["Launch a campaign in the next 4 weeks."]
        violations = strat.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


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


# --- 18: existing Stage 4.1 output remains untouched ---
class TestStage41Untouched(MainEndToEndMixin, unittest.TestCase):
    def test_stage41_file_unchanged_after_run(self):
        before = self.stage41_path.read_text()
        self.run_main([make_completed_stream("end_turn", make_strategy_response())])
        after = self.stage41_path.read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
