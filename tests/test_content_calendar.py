"""
Tests for scripts/content_calendar.py (Stage 7 - Content Calendar Generator).

Pure-function tests exercise validation/violation logic directly with hand-built
synthetic dicts (never real FlyingFish data). End-to-end tests mock anthropic.Anthropic
entirely, so no real API calls are made by running this file.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-fake-key-never-used-in-mocked-tests")

import content_calendar as cal

VALID_POST_IDS = {"POST_TOP1", "POST_TOP2"}

STRATEGY_FIXTURE = {
    "metadata": {"agent": "content_strategy", "model": "claude-haiku-4-5"},
    "executive_summary": "SYNTHETIC - testimonial and educational content perform well.",
    "content_opportunities": [
        {
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
            "verification_reason": None,
        }
    ],
    "strategy_themes": [
        {
            "theme": "Instructor trust",
            "observation": "POST_TOP1 had 3,200 likes.",
            "interpretation": "Instructor praise is associated with strong engagement in the observed sample.",
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
            "observation": "POST_TOP2 had 480 likes.",
            "interpretation": "This format is associated with the strongest observed performer.",
            "evidence_type": "interpretation",
            "evidence_post_ids": ["POST_TOP2"],
            "sample_size": 1,
            "confidence": "low",
            "requires_verification": False,
            "verification_reason": None,
        }
    ],
    "recommended_tests": [
        {
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
            "verification_reason": None,
        }
    ],
    "action_plan": {"immediate": ["Draft one testimonial reel"], "next": [], "later": []},
}

_TOPICS = [
    "Beginner scuba preparation checklist",
    "Meet the instructors behind FlyingFish",
    "Marine life you can spot in Goa waters",
    "What SSI certification actually involves",
    "Underwater photography basics for beginners",
    "Grande Island dive site highlights",
    "First-time diver safety briefing walkthrough",
    "PADI vs SSI: what beginners should know",
    "How instructor-led diving builds confidence",
    "Preparing your gear before a Goa dive trip",
]


def make_calendar_item(index=0, **overrides):
    base = {
        "content_type": "Reel",
        "recommended_format": "Reel with on-screen captions",
        "topic": f"{_TOPICS[index % len(_TOPICS)]} (Day {index + 1})",
        "hook": "What should you know before your first scuba dive?",
        "objective": "Educational",
        "target_audience": "First-time divers researching certification",
        "content_angle": "Simple beginner education",
        "cta": "Save this before your first dive.",
        "priority": "medium",
        "evidence_basis": "POST_TOP1 had 3,200 likes and included instructor praise.",
        "evidence_type": "interpretation",
        "source_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": "",
    }
    base.update(overrides)
    return base


def make_calendar_response(days=7):
    return {
        "calendar_summary": "A balanced mix of testimonial, educational, and community content.",
        "calendar_items": [make_calendar_item(i) for i in range(days)],
    }


# --- input loading ---
class TestInputLoading(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(cal.DataError):
            cal.load_strategy_report(Path("/tmp/does_not_exist_strategy.json"))

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = Path(f.name)
        try:
            with self.assertRaises(cal.DataError):
                cal.load_strategy_report(path)
        finally:
            path.unlink()

    def test_missing_required_section(self):
        incomplete = {"metadata": {}, "executive_summary": "x"}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(incomplete, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cal.DataError):
                cal.load_strategy_report(path)
        finally:
            path.unlink()

    def test_insufficient_evidence_rejected(self):
        empty = {
            "metadata": {}, "executive_summary": "x",
            "content_opportunities": [], "strategy_themes": [],
            "recommended_formats": [], "recommended_tests": [], "action_plan": {},
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(empty, f)
            path = Path(f.name)
        try:
            with self.assertRaises(cal.DataError):
                cal.load_strategy_report(path)
        finally:
            path.unlink()

    def test_valid_fixture_loads(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(STRATEGY_FIXTURE, f)
            path = Path(f.name)
        try:
            data = cal.load_strategy_report(path)
            self.assertEqual(sorted(data.keys()), sorted(STRATEGY_FIXTURE.keys()))
        finally:
            path.unlink()


class TestKnownPostIds(unittest.TestCase):
    def test_known_post_ids_from_fixture(self):
        ids = cal.known_post_ids(STRATEGY_FIXTURE)
        self.assertEqual(ids, {"POST_TOP1", "POST_TOP2"})


# --- deterministic calendar skeleton ---
class TestCalendarSkeleton(unittest.TestCase):
    def test_seven_day_skeleton_has_seven_slots(self):
        skeleton = cal.build_calendar_skeleton(7, start_date=date(2026, 1, 1))
        self.assertEqual(len(skeleton), 7)
        self.assertEqual([s["day_number"] for s in skeleton], list(range(1, 8)))

    def test_thirty_day_skeleton_has_thirty_slots(self):
        skeleton = cal.build_calendar_skeleton(30, start_date=date(2026, 1, 1))
        self.assertEqual(len(skeleton), 30)

    def test_dates_are_sequential(self):
        skeleton = cal.build_calendar_skeleton(3, start_date=date(2026, 1, 1))
        self.assertEqual([s["date"] for s in skeleton], ["2026-01-01", "2026-01-02", "2026-01-03"])

    def test_platform_rotation_is_deterministic_and_allowed(self):
        skeleton = cal.build_calendar_skeleton(30, start_date=date(2026, 1, 1))
        platforms = {s["platform"] for s in skeleton}
        self.assertTrue(platforms.issubset(cal.ALLOWED_PLATFORMS))
        gbp_days = [s["day_number"] for s in skeleton if s["platform"] == "Google Business Profile"]
        self.assertEqual(gbp_days, [5, 10, 15, 20, 25, 30])

    def test_skeleton_is_reproducible_for_same_start_date(self):
        a = cal.build_calendar_skeleton(7, start_date=date(2026, 1, 1))
        b = cal.build_calendar_skeleton(7, start_date=date(2026, 1, 1))
        self.assertEqual(a, b)


# --- schema complexity regression (same lessons as Stage 6) ---
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
        enums, _ = self._count_enums_and_unions(cal.CONTENT_CALENDAR_RESPONSE_SCHEMA)
        self.assertEqual(enums, 0)

    def test_schema_has_no_nullable_type_unions(self):
        _, unions = self._count_enums_and_unions(cal.CONTENT_CALENDAR_RESPONSE_SCHEMA)
        self.assertEqual(unions, 0)

    def test_schema_size_below_reasonable_threshold(self):
        size = len(json.dumps(cal.CONTENT_CALENDAR_RESPONSE_SCHEMA))
        self.assertLess(size, 4000, f"schema grew to {size} chars - re-check grammar complexity")

    def test_additional_properties_false(self):
        top = cal.CONTENT_CALENDAR_RESPONSE_SCHEMA
        self.assertFalse(top.get("additionalProperties", True))
        item_schema = top["properties"]["calendar_items"]["items"]
        self.assertFalse(item_schema.get("additionalProperties", True))

    def test_schema_does_not_include_day_number_date_or_platform(self):
        # Day/date/platform are assigned entirely in Python - Claude's schema must
        # not even offer a place to put them.
        props = cal.CONTENT_CALENDAR_RESPONSE_SCHEMA["properties"]["calendar_items"]["items"]["properties"]
        for forbidden in ("day_number", "date", "platform", "status"):
            self.assertNotIn(forbidden, props)


# --- response validation ---
class TestValidation(unittest.TestCase):
    def test_missing_top_level_field_rejected(self):
        resp = make_calendar_response(3)
        del resp["calendar_summary"]
        with self.assertRaises(cal.DataError):
            cal.validate_calendar_response(resp)

    def test_calendar_items_wrong_type_rejected(self):
        resp = make_calendar_response(3)
        resp["calendar_items"] = "not a list"
        with self.assertRaises(cal.DataError):
            cal.validate_calendar_response(resp)

    def test_valid_response_accepted(self):
        resp = make_calendar_response(3)
        cal.validate_calendar_response(resp)  # should not raise


# --- evidence-safety violations ---
class TestCalendarViolations(unittest.TestCase):
    def test_valid_seven_day_calendar_has_no_violations(self):
        resp = make_calendar_response(7)
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=7)
        self.assertEqual(violations["hard"], [])

    def test_valid_thirty_day_calendar_has_no_violations(self):
        resp = make_calendar_response(30)
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=30)
        self.assertEqual(violations["hard"], [])

    def test_wrong_item_count_is_hard_violation(self):
        resp = make_calendar_response(5)
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=7)
        self.assertTrue(any("exactly 7" in v for v in violations["hard"]))

    def test_invented_post_id_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["source_post_ids"] = ["POST_DOES_NOT_EXIST"]
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("POST_DOES_NOT_EXIST" in v for v in violations["hard"]))

    def test_real_post_id_accepted(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["source_post_ids"] = ["POST_TOP1", "POST_TOP2"]
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertEqual(violations["hard"], [])

    def test_unhedged_competitor_claim_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["target_audience"] = "Students comparing FlyingFish structure vs. competitors."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("competitor" in v.lower() for v in violations["hard"]))

    def test_competitor_claim_with_verification_allowed(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["target_audience"] = "Students comparing FlyingFish structure vs. competitors."
        resp["calendar_items"][0]["requires_verification"] = True
        resp["calendar_items"][0]["verification_reason"] = "Competitor validation required; no competitor data supplied."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertEqual(violations["hard"], [])

    def test_causal_language_in_evidence_basis_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_basis"] = "Instructor praise is the primary engagement driver."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_hedged_evidence_basis_is_allowed(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_basis"] = "POST_TOP1 is associated with strong observed engagement."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertEqual(violations["hard"], [])

    def test_compound_adjective_allowed_in_evidence_basis(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_basis"] = "Narrative-driven content appears among the observed posts."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertEqual(violations["hard"], [])

    def test_hypothesis_presented_as_fact_is_rejected(self):
        # evidence_type says "observed" (a stated fact) but the text is really a
        # causal hypothesis dressed up as an observation.
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_type"] = "observed"
        resp["calendar_items"][0]["evidence_basis"] = "Named-instructor content increases bookings."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("causal" in v.lower() for v in violations["hard"]))

    def test_invalid_evidence_type_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_type"] = "definitely-true-fact"
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("evidence_type" in v for v in violations["hard"]))

    def test_invalid_confidence_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["confidence"] = "extremely high"
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("confidence" in v for v in violations["hard"]))

    def test_invalid_priority_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["priority"] = "urgent!!!"
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("priority" in v for v in violations["hard"]))

    def test_invalid_content_type_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["content_type"] = "TikTok Dance Challenge"
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("content_type" in v for v in violations["hard"]))

    def test_valid_content_types_accepted_case_insensitively(self):
        for ct in ("Reel", "carousel", "STATIC POST", "Story", "Educational Post", "faq", "Q&A", "Community Content"):
            with self.subTest(content_type=ct):
                resp = make_calendar_response(1)
                resp["calendar_items"][0]["content_type"] = ct
                violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
                self.assertEqual(violations["hard"], [])

    def test_empty_topic_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["topic"] = ""
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("topic" in v for v in violations["hard"]))

    def test_vague_topic_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["topic"] = "Post content"
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("topic" in v for v in violations["hard"]))

    def test_duplicate_topics_are_hard_violation(self):
        resp = make_calendar_response(2)
        resp["calendar_items"][1]["topic"] = resp["calendar_items"][0]["topic"]
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=2)
        self.assertTrue(any("duplicate" in v.lower() for v in violations["hard"]))

    def test_observed_evidence_type_without_source_post_ids_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_type"] = "observed"
        resp["calendar_items"][0]["source_post_ids"] = []
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("must cite at least one" in v for v in violations["hard"]))

    def test_hypothesis_evidence_type_without_source_post_ids_is_allowed(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["evidence_type"] = "hypothesis"
        resp["calendar_items"][0]["source_post_ids"] = []
        resp["calendar_items"][0]["evidence_basis"] = "Not directly evidenced in the supplied dataset; a hypothesis-based idea."
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertEqual(violations["hard"], [])

    def test_hardcoded_calendar_quarter_is_hard_violation(self):
        resp = make_calendar_response(1)
        resp["calendar_items"][0]["hook"] = "Get certified before Q4 2025!"
        violations = cal.find_calendar_violations(resp, VALID_POST_IDS, expected_days=1)
        self.assertTrue(any("calendar" in v.lower() for v in violations["hard"]))


# --- deterministic assembly ---
class TestAssembleCalendarItems(unittest.TestCase):
    def test_merges_skeleton_and_claude_output(self):
        skeleton = cal.build_calendar_skeleton(2, start_date=date(2026, 1, 1))
        claude_items = [make_calendar_item(0), make_calendar_item(1)]
        assembled = cal.assemble_calendar_items(claude_items, skeleton)
        self.assertEqual(assembled[0]["day_number"], 1)
        self.assertEqual(assembled[0]["date"], "2026-01-01")
        self.assertEqual(assembled[0]["platform"], "Instagram")
        self.assertEqual(assembled[0]["topic"], claude_items[0]["topic"])

    def test_status_is_always_planned(self):
        skeleton = cal.build_calendar_skeleton(1, start_date=date(2026, 1, 1))
        assembled = cal.assemble_calendar_items([make_calendar_item(0)], skeleton)
        self.assertEqual(assembled[0]["status"], "planned")

    def test_empty_verification_reason_becomes_null(self):
        skeleton = cal.build_calendar_skeleton(1, start_date=date(2026, 1, 1))
        assembled = cal.assemble_calendar_items([make_calendar_item(0, verification_reason="")], skeleton)
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
        self.strategy_path = Path(self.tmpdir.name) / "strategy.json"
        self.output_path = Path(self.tmpdir.name) / "calendar.json"
        with open(self.strategy_path, "w") as f:
            json.dump(STRATEGY_FIXTURE, f)

    def tearDown(self):
        self.tmpdir.cleanup()

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
            sys.argv = ["content_calendar.py", "--input", str(self.strategy_path), "--output", str(self.output_path)]
            sys.argv += extra_args or []
            try:
                exit_code = cal.main()
            finally:
                sys.argv = argv_backup
        return exit_code, mock_client.messages.create.call_args_list


class TestDryRun(MainEndToEndMixin, unittest.TestCase):
    def test_dry_run_makes_no_api_call(self):
        with patch("anthropic.Anthropic") as mock_client_cls:
            argv_backup = sys.argv
            sys.argv = ["content_calendar.py", "--input", str(self.strategy_path), "--output", str(self.output_path), "--dry-run"]
            try:
                exit_code = cal.main()
            finally:
                sys.argv = argv_backup
        self.assertEqual(exit_code, 0)
        mock_client_cls.assert_not_called()
        self.assertFalse(self.output_path.exists())


class TestValidResponseEndToEnd(MainEndToEndMixin, unittest.TestCase):
    def test_valid_seven_day_calendar_succeeds_with_one_call(self):
        exit_code, calls = self.run_main([make_completed_stream("end_turn", make_calendar_response(7))])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        self.assertTrue(self.output_path.exists())
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertEqual(output["metadata"]["agent"], "content_calendar")
        self.assertEqual(len(output["calendar_items"]), 7)
        self.assertEqual(output["calendar_items"][0]["day_number"], 1)
        self.assertEqual(output["calendar_items"][-1]["day_number"], 7)

    def test_valid_thirty_day_calendar_succeeds(self):
        exit_code, calls = self.run_main(
            [make_completed_stream("end_turn", make_calendar_response(30))], extra_args=["--days", "30"]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 1)
        with open(self.output_path) as f:
            output = json.load(f)
        self.assertEqual(len(output["calendar_items"]), 30)
        self.assertEqual(output["metadata"]["days"], 30)

    def test_invalid_days_argument_rejected(self):
        exit_code, calls = self.run_main([], extra_args=["--days", "0"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 0)


class TestTruncation(MainEndToEndMixin, unittest.TestCase):
    def test_truncation_then_success(self):
        exit_code, calls = self.run_main(
            [make_completed_stream("max_tokens", {}), make_completed_stream("end_turn", make_calendar_response(7))]
        )
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.output_path.exists())

    def test_truncation_twice_fails_no_output(self):
        exit_code, calls = self.run_main([make_completed_stream("max_tokens", {}), make_completed_stream("max_tokens", {})])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())


class TestRetryAndFailure(MainEndToEndMixin, unittest.TestCase):
    def test_hard_violation_then_clean_retry_succeeds(self):
        bad = make_calendar_response(7)
        bad["calendar_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        good = make_calendar_response(7)
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", good)])
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(calls), 2)
        second_call_messages = calls[1].kwargs["messages"]
        self.assertIn("CORRECTION REQUIRED", second_call_messages[0]["content"])
        self.assertTrue(self.output_path.exists())

    def test_hard_violation_persists_fails_cleanly(self):
        bad = make_calendar_response(7)
        bad["calendar_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        exit_code, calls = self.run_main([make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)])
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)
        self.assertFalse(self.output_path.exists())

    def test_retry_count_bounded_at_two_calls(self):
        bad = make_calendar_response(7)
        bad["calendar_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        exit_code, calls = self.run_main(
            [make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad), make_completed_stream("end_turn", bad)]
        )
        self.assertEqual(exit_code, 1)
        self.assertEqual(len(calls), 2)

    def test_no_partial_output_on_any_failure(self):
        exit_code, calls = self.run_main([make_completed_stream("max_tokens", {}), make_completed_stream("max_tokens", {})])
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())
        self.assertEqual(list(Path(self.tmpdir.name).glob("calendar*")), [])


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
            sys.argv = ["content_calendar.py", "--input", str(self.strategy_path), "--output", str(self.output_path)]
            try:
                import io
                import contextlib

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    exit_code = cal.main()
            finally:
                sys.argv = argv_backup

        self.assertEqual(exit_code, 1)
        output = buf.getvalue()
        self.assertIn("schema validation failed: unexpected token", output)
        self.assertIn("400", output)
        self.assertFalse(self.output_path.exists())


class TestStrategyFileUntouched(MainEndToEndMixin, unittest.TestCase):
    def test_strategy_file_unchanged_after_run(self):
        before = self.strategy_path.read_text()
        self.run_main([make_completed_stream("end_turn", make_calendar_response(7))])
        after = self.strategy_path.read_text()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
