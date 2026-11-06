"""Deterministic tests for supported transcript markers."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = SCRIPT_DIR / "check_fidelity.py"
sys.path.insert(0, str(SCRIPT_DIR))

import check_fidelity as checker  # noqa: E402


class FidelitySignalsTest(unittest.TestCase):
    def test_prose_reflow_and_list_markup_preserve_supported_markers(self):
        source = "呃这个值是0.08。第一步读 `config_v2`，第二步等待1,024毫秒。\n"
        candidate = "这个值是 0.08。\n\n1. 第一步读 `config_v2`。\n2. 第二步等待 1,024 毫秒。\n"
        self.assertEqual(checker.compare(source, candidate), [])

    def test_numeric_order_duplicates_and_dates_are_visible(self):
        source = "2026-03-08 用 3 个样本，再用 4 个样本，最后再测 3 个。"
        for candidate in (
            "2026-03-09 用 3 个样本，再用 4 个样本，最后再测 3 个。",
            "2026-03-08 用 4 个样本，再用 3 个样本，最后再测 3 个。",
            "2026-03-08 用 3 个样本，再用 4 个样本。",
        ):
            with self.subTest(candidate=candidate):
                self.assertIn("Numeric or date token", checker.compare(source, candidate)[0])

    def test_numeric_values_cover_cjk_dates_and_signed_decimals(self):
        source = "2026年3月8日，设为 −0.8％，再比较 1e-3。"
        for original, modified in (("3月", "4月"), ("−0.8％", "0.8％"), ("1e-3", "1e-2")):
            with self.subTest(original=original):
                candidate = source.replace(original, modified)
                self.assertIn("Numeric or date token", checker.compare(source, candidate)[0])

    def test_ascii_identifier_digits_are_not_prose_numbers(self):
        source = "foo_v2 calls H264 and uses build3.2 as its identifier."
        candidate = "foo_v3 calls H265 and uses build4.2 as its identifier."
        self.assertEqual(checker.compare(source, candidate), [])

    def test_timestamp_and_speaker_changes_are_reviewable(self):
        source = "[00:03] 讲者：先把缓存关掉。\n00:15 Speaker 1: Does that also apply here?\n"
        for candidate in (
            source.replace("[00:03]", "[00:04]"),
            source.replace("Speaker 1:", "Speaker 2:"),
            source.replace("00:15 Speaker 1: ", ""),
        ):
            with self.subTest(candidate=candidate):
                findings = checker.compare(source, candidate)
                self.assertEqual(len(findings), 1)
                self.assertIn("Timestamp or speaker marker", findings[0])

    def test_frontmatter_prefix_keeps_bom_and_crlf_significant(self):
        source = "\ufeff---\r\ntitle: Test 4\r\n---\r\n\r\n讲者：开始了。\r\n"
        self.assertEqual(checker.compare(source, source.replace("开始了", "现在开始")), [])
        for candidate in (source.replace("\r\n", "\n"), source.removeprefix("\ufeff"), source.replace("Test 4", "Test 5")):
            with self.subTest(candidate=candidate):
                findings = checker.compare(source, candidate)
                self.assertEqual(len(findings), 1)
                self.assertIn("Frontmatter prefix", findings[0])

    def test_fenced_code_and_inline_code_are_checked_separately(self):
        source = "````python\nprint(3)\n```\n````\n\n保持 `` `timeout_ms` ``。\n"
        candidate = source.replace("print(3)", "print(4)").replace("timeout_ms", "retry_ms")
        findings = checker.compare(source, candidate)
        self.assertEqual(len(findings), 2)
        self.assertIn("Fenced code", findings[0])
        self.assertIn("Inline code", findings[1])

    def test_missing_boundaries_and_empty_body_are_signals(self):
        source = "---\ntitle: Fixture\n---\n\n内容。\n"
        self.assertTrue(any("body is empty" in finding for finding in checker.compare(source, "")))
        self.assertTrue(any("no closing ---" in finding for finding in checker.compare(source, "---\n")))
        self.assertTrue(any("Fence at line 1" in finding for finding in checker.compare(source, "~~~\ncode\n")))

    def test_matching_signals_do_not_mean_unchanged_meaning(self):
        self.assertEqual(checker.compare("只有缓存启用时才可能失败。", "缓存一定会失败。"), [])


class FidelityCLITest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.source = Path(directory.name) / "source.md"
        self.candidate = Path(directory.name) / "candidate.md"
        self.source.write_bytes(b"3 requests\r\n")
        self.candidate.write_bytes(b"4 requests\n")

    def run_cli(self):
        return subprocess.run(
            [sys.executable, "-X", "utf8", str(SCRIPT), str(self.source), str(self.candidate)],
            capture_output=True,
            encoding="utf-8",
            check=False,
        )

    def test_findings_exit_zero_and_leave_files_unchanged(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Numeric or date token", result.stdout)
        self.assertEqual(self.source.read_bytes(), b"3 requests\r\n")
        self.assertEqual(self.candidate.read_bytes(), b"4 requests\n")

    def test_input_failure_has_nonzero_exit_and_no_scan(self):
        self.candidate.write_bytes(b"\xff")
        invalid = self.run_cli()
        self.candidate.unlink()
        missing = self.run_cli()
        for result in (invalid, missing):
            self.assertEqual(result.returncode, 2)
            self.assertIn("error", result.stderr)
            self.assertIn("candidate.md", result.stderr)
            self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
