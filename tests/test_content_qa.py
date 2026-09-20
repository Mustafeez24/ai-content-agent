"""
Tests for scripts/content_qa.py (Stage 9 - Content QA / Final Quality Gate).

Pure-function tests exercise every check directly with hand-built synthetic dicts
(never real FlyingFish data). This stage makes no Anthropic API calls, so there is
nothing to mock - every test here runs against plain Python data and files.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-fake-key-never-used-in-mocked-tests")

import content_qa as qa
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


_ROTATION = ["Reel", "Carousel", "Static Post", "Story", "Educational Post"]


def make_calendar(days=3, distinct_topics=None):
    items = []
    for i in range(1, days + 1):
        content_type = _ROTATION[(i - 1) % len(_ROTATION)]
        platform = "Google Business Profile" if i % 5 == 0 else "Instagram"
        topic = distinct_topics[i - 1] if distinct_topics else f"Topic for day {i}"
        items.append(make_calendar_item(i, content_type=content_type, platform=platform, topic=topic))
    return {"metadata": {}, "calendar_summary": "SYNTHETIC calendar for testing.", "calendar_items": items}


def make_content_item_for(calendar_item, index=0, **overrides):
    package_type = cg.package_type_for_item(calendar_item)
    base = {
        "day_number": calendar_item["day_number"],
        "date": calendar_item["date"],
        "platform": calendar_item["platform"],
        "content_type": calendar_item["content_type"],
        "package_type": package_type,
        "topic": calendar_item["topic"],
        "objective": calendar_item["objective"],
        "target_audience": calendar_item["target_audience"],
        "content_angle": calendar_item["content_angle"],
        "priority": calendar_item["priority"],
        "status": "drafted",
        "hook": "", "script_scenes": [], "slides": [], "frames": [], "interaction_suggestion": "",
        "headline": "", "body": "", "caption": "",
        "cta": f"DM us to book your first Goa dive. ({index})",
        "footage_note": "",
        "evidence_basis": "POST_TOP1 had 3,200 likes and included instructor praise.",
        "evidence_type": "interpretation",
        "source_post_ids": ["POST_TOP1"],
        "confidence": "low",
        "requires_verification": False,
        "verification_reason": None,
    }
    if package_type == "reel":
        base.update({
            "hook": f"Never dived before? Here's what happens before you enter the water. ({index})",
            "script_scenes": [
                f"Scene 1 (~3s) - Visual: existing FlyingFish boat footage. On-screen text: 'First dive?' ({index})",
                f"Scene 2 (~5s) - Visual: instructor briefing footage. Point: safety basics. ({index})",
            ],
            "caption": f"What happens before your first Goa dive. ({index})",
            "footage_note": "Use existing FlyingFish boat and instructor footage if available.",
        })
    elif package_type == "carousel":
        base.update({
            "hook": f"What SSI certification actually involves. ({index})",
            "slides": [
                f"Slide 1: What SSI certification involves. ({index})",
                f"Slide 2: Step one is the classroom sessions. ({index})",
                f"Slide 3: Ready to start? DM us. ({index})",
            ],
            "caption": f"A breakdown of the FlyingFish certification path. ({index})",
            "footage_note": "Use existing FlyingFish classroom footage if available.",
        })
    elif package_type == "story":
        base.update({
            "frames": [
                f"Frame 1: Ever wondered about marine life near Goa? ({index})",
                f"Frame 2: Real footage from our recent FlyingFish dives. ({index})",
            ],
            "footage_note": "Use existing FlyingFish marine-life footage if available.",
        })
    elif package_type == "static":
        base.update({
            "headline": f"Beginner scuba preparation checklist ({index})",
            "body": f"Here is what first-time divers should know before their first FlyingFish session in Goa. ({index})",
            "caption": f"Save this before your first Goa dive. ({index})",
            "footage_note": "Use existing FlyingFish pool footage if available.",
        })
    elif package_type == "gbp":
        base.update({
            "headline": f"Learn to dive at FlyingFish Scuba School ({index})",
            "body": f"FlyingFish offers SSI and PADI certifications at Novotel Resort and Spa, Candolim, Goa. ({index})",
        })
    base.update(overrides)
    return base


def make_content(calendar):
    items = [make_content_item_for(it, index=i) for i, it in enumerate(calendar["calendar_items"])]
    return {"metadata": {}, "content_summary": "SYNTHETIC content for testing.", "content_items": items}


# --- load_content_package ---
class TestLoadContentPackage(unittest.TestCase):
    def _write(self, data):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            return Path(f.name)

    def test_missing_file(self):
        with self.assertRaises(qa.DataError):
            qa.load_content_package(Path("/tmp/does_not_exist_content.json"))

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = Path(f.name)
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    def test_missing_top_level_section(self):
        path = self._write({"metadata": {}})
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    def test_empty_content_items_rejected(self):
        path = self._write({"metadata": {}, "content_summary": "x", "content_items": []})
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    def test_item_missing_required_field_rejected(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        del content["content_items"][0]["evidence_basis"]
        path = self._write(content)
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    def test_invalid_package_type_rejected(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["package_type"] = "tiktok_dance"
        path = self._write(content)
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    def test_invalid_platform_rejected(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["platform"] = "TikTok"
        path = self._write(content)
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    # Scenario: duplicate content item IDs (day_number is the item's identifier).
    def test_duplicate_day_number_rejected(self):
        calendar = make_calendar(2)
        content = make_content(calendar)
        content["content_items"][1]["day_number"] = 1
        path = self._write(content)
        try:
            with self.assertRaises(qa.DataError):
                qa.load_content_package(path)
        finally:
            path.unlink()

    def test_valid_content_package_loads(self):
        calendar = make_calendar(3)
        content = make_content(calendar)
        path = self._write(content)
        try:
            data = qa.load_content_package(path)
            self.assertEqual(len(data["content_items"]), 3)
        finally:
            path.unlink()


# --- check_calendar_consistency ---
class TestCalendarConsistency(unittest.TestCase):
    def test_matching_calendar_and_content_has_no_hard_failures(self):
        calendar = make_calendar(3)
        content = make_content(calendar)
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertEqual(result["hard"], [])
        self.assertEqual(result["coverage"]["missing_days"], [])
        self.assertEqual(result["coverage"]["extra_days"], [])
        self.assertEqual(result["coverage"]["mismatched_days"], [])

    def test_missing_day_is_hard_failure(self):
        calendar = make_calendar(3)
        content = make_content(calendar)
        del content["content_items"][2]
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertTrue(any("no matching Stage 8 content package" in v for v in result["hard"]))
        self.assertEqual(result["coverage"]["missing_days"], [3])

    def test_extra_day_is_hard_failure(self):
        calendar = make_calendar(2)
        content = make_content(calendar)
        extra_calendar_item = make_calendar_item(3, content_type="Static Post")
        content["content_items"].append(make_content_item_for(extra_calendar_item, index=2))
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertTrue(any("no matching Stage 7 calendar day" in v for v in result["hard"]))
        self.assertEqual(result["coverage"]["extra_days"], [3])

    def test_wrong_date_is_hard_failure(self):
        calendar = make_calendar(2)
        content = make_content(calendar)
        content["content_items"][0]["date"] = "2099-12-31"
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertTrue(any("date mismatch" in v for v in result["hard"]))

    def test_wrong_platform_is_hard_failure(self):
        calendar = make_calendar(2)
        content = make_content(calendar)
        content["content_items"][0]["platform"] = "Google Business Profile"
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertTrue(any("platform mismatch" in v for v in result["hard"]))

    def test_wrong_content_type_is_hard_failure(self):
        calendar = make_calendar(2)
        content = make_content(calendar)
        content["content_items"][0]["content_type"] = "Story"
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertTrue(any("content_type mismatch" in v for v in result["hard"]))

    def test_wrong_package_type_is_hard_failure(self):
        calendar = make_calendar(2)
        content = make_content(calendar)
        content["content_items"][0]["package_type"] = "story"
        result = qa.check_calendar_consistency(calendar["calendar_items"], content["content_items"])
        self.assertTrue(any("package_type mismatch" in v for v in result["hard"]))


# --- promote_soft_to_hard / partnership-inclusion ---
class TestPromoteSoftToHard(unittest.TestCase):
    def test_soft_violation_becomes_hard_failure_string(self):
        soft = [{"loc": "content_items[0]", "type": "flag_verification", "detail": "references a specific factual claim"}]
        promoted = qa.promote_soft_to_hard(soft)
        self.assertEqual(len(promoted), 1)
        self.assertIn("content_items[0]", promoted[0])
        self.assertIn("not auto-flagged", promoted[0])


class TestPartnershipInclusion(unittest.TestCase):
    def test_unverified_partnership_claim_is_hard_failure(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["body"] = "FlyingFish is an official partner of the resort's dive program."
        violations = qa.find_partnership_inclusion_violations(content["content_items"])
        self.assertTrue(any("partnership" in v.lower() for v in violations))

    def test_verified_partnership_claim_allowed(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["body"] = "FlyingFish is an official partner of the resort's dive program."
        content["content_items"][0]["requires_verification"] = True
        content["content_items"][0]["verification_reason"] = "Partnership claim requires confirmation before publishing."
        violations = qa.find_partnership_inclusion_violations(content["content_items"])
        self.assertEqual(violations, [])


class TestClassifyViolation(unittest.TestCase):
    def test_classifications(self):
        cases = {
            "content_items[0]: source_post_ids references post_id(s) not in the supplied Stage 7 evidence: ['X']": "invalid_source_post_ids",
            "content_items[0]: evidence_type='observed' but source_post_ids is empty - an observed/interpretation claim must cite at least one source_post_id": "missing_citations",
            "content_items[0].evidence_basis: uses unsupported causal language ('drives') - state only what was observed": "causal_language",
            "content_items[0]: makes a competitor claim without competitor data": "competitor_claims",
            "content_items[0]: states a specific price/currency amount without requires_verification=true": "price_claims",
            "content_items[0]: states a specific offer/discount/promotion without requires_verification=true": "offer_claims",
            "content_items[0]: instructs AI-generated footage/video": "ai_footage",
            "content_items[0]: references a specific factual claim - not auto-flagged with requires_verification=true in the final file": "unflagged_facts",
            "content_items[0].headline: missing/too short/vague for a Static Post": "structural_issues",
        }
        for v, expected in cases.items():
            with self.subTest(v=v):
                self.assertEqual(qa.classify_violation(v), expected)


# --- quality signals ---
class TestQualitySignals(unittest.TestCase):
    def test_generic_cta_is_a_warning(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["cta"] = "Learn more"
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "generic_cta" for s in signals))

    def test_weak_hook_is_a_warning(self):
        calendar = make_calendar(1, distinct_topics=["Beginner diving checklist"])
        content = make_content(calendar)
        content["content_items"][0]["package_type"] = "reel"
        content["content_items"][0]["hook"] = "Dive tips"
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "weak_hook" for s in signals))

    def test_excessive_promotional_wording_is_a_warning(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["body"] = "Book now, DM us, sign up, join now, hurry, limited spots at FlyingFish Goa."
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "excessive_promotional_wording" for s in signals))

    def test_missing_brand_context_is_a_warning(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        item = content["content_items"][0]
        for f in ("hook", "headline", "body", "caption", "cta", "footage_note"):
            item[f] = ""
        for f in ("script_scenes", "slides", "frames"):
            item[f] = []
        item["evidence_basis"] = "The supplied dataset shows a high-performing example with strong likes."
        item["headline"] = "General water safety advice"
        item["body"] = "Always check the weather before any water activity and tell someone your plans."
        item["cta"] = "Stay safe out there"
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "missing_brand_context" for s in signals))

    def test_possible_fabricated_testimonial_without_evidence_is_a_warning(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["evidence_type"] = "hypothesis"
        content["content_items"][0]["source_post_ids"] = []
        content["content_items"][0]["body"] = "A student told us diving with FlyingFish changed their life."
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "possible_fabricated_testimonial" for s in signals))

    def test_testimonial_backed_by_evidence_is_not_flagged(self):
        calendar = make_calendar(1)
        content = make_content(calendar)
        content["content_items"][0]["evidence_type"] = "observed"
        content["content_items"][0]["source_post_ids"] = ["POST_TOP1"]
        content["content_items"][0]["body"] = "A student told us diving with FlyingFish changed their life."
        signals = qa.find_quality_signals(content["content_items"])
        self.assertFalse(any(s["category"] == "possible_fabricated_testimonial" for s in signals))

    def test_repeated_cta_is_a_warning(self):
        calendar = make_calendar(2, distinct_topics=["Beginner diving checklist", "Marine life near Goa"])
        content = make_content(calendar)
        content["content_items"][0]["cta"] = "DM us to learn more"
        content["content_items"][1]["cta"] = "DM us to learn more"
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "repeated_cta" for s in signals))

    def test_repetitive_topic_near_days_is_a_warning(self):
        calendar = make_calendar(2, distinct_topics=["Beginner scuba preparation checklist", "Beginner scuba preparation checklist tips"])
        content = make_content(calendar)
        signals = qa.find_quality_signals(content["content_items"])
        self.assertTrue(any(s["category"] == "repetitive_topic_near_days" for s in signals))

    def test_distinct_topics_far_apart_are_not_flagged(self):
        calendar = make_calendar(
            5, distinct_topics=["Beginner scuba checklist", "Marine life", "SSI certification", "Boat safety", "Beginner scuba checklist redo"]
        )
        content = make_content(calendar)
        signals = qa.find_quality_signals(content["content_items"])
        # days 1 and 5 are similar but 4 days apart - outside the near-day window.
        near_day_signals = [s for s in signals if s["category"] == "repetitive_topic_near_days"]
        self.assertEqual(near_day_signals, [])


# --- build_report end-to-end (in-memory, no file IO) ---
class TestBuildReport(unittest.TestCase):
    def _clean_pair(self, days=3):
        topics = [f"Distinct topic number {i} about a different scuba subject entirely" for i in range(days)]
        calendar = make_calendar(days, distinct_topics=topics)
        content = make_content(calendar)
        return calendar, content

    def test_clean_valid_package_passes_with_no_hard_failures(self):
        calendar, content = self._clean_pair()
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["hard_failures"], [])
        self.assertEqual(report["summary"]["hard_failure_count"], 0)

    def test_invented_offer_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["body"] += " Enjoy our limited-time offer this week only."
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["safety_validation"]["offer_claims"])

    def test_invented_price_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["cta"] = "Book now for just ₹5000!"
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["safety_validation"]["price_claims"])

    def test_ai_footage_instruction_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        reel_item = next(it for it in content["content_items"] if it["package_type"] == "reel")
        reel_item["footage_note"] = "Generate footage using AI for the underwater scene."
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["safety_validation"]["ai_footage"])

    def test_causal_claim_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["safety_validation"]["causal_language"])

    def test_invalid_source_post_id_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["source_post_ids"] = ["POST_INVENTED"]
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["evidence_validation"]["invalid_source_post_ids"])

    def test_missing_required_package_field_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        reel_item = next(it for it in content["content_items"] if it["package_type"] == "reel")
        reel_item["hook"] = ""
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["package_validation"]["structural_issues"])

    def test_unflagged_fact_is_a_hard_failure(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["body"] += " Our certified instructors have years of experience."
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report["safety_validation"]["unflagged_facts"])

    def test_warning_only_case_still_passes(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["cta"] = "Learn more"
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["hard_failures"], [])
        self.assertTrue(report["warnings"])

    def test_multiple_simultaneous_hard_failures(self):
        calendar, content = self._clean_pair()
        content["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."
        content["content_items"][1]["source_post_ids"] = ["POST_INVENTED"]
        del content["content_items"][2]
        report = qa.build_report(calendar, content, Path("cal.json"), Path("content.json"))
        self.assertEqual(report["status"], "FAIL")
        self.assertGreaterEqual(report["summary"]["hard_failure_count"], 3)
        self.assertTrue(report["safety_validation"]["causal_language"])
        self.assertTrue(report["evidence_validation"]["invalid_source_post_ids"])
        self.assertTrue(report["coverage"]["missing_days"])


# --- main() end-to-end (real files, no API calls involved at all) ---
class MainEndToEndMixin:
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.calendar_path = Path(self.tmpdir.name) / "calendar.json"
        self.content_path = Path(self.tmpdir.name) / "content.json"
        self.output_path = Path(self.tmpdir.name) / "qa.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_pair(self, days=3, mutate_content=None):
        topics = [f"Distinct topic number {i} about a different scuba subject entirely" for i in range(days)]
        calendar = make_calendar(days, distinct_topics=topics)
        content = make_content(calendar)
        if mutate_content:
            mutate_content(content)
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        with open(self.content_path, "w") as f:
            json.dump(content, f)

    def run_main(self, extra_args=None):
        argv_backup = sys.argv
        sys.argv = [
            "content_qa.py",
            "--calendar-input", str(self.calendar_path),
            "--content-input", str(self.content_path),
            "--output", str(self.output_path),
        ]
        sys.argv += extra_args or []
        try:
            return qa.main()
        finally:
            sys.argv = argv_backup


class TestMainEndToEnd(MainEndToEndMixin, unittest.TestCase):
    def test_missing_calendar_file_fails(self):
        with open(self.content_path, "w") as f:
            json.dump({"metadata": {}, "content_summary": "x", "content_items": [{}]}, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())

    def test_missing_content_file_fails(self):
        calendar = make_calendar(1)
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_path.exists())

    def test_dry_run_writes_no_report(self):
        self.write_pair()
        exit_code = self.run_main(extra_args=["--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertFalse(self.output_path.exists())

    def test_clean_pair_passes_and_writes_report(self):
        self.write_pair()
        exit_code = self.run_main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(self.output_path.exists())
        with open(self.output_path) as f:
            report = json.load(f)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["summary"]["hard_failure_count"], 0)

    def test_failing_pair_fails_and_writes_report(self):
        def mutate(content):
            content["content_items"][0]["evidence_basis"] = "This is the primary engagement driver."

        self.write_pair(mutate_content=mutate)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertTrue(self.output_path.exists())
        with open(self.output_path) as f:
            report = json.load(f)
        self.assertEqual(report["status"], "FAIL")
        self.assertGreater(report["summary"]["hard_failure_count"], 0)

    def test_calendar_and_content_files_untouched_after_run(self):
        self.write_pair()
        before_cal = self.calendar_path.read_text()
        before_content = self.content_path.read_text()
        self.run_main()
        self.assertEqual(before_cal, self.calendar_path.read_text())
        self.assertEqual(before_content, self.content_path.read_text())


if __name__ == "__main__":
    unittest.main()
