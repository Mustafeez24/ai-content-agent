"""
Tests for Stage 4.1 evidence/hallucination hardening in scripts/content_scout.py.

Pure-function tests exercise find_evidence_violations/apply_auto_corrections directly
with hand-built synthetic response dicts (never real FlyingFish data). End-to-end tests
mock anthropic.Anthropic entirely, so no real API calls are made by running this file.
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

import content_scout as cs

VALID_POST_IDS = {"POST_TOP1", "POST_TOP2", "POST_LOW1"}


def make_item(**overrides):
    base = {
        "pattern": "Testimonial-style captions",
        "evidence": "Observed in the top-performing post's caption",
        "recommendation": "Test more testimonial-style content",
        "evidence_type": "interpretation",
        "evidence_post_ids": ["POST_TOP1"],
        "sample_size": 1,
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": None,
    }
    base.update(overrides)
    return base


def make_response(pattern_overrides=None, **top_overrides):
    item = make_item(**(pattern_overrides or {}))
    resp = {
        "executive_summary": "A small set of posts show above-average engagement in this sample.",
        "top_content_patterns": [item],
        "top_performing_content_notes": [{"post_id": "POST_TOP1", "likely_reason": "x", "evidence": "y"}],
        "weak_content_patterns": [],
        "content_gaps": [],
        "opportunities": [],
        "recommended_tests": [
            {
                "test": "Post 2 testimonial-style reels",
                "hypothesis": "May be associated with higher engagement",
                "expected_signal": "Likes above dataset average",
                "target_type": "proposed_test_target",
            }
        ],
        "action_plan": ["Publish one testimonial-style reel in the next 30 days"],
    }
    resp.update(top_overrides)
    return resp


STAGE3_FIXTURE = {
    "metadata": {"posts_analyzed": 3, "model_used": "claude-haiku-4-5"},
    "dataset_summary": {
        "total_posts": 3,
        "top_posts": [
            {"post_id": "POST_TOP1", "engagement_score": 3315, "likes": 3200, "comments": 115},
            {"post_id": "POST_TOP2", "engagement_score": 500, "likes": 480, "comments": 20},
        ],
        "lowest_posts": [{"post_id": "POST_LOW1", "engagement_score": 10, "likes": 8, "comments": 2}],
        "average_likes": 1200,
        "average_comments": 45,
        "average_video_views": None,
        "date_range": {"earliest": "2026-01-01T00:00:00.000Z", "latest": "2026-01-20T00:00:00.000Z"},
        "post_type_distribution": {"Image": 2, "Video": 1},
        "top_hashtags": [["scuba", 3]],
    },
    "content_patterns": {"strongest_themes": ["SYNTHETIC"], "recurring_topics": [], "common_hooks": [], "common_ctas": [], "content_formats_used": []},
    "performance_patterns": {"traits_of_top_performers": [], "traits_of_low_performers": [], "weak_or_underused_content_areas": []},
    "claude_analysis": {
        "post_analyses": [
            {"post_id": "POST_TOP1", "main_topic": "SYNTHETIC", "content_category": "x", "hook": "x", "cta": "x", "tone": "x", "target_audience": "x", "content_format": "x", "diving_subject": "x", "content_intent": "promotional", "key_themes": []},
            {"post_id": "POST_TOP2", "main_topic": "SYNTHETIC", "content_category": "x", "hook": "x", "cta": "x", "tone": "x", "target_audience": "x", "content_format": "x", "diving_subject": "x", "content_intent": "promotional", "key_themes": []},
            {"post_id": "POST_LOW1", "main_topic": "SYNTHETIC", "content_category": "x", "hook": "x", "cta": "x", "tone": "x", "target_audience": "x", "content_format": "x", "diving_subject": "x", "content_intent": "promotional", "key_themes": []},
        ]
    },
    "recommendations": ["SYNTHETIC recommendation"],
}


# --- 1. Unsupported competitor claim ---
class TestCompetitorClaims(unittest.TestCase):
    def test_unhedged_competitor_claim_is_hard_violation(self):
        resp = make_response(pattern_overrides={"evidence": "No competitor is doing this kind of content."})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_hedged_competitor_mention_is_allowed(self):
        resp = make_response(
            pattern_overrides={
                "evidence": "This may represent a potential differentiation opportunity; competitor validation is required.",
                "requires_verification": True,
            }
        )
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- 2. Unsupported external/business claim flagged with requires_verification ---
class TestBusinessFactClaims(unittest.TestCase):
    def test_unverified_business_fact_is_soft_flagged(self):
        resp = make_response(pattern_overrides={"evidence": "The post mentions PADI certification.", "requires_verification": False})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])
        self.assertTrue(any(v["type"] == "flag_verification" for v in violations["soft"]))

    def test_auto_correction_sets_requires_verification_true(self):
        resp = make_response(pattern_overrides={"evidence": "References a scam concern in the tourist market.", "requires_verification": False})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        applied = cs.apply_auto_corrections(resp, violations)
        self.assertGreater(applied, 0)
        item = resp["top_content_patterns"][0]
        self.assertTrue(item["requires_verification"])
        self.assertIsNotNone(item["verification_reason"])


# --- 3. Causal wording rejected/flagged ---
class TestCausalLanguage(unittest.TestCase):
    def test_causal_verb_is_hard_violation(self):
        resp = make_response(pattern_overrides={"evidence": "Testimonial framing drives higher engagement."})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_hedged_language_is_allowed(self):
        resp = make_response(pattern_overrides={"evidence": "Testimonial framing appears associated with higher engagement."})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- 4. Small-sample claims require sample_size / are qualified ---
class TestSmallSample(unittest.TestCase):
    def test_high_confidence_with_small_sample_is_downgraded(self):
        resp = make_response(pattern_overrides={"sample_size": 1, "confidence": "high"})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        applied = cs.apply_auto_corrections(resp, violations)
        self.assertGreater(applied, 0)
        self.assertEqual(resp["top_content_patterns"][0]["confidence"], "medium")

    def test_universal_language_with_small_sample_is_flagged(self):
        resp = make_response(pattern_overrides={"sample_size": 1, "evidence": "This format always performs well."})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any(v["type"] == "flag_verification" for v in violations["soft"]))

    def test_sample_size_field_is_structurally_required(self):
        schema = cs.CONTENT_SCOUT_RESPONSE_SCHEMA["properties"]["top_content_patterns"]["items"]
        self.assertIn("sample_size", schema["required"])


# --- 5. Experimental numeric targets labeled ---
class TestExperimentalTargets(unittest.TestCase):
    def test_schema_requires_target_type_enum(self):
        schema = cs.CONTENT_SCOUT_RESPONSE_SCHEMA["properties"]["recommended_tests"]["items"]
        self.assertIn("target_type", schema["required"])
        self.assertEqual(schema["properties"]["target_type"]["enum"], ["proposed_test_target"])


# --- 6. Invented / missing post_id evidence ---
class TestInventedPostIds(unittest.TestCase):
    def test_invented_post_id_in_evidence_is_hard_violation(self):
        resp = make_response(pattern_overrides={"evidence_post_ids": ["POST_DOES_NOT_EXIST"]})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("POST_DOES_NOT_EXIST" in v for v in violations["hard"]))

    def test_real_post_ids_are_accepted(self):
        resp = make_response(pattern_overrides={"evidence_post_ids": ["POST_TOP1", "POST_LOW1"]})
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])

    def test_evidence_post_ids_field_is_structurally_required(self):
        schema = cs.CONTENT_SCOUT_RESPONSE_SCHEMA["properties"]["opportunities"]["items"]
        self.assertIn("evidence_post_ids", schema["required"])


# --- Calendar-period hardening ---
class TestCalendarPeriods(unittest.TestCase):
    def test_hardcoded_quarter_is_hard_violation(self):
        resp = make_response()
        resp["action_plan"] = ["Launch a Q4 2025 campaign focused on certifications."]
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertTrue(any("calendar" in v.lower() for v in violations["hard"]))

    def test_relative_timeframe_is_allowed(self):
        resp = make_response()
        resp["action_plan"] = ["Launch a campaign in the next 4 weeks focused on certifications."]
        violations = cs.find_evidence_violations(resp, VALID_POST_IDS)
        self.assertEqual(violations["hard"], [])


# --- 7. Deterministic Stage 3 numbers cannot be overwritten ---
class TestDeterministicProtection(unittest.TestCase):
    def test_claude_cannot_override_stage3_numbers(self):
        top_posts = [{"post_id": "POST_TOP1", "engagement_score": 3315, "likes": 3200, "comments": 115}]
        claude_notes = [{"post_id": "POST_TOP1", "likely_reason": "testimonial framing", "evidence": "strong caption"}]
        result = cs.assemble_top_performing_content(top_posts, claude_notes)
        self.assertEqual(result[0]["engagement_score"], 3315)
        self.assertEqual(result[0]["likes"], 3200)
        self.assertEqual(result[0]["comments"], 115)

    def test_claude_cannot_inject_a_different_post(self):
        top_posts = [{"post_id": "POST_TOP1", "engagement_score": 3315, "likes": 3200, "comments": 115}]
        claude_notes = [{"post_id": "SOME_OTHER_POST", "likely_reason": "x", "evidence": "y"}]
        result = cs.assemble_top_performing_content(top_posts, claude_notes)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["post_id"], "POST_TOP1")
        self.assertEqual(result[0]["likely_reason"], "unknown")


# --- 8. Existing JSON structured-output validation still works ---
class TestJsonValidationRegression(unittest.TestCase):
    def test_valid_json_parses_and_validates(self):
        resp = make_response()
        text = json.dumps(resp)
        parsed = cs.extract_json_object(text)
        cs.validate_scout_response(parsed)  # should not raise

    def test_fenced_json_parses(self):
        resp = make_response()
        text = "```json\n" + json.dumps(resp) + "\n```"
        parsed = cs.extract_json_object(text)
        cs.validate_scout_response(parsed)

    def test_missing_top_level_field_rejected(self):
        resp = make_response()
        del resp["executive_summary"]
        with self.assertRaises(cs.DataError):
            cs.validate_scout_response(resp)


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
        self.stage3_path = Path(self.tmpdir.name) / "stage3.json"
        self.output_path = Path(self.tmpdir.name) / "scout.json"
        with open(self.stage3_path, "w") as f:
            json.dump(STAGE3_FIXTURE, f)

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
            sys.argv = ["content_scout.py", "--input", str(self.stage3_path), "--output", str(self.output_path)]
            try:
                exit_code = cs.main()
            finally:
                sys.argv = argv_backup
        return exit_code, mock_client.messages.create.call_args_list


# --- 9. Existing retry/truncation behavior continues working ---
class TestTruncationRegression(MainEndToEndMixin, unittest.TestCase):
    def test_truncation_then_success(self):
        exit_code, calls = self.run_main(
            [
                make_completed_stream("max_tokens", {}),
                make_completed_stream("end_turn", make_response()),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.output_path.exists())

    def test_truncation_twice_fails_cleanly_no_output(self):
        exit_code, calls = self.run_main(
            [
                make_completed_stream("max_tokens", {}),
                make_completed_stream("max_tokens", {}),
            ]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())


# --- New hardening behavior: hard-violation retry/failure ---
class TestHardViolationRetry(MainEndToEndMixin, unittest.TestCase):
    def test_hard_violation_then_clean_retry_succeeds(self):
        bad = make_response(pattern_overrides={"evidence": "No competitor addresses this."})
        good = make_response()
        exit_code, calls = self.run_main(
            [
                make_completed_stream("end_turn", bad),
                make_completed_stream("end_turn", good),
            ]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        # the retry call should carry a correction note
        second_call_messages = calls[1].kwargs["messages"]
        self.assertIn("CORRECTION REQUIRED", second_call_messages[0]["content"])
        self.assertTrue(self.output_path.exists())

    def test_hard_violation_persists_fails_cleanly_no_output(self):
        bad = make_response(pattern_overrides={"evidence": "No competitor addresses this."})
        exit_code, calls = self.run_main(
            [
                make_completed_stream("end_turn", bad),
                make_completed_stream("end_turn", bad),
            ]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())

    def test_soft_violation_is_auto_corrected_not_retried(self):
        # A response with only a soft violation (unverified business fact, requires_verification
        # already False) should succeed on the FIRST call, with an auto-correction applied.
        resp = make_response(pattern_overrides={"evidence": "Mentions PADI certification.", "requires_verification": False})
        exit_code, calls = self.run_main([make_completed_stream("end_turn", resp)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)  # no retry needed for a soft violation
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertTrue(output["top_content_patterns"][0]["requires_verification"])


# --- 10. Existing dry-run behavior continues working ---
class TestDryRunRegression(MainEndToEndMixin, unittest.TestCase):
    def test_dry_run_makes_no_api_call(self):
        with patch("anthropic.Anthropic") as mock_client_cls:
            argv_backup = sys.argv
            sys.argv = ["content_scout.py", "--input", str(self.stage3_path), "--output", str(self.output_path), "--dry-run"]
            try:
                exit_code = cs.main()
            finally:
                sys.argv = argv_backup
        self.assertEqual(exit_code, 0)
        mock_client_cls.assert_not_called()
        self.assertFalse(self.output_path.exists())


if __name__ == "__main__":
    unittest.main()
