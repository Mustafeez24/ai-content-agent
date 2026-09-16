"""
Tests for scripts/run_content_pipeline.py orchestration logic.

These test only the orchestration control flow (stage ordering, failure
handling, mode selection). subprocess.run is mocked throughout, so no real
Apify or Anthropic calls are ever made by running this test file.

Usage:
    source venv/bin/activate
    python -m unittest tests.test_run_content_pipeline -v
"""

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import run_content_pipeline as pipeline


def make_completed(returncode):
    proc = MagicMock()
    proc.returncode = returncode
    return proc


class TestModeSelection(unittest.TestCase):
    @patch("run_content_pipeline.subprocess.run")
    def test_no_mode_selected_refuses_real_run(self, mock_run):
        exit_code = pipeline.main([])
        self.assertNotEqual(exit_code, 0)
        mock_run.assert_not_called()

    @patch("run_content_pipeline.subprocess.run")
    def test_run_id_and_new_scrape_mutually_exclusive(self, mock_run):
        exit_code = pipeline.main(["--run-id", "abc123", "--new-scrape"])
        self.assertNotEqual(exit_code, 0)
        mock_run.assert_not_called()


class TestDryRun(unittest.TestCase):
    @patch("run_content_pipeline.subprocess.run")
    def test_dry_run_never_invokes_stage_scripts(self, mock_run):
        mock_run.return_value = make_completed(0)  # for the git check-ignore calls
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = pipeline.main(["--dry-run"])
        self.assertEqual(exit_code, 0)

        for call in mock_run.call_args_list:
            cmd = call.args[0] if call.args else call.kwargs.get("cmd", [])
            cmd_str = " ".join(str(c) for c in cmd)
            self.assertNotIn("scrape_instagram_flyingfish.py", cmd_str)
            self.assertNotIn("analyze_instagram_content.py", cmd_str)
            self.assertNotIn("content_scout.py", cmd_str)

        output = buf.getvalue()
        self.assertIn("DRY RUN", output)
        self.assertIn("No Apify or Anthropic calls will be made", output)

    @patch("run_content_pipeline.subprocess.run")
    def test_dry_run_reports_run_id_mode(self, mock_run):
        mock_run.return_value = make_completed(0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pipeline.main(["--dry-run", "--run-id", "qyhgaXpKzggq6tf1c"])
        output = buf.getvalue()
        self.assertIn("reuse existing Apify run 'qyhgaXpKzggq6tf1c'", output)
        self.assertIn("no new Actor run", output)

    @patch("run_content_pipeline.subprocess.run")
    def test_dry_run_never_prints_secrets(self, mock_run):
        mock_run.return_value = make_completed(0)
        with patch.dict("os.environ", {"APIFY_API_TOKEN": "super-secret-token-value", "ANTHROPIC_API_KEY": "super-secret-key-value"}):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pipeline.main(["--dry-run"])
        output = buf.getvalue()
        self.assertNotIn("super-secret-token-value", output)
        self.assertNotIn("super-secret-key-value", output)
        self.assertIn("APIFY_API_TOKEN: set", output)
        self.assertIn("ANTHROPIC_API_KEY: set", output)


class TestMissingScripts(unittest.TestCase):
    def test_missing_stage_script_fails_before_any_call(self):
        original = pipeline.STAGE2_SCRIPT
        pipeline.STAGE2_SCRIPT = Path("scripts/does_not_exist.py")
        try:
            with patch("run_content_pipeline.subprocess.run") as mock_run:
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    exit_code = pipeline.main(["--run-id", "abc"])
                self.assertNotEqual(exit_code, 0)
                mock_run.assert_not_called()
                self.assertIn("Missing required stage script", buf.getvalue())
        finally:
            pipeline.STAGE2_SCRIPT = original


class TestPipelineExecution(unittest.TestCase):
    @patch("run_content_pipeline.subprocess.run")
    def test_stage2_failure_stops_pipeline(self, mock_run):
        mock_run.return_value = make_completed(1)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = pipeline.main(["--run-id", "abc123"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(mock_run.call_count, 1)
        self.assertIn("Stage 2", buf.getvalue())

    @patch("run_content_pipeline.subprocess.run")
    def test_stage3_failure_stops_before_stage4(self, mock_run):
        mock_run.side_effect = [make_completed(0), make_completed(1)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = pipeline.main(["--run-id", "abc123"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(mock_run.call_count, 2)
        self.assertIn("Stage 3", buf.getvalue())

    @patch("run_content_pipeline.subprocess.run")
    def test_stage4_failure_reported(self, mock_run):
        mock_run.side_effect = [make_completed(0), make_completed(0), make_completed(1)]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = pipeline.main(["--run-id", "abc123"])
        self.assertEqual(exit_code, 1)
        self.assertEqual(mock_run.call_count, 3)
        self.assertIn("Stage 4", buf.getvalue())

    @patch("run_content_pipeline.read_posts_analyzed", return_value="20")
    @patch("run_content_pipeline.subprocess.run")
    def test_full_success_runs_all_three_in_order(self, mock_run, mock_read):
        mock_run.return_value = make_completed(0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exit_code = pipeline.main(["--run-id", "abc123"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(mock_run.call_count, 3)

        called_scripts = []
        for call in mock_run.call_args_list:
            cmd = call.args[0]
            called_scripts.append(next(c for c in cmd if str(c).endswith(".py")))
        self.assertEqual(
            called_scripts,
            ["scripts/scrape_instagram_flyingfish.py", "scripts/analyze_instagram_content.py", "scripts/content_scout.py"],
        )

        output = buf.getvalue()
        self.assertIn("PIPELINE SUCCESS", output)
        self.assertIn("Posts processed: 20", output)
        self.assertIn("Analysis: completed", output)
        self.assertIn("Content Scout: completed", output)

    @patch("run_content_pipeline.read_posts_analyzed", return_value="20")
    @patch("run_content_pipeline.subprocess.run")
    def test_run_id_passed_through_to_stage2_only(self, mock_run, mock_read):
        mock_run.return_value = make_completed(0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pipeline.main(["--run-id", "qyhgaXpKzggq6tf1c"])

        stage2_call = mock_run.call_args_list[0]
        self.assertIn("--run-id", stage2_call.args[0])
        self.assertIn("qyhgaXpKzggq6tf1c", stage2_call.args[0])

        # Stage 3 and 4 should NOT receive --run-id - it is scraper-specific.
        for call in mock_run.call_args_list[1:]:
            self.assertNotIn("--run-id", call.args[0])

    @patch("run_content_pipeline.read_posts_analyzed", return_value="20")
    @patch("run_content_pipeline.subprocess.run")
    def test_new_scrape_mode_passes_no_run_id(self, mock_run, mock_read):
        mock_run.return_value = make_completed(0)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            pipeline.main(["--new-scrape"])
        stage2_call = mock_run.call_args_list[0]
        self.assertNotIn("--run-id", stage2_call.args[0])


if __name__ == "__main__":
    unittest.main()
