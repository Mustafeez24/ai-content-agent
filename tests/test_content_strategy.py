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
