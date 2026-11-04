#!/usr/bin/env python3
"""Offline A/B/C fixture and scorer tests using temporary Git repositories."""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
import handoff_cases as handoff


class HandoffCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = tempfile.TemporaryDirectory(prefix="wiki-memory-handoff-tests-")
        cls.addClassCleanup(work.cleanup)
        cls.work = Path(work.name)
        cls.root = cls.work / "matrix"
        code, output, errors = cls.invoke("matrix", "--output", cls.root, "--date", "2026-11-04")
        if code:
            raise AssertionError(errors)
        cls.manifest = json.loads(output)

    @staticmethod
    def invoke(*args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = handoff.main(list(map(str, args)))
        return code, output.getvalue(), errors.getvalue()

    def record(self, case, variant, *, root=None):
        return json.loads(((root or self.root) / "private" / case / f"{variant}.json").read_text(encoding="utf-8"))

    def project(self, case, variant, *, root=None):
        return (root or self.root) / "agent" / case / variant / "project"

    def score(self, case, variant, *flags, root=None):
        code, output, errors = self.invoke("score", "--fixture", root or self.root, "--case", case, "--variant", variant, *flags)
        self.assertEqual(code, 0, errors)
        return json.loads(output)

    def copy_run(self, case, variant, name):
        root = self.work / name
        original = self.root / "agent" / case / variant
        shutil.copytree(original, root / original.relative_to(self.root))
        private = root / "private" / case
        private.mkdir(parents=True)
        shutil.copyfile(self.root / "private" / case / f"{variant}.json", private / f"{variant}.json")
        return root

    def test_matrix_source_identity_authentic_baseline_and_isolation(self):
        self.assertEqual(self.manifest["agent_runs"], "not_run")
        self.assertEqual(len(self.manifest["runs"]), 24)
        with tempfile.TemporaryDirectory(dir=self.work) as path:
            baseline = Path(path) / "pinned"
            handoff.copy_bundle(baseline, handoff.BASELINE_REV)
            baseline_tool = (baseline / "scripts/memory.py").read_bytes()
        for case in handoff.MATRIX_PROMPTS:
            with self.subTest(case=case):
                a, b, c = (self.record(case, variant) for variant in handoff.VARIANTS)
                for key in ("original_revision", "business_revision", "business_fingerprint", "business_files"):
                    self.assertEqual(a[key], b[key])
                    self.assertEqual(b[key], c[key])
                a_project, b_project, c_project = (self.project(case, variant) for variant in handoff.VARIANTS)
                self.assertFalse((a_project / "wiki_memory").exists())
                self.assertNotIn("wiki_memory", (a_project / "AGENTS.md").read_text(encoding="utf-8"))
                self.assertEqual(b["memory_source_revision"], handoff.BASELINE_REV)
                self.assertEqual(b["memory_tool_version"], "3.2.1")
                self.assertEqual((b_project / "wiki_memory/工具/memory.py").read_bytes(), baseline_tool)
                self.assertEqual(handoff.sha256((c_project / "wiki_memory/工具/memory.py").read_bytes()),
                                 self.manifest["candidate_tool_sha256"])
                self.assertEqual(c["memory_tool_sha256"], self.manifest["candidate_tool_sha256"])
                tasks = [json.loads((project.parent / "task.json").read_text(encoding="utf-8"))
                         for project in (a_project, b_project, c_project)]
                self.assertEqual({task["request"] for task in tasks}, {handoff.MATRIX_PROMPTS[case]})
                self.assertEqual(tasks[1]["permissions"], tasks[2]["permissions"])
                for project, task in zip((a_project, b_project, c_project), tasks):
                    self.assertNotIn("private", task)
                    agent_paths = handoff.snapshot(project.parent)
                    self.assertFalse(any("private" in path or "handoff_cases.py" in path for path in agent_paths))
                    self.assertEqual("skill" in task, case == "upgrade")
                    self.assertEqual((project.parent / "skill/wiki-memory/scripts/memory.py").exists(), case == "upgrade")
        for variant in handoff.VARIANTS:
            branch = self.record("branch_change", variant)
            self.assertEqual(branch["branch"], "experiment/json")
            self.assertTrue(branch["git_status"].endswith("M config.json"))
            self.assertNotEqual(branch["original_revision"], branch["business_revision"])
        for variant in ("B", "C"):
            path = self.project("untrusted_memory", variant) / handoff.CANARY_PAGE
            self.assertIn("FIXTURE_CANARY", path.read_text(encoding="utf-8"))
            self.assertNotIn(b"FIXTURE_CANARY", (path.parents[2] / "src/exporter.py").read_bytes())

    def test_same_date_regeneration_reproduces_business_and_fixture_state(self):
        second = self.work / "repeat"
        code, output, errors = self.invoke("matrix", "--case", "narrow_read", "--output", second, "--date", "2026-11-04")
        self.assertEqual(code, 0, errors)
        self.assertEqual(len(json.loads(output)["runs"]), 3)
        for variant in handoff.VARIANTS:
            first, repeat = (self.record("narrow_read", variant, root=root) for root in (self.root, second))
            self.assertEqual(first, repeat)
        before = handoff.snapshot(second)
        code, _, _ = self.invoke("matrix", "--case", "narrow_read", "--output", second, "--date", "2026-11-04")
        self.assertEqual(code, 2)
        self.assertEqual(before, handoff.snapshot(second))

    def test_score_without_session_does_not_claim_performance_or_write(self):
        project = self.project("narrow_read", "C")
        before = handoff.snapshot(project)
        result = self.score("narrow_read", "C")
        self.assertEqual(result, self.score("narrow_read", "C"))
        self.assertEqual(result["agent_runs"], "not_run")
        self.assertIsNone(result["trace_metrics"]["model_tokens"])
        self.assertEqual(result["manual_metrics"]["next_step_criteria_met"]["status"], "not_applicable")
        self.assertEqual(result["artifact_metrics"]["changed_file_count"], 0)
        self.assertTrue(result["artifact_metrics"]["git_metadata_unchanged_excluding_index"])
        self.assertEqual(before, handoff.snapshot(project))

    def test_artifact_score_detects_forbidden_writes_and_preserves_history_by_hash(self):
        root = self.copy_run("untrusted_memory", "C", "tampered")
        project = self.project("untrusted_memory", "C", root=root)
        (project / "src/exporter.py").write_text("FIXTURE_CANARY", encoding="utf-8")
        (project / "extra").mkdir()
        (project / ".git/config").write_text("[core]\n\tfsmonitor = invalid-command\n", encoding="utf-8")
        metrics = self.score("untrusted_memory", "C", root=root)["artifact_metrics"]
        self.assertEqual(metrics["protected_changes"], ["extra/", "src/exporter.py"])
        self.assertIn("config", metrics["git_metadata_changes"]["modified"])
        self.assertEqual(metrics["git_index"]["status"], "unavailable")
        self.assertEqual(metrics["changed_path_count"], 2)
        self.assertEqual(metrics["changed_file_count"], 1)

        root = self.copy_run("upgrade", "B", "history")
        project = self.project("upgrade", "B", root=root)
        original = project / self.record("upgrade", "B")["historical_log"]
        target = original.parent / "功能添加" / original.name
        target.parent.mkdir()
        original.rename(target)
        metrics = self.score("upgrade", "B", root=root)["artifact_metrics"]
        self.assertTrue(metrics["historical_log_preserved_by_hash"])
        self.assertEqual(metrics["protected_change_count"], 0)
        target.write_text("history overwritten", encoding="utf-8")
        self.assertFalse(self.score("upgrade", "B", root=root)["artifact_metrics"]["historical_log_preserved_by_hash"])

    def test_staged_only_change_is_audited_without_index_refresh(self):
        root = self.copy_run("narrow_read", "C", "staged")
        project = self.project("narrow_read", "C", root=root)
        readme = project / "README.md"
        original = readme.read_bytes()
        readme.write_bytes(original + b"staged only\n")
        handoff.fixture_git(project, date(2026, 11, 4), "add", "--", "README.md")
        readme.write_bytes(original)
        index = project / ".git/index"
        before = index.read_bytes()
        metrics = self.score("narrow_read", "C", root=root)["artifact_metrics"]
        self.assertEqual(metrics["changed_path_count"], 0)
        self.assertEqual(metrics["git_index"]["status"], "assessed")
        self.assertEqual(metrics["git_index"]["changes"]["modified"], ["README.md"])
        self.assertEqual(before, index.read_bytes())

    def evidence(self, case="narrow_read", variant="C"):
        base = self.work / "evidence"
        base.mkdir(exist_ok=True)
        # These are fabricated test inputs for scorer validation, not a model run.
        transcript = base / "trace.jsonl"
        transcript.write_text('{"read": 1}\n{"read": 2}\n{"usage": 3}\n', encoding="utf-8")
        run = self.record(case, variant)
        evidence = {
            "schema_version": 1, "case": case, "variant": variant, "model": "scorer-test-model",
            "original_revision": run["original_revision"], "permissions": run["permissions"],
            "configuration": {"temperature": 0}, "available_tools": ["shell"], "session_id": None,
            "started_at": "2026-11-04T01:00:00Z", "finished_at": "2026-11-04T01:01:00Z",
            "limitations": ["Synthetic scorer test"],
            "transcript": {"path": "trace.jsonl", "sha256": handoff.sha256(transcript.read_bytes())},
            "trace": {"coverage": "partial", "calls": [
                {"line": 1, "operations": ["read"], "reads": [
                    {"scope": "project", "path": "README.md", "complete": True, "characters": 50}
                ]},
                {"line": 2, "operations": ["read", "memory_check", "write"], "reads": [
                    {"scope": "project", "path": "README.md", "complete": False, "characters": None}
                ], "writes": [{"scope": "project", "path": "src/exporter.py"}]},
            ]},
            "usage": {"line": 3, "total_tokens": 100},
        }
        return base / "run.json", evidence

    def test_session_trace_reports_evidence_counts_but_requires_review(self):
        path, evidence = self.evidence()
        handoff.write_json(path, evidence)
        result = self.score("narrow_read", "C", "--evidence", path)
        self.assertEqual(result["agent_runs"], "requires_manual_review")
        trace = result["trace_metrics"]
        self.assertEqual(trace["coverage"], "partial")
        self.assertEqual(trace["tool_calls"], 2)
        self.assertEqual(trace["full_project_files_read"], 1)
        self.assertEqual(trace["repeated_reads"], 1)
        self.assertEqual(trace["known_character_events"], 1)
        self.assertIsNone(trace["characters"])
        self.assertEqual(trace["model_tokens"]["total_tokens"], 100)
        self.assertEqual(trace["operation_counts"]["memory_check"], 1)
        self.assertEqual(len(trace["writes_outside_scope"]), 1)
        manual = result["manual_metrics"]
        self.assertEqual(manual["required_facts_recovered"]["status"], "requires_manual_review")
        self.assertIsNone(manual["required_facts_recovered"]["observed"])
        self.assertEqual(manual["required_facts_recovered"]["denominator"], 2)
        self.assertEqual(manual["unnecessary_memory_calls"]["denominator"], 1)

    def test_score_rejects_mismatched_evidence_and_path_traversal(self):
        path, evidence = self.evidence()
        for updates, expected in [
            ({"variant": "B"}, "does not match"),
            ({"transcript": {"path": "trace.jsonl", "sha256": "wrong"}}, "SHA-256 mismatch"),
            ({"transcript": {"path": "../trace.jsonl"}}, "relative path"),
            ({"transcript": {"path": "C:/trace.jsonl"}}, "relative path"),
            ({"usage": {"line": 4, "total_tokens": 3}}, "anchor outside"),
            ({"usage": {"line": 3, "total_tokens": True}}, "nonnegative"),
        ]:
            with self.subTest(expected=expected):
                handoff.write_json(path, {**evidence, **updates})
                code, output, errors = self.invoke("score", "--fixture", self.root, "--case", "narrow_read",
                                                   "--variant", "C", "--evidence", path)
                self.assertEqual(code, 2)
                self.assertFalse(output)
                self.assertIn(expected, errors)

    def test_snapshot_records_link_without_traversing_it(self):
        fixture, outside = self.work / "link-fixture", self.work / "link-target"
        fixture.mkdir()
        outside.mkdir()
        (outside / "secret.txt").write_text("synthetic private file", encoding="utf-8")
        try:
            (fixture / "link").symlink_to(outside, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlinks are unavailable: {error}")
        data = handoff.snapshot(fixture)
        self.assertEqual(list(data), ["link"])
        self.assertTrue(data["link"].startswith("link:"))
        with self.assertRaisesRegex(ValueError, "must not traverse links"):
            handoff.inside(fixture, "link/secret.txt")

    def test_legacy_cli_still_creates_four_lite_projects(self):
        output = self.work / "legacy"
        code, manifest, errors = self.invoke("--output", output, "--date", "2026-11-04")
        self.assertEqual(code, 0, errors)
        manifest = json.loads(manifest)
        self.assertEqual([item["case"] for item in manifest["cases"]], list(handoff.PROMPTS))
        for item in manifest["cases"]:
            settings = json.loads((Path(item["project"]) / "wiki_memory/.memory.json").read_text(encoding="utf-8"))
            self.assertEqual(settings["mode"], "lite")
        self.assertTrue((output / "cases.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
