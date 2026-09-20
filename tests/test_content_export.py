"""
Tests for scripts/content_export.py (Stage 10 - Content Export / Publishing-Ready Delivery).

Pure-function and file-based tests only - this stage makes no Anthropic API calls, so
there is nothing to mock. Reuses tests/test_content_qa.py's calendar/content fixtures
(same underlying shape) and content_qa.build_report() to construct realistic QA reports.
"""

import csv
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-fake-key-never-used-in-mocked-tests")

import content_export as ce
import content_qa as qa
import test_content_qa as tqa

VALID_POST_IDS = {"POST_TOP1", "POST_TOP2"}


def clean_pair(days=5):
    """A calendar + content pair with distinct topics (avoids QA's own repetitive-topic
    warning noise) that passes Stage 9 QA cleanly, plus the resulting QA report."""
    topics = [f"Distinct topic number {i} about a different scuba subject entirely" for i in range(days)]
    calendar = tqa.make_calendar(days, distinct_topics=topics)
    content = tqa.make_content(calendar)
    report = qa.build_report(calendar, content, Path("calendar.json"), Path("content.json"))
    return calendar, content, report


def write_json(data, tmpdir, name):
    path = Path(tmpdir) / name
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


# --- load_qa_report / verify_qa_gate ---
class TestLoadQaReport(unittest.TestCase):
    def test_missing_file(self):
        with self.assertRaises(ce.DataError):
            ce.load_qa_report(Path("/tmp/does_not_exist_qa.json"))

    def test_invalid_json(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            f.write("{not valid json")
            path = Path(f.name)
        try:
            with self.assertRaises(ce.DataError):
                ce.load_qa_report(path)
        finally:
            path.unlink()

    def test_missing_required_field_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json({"metadata": {}, "status": "PASS"}, tmp, "qa.json")
            with self.assertRaises(ce.DataError):
                ce.load_qa_report(path)

    def test_unrecognized_status_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(
                {"metadata": {}, "status": "MAYBE", "summary": {}, "hard_failures": [], "warnings": []}, tmp, "qa.json"
            )
            with self.assertRaises(ce.DataError):
                ce.load_qa_report(path)

    def test_valid_report_loads(self):
        _, _, report = clean_pair(2)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_json(report, tmp, "qa.json")
            loaded = ce.load_qa_report(path)
            self.assertEqual(loaded["status"], "PASS")


class TestVerifyQaGate(unittest.TestCase):
    def test_pass_with_no_hard_failures_allowed(self):
        _, _, report = clean_pair(2)
        ce.verify_qa_gate(report)  # should not raise

    def test_fail_status_blocked(self):
        report = {"status": "FAIL", "hard_failures": ["something bad"], "warnings": [], "summary": {}, "metadata": {}}
        with self.assertRaises(ce.DataError):
            ce.verify_qa_gate(report)

    def test_pass_status_with_hard_failures_present_is_blocked(self):
        # Internally inconsistent report (status says PASS but hard_failures is non-empty) -
        # never trust the status string alone.
        report = {"status": "PASS", "hard_failures": ["should not be possible"], "warnings": [], "summary": {}, "metadata": {}}
        with self.assertRaises(ce.DataError):
            ce.verify_qa_gate(report)


# --- spot_check_calendar ---
class TestSpotCheckCalendar(unittest.TestCase):
    def test_absent_default_calendar_produces_no_note(self):
        _, content, _ = clean_pair(2)
        notes = ce.spot_check_calendar(Path("/tmp/does_not_exist_calendar.json"), explicit=False, content_items=content["content_items"])
        self.assertEqual(notes, [])

    def test_absent_explicit_calendar_produces_a_note(self):
        _, content, _ = clean_pair(2)
        notes = ce.spot_check_calendar(Path("/tmp/does_not_exist_calendar.json"), explicit=True, content_items=content["content_items"])
        self.assertTrue(notes)
        self.assertIn("skipped", notes[0].lower())

    def test_consistent_calendar_produces_no_note(self):
        calendar, content, _ = clean_pair(2)
        with tempfile.TemporaryDirectory() as tmp:
            cal_path = write_json(calendar, tmp, "calendar.json")
            notes = ce.spot_check_calendar(cal_path, explicit=True, content_items=content["content_items"])
        self.assertEqual(notes, [])

    def test_missing_day_produces_an_informational_note_not_an_exception(self):
        calendar, content, _ = clean_pair(3)
        content["content_items"].pop()
        with tempfile.TemporaryDirectory() as tmp:
            cal_path = write_json(calendar, tmp, "calendar.json")
            notes = ce.spot_check_calendar(cal_path, explicit=True, content_items=content["content_items"])
        self.assertTrue(notes)
        self.assertIn("day coverage differs", notes[0])
        self.assertIn("authoritative", notes[0])

    def test_package_type_mismatch_produces_a_note(self):
        calendar, content, _ = clean_pair(2)
        content["content_items"][0]["package_type"] = "story"
        with tempfile.TemporaryDirectory() as tmp:
            cal_path = write_json(calendar, tmp, "calendar.json")
            notes = ce.spot_check_calendar(cal_path, explicit=True, content_items=content["content_items"])
        self.assertTrue(any("package_type differs" in n for n in notes))


# --- JSON export ---
class TestJsonExport(unittest.TestCase):
    def test_content_items_have_exactly_the_27_fields(self):
        _, content, report = clean_pair(2)
        result = ce.build_json_export(content["content_items"], report, "content.json", "qa.json", [])
        for item in result["content_items"]:
            self.assertEqual(set(item.keys()), set(ce.CONTENT_ITEM_FIELDS))

    def test_content_integrity_exact_passthrough(self):
        _, content, report = clean_pair(2)
        result = ce.build_json_export(content["content_items"], report, "content.json", "qa.json", [])
        for original, exported in zip(content["content_items"], result["content_items"]):
            for field in ce.CONTENT_ITEM_FIELDS:
                self.assertEqual(original.get(field), exported[field], f"field {field} was altered")

    def test_qa_info_kept_separate_from_content_items(self):
        _, content, report = clean_pair(2)
        result = ce.build_json_export(content["content_items"], report, "content.json", "qa.json", [])
        self.assertIn("qa_summary", result)
        self.assertIn("qa_warnings", result)
        for item in result["content_items"]:
            self.assertNotIn("qa_summary", item)
            self.assertNotIn("status_qa", item)  # no QA field leaked into a content item

    def test_export_does_not_mutate_source_items(self):
        _, content, report = clean_pair(2)
        before = json.dumps(content["content_items"], sort_keys=True)
        ce.build_json_export(content["content_items"], report, "content.json", "qa.json", [])
        after = json.dumps(content["content_items"], sort_keys=True)
        self.assertEqual(before, after)

    def test_qa_warnings_carried_forward_verbatim(self):
        _, content, report = clean_pair(2)
        report["warnings"] = ["[generic_cta] day 1: CTA is generic/non-specific: 'Learn more'"]
        result = ce.build_json_export(content["content_items"], report, "content.json", "qa.json", [])
        self.assertEqual(result["qa_warnings"], report["warnings"])


# --- CSV export ---
class TestCsvExport(unittest.TestCase):
    def test_all_package_types_present_and_readable(self):
        calendar, content, _ = clean_pair(5)  # rotation covers reel/carousel/static/story/gbp-ish
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            ce.write_csv_export(content["content_items"], path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["day_number"], "1")

    def test_array_fields_flattened_and_numbered(self):
        calendar, content, _ = clean_pair(1)
        reel_item = content["content_items"][0]
        reel_item["package_type"] = "reel"
        reel_item["script_scenes"] = ["First scene text", "Second scene text"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            ce.write_csv_export([reel_item], path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertIn("1. First scene text", rows[0]["script_scenes"])
        self.assertIn("2. Second scene text", rows[0]["script_scenes"])

    def test_source_post_ids_comma_joined(self):
        _, content, _ = clean_pair(1)
        content["content_items"][0]["source_post_ids"] = ["POST_TOP1", "POST_TOP2"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.csv"
            ce.write_csv_export(content["content_items"], path)
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["source_post_ids"], "POST_TOP1, POST_TOP2")

    def test_all_csv_columns_present(self):
        self.assertEqual(len(ce.CSV_COLUMNS), len(ce.CONTENT_ITEM_FIELDS))
        self.assertEqual(set(ce.CSV_COLUMNS), set(ce.CONTENT_ITEM_FIELDS))


# --- Markdown export ---
class TestMarkdownExport(unittest.TestCase):
    def test_reel_section_has_hook_and_scenes(self):
        _, content, report = clean_pair(1)
        content["content_items"][0]["package_type"] = "reel"
        content["content_items"][0]["hook"] = "A specific attention-grabbing hook."
        content["content_items"][0]["script_scenes"] = ["Scene A", "Scene B"]
        text = ce.build_markdown_export(content["content_items"], report, [])
        self.assertIn("**Hook:**", text)
        self.assertIn("1. Scene A", text)
        self.assertIn("2. Scene B", text)

    def test_carousel_section_has_slides(self):
        _, content, report = clean_pair(1)
        content["content_items"][0]["package_type"] = "carousel"
        content["content_items"][0]["slides"] = ["Slide one", "Slide two", "Slide three"]
        text = ce.build_markdown_export(content["content_items"], report, [])
        self.assertIn("**Slides:**", text)
        self.assertIn("1. Slide one", text)

    def test_story_section_has_frames(self):
        _, content, report = clean_pair(1)
        content["content_items"][0]["package_type"] = "story"
        content["content_items"][0]["frames"] = ["Frame one", "Frame two"]
        text = ce.build_markdown_export(content["content_items"], report, [])
        self.assertIn("**Frames:**", text)
        self.assertIn("1. Frame one", text)

    def test_static_and_gbp_sections_have_headline_and_body(self):
        _, content, report = clean_pair(1)
        content["content_items"][0]["package_type"] = "static"
        content["content_items"][0]["headline"] = "A clear headline"
        content["content_items"][0]["body"] = "Useful body copy about diving."
        text = ce.build_markdown_export(content["content_items"], report, [])
        self.assertIn("**Headline:** A clear headline", text)
        self.assertIn("**Body:** Useful body copy about diving.", text)

    def test_qa_warnings_and_export_notes_both_shown(self):
        _, content, report = clean_pair(1)
        report["warnings"] = ["[generic_cta] day 1: something"]
        text = ce.build_markdown_export(content["content_items"], report, ["Calendar spot-check: day coverage differs"])
        self.assertIn("QA warnings", text)
        self.assertIn("something", text)
        self.assertIn("Export notes", text)
        self.assertIn("day coverage differs", text)

    def test_verification_reason_shown_when_present(self):
        _, content, report = clean_pair(1)
        content["content_items"][0]["requires_verification"] = True
        content["content_items"][0]["verification_reason"] = "Price not confirmed."
        text = ce.build_markdown_export(content["content_items"], report, [])
        self.assertIn("**Requires verification:** Yes", text)
        self.assertIn("Price not confirmed.", text)


# --- main() end-to-end ---
class MainEndToEndMixin:
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.qa_path = Path(self.tmpdir.name) / "qa.json"
        self.content_path = Path(self.tmpdir.name) / "content.json"
        self.calendar_path = Path(self.tmpdir.name) / "calendar.json"
        self.output_dir = Path(self.tmpdir.name) / "exports"

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_all(self, days=5, mutate_content=None, mutate_report=None):
        calendar, content, report = clean_pair(days)
        if mutate_content:
            mutate_content(content)
            report = qa.build_report(calendar, content, self.calendar_path, self.content_path)
        if mutate_report:
            mutate_report(report)
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        with open(self.content_path, "w") as f:
            json.dump(content, f)
        with open(self.qa_path, "w") as f:
            json.dump(report, f)
        return calendar, content, report

    def run_main(self, extra_args=None, use_calendar=False):
        argv_backup = sys.argv
        sys.argv = [
            "content_export.py",
            "--qa-input", str(self.qa_path),
            "--content-input", str(self.content_path),
            "--output-dir", str(self.output_dir),
        ]
        if use_calendar:
            sys.argv += ["--calendar-input", str(self.calendar_path)]
        sys.argv += extra_args or []
        try:
            return ce.main()
        finally:
            sys.argv = argv_backup


class TestMainEndToEnd(MainEndToEndMixin, unittest.TestCase):
    def test_qa_pass_allows_export_all_three_files_written(self):
        self.write_all()
        exit_code = self.run_main()
        self.assertEqual(exit_code, 0)
        self.assertTrue((self.output_dir / ce.JSON_OUTPUT_FILENAME).exists())
        self.assertTrue((self.output_dir / ce.CSV_OUTPUT_FILENAME).exists())
        self.assertTrue((self.output_dir / ce.MARKDOWN_OUTPUT_FILENAME).exists())

    def test_qa_fail_blocks_export_no_files_written(self):
        def make_fail(report):
            report["status"] = "FAIL"
            report["hard_failures"] = ["content_items[0].evidence_basis: uses unsupported causal language"]

        self.write_all(mutate_report=make_fail)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_dir.exists())

    def test_missing_qa_file_fails(self):
        _, content, _ = clean_pair(2)
        with open(self.content_path, "w") as f:
            json.dump(content, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_dir.exists())

    def test_malformed_qa_json_fails(self):
        with open(self.qa_path, "w") as f:
            f.write("{not valid json")
        _, content, _ = clean_pair(2)
        with open(self.content_path, "w") as f:
            json.dump(content, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_dir.exists())

    def test_missing_content_file_fails(self):
        _, _, report = clean_pair(2)
        with open(self.qa_path, "w") as f:
            json.dump(report, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_dir.exists())

    def test_duplicate_day_in_content_file_fails(self):
        def dup(content):
            content["content_items"][1]["day_number"] = content["content_items"][0]["day_number"]

        # Build report from the ORIGINAL (valid) content, then corrupt the on-disk content
        # file afterward - load_content_package must still catch the duplicate at load time.
        calendar, content, report = clean_pair(3)
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        with open(self.qa_path, "w") as f:
            json.dump(report, f)
        dup(content)
        with open(self.content_path, "w") as f:
            json.dump(content, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_dir.exists())

    def test_ordering_preserved_by_day_number(self):
        calendar, content, report = clean_pair(5)
        content["content_items"].reverse()  # shuffle on-disk order
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        with open(self.content_path, "w") as f:
            json.dump(content, f)
        with open(self.qa_path, "w") as f:
            json.dump(report, f)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 0)
        with open(self.output_dir / ce.JSON_OUTPUT_FILENAME) as f:
            exported = json.load(f)
        day_numbers = [item["day_number"] for item in exported["content_items"]]
        self.assertEqual(day_numbers, sorted(day_numbers))

    def test_verification_metadata_preserved_across_all_formats(self):
        def mutate(content):
            content["content_items"][0]["requires_verification"] = True
            content["content_items"][0]["verification_reason"] = "Needs a human check."

        self.write_all(mutate_content=mutate)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 0)

        with open(self.output_dir / ce.JSON_OUTPUT_FILENAME) as f:
            exported = json.load(f)
        self.assertTrue(exported["content_items"][0]["requires_verification"])
        self.assertEqual(exported["content_items"][0]["verification_reason"], "Needs a human check.")

        with open(self.output_dir / ce.CSV_OUTPUT_FILENAME, newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(rows[0]["requires_verification"], "True")
        self.assertEqual(rows[0]["verification_reason"], "Needs a human check.")

        md_text = (self.output_dir / ce.MARKDOWN_OUTPUT_FILENAME).read_text()
        self.assertIn("Needs a human check.", md_text)

    def test_qa_warnings_carried_forward_into_export(self):
        def mutate_report(report):
            report["warnings"] = ["[generic_cta] day 1: CTA is generic/non-specific: 'Learn more'"]

        self.write_all(mutate_report=mutate_report)
        exit_code = self.run_main()
        self.assertEqual(exit_code, 0)
        with open(self.output_dir / ce.JSON_OUTPUT_FILENAME) as f:
            exported = json.load(f)
        self.assertEqual(len(exported["qa_warnings"]), 1)

    def test_output_directory_auto_created(self):
        self.write_all()
        self.assertFalse(self.output_dir.exists())
        exit_code = self.run_main()
        self.assertEqual(exit_code, 0)
        self.assertTrue(self.output_dir.exists())

    def test_dry_run_writes_no_files(self):
        self.write_all()
        exit_code = self.run_main(extra_args=["--dry-run"])
        self.assertEqual(exit_code, 0)
        self.assertFalse(self.output_dir.exists())

    def test_unknown_format_rejected(self):
        self.write_all()
        exit_code = self.run_main(extra_args=["--formats", "pdf"])
        self.assertEqual(exit_code, 1)
        self.assertFalse(self.output_dir.exists())

    def test_selecting_a_single_format_only_writes_that_file(self):
        self.write_all()
        exit_code = self.run_main(extra_args=["--formats", "json"])
        self.assertEqual(exit_code, 0)
        self.assertTrue((self.output_dir / ce.JSON_OUTPUT_FILENAME).exists())
        self.assertFalse((self.output_dir / ce.CSV_OUTPUT_FILENAME).exists())
        self.assertFalse((self.output_dir / ce.MARKDOWN_OUTPUT_FILENAME).exists())

    def test_optional_calendar_mismatch_does_not_block_export(self):
        def mutate(content):
            content["content_items"][0]["package_type"] = "story"  # deliberately wrong

        calendar, content, report = clean_pair(3)
        mutate(content)
        with open(self.calendar_path, "w") as f:
            json.dump(calendar, f)
        with open(self.content_path, "w") as f:
            json.dump(content, f)
        # Report built from the ORIGINAL (matching) content, so QA itself still PASSes -
        # the calendar spot-check disagreement must remain informational only.
        with open(self.qa_path, "w") as f:
            json.dump(report, f)
        exit_code = self.run_main(use_calendar=True)
        self.assertEqual(exit_code, 0)
        with open(self.output_dir / ce.JSON_OUTPUT_FILENAME) as f:
            exported = json.load(f)
        self.assertTrue(exported["export_notes"])

    def test_deterministic_output_ignoring_generated_at(self):
        self.write_all()
        self.run_main()
        with open(self.output_dir / ce.JSON_OUTPUT_FILENAME) as f:
            first = json.load(f)
        first_csv = (self.output_dir / ce.CSV_OUTPUT_FILENAME).read_text()

        output_dir_2 = Path(self.tmpdir.name) / "exports2"
        argv_backup = sys.argv
        sys.argv = [
            "content_export.py",
            "--qa-input", str(self.qa_path),
            "--content-input", str(self.content_path),
            "--output-dir", str(output_dir_2),
        ]
        try:
            ce.main()
        finally:
            sys.argv = argv_backup
        with open(output_dir_2 / ce.JSON_OUTPUT_FILENAME) as f:
            second = json.load(f)
        second_csv = (output_dir_2 / ce.CSV_OUTPUT_FILENAME).read_text()

        first["metadata"].pop("generated_at")
        second["metadata"].pop("generated_at")
        self.assertEqual(first, second)
        self.assertEqual(first_csv, second_csv)  # CSV has no timestamp at all

    def test_source_files_untouched_after_run(self):
        self.write_all()
        before_qa = self.qa_path.read_text()
        before_content = self.content_path.read_text()
        self.run_main()
        self.assertEqual(before_qa, self.qa_path.read_text())
        self.assertEqual(before_content, self.content_path.read_text())


if __name__ == "__main__":
    unittest.main()
