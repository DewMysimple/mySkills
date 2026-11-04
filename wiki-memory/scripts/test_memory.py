"""Behavioral tests; all writes stay in temporary projects."""

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
import memory


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wiki-memory-test-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name).resolve()
        self.root = self.project / "wiki_memory"
        self.today = date(2026, 10, 7)

    def run_cli(self, *args):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            code = memory.main([args[0], "--project", str(self.project), "--date", str(self.today), *args[1:]])
        return code, output.getvalue(), error.getvalue()

    def init(self, *args):
        code, _, error = self.run_cli("init", *args, "--apply")
        self.assertEqual(code, 0, error)

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.project.rglob("*") if p.is_file()}

    def add_page(self, rel, page_type="knowledge", status="active", topic="sample", body="结论。", sources=None, extra=""):
        text = memory.make_page(page_type, status, topic, Path(rel).stem, body, self.today)
        text = text.replace("sources: []", "sources: " + json.dumps(sources or [], ensure_ascii=False) + extra)
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def check(self):
        code, output, error = self.run_cli("check")
        self.assertNotEqual(code, 2, error)
        return code, json.loads(output)

    def legacy_layout(self, rel="wiki_memory"):
        """Build an old layout from a temporary fixture, without calling old code."""
        self.init()
        (self.root / memory.ENTRY).rename(self.root / memory.LEGACY_ENTRY)
        protocol = self.root / "AGENTS.md"
        protocol.write_text(memory.read_text(protocol).replace("README.md", "入口.md"), encoding="utf-8")
        data = json.loads(memory.read_text(self.root / ".memory.json"))
        data.update(schema_version=1, tool_version="2.1.0")
        data.pop("navigation")
        (self.root / ".memory.json").write_text(json.dumps(data), encoding="utf-8")
        target = self.project / rel
        if target != self.root:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.root.rename(target)
        agents = self.project / "AGENTS.md"
        agents.write_text(memory.read_text(agents).replace("wiki_memory/AGENTS.md", rel + "/AGENTS.md")
                          .replace("wiki_memory/README.md", rel + "/入口.md"), encoding="utf-8")
        return target

    def populate_states(self, mode="lite"):
        for title in memory.STATE_TITLES[mode]:
            path = self.root / "当前状态" / (title + ".md")
            text = memory.read_text(path).replace("status: proposed", "status: active")
            text = text.replace("sources: []", 'sources: ["AGENTS.md"]')
            text = text.replace("> 初始化结构，尚未核实项目事实；填写证据后改为 active。", "临时测试项目的已核实状态。")
            for heading in memory.STATE_SECTIONS[title]:
                text = text.replace("- " + memory.STATE_PROMPTS[heading], "- 已核实的临时项目事实；验证范围仅此测试项目。")
            path.write_text(text, encoding="utf-8")

    def test_preview_is_read_only(self):
        (self.project / "AGENTS.md").write_bytes(b"User rules\r\n")
        before = self.snapshot()
        code, output, error = self.run_cli("init")
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertFalse(report["apply"])
        self.assertEqual(report["mode"], "lite")
        self.assertEqual(report["link_style"], "markdown")
        self.assertEqual(report["blockers"], [])
        self.assertEqual([entry["path"] for entry in report["changes"]], report["files"])
        actions = {entry["path"]: entry["action"] for entry in report["changes"]}
        self.assertEqual(actions["AGENTS.md"], "append")
        self.assertEqual(actions["wiki_memory/README.md"], "create")
        self.assertEqual(before, self.snapshot())

    def test_init_preview_reports_existing_lock_without_writes(self):
        (self.project / ".wiki-memory.lock").write_text("External writer\n", encoding="utf-8")
        before = self.snapshot()
        code, output, error = self.run_cli("init", "--mode", "standard", "--link-style", "wiki")
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertEqual((report["mode"], report["link_style"]), ("standard", "wiki"))
        self.assertIn(".wiki-memory.lock", report["blockers"][0])
        self.assertIn({"path": "AGENTS.md", "action": "create"}, report["changes"])
        self.assertEqual(before, self.snapshot())

    def test_lite_standalone_copied_tool(self):
        self.init()
        self.assertEqual(len(list((self.root / "当前状态").glob("*.md"))), 1)
        self.assertFalse((self.root / "知识").exists())
        self.assertFalse((self.root / "决策").exists())
        result = subprocess.run([sys.executable, "-B", str(self.root / "工具/memory.py"), "check", "--project", str(self.project), "--date", str(self.today)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["errors"], [])

    def test_standard_mode(self):
        self.init("--mode", "standard")
        self.assertEqual(len(list((self.root / "当前状态").glob("*.md"))), 5)
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertEqual(report["pages"], 8)
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("no active current state" in x for x in report["warnings"]))

    def test_standard_init_previews_and_creates_trackable_log_directories(self):
        before = self.snapshot()
        code, output, error = self.run_cli("init", "--mode", "standard")
        self.assertEqual(code, 0, error)
        files = json.loads(output)["files"]
        for folder in memory.LOG_CATEGORIES.values():
            self.assertIn(f"wiki_memory/日志/{folder}/.gitkeep", files)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.root.exists())
        self.init("--mode", "standard")
        self.assertEqual(json.loads(memory.read_text(self.root / ".memory.json"))["tool_version"], memory.VERSION)
        for folder in memory.LOG_CATEGORIES.values():
            self.assertEqual((self.root / "日志" / folder / ".gitkeep").read_bytes(), b"")
        self.assertEqual(list((self.root / "日志").rglob("MOC*.md")), [self.root / memory.LOG_INDEX])

    def test_standard_empty_log_directories_survive_git_tracking(self):
        if not shutil.which("git"):
            self.skipTest("Git unavailable")
        self.init("--mode", "standard")
        for args in (("init", "--quiet"), ("add", "--", "wiki_memory/日志")):
            result = subprocess.run(["git", "-C", str(self.project), *args], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(["git", "-C", str(self.project), "ls-files", "-z"], capture_output=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0, result.stderr)
        tracked = set(result.stdout.split("\0"))
        for folder in memory.LOG_CATEGORIES.values():
            self.assertIn(f"wiki_memory/日志/{folder}/.gitkeep", tracked)

    def test_lite_allows_flat_logs_without_kind_or_category_directories(self):
        self.init()
        self.populate_states()
        log = self.add_page("日志/flat.md", "log", "archived")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 0)
        self.assertEqual(set((self.root / "日志").iterdir()), {self.root / memory.LOG_INDEX, log})

    def test_standard_category_logs_feed_one_recursive_moc_and_resolve_links(self):
        self.init("--mode", "standard")
        self.populate_states("standard")
        paths = []
        for kind, folder in memory.LOG_CATEGORIES.items():
            paths.append(self.add_page(f"日志/{folder}/2026-10-07-{kind}.md", "log", "archived", topic=f"log-{kind}",
                                       extra=f"\nkind: {kind}\ntask_status: completed"))
        nested = self.add_page("日志/功能添加/子任务/配置#%20.MD", "log", "archived", topic="nested-log",
                               body="[相关功能](../2026-10-07-feature.md)。", extra="\nkind: feature\ntask_status: completed")
        paths.append(nested)
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        code, report = self.run_cli("check", "--require-ready")[:2]
        self.assertEqual(code, 0, report)
        pages = memory.load_pages(self.root)
        moc = next(p for p in pages if p.path == memory.LOG_INDEX)
        resolved = {memory.resolve_target(kind, target, moc, self.project, self.root, pages)
                    for kind, target in memory.links(moc.body)}
        self.assertEqual(resolved, set(paths))
        self.assertIn("%23%2520.MD", moc.body)
        self.assertEqual(list((self.root / "日志").rglob("MOC*.md")), [self.root / memory.LOG_INDEX])
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(before, self.snapshot())

    def test_standard_missing_category_blocks_checks_and_index_without_repair(self):
        self.init("--mode", "standard")
        self.populate_states("standard")
        directory = self.root / "日志/测试验证"
        (directory / ".gitkeep").unlink()
        directory.rmdir()
        before = self.snapshot()
        self.assertTrue(any("日志/测试验证" in x and "directory missing" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 1)
        code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2, error)
        self.assertIn("migrate", error)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(directory.exists())

    def test_standard_flat_log_cannot_be_indexed_or_pass_delivery(self):
        self.init("--mode", "standard")
        self.populate_states("standard")
        log = self.add_page("日志/flat.md", "log", "archived", extra="\nkind: maintenance")
        before = self.snapshot()
        self.assertTrue(any("requires 日志/工程维护/" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 1)
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(log.exists())

    def test_standard_logs_require_valid_kind_and_matching_directory(self):
        self.init("--mode", "standard")
        for kind in (None, "unknown", "bug", ["feature"]):
            with self.subTest(kind=kind):
                extra = "" if kind is None else "\nkind: " + json.dumps(kind)
                log = self.add_page("日志/功能添加/mismatch.md", "log", "archived", extra=extra)
                errors = self.check()[1]["errors"]
                phrase = "requires 日志/Bug处理/" if kind == "bug" else "requires a valid kind"
                self.assertTrue(any(phrase in x for x in errors), errors)
                before = self.snapshot()
                self.assertEqual(self.run_cli("index", "--apply")[0], 2)
                self.assertEqual(before, self.snapshot())
                log.unlink()

    def test_standard_log_outside_log_section_is_rejected(self):
        self.init("--mode", "standard")
        self.add_page("root-log.md", "log", "archived", extra="\nkind: test")
        self.assertTrue(any("root-log.md" in x and "requires 日志/测试验证/" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)

    def test_old_standard_flat_layout_is_read_only_compatible_but_not_deliverable(self):
        self.init("--mode", "standard")
        self.populate_states("standard")
        self.add_page("日志/old.md", "log", "archived", extra="\nkind: maintenance")
        # Fixture of an already-generated 3.0.0 flat layout, not a migration.
        pages = memory.load_pages(self.root)
        for path, generated in memory.index_contents(pages).items():
            target = self.root / path
            target.write_text(memory.replace_auto(memory.read_text(target), generated, path), encoding="utf-8")
        for folder in memory.LOG_CATEGORIES.values():
            directory = self.root / "日志" / folder
            (directory / ".gitkeep").unlink()
            directory.rmdir()
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        for version in ("3.0.0", "2.1.0", None):
            with self.subTest(version=version):
                if version is None:
                    data.pop("tool_version", None)
                else:
                    data["tool_version"] = version
                config.write_text(json.dumps(data), encoding="utf-8")
                before = self.snapshot()
                code, report = self.check()
                self.assertEqual(code, 0, report)
                self.assertTrue(any("legacy standard log layout" in x for x in report["warnings"]))
                self.assertEqual(self.run_cli("check", "--require-ready")[0], 1)
                self.assertEqual(self.run_cli("index", "--apply")[0], 2)
                self.assertEqual(before, self.snapshot())

    def test_legacy_schema_standard_log_layout_warns_without_changing_history(self):
        self.init("--mode", "standard")
        (self.root / memory.ENTRY).rename(self.root / memory.LEGACY_ENTRY)
        protocol = self.root / "AGENTS.md"
        protocol.write_text(memory.read_text(protocol).replace("README.md", "入口.md"), encoding="utf-8")
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        data.update(schema_version=1, tool_version="2.1.0")
        data.pop("navigation")
        config.write_text(json.dumps(data), encoding="utf-8")
        agents = self.project / "AGENTS.md"
        agents.write_text(memory.read_text(agents).replace("wiki_memory/README.md", "wiki_memory/入口.md"), encoding="utf-8")
        directory = self.root / "日志/Bug处理"
        (directory / ".gitkeep").unlink()
        directory.rmdir()
        before = self.snapshot()
        code, report = self.check()
        self.assertEqual(code, 0, report)
        self.assertTrue(any("legacy standard log layout" in x for x in report["warnings"]))
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 1)
        self.assertEqual(before, self.snapshot())

    def test_standard_category_symlink_escape_is_read_only_and_blocks_index(self):
        self.init("--mode", "standard")
        directory = self.root / "日志/工程维护"
        (directory / ".gitkeep").unlink()
        directory.rmdir()
        with tempfile.TemporaryDirectory(prefix="wiki-memory-external-category-") as outside:
            external = Path(outside)
            sentinel = external / "sentinel.txt"
            sentinel.write_bytes(b"external original\n")
            try:
                directory.symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks unavailable")
            before = self.snapshot()
            code, report = self.check()
            self.assertEqual(code, 1, report)
            self.assertTrue(any("symlinked" in x for x in report["errors"]))
            self.assertEqual(self.run_cli("index", "--apply")[0], 2)
            self.assertEqual(before, self.snapshot())
            self.assertEqual(list(external.iterdir()), [sentinel])
            self.assertEqual(sentinel.read_bytes(), b"external original\n")
            escaped = external / "outside.md"
            escaped.write_bytes(b"# External page\n")
            before = self.snapshot()
            code, report = self.check()
            self.assertEqual(code, 1, report)
            self.assertTrue(any("symlinked" in x for x in report["errors"]))
            self.assertEqual(self.run_cli("index", "--apply")[0], 2)
            self.assertEqual(before, self.snapshot())
            self.assertEqual(escaped.read_bytes(), b"# External page\n")

    def test_standard_init_rolls_back_log_placeholders_after_late_failure(self):
        agents = self.project / "AGENTS.md"
        agents.write_bytes(b"Original project rules\n")
        before = self.snapshot()
        original = memory.atomic_write

        def fail(path, data, **kwargs):
            if path.name == ".memory.json":
                self.assertTrue(all((self.root / "日志" / folder / ".gitkeep").exists()
                                    for folder in memory.LOG_CATEGORIES.values()))
                raise OSError("simulated failure after category creation")
            return original(path, data, **kwargs)

        with mock.patch.object(memory, "atomic_write", side_effect=fail):
            self.assertEqual(self.run_cli("init", "--mode", "standard", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.root.exists())
        self.assertFalse((self.project / ".wiki-memory.lock").exists())

    def test_index_detects_standard_category_deleted_after_validation(self):
        self.init("--mode", "standard")
        self.add_page("知识/new.md")
        directory = self.root / "日志/测试验证"
        original = memory.index_contents
        before_entry = (self.root / memory.ENTRY).read_bytes()

        def remove_category(pages, link_style):
            (directory / ".gitkeep").unlink()
            directory.rmdir()
            return original(pages, link_style)

        with mock.patch.object(memory, "index_contents", side_effect=remove_category):
            code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2, error)
        self.assertIn("directory changed while generating indexes", error)
        self.assertEqual((self.root / memory.ENTRY).read_bytes(), before_entry)
        self.assertFalse((self.root / "知识/MOC_知识.md").exists())
        self.assertFalse(directory.exists())

    def test_preserves_agents_bytes_and_uses_nonempty_override(self):
        original = b"\xef\xbb\xbf# Rules\r\n\r\nKeep this.\r\n"
        agents = self.project / "AGENTS.md"
        agents.write_bytes(original)
        override = self.project / "AGENTS.override.md"
        override.write_bytes(original + b"Override\r\n")
        self.init()
        self.assertEqual(agents.read_bytes(), original)
        self.assertTrue(override.read_bytes().startswith(original + b"Override\r\n"))
        self.assertEqual(override.read_bytes().count(memory.HOOK_START.encode()), 1)
        self.assertFalse(any("root instructions" in x for x in self.check()[1]["warnings"]))

    def test_empty_override_falls_back(self):
        override = self.project / "AGENTS.override.md"
        override.write_bytes(b"\r\n")
        self.init()
        self.assertEqual(override.read_bytes(), b"\r\n")
        self.assertIn(memory.HOOK_START, memory.read_text(self.project / "AGENTS.md"))

    def test_non_utf8_root_rules_are_not_mixed_with_utf8(self):
        (self.project / "AGENTS.md").write_bytes("# 项目规则\n保持接口兼容。\n".encode("gbk"))
        before = self.snapshot()
        code, _, error = self.run_cli("init", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("not UTF-8", error)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(self.root.exists())

    def test_init_refuses_existing_memory_or_hook_without_writes(self):
        self.init()
        before = self.snapshot()
        for args in ((), ("--memory-dir", "another-memory")):
            code, _, _ = self.run_cli("init", *args, "--apply")
            self.assertEqual(code, 2)
            self.assertEqual(before, self.snapshot())

    def test_new_memory_must_live_at_project_root(self):
        for rel in ("docs/wiki_memory", "docs/工程 记忆", "another-memory"):
            for apply in ((), ("--apply",)):
                with self.subTest(rel=rel, apply=apply):
                    before = self.snapshot()
                    code, _, error = self.run_cli("init", "--memory-dir", rel, *apply)
                    self.assertEqual(code, 2)
                    self.assertIn("must be <project>/wiki_memory", error)
                    self.assertEqual(before, self.snapshot())

    def test_new_navigation_uses_only_readme_and_updated_root_hook(self):
        self.init()
        self.assertTrue((self.root / "README.md").is_file())
        self.assertFalse((self.root / "入口.md").exists())
        data = json.loads(memory.read_text(self.root / ".memory.json"))
        self.assertEqual(data["schema_version"], 2)
        self.assertEqual(data["navigation"], "README.md")
        self.assertEqual(data["link_style"], "markdown")
        self.assertIn("[当前状态](当前状态/当前状态.md)", memory.read_text(self.root / "README.md"))
        agents = memory.read_text(self.project / "AGENTS.md")
        self.assertIn("wiki_memory/README.md", agents)
        self.assertNotIn("wiki_memory/入口.md", agents)

    def test_legacy_nested_memory_remains_read_only_checkable(self):
        self.legacy_layout("docs/工程 记忆")
        before = self.snapshot()
        code, output, error = self.run_cli("check", "--memory-dir", "docs/工程 记忆")
        self.assertEqual(code, 0, error)
        report = json.loads(output)
        self.assertFalse(any("root instructions" in x for x in report["warnings"]))
        self.assertTrue(any("legacy memory location" in x for x in report["warnings"]))
        self.assertTrue(any("legacy schema_version 1" in x for x in report["warnings"]))
        for apply in ((), ("--apply",)):
            code, _, error = self.run_cli("index", "--memory-dir", "docs/工程 记忆", *apply)
            self.assertEqual(code, 2)
            self.assertIn("migrate", error)
        self.assertEqual(before, self.snapshot())

    def test_legacy_schema_cannot_create_competing_readme(self):
        self.legacy_layout()
        before = self.snapshot()
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 1)
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertFalse((self.root / "README.md").exists())
        self.assertEqual(before, self.snapshot())

    def test_legacy_entry_keeps_priority_over_human_readme(self):
        target = self.legacy_layout()
        (target / "README.md").write_text("# 旧版人类说明\n\n具体导航由旧入口提供。\n", encoding="utf-8")
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertFalse(any("unreachable" in x for x in report["warnings"]))

    def test_schema_two_still_cannot_index_a_nested_location(self):
        self.init()
        nested = self.project / "docs/wiki_memory"
        nested.parent.mkdir()
        self.root.rename(nested)
        before = self.snapshot()
        code, _, error = self.run_cli("index", "--memory-dir", "docs/wiki_memory", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("migrate", error)
        self.assertEqual(before, self.snapshot())

    def test_schema_two_requires_readme_navigation_and_no_legacy_entry(self):
        self.init()
        config = self.root / ".memory.json"
        original = config.read_bytes()
        data = json.loads(original)
        data["navigation"] = "入口.md"
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.check()[0], 1)
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        config.write_bytes(original)
        (self.root / "入口.md").write_bytes((self.root / "README.md").read_bytes())
        before = self.snapshot()
        self.assertTrue(any("legacy 入口.md remains" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_ready_gate_rejects_scaffold_then_accepts_populated_state(self):
        for mode in ("lite", "standard"):
            with self.subTest(mode=mode):
                if self.root.exists():
                    # Each mode uses its own project; avoid deleting a live tree.
                    self.project = self.project / "next-project"
                    self.project.mkdir()
                    self.root = self.project / "wiki_memory"
                self.init("--mode", mode)
                before = self.snapshot()
                code, output, _ = self.run_cli("check", "--require-ready")
                self.assertEqual(code, 1)
                self.assertTrue(any("not active" in x for x in json.loads(output)["errors"]))
                self.assertEqual(before, self.snapshot())
                self.populate_states(mode)
                code, output, error = self.run_cli("check", "--require-ready")
                self.assertEqual(code, 0, error + output)

    def test_ready_gate_requires_evidence_sections_and_real_content(self):
        self.init("--mode", "standard")
        self.populate_states("standard")
        overview = self.root / "当前状态/项目概览.md"
        original = memory.read_text(overview).replace("\r\n", "\n")
        variants = (
            (original.replace('sources: ["AGENTS.md"]', "sources: []"), "no evidence references"),
            (original.replace("## 工作区背景", "## 其他说明"), "required section missing"),
            (original.replace("status: active", "status: proposed"), "not active"),
            (original.replace("## 核心入口\n\n- 已核实的临时项目事实；验证范围仅此测试项目。", "## 核心入口\n\n- " + memory.STATE_PROMPTS["核心入口"]), "still scaffold"),
        )
        for text, message in variants:
            with self.subTest(message=message):
                overview.write_text(text, encoding="utf-8")
                before = self.snapshot()
                code, output, _ = self.run_cli("check", "--require-ready")
                self.assertEqual(code, 1)
                self.assertTrue(any(message in x for x in json.loads(output)["errors"]))
                self.assertEqual(before, self.snapshot())

    def test_ready_gate_accepts_valid_source_log_evidence(self):
        self.init()
        self.populate_states()
        self.add_page("日志/evidence.md", "log", "archived", sources=["AGENTS.md"])
        state = self.root / "当前状态/当前状态.md"
        state.write_text(memory.read_text(state).replace('sources: ["AGENTS.md"]', 'sources: []\nsource_logs: ["日志/evidence.md"]'), encoding="utf-8")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 0)

    def test_ready_gate_is_only_a_check_option(self):
        self.assertEqual(self.run_cli("init", "--require-ready", "--apply")[0], 2)
        self.assertFalse(self.root.exists())

    def test_ready_sections_accept_code_content_but_ignore_headings_in_examples(self):
        self.init()
        self.populate_states()
        state = self.root / "当前状态/当前状态.md"
        original = memory.read_text(state).replace("\r\n", "\n")
        text = original.replace(
            "## 关键入口与运行命令\n\n- 已核实的临时项目事实；验证范围仅此测试项目。",
            "## 关键入口与运行命令\n\n```text\npython -B main.py\n```",
        )
        state.write_text(text, encoding="utf-8")
        self.assertEqual(self.run_cli("check", "--require-ready")[0], 0)
        # An example heading cannot fill in for a missing real state section.
        state.write_text(text.replace("## 约束与已确认选择", "## 其他事项") +
                         "\n```md\n## 约束与已确认选择\n示例约束\n```\n", encoding="utf-8")
        code, output, _ = self.run_cli("check", "--require-ready")
        self.assertEqual(code, 1)
        self.assertTrue(any("required section missing: 约束与已确认选择" in x for x in json.loads(output)["errors"]))

    def test_unmarked_legacy_memory_refuses_competing_initialization(self):
        legacy = self.project / "docs/wiki_memory"
        (legacy / "当前状态").mkdir(parents=True)
        (legacy / "AGENTS.md").write_text("Existing memory protocol\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("Read `docs/wiki_memory/AGENTS.md`.\n", encoding="utf-8")
        before = self.snapshot()
        for args in ((), ("--apply",)):
            code, _, error = self.run_cli("init", *args)
            self.assertEqual(code, 2)
            self.assertIn("existing memory found at docs/wiki_memory", error)
            self.assertEqual(before, self.snapshot())

    def test_custom_legacy_path_with_spaces_is_discovered(self):
        legacy = self.project / "notes/工程 记忆"
        (legacy / "当前状态").mkdir(parents=True)
        (legacy / "AGENTS.md").write_text("Existing protocol\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("Read [memory](notes/工程%20记忆/AGENTS.md).\n", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(self.run_cli("init", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_conventional_memory_is_discovered_without_root_hook(self):
        (self.root / "当前状态").mkdir(parents=True)
        (self.root / "AGENTS.md").write_text("Existing protocol\n", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(self.run_cli("init", "--memory-dir", "docs/wiki_memory", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_legacy_memory_referenced_by_readme_is_discovered(self):
        legacy = self.project / "notes/project-memory"
        (legacy / "当前状态").mkdir(parents=True)
        (legacy / "AGENTS.md").write_text("Existing protocol\n", encoding="utf-8")
        (legacy / "README.md").write_text("Existing entry\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("Read [memory](notes/project-memory/README.md).\n", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(self.run_cli("init", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_literal_percent_in_legacy_path_is_not_url_decoded(self):
        legacy = self.project / "notes/memory%20literal"
        (legacy / "当前状态").mkdir(parents=True)
        (legacy / "AGENTS.md").write_text("Existing protocol\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text("Read `notes/memory%20literal/AGENTS.md`.\n", encoding="utf-8")
        before = self.snapshot()
        self.assertEqual(self.run_cli("init", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_ordinary_nested_rules_and_external_links_do_not_block_init(self):
        (self.project / "src").mkdir()
        (self.project / "src/AGENTS.md").write_text("Source rules\n", encoding="utf-8")
        (self.project / "AGENTS.md").write_text('Read `src/AGENTS.md`, [docs](https://example.com/docs), and `a < b`.\n', encoding="utf-8")
        self.init()

    def test_similar_but_wrong_memory_hook_is_reported(self):
        self.init()
        agents = self.project / "AGENTS.md"
        agents.write_text(memory.read_text(agents).replace("wiki_memory/AGENTS.md", "docs/wiki_memory/AGENTS.md")
                          .replace("wiki_memory/README.md", "docs/wiki_memory/README.md"), encoding="utf-8")
        self.assertTrue(any("lack memory hook" in x for x in self.check()[1]["warnings"]))

    def test_dot_relative_memory_hook_is_recognized(self):
        self.init()
        agents = self.project / "AGENTS.md"
        agents.write_text(memory.read_text(agents).replace("wiki_memory/AGENTS.md", "./wiki_memory/AGENTS.md")
                          .replace("wiki_memory/README.md", "./wiki_memory/README.md"), encoding="utf-8")
        self.assertFalse(any("lack memory hook" in x for x in self.check()[1]["warnings"]))

    def test_unsafe_memory_paths_do_not_write(self):
        for path in ("..", "../escape", ".", "C:/outside", "/absolute", "wiki_memory/../../escape", "bad`name"):
            with self.subTest(path=path):
                code, _, _ = self.run_cli("init", "--memory-dir", path, "--apply")
                self.assertEqual(code, 2)
                self.assertEqual(self.snapshot(), {})

    def test_root_concurrent_edit_is_preserved(self):
        plan, agents, previous = memory.initialize(self.project, self.root, "lite", self.today)
        agents.write_bytes(b"User concurrently added rules\n")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            memory.apply_plan(plan, self.project, True, agents, previous)
        self.assertEqual(agents.read_bytes(), b"User concurrently added rules\n")
        self.assertFalse(self.root.exists())

    def test_source_paths_and_relative_links_normalize_correctly(self):
        self.init()
        source = self.project / "src" / "main.py"
        source.parent.mkdir()
        source.write_text("print('hello')\n", encoding="utf-8")
        self.add_page("知识/module.md", sources=["src/main.py"], body="[代码](../../src/main.py)；[状态](../当前状态/当前状态.md)。")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])

    def test_metadata_sources_are_checked(self):
        self.init()
        self.add_page("知识/bad.md", sources=["src/missing.ts"])
        self.add_page("决策/ADR-001-test.md", "decision", sources=["用户指令：2026-10-07 明确选择"], extra='\nsupersedes: "[[决策/missing]]"')
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(any("src/missing.ts" in x for x in report["errors"]))
        self.assertTrue(any("决策/missing" in x for x in report["errors"]))

    def test_index_preview_then_refresh_preserves_history_and_human_regions(self):
        self.init()
        log = self.add_page("日志/2026-10-07-fix.md", "log", "archived", body="A correction.\n", extra="\nkind: bug\ntask_status: blocked")
        original_log = log.read_bytes()
        entry = self.root / memory.ENTRY
        original = entry.read_bytes()
        entry.write_bytes(b"\xef\xbb\xbf" + original + "\r\n人工说明：保留。\r\n".encode("utf-8"))
        before = self.snapshot()
        self.assertTrue(any("missing from log MOC" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("index")[0], 0)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertTrue(entry.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertTrue(entry.read_bytes().endswith("\r\n人工说明：保留。\r\n".encode("utf-8")))
        self.assertEqual(log.read_bytes(), original_log)
        self.assertEqual(self.check()[1]["errors"], [])
        refreshed = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(refreshed, self.snapshot())

    def test_legacy_unmarked_index_refuses_all_writes(self):
        self.init()
        entry = self.root / memory.ENTRY
        entry.write_text(memory.read_text(entry).replace(memory.AUTO_START, ""), encoding="utf-8")
        self.add_page("日志/new.md", "log", "archived")
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_managed_navigation_damage_is_reported_by_check(self):
        self.init()
        entry = self.root / memory.ENTRY
        original = memory.read_text(entry)
        variants = [original.replace(memory.AUTO_START, ""), original + memory.AUTO_END,
                    original.replace(memory.AUTO_START, "TEMP").replace(memory.AUTO_END, memory.AUTO_START).replace("TEMP", memory.AUTO_END)]
        for text in variants:
            with self.subTest(text=text[-100:]):
                entry.write_text(text, encoding="utf-8")
                before = self.snapshot()
                self.assertTrue(any("invalid auto region" in x for x in self.check()[1]["errors"]))
                self.assertEqual(self.run_cli("index", "--apply")[0], 2)
                self.assertEqual(before, self.snapshot())

    def test_legacy_pages_without_config_need_no_auto_markers(self):
        self.init()
        (self.root / ".memory.json").unlink()
        for rel in (memory.ENTRY, memory.LOG_INDEX):
            path = self.root / rel
            path.write_text(memory.read_text(path).replace(memory.AUTO_START, "").replace(memory.AUTO_END, ""), encoding="utf-8")
        self.assertEqual(self.check()[1]["errors"], [])

    def test_managed_navigation_must_remain_an_active_moc(self):
        self.init()
        entry = self.root / memory.ENTRY
        entry.write_text(memory.read_text(entry).replace("type: moc", "type: knowledge"), encoding="utf-8")
        before = self.snapshot()
        self.assertTrue(any("navigation must be an active MOC" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_log_table_has_four_cells_and_resolvable_markdown_links(self):
        self.init()
        log = self.add_page("日志/2026-10-07-问题#%.md", "log", "archived", extra="\nkind: bug\ntask_status: completed")
        log.write_text(memory.read_text(log).replace("# 2026-10-07-问题#%", r"# 修复 \| [renderer]"), encoding="utf-8")
        original = log.read_bytes()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        table = memory.read_text(self.root / memory.LOG_INDEX)
        row = next(line for line in table.splitlines() if line.startswith("| 2026-10-07"))
        self.assertEqual(len(re.split(r"(?<!\\)\|", row)) - 2, 4)
        pages = memory.load_pages(self.root)
        source = next(p for p in pages if p.path == memory.LOG_INDEX)
        targets = [memory.resolve_target(kind, target, source, self.project, self.root, pages) for kind, target in memory.links(row)]
        self.assertEqual(targets, [log])
        self.assertEqual(self.check()[1]["errors"], [])
        self.assertEqual(log.read_bytes(), original)

    def test_moc_defaults_apply_to_new_indexes_and_preserve_existing_metadata(self):
        self.init()
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        data["moc_defaults"] = {"kind": "process", "importance": "high"}
        config.write_text(json.dumps(data), encoding="utf-8")
        entry = self.root / memory.ENTRY
        entry.write_text(memory.read_text(entry).replace("type: moc", "type: moc\nkind: ui") + "\nKeep my manual note.\n", encoding="utf-8")
        manual_tail = entry.read_bytes().split(memory.AUTO_END.encode(), 1)[1]
        self.add_page("知识/new.md")
        self.add_page("当前状态/history.md", "state", "superseded", topic="old-state")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        for page_type in ("knowledge", "state"):
            path = memory.CATALOGS[page_type][0]
            page = memory.parse_page(path, memory.read_text(self.root / path))
            self.assertEqual(page.fields["kind"], "process")
            self.assertEqual(page.fields["importance"], "high")
        self.assertIn("kind: ui", memory.read_text(entry))
        self.assertTrue(entry.read_bytes().endswith(manual_tail))
        self.assertEqual(self.check()[1]["errors"], [])

    def test_invalid_moc_defaults_cannot_write_indexes(self):
        self.init()
        self.add_page("知识/new.md")
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        for defaults in ([], None, {"type": "knowledge"}, {"kind": ""}, {"importance": ["high"]}):
            with self.subTest(defaults=defaults):
                data["moc_defaults"] = defaults
                config.write_text(json.dumps(data), encoding="utf-8")
                before = self.snapshot()
                self.assertTrue(any("moc_defaults" in x for x in self.check()[1]["errors"]))
                self.assertEqual(self.run_cli("index", "--apply")[0], 2)
                self.assertEqual(before, self.snapshot())

    def test_active_topics_and_padded_adr_numbers(self):
        self.init()
        self.add_page("决策/ADR-001-first.md", "decision", topic="storage")
        self.add_page("决策/ADR-1-second.md", "decision", topic="storage")
        self.add_page("决策/ADR-002-proposal.md", "decision", "proposed", "storage")
        errors = self.check()[1]["errors"]
        self.assertTrue(any("multiple active" in x for x in errors))
        self.assertTrue(any("duplicate ADR-1" in x for x in errors))
        self.assertFalse(any("ADR-002" in x for x in errors if "multiple active" in x))

    def test_invalid_frontmatter_reports_without_crash(self):
        self.init()
        path = self.add_page("知识/bad.md")
        path.write_text(memory.read_text(path).replace("type: knowledge", 'type: ["knowledge"]').replace("sources: []", "sources: |\n  complex YAML"), encoding="utf-8")
        self.assertEqual(self.check()[0], 1)
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)

    def test_code_examples_ignored_but_links_cannot_escape_project(self):
        self.init()
        self.add_page("知识/examples.md", body="```md\n[[not-real]]\n```\n`[[also-not-real]]`\n[escape](../../../outside.md)")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        errors = self.check()[1]["errors"]
        self.assertEqual(len(errors), 1)
        self.assertIn("escapes project", errors[0])

    def test_check_rejects_apply_and_is_read_only(self):
        self.init()
        before = self.snapshot()
        self.assertEqual(self.run_cli("check", "--apply")[0], 2)
        self.check()
        self.assertEqual(before, self.snapshot())

    def test_empty_memory_does_not_pass(self):
        self.root.mkdir()
        self.assertEqual(self.check()[0], 1)

    def test_ambiguous_wiki_links_and_metadata_block_lists(self):
        self.init()
        self.add_page("知识/a/same.md", topic="a")
        self.add_page("知识/b/same.md", topic="b")
        log = self.add_page("日志/source.md", "log", "archived")
        self.add_page("知识/consumer.md", topic="consumer", body="[[same]]", extra='\nsource_logs:\n  - "[[日志/source]]"')
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        errors = self.check()[1]["errors"]
        self.assertEqual(len(errors), 1)
        self.assertIn("ambiguous wiki link", errors[0])
        self.assertTrue(log.exists())

    def test_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="wiki-memory-outside-") as outside:
            external = Path(outside)
            link = self.project / "linked-memory"
            try:
                link.symlink_to(external, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks unavailable")
            self.assertEqual(self.run_cli("init", "--memory-dir", "linked-memory/new", "--apply")[0], 2)
            self.assertEqual(list(external.iterdir()), [])

    def test_root_instruction_symlink_escape_never_reads_target(self):
        with tempfile.TemporaryDirectory(prefix="wiki-memory-root-rules-") as outside:
            external = Path(outside).resolve() / "external.md"
            external.write_bytes(b"Private instructions\n")
            override = self.project / "AGENTS.override.md"
            try:
                override.symlink_to(external)
            except OSError:
                self.skipTest("file symlinks unavailable")
            original_read = Path.read_bytes

            def guarded_read(path):
                self.assertNotIn(path, {override, external})
                return original_read(path)

            with mock.patch.object(Path, "read_bytes", guarded_read):
                code, _, error = self.run_cli("init", "--apply")
                self.assertEqual(code, 2)
                self.assertIn("read target escapes", error)
            self.assertFalse(self.root.exists())
            override.unlink()
            self.init()
            override.symlink_to(external)
            before = self.snapshot()
            with mock.patch.object(Path, "read_bytes", guarded_read):
                code, report = self.check()
                self.assertEqual(code, 1)
                self.assertTrue(any("root instructions: read target escapes" in error for error in report["errors"]))
                self.assertEqual(self.run_cli("index", "--apply")[0], 2)
            self.assertEqual(before, self.snapshot())
            self.assertEqual(external.read_bytes(), b"Private instructions\n")

    def test_escaping_memory_config_is_not_read_by_any_legacy_command(self):
        self.init()
        config = self.root / ".memory.json"
        original = config.read_bytes()
        with tempfile.TemporaryDirectory(prefix="wiki-memory-config-") as outside:
            external = Path(outside).resolve() / "external.json"
            external.write_bytes(original)
            config.unlink()
            try:
                config.symlink_to(external)
            except OSError:
                self.skipTest("file symlinks unavailable")
            before = self.snapshot()
            original_read = Path.read_bytes

            def guarded_read(path):
                self.assertNotIn(path, {config, external})
                return original_read(path)

            with mock.patch.object(Path, "read_bytes", guarded_read):
                code, report = self.check()
                self.assertEqual(code, 1)
                self.assertTrue(any("read target escapes" in error for error in report["errors"]))
                code, output, _ = self.run_cli("plan-migration")
                self.assertEqual(code, 1)
                self.assertTrue(any("read target escapes" in blocker for blocker in json.loads(output)["blockers"]))
                self.assertEqual(self.run_cli("index")[0], 2)
                self.assertEqual(self.run_cli("index", "--apply")[0], 2)
            self.assertEqual(before, self.snapshot())
            self.assertEqual(external.read_bytes(), original)

    def test_memory_and_migration_scans_skip_hidden_and_dependency_content(self):
        self.init()
        excluded = [
            self.project / ".private.md",
            self.project / "build/private.md",
            self.root / "知识/.private.md",
            self.root / "知识/.private/private.md",
        ]
        for path in excluded:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"Do not inspect this content.\n")
        topic = self.add_page("知识/运维/env/运行环境.md")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        catalog = self.root / memory.CATALOGS["knowledge"][0]
        self.assertIn(f"(运维/env/{topic.name})", memory.read_text(catalog))
        before = self.snapshot()
        original_read = Path.read_bytes

        def guarded_read(path):
            self.assertNotIn(path, excluded)
            return original_read(path)

        with mock.patch.object(Path, "read_bytes", guarded_read):
            self.assertEqual(self.check()[0], 0)
            code, _, error = self.run_cli("plan-migration")
            self.assertEqual(code, 0, error)
        self.assertEqual(before, self.snapshot())

    def test_old_dates_prompt_review_without_invalidating_facts(self):
        self.init()
        self.add_page("知识/old.md", extra="", body="当前实现仍需检查。")
        path = self.root / "知识/old.md"
        path.write_text(memory.read_text(path).replace("2026-10-07", "2020-01-01"), encoding="utf-8")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        code, report = self.check()
        self.assertEqual(code, 0)
        self.assertTrue(any("old edit date" in x for x in report["warnings"]))

    def test_old_source_can_disappear_without_rewriting_history(self):
        self.init()
        log = self.add_page("日志/history.md", "log", "archived", sources=["src/removed.py"], extra="\nkind: bug\ntask_status: completed")
        original = log.read_bytes()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        code, report = self.check()
        self.assertEqual(code, 0, report)
        self.assertTrue(any("historical source no longer exists" in x for x in report["warnings"]))
        self.assertEqual(log.read_bytes(), original)
        self.add_page("知识/current.md", sources=["src/removed.py"])
        self.assertTrue(any("知识/current.md: missing link/source" in x for x in self.check()[1]["errors"]))

    def test_history_memory_links_remain_required(self):
        self.init()
        self.add_page("日志/history.md", "log", "archived", body="[[决策/missing]]")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertTrue(any("missing link/source: 决策/missing" in x for x in self.check()[1]["errors"]))

    def test_invalid_status_cannot_enter_generated_indexes(self):
        self.init()
        self.add_page("知识/invalid.md", status="not-a-status")
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_many_modules_use_a_catalog_and_keep_startup_small(self):
        self.init()
        for n in range(200):
            self.add_page(f"知识/模块/module-{n}.md", topic=f"module-{n}")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        entry = memory.read_text(self.root / memory.ENTRY)
        self.assertLess(len(entry.splitlines()), 35)
        self.assertNotIn("module-199.md", entry)
        catalog = memory.read_text(self.root / memory.CATALOGS["knowledge"][0])
        self.assertIn("module-199.md", catalog)
        self.assertEqual(self.check()[1]["errors"], [])

    def test_active_replacement_retires_old_decision_and_rejects_cycles(self):
        self.init()
        old = self.add_page("决策/ADR-001-old.md", "decision", topic="storage-v1")
        new = self.add_page("决策/ADR-002-new.md", "decision", topic="storage-v2", extra='\nsupersedes: "[[决策/ADR-001-old]]"')
        self.assertTrue(any("active replacement requires" in x for x in self.check()[1]["errors"]))
        old.write_text(memory.read_text(old).replace("status: active", "status: superseded"), encoding="utf-8")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])
        old.write_text(memory.read_text(old).replace("sources: []", 'sources: []\nsupersedes: "[[决策/ADR-002-new]]"'), encoding="utf-8")
        self.assertTrue(any("supersession cycle" in x for x in self.check()[1]["errors"]))
        self.assertTrue(new.exists())

    def test_fresh_edit_does_not_refresh_old_verification(self):
        self.init()
        self.add_page("知识/verified.md", extra="\nverified: 2020-01-01")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertTrue(any("old verification date" in x for x in self.check()[1]["warnings"]))

    def test_index_detects_concurrent_target_edit(self):
        self.init()
        entry = self.root / memory.ENTRY
        original = entry.read_bytes()
        plan = {entry: original + b"\nOld generated contents\n"}
        entry.write_bytes(original + b"\nConcurrent user note\n")
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            memory.apply_plan(plan, self.project, True, snapshots={entry: original})
        self.assertIn(b"Concurrent user note", entry.read_bytes())

    def test_index_detects_new_page_during_generation(self):
        self.init()
        original = memory.index_contents
        before_entry = (self.root / memory.ENTRY).read_bytes()

        def new_log(pages, link_style):
            self.add_page("日志/concurrent.md", "log", "archived")
            return original(pages, link_style)

        with mock.patch.object(memory, "index_contents", side_effect=new_log):
            code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2, error)
        self.assertIn("page set changed", error)
        self.assertEqual((self.root / memory.ENTRY).read_bytes(), before_entry)
        self.assertTrue((self.root / "日志/concurrent.md").exists())

    def test_index_detects_config_change_after_validation(self):
        self.init()
        self.add_page("知识/new.md")
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        data["mode"] = "standard"
        changed = json.dumps(data).encode("utf-8")
        original_inspect = memory.inspect

        def race(*args, **kwargs):
            result = original_inspect(*args, **kwargs)
            config.write_bytes(changed)
            return result

        with mock.patch.object(memory, "inspect", side_effect=race):
            code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2, error)
        self.assertIn("file changed after it was read", error)
        self.assertEqual(config.read_bytes(), changed)
        self.assertFalse((self.root / "知识/MOC_知识.md").exists())

    def test_unconfigured_legacy_memory_cannot_be_indexed(self):
        self.init()
        self.add_page("知识/new.md")
        config = self.root / ".memory.json"
        config.unlink()
        before = self.snapshot()
        code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2, error)
        self.assertIn("migrate", error)
        self.assertEqual(before, self.snapshot())
        self.assertFalse(config.exists())
        self.assertFalse((self.root / "知识/MOC_知识.md").exists())

    def test_initialization_rolls_back_normal_write_failure(self):
        agents = self.project / "AGENTS.md"
        agents.write_bytes(b"Original rules\n")
        before = self.snapshot()
        original = memory.atomic_write

        def fail(path, data, **kwargs):
            if path.name == "当前状态.md":
                raise OSError("simulated disk write failure")
            return original(path, data, **kwargs)

        with mock.patch.object(memory, "atomic_write", side_effect=fail):
            self.assertEqual(self.run_cli("init", "--apply")[0], 2)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.project / ".wiki-memory.lock").exists())

    def test_index_rolls_back_normal_write_failure(self):
        self.init()
        self.add_page("知识/new.md")
        before = self.snapshot()
        original = memory.atomic_write

        def fail(path, data, **kwargs):
            if path.name == "MOC_知识.md":
                raise OSError("simulated disk write failure")
            return original(path, data, **kwargs)

        with mock.patch.object(memory, "atomic_write", side_effect=fail):
            self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(self.snapshot(), before)

    def test_rollback_preserves_new_user_edit(self):
        self.init()
        self.add_page("知识/new.md")
        entry = self.root / memory.ENTRY
        original = memory.atomic_write

        def change_then_fail(path, data, **kwargs):
            if path.name == "MOC_知识.md":
                entry.write_bytes(entry.read_bytes() + b"\nConcurrent note during write\n")
                raise OSError("simulated failure")
            return original(path, data, **kwargs)

        with mock.patch.object(memory, "atomic_write", side_effect=change_then_fail):
            code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("preserved changed files", error)
        self.assertIn(b"Concurrent note during write", entry.read_bytes())

    def test_existing_lock_stops_writes_but_allows_read_only_checks(self):
        self.init()
        lock = self.project / ".wiki-memory.lock"
        lock.write_bytes(b"External writer\n")
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.run_cli("index")[0], 0)
        self.assertEqual(self.snapshot(), before)

    def test_two_writers_detect_lock_and_require_fresh_snapshot(self):
        self.init()
        entry = self.root / memory.ENTRY
        original = entry.read_bytes()
        first = original + b"\nFirst writer's note.\n"
        second_note = b"\nSecond writer's note.\n"
        active, release = threading.Event(), threading.Event()
        original_write = memory.atomic_write

        def block_first(path, data, **kwargs):
            if path == entry and data == first:
                active.set()
                if not release.wait(10):
                    raise TimeoutError("test writer did not resume")
            return original_write(path, data, **kwargs)

        def write(data, expected):
            memory.apply_plan({entry: data}, self.project, True, snapshots={entry: expected})

        with contextlib.redirect_stdout(io.StringIO()), mock.patch.object(memory, "atomic_write", block_first):
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(write, first, original)
                try:
                    self.assertTrue(active.wait(10))
                    with self.assertRaisesRegex(ValueError, "writer lock exists"):
                        write(original + second_note, original)
                    self.assertEqual(entry.read_bytes(), original)
                finally:
                    release.set()
                future.result(timeout=10)
            with self.assertRaisesRegex(ValueError, "file changed after it was read"):
                write(original + second_note, original)
            write(first + second_note, first)

        self.assertEqual(entry.read_bytes(), first + second_note)
        self.assertFalse((self.project / ".wiki-memory.lock").exists())

    def test_plain_source_path_can_contain_hash(self):
        self.init()
        source = self.project / "src/config#prod.py"
        source.parent.mkdir()
        source.write_text("VALUE = 1\n", encoding="utf-8")
        self.add_page("知识/config.md", sources=["src/config#prod.py"])
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])

    def test_generated_wiki_paths_encode_hash_and_literal_percent_once(self):
        self.init("--link-style", "wiki")
        first = self.add_page("知识/配置#生产.md", topic="hash-config")
        second = self.add_page("知识/配置%20字面.md", topic="percent-config")
        self.add_page("知识/消费者.md", topic="consumer", body="[[知识/配置%23生产.md]] 与 [[知识/配置%2520字面.md]]。")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        catalog = memory.read_text(self.root / memory.CATALOGS["knowledge"][0])
        self.assertIn("知识/配置%23生产.md", catalog)
        self.assertIn("知识/配置%2520字面.md", catalog)
        self.assertNotIn("%E7%9F", catalog)
        self.assertEqual(self.check()[1]["errors"], [])
        pages = memory.load_pages(self.root)
        source = next(p for p in pages if p.path == memory.CATALOGS["knowledge"][0])
        self.assertEqual(memory.resolve_target("wiki", "知识/配置%23生产.md", source, self.project, self.root, pages), first)
        self.assertEqual(memory.resolve_target("wiki", "知识/配置%2520字面.md", source, self.project, self.root, pages), second)
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(before, self.snapshot())

    def test_markdown_navigation_resolves_from_each_moc(self):
        self.init("--mode", "standard")
        title = "中文 [#]%20 (旧).md"
        historical = self.add_page("历史 状态.md", "state", "archived")
        decision = self.add_page("决策/模块/ADR-042-" + title, "decision")
        knowledge = self.add_page("知识/一/" + title, topic="one")
        duplicate_title = self.add_page("知识/二/" + title, topic="two")
        log = self.add_page("日志/工程维护/子目录/" + title, "log", "archived",
                            extra='\nkind: maintenance\ntask_status: completed')
        code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 0, error)
        self.assertEqual(self.check()[1]["errors"], [])
        pages = memory.load_pages(self.root)
        by_path = {p.rel: p for p in pages}
        expected = {
            "README.md": {self.root / "当前状态/当前待办.md", self.root / "当前状态/MOC_状态.md",
                          self.root / "决策/MOC_决策.md", self.root / "知识/MOC_知识.md"},
            "当前状态/MOC_状态.md": {historical},
            "决策/MOC_决策.md": {decision},
            "知识/MOC_知识.md": {knowledge, duplicate_title},
            "日志/MOC_工作日志.md": {log},
        }
        for source, targets in expected.items():
            with self.subTest(source=source):
                page = by_path[source]
                generated = page.body.split(memory.AUTO_START)[1].split(memory.AUTO_END)[0]
                links = list(memory.links(generated))
                self.assertTrue(links)
                self.assertTrue(all(kind == "markdown" for kind, _ in links))
                self.assertLessEqual(targets, {
                    memory.resolve_target(kind, raw, page, self.project, self.root, pages)
                    for kind, raw in links
                })
        self.assertIn("(../历史%20状态.md)", by_path["当前状态/MOC_状态.md"].body)
        self.assertIn("(一/中文%20%5B%23%5D%2520%20%28旧%29.md)", by_path["知识/MOC_知识.md"].body)
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply", "--date", "2026-10-08")[0], 0)
        self.assertEqual(before, self.snapshot())

    def test_missing_style_preserves_legacy_indexes_then_explicitly_switches(self):
        self.init("--link-style", "wiki")
        history = self.add_page("日志/人工 记录.md", "log", "archived",
                                body="旧记录保留 [[当前状态/当前状态.md]]。")
        entry = self.root / memory.ENTRY
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        self.assertEqual(data.pop("link_style"), "wiki")
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(before, self.snapshot())
        self.assertIn("[[当前状态/当前状态.md|当前状态]]", memory.read_text(entry))
        self.assertIn("%E4%BA%BA%E5%B7%A5%20", memory.read_text(self.root / memory.LOG_INDEX))

        text = memory.read_text(entry).replace("\r\n", "\n").replace("\n", "\r\n")
        text += "保留手写 [[当前状态/当前状态.md]]。\r\n"
        entry.write_bytes(text.encode("utf-8"))
        history_before = history.read_bytes()
        data["link_style"] = "markdown"
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        migrated = memory.read_text(entry)
        self.assertIn("[当前状态](当前状态/当前状态.md)", migrated)
        self.assertNotIn("\n", migrated.replace("\r\n", ""))
        self.assertEqual(text.split(memory.AUTO_START)[0], migrated.split(memory.AUTO_START)[0])
        self.assertEqual(text.split(memory.AUTO_END)[1], migrated.split(memory.AUTO_END)[1])
        self.assertEqual(history_before, history.read_bytes())
        self.assertEqual(self.check()[1]["errors"], [])

    def test_invalid_link_style_fails_before_index_writes(self):
        self.init()
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        data["link_style"] = ["markdown"]
        config.write_text(json.dumps(data), encoding="utf-8")
        before = self.snapshot()
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn(".memory.json: link_style must be markdown or wiki", report["errors"])
        code, _, error = self.run_cli("index", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("link_style must be markdown or wiki", error)
        self.assertEqual(before, self.snapshot())

    def test_markdown_links_escape_table_syntax_and_nonportable_paths(self):
        title = "配置 \\ [旧] | `标题`"
        source = memory.LOG_INDEX
        relative = "日志/配置%23.md"
        if sys.platform != "win32":
            relative = "日志/配置 \\?|.md"
        target = self.add_page(relative, "log", "archived")
        rendered = memory.render_memory_link(Path(relative), title, source, "markdown")
        self.assertNotIn("`", rendered)
        self.assertNotIn("|", rendered.replace("\\|", ""))
        [(kind, raw)] = memory.links(rendered)
        if sys.platform != "win32":
            self.assertIn("%5C%3F%7C", raw)
        else:
            self.assertIn("%2523", raw)
        page = memory.parse_page(source, "# 工作日志\n")
        self.assertEqual(memory.resolve_target(kind, raw, page, self.project, self.root, []), target)

    def test_uppercase_markdown_extension_indexes_without_false_concurrency(self):
        self.init()
        page = self.add_page("知识/Uppercase.MD", topic="uppercase")
        log = self.add_page("日志/历史#%20.MD", "log", "archived", topic="uppercase-log")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])
        catalog = memory.read_text(self.root / memory.CATALOGS["knowledge"][0])
        self.assertIn("Uppercase.MD", catalog)
        self.assertTrue(page.exists() and log.exists())
        before = self.snapshot()
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(before, self.snapshot())

    def test_markdown_parentheses_and_dotted_wiki_titles(self):
        self.init()
        source = self.project / "docs/design(old).md"
        source.parent.mkdir()
        source.write_text("# Design\n", encoding="utf-8")
        self.add_page("知识/API.v2.md", topic="api-v2")
        self.add_page("知识/consumer.md", topic="consumer", body="[设计](../../docs/design(old).md) 与 [[知识/API.v2]]。")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])

    def test_bare_wiki_name_preserves_legacy_root_priority(self):
        self.init()
        (self.root / "same.md").write_text("# Root\n", encoding="utf-8")
        self.add_page("知识/same.md", topic="same")
        self.add_page("知识/consumer.md", topic="consumer", body="[[same]]")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])
        pages = memory.load_pages(self.root)
        consumer = next(p for p in pages if p.path == Path("知识/consumer.md"))
        self.assertEqual(memory.resolve_target("wiki", "same", consumer, self.project, self.root, pages), self.root / "same.md")

    def test_standard_mode_requires_global_constraints_page(self):
        self.init("--mode", "standard")
        (self.root / "当前状态/当前约束.md").unlink()
        self.assertTrue(any("required state page missing" in x for x in self.check()[1]["errors"]))
        self.assertEqual(self.run_cli("index", "--apply")[0], 2)
        self.add_page("当前状态/当前约束.md", "state", "archived", "project-constraints")
        self.assertTrue(any("required state page must be current" in x for x in self.check()[1]["errors"]))

    def test_generated_moc_edit_date_advances_without_touching_other_fields(self):
        self.init()
        entry = self.root / memory.ENTRY
        old = memory.read_text(entry).replace("updated: 2026-10-07", "updated: 2020-01-01") + "\r\nPreserve this note\r\n"
        entry.write_bytes(old.encode("utf-8"))
        self.add_page("知识/new.md")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        refreshed = entry.read_bytes()
        self.assertIn(b"updated: 2026-10-07", refreshed)
        self.assertTrue(refreshed.endswith(b"\r\nPreserve this note\r\n"))
        self.assertIn(b"topic: memory-entry", refreshed)

    def test_examples_and_negative_rules_cannot_pass_discovery_gate(self):
        self.init()
        self.populate_states()
        agents = self.project / "AGENTS.md"
        cases = [
            "```text\n读取 wiki_memory/AGENTS.md 和 wiki_memory/README.md\n```",
            "<!-- 读取 wiki_memory/AGENTS.md 和 wiki_memory/README.md -->",
            "    读取 wiki_memory/AGENTS.md 和 wiki_memory/README.md",
            "> 读取 wiki_memory/AGENTS.md 和 wiki_memory/README.md",
            "不要读取 wiki_memory/AGENTS.md 和 wiki_memory/README.md。",
            "Do not read wiki_memory/AGENTS.md or wiki_memory/README.md.",
            "wiki_memory/AGENTS.md\nwiki_memory/README.md",
            "```text\n" + memory.HOOK_START + "\n读取 wiki_memory/AGENTS.md 和 wiki_memory/README.md\n" + memory.HOOK_END + "\n```",
        ]
        for text in cases:
            with self.subTest(text=text):
                agents.write_text(text, encoding="utf-8")
                before = self.snapshot()
                code, output, _ = self.run_cli("check", "--require-ready")
                self.assertEqual(code, 1)
                self.assertTrue(any("lack memory hook" in e for e in json.loads(output)["errors"]))
                self.assertEqual(self.snapshot(), before)

    def test_legacy_inline_hook_remains_usable_with_manual_review_warning(self):
        self.init()
        self.populate_states()
        (self.project / "AGENTS.md").write_text("Read `wiki_memory/AGENTS.md` and `wiki_memory/README.md`; do not create a second entry.", encoding="utf-8")
        code, output, _ = self.run_cli("check", "--require-ready")
        self.assertEqual(code, 0)
        self.assertTrue(any("unmarked legacy memory hook" in x for x in json.loads(output)["warnings"]))

    def test_managed_hook_must_be_unique_ordered_and_contain_its_own_paths(self):
        self.init()
        agents = self.project / "AGENTS.md"
        real = memory.read_text(agents)
        for text in (real + real, memory.HOOK_END + real, real.replace("wiki_memory/README.md", "other/README.md") + "\nRead wiki_memory/README.md"):
            agents.write_text(text, encoding="utf-8")
            self.assertFalse(memory.has_memory_hook(text, "wiki_memory"))

    def test_example_hook_does_not_block_initialization(self):
        agents = self.project / "AGENTS.md"
        example = "```text\n" + memory.HOOK_START + "\n" + memory.HOOK_END + "\n```\n"
        agents.write_text(example, encoding="utf-8")
        self.init()
        self.assertTrue(agents.read_text(encoding="utf-8").startswith(example))
        self.assertEqual(memory.memory_hook_status(memory.read_text(agents), "wiki_memory"), "managed")

    def test_comment_links_are_not_real_sources(self):
        self.init()
        self.add_page("知识/comments.md", body="<!-- [old](../../missing.py) [[missing]] -->\n正文。")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])

    def test_comment_or_example_delimiters_do_not_hide_real_hook(self):
        self.init()
        real = memory.read_text(self.project / "AGENTS.md")
        for prefix in ("<!--\n```\nexample\n-->\n", "```text\n<!-- unclosed example comment\n```\n"):
            self.assertEqual(memory.memory_hook_status(prefix + real, "wiki_memory"), "managed")

    def test_inline_marker_examples_do_not_override_valid_legacy_instructions(self):
        prose = "接入标记示例：`" + memory.HOOK_START + "` / `" + memory.HOOK_END + "`。\nRead wiki_memory/AGENTS.md and wiki_memory/README.md."
        self.assertEqual(memory.memory_hook_status(prose, "wiki_memory"), "legacy")

    def test_legacy_hook_accepts_sentence_period_but_rejects_path_suffixes(self):
        text = "Read wiki_memory/AGENTS.md and wiki_memory/README.md."
        self.assertEqual(memory.memory_hook_status(text, "wiki_memory"), "legacy")
        for suffix in (".backup", "/child", "_other"):
            wrong = "Read wiki_memory/AGENTS.md and wiki_memory/README.md" + suffix
            self.assertFalse(memory.has_memory_hook(wrong, "wiki_memory"))

    def test_ready_gate_rejects_comment_only_headings_and_empty_code_sections(self):
        self.init()
        self.populate_states()
        path = self.root / "当前状态/当前状态.md"
        original = memory.read_text(path)
        for filler in ("<!-- 已填写 -->", "### 尚未填内容", "```text\n```"):
            section = "## 恢复位置与下一步\n\n" + filler + "\n\n"
            text = re.sub(r"## 恢复位置与下一步.*?(?=## 证据与未核实项)", lambda _: section, original, flags=re.DOTALL)
            path.write_text(text, encoding="utf-8")
            code, output, _ = self.run_cli("check", "--require-ready")
            self.assertEqual(code, 1)
            self.assertTrue(any("still scaffold: 恢复位置与下一步" in x for x in json.loads(output)["errors"]))

    def test_boolean_schema_version_is_not_a_legacy_integer(self):
        self.init()
        path = self.root / ".memory.json"
        data = json.loads(memory.read_text(path))
        data["schema_version"] = True
        path.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(any("unsupported schema_version" in x for x in self.check()[1]["errors"]))

    def test_migration_plan_lists_encoded_links_and_missing_sources_without_writes(self):
        self.init()
        log = self.add_page("日志/导出#字面%20.md", "log", "archived", topic="encoded-log", extra="\nkind: feature")
        self.add_page("知识/use.md", topic="encoded-consumer", body="[[日志/导出%23字面%2520.md#细节]]", sources=["missing-old-source.py"])
        before = self.snapshot()
        report = json.loads(self.run_cli("plan-migration", "--mode", "standard")[1])
        self.assertTrue(any(r["proposed_target"] == "日志/功能添加/导出%23字面%2520.md#细节" for r in report["affected_references"]))
        self.assertTrue(any(r["target"] == "missing-old-source.py" for r in report["unresolved_references"]))
        self.assertTrue(log.exists())
        self.assertEqual(before, self.snapshot())

    def test_budget_limits_warn_without_blocking_ready_or_writing(self):
        self.init()
        self.populate_states()
        path = self.root / "当前状态/当前状态.md"
        path.write_text(memory.read_text(path).replace("## 恢复位置与下一步", "## 恢复位置与下一步\n\n- 核实入口。\n- 执行验收。\n- [x] 已完成不计入待办。"), encoding="utf-8")
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        data["read_budget"] = {"startup_chars": 1, "page_chars": 1, "todo_items": 1}
        config.write_text(json.dumps(data), encoding="utf-8")
        before = self.snapshot()
        code, output, _ = self.run_cli("check", "--require-ready")
        report = json.loads(output)
        self.assertEqual(code, 0)
        self.assertEqual(report["errors"], [])
        self.assertTrue(any("startup pages" in w for w in report["warnings"]))
        self.assertTrue(any("split stable topics" in w for w in report["warnings"]))
        self.assertTrue(any("pending todo" in w for w in report["warnings"]))
        self.assertEqual(report["read_budget"]["todo_items"], 4)
        self.assertIn("AGENTS.md", report["read_budget"]["startup_pages"])
        self.assertEqual(before, self.snapshot())
        data["read_budget"] = {key: 0 for key in memory.READ_BUDGET}
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(any("read budget" in w for w in self.check()[1]["warnings"]))

    def test_invalid_budget_configuration_is_reported_before_index_writes(self):
        self.init()
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        for limits in ({"startup_chars": True}, {"page_chars": -1}, {"todo_items": "20"}, {"unknown": 1}, []):
            data["read_budget"] = limits
            config.write_text(json.dumps(data), encoding="utf-8")
            before = self.snapshot()
            self.assertEqual(self.check()[0], 1)
            self.assertEqual(self.run_cli("index", "--apply")[0], 2)
            self.assertEqual(before, self.snapshot())

    def test_migration_plan_is_read_only_and_reports_moves_and_reference_rebasing(self):
        old = self.legacy_layout("docs/wiki_memory")
        source = self.project / "src/task.py"
        source.parent.mkdir()
        source.write_text("TASK = 1\n", encoding="utf-8")
        log = old / "日志/2026-10-07-task.md"
        log.write_text(memory.make_page("log", "archived", "task", "任务", "[实现](../../../src/task.py)\n", self.today, extra_fields={"kind": "feature"}), encoding="utf-8")
        state = old / "当前状态/当前状态.md"
        state.write_text(memory.read_text(state).replace("sources: []", 'source_logs: ["[[日志/2026-10-07-task]]"]\nsources: ["docs/wiki_memory/日志/2026-10-07-task.md"]'), encoding="utf-8")
        before = self.snapshot()
        code, output, error = self.run_cli("plan-migration", "--memory-dir", "docs/wiki_memory", "--mode", "standard")
        report = json.loads(output)
        self.assertEqual(code, 0, error)
        self.assertTrue(report["read_only"])
        self.assertIn({"source": "docs/wiki_memory/日志/2026-10-07-task.md", "destination": "wiki_memory/日志/功能添加/2026-10-07-task.md"}, report["moves"])
        refs = report["affected_references"]
        self.assertTrue(any(r["field"] == "source_logs" and r["proposed_target"] == "日志/功能添加/2026-10-07-task.md" for r in refs))
        self.assertTrue(any(r["field"] == "sources" and r["proposed_target"] == "wiki_memory/日志/功能添加/2026-10-07-task.md" for r in refs))
        self.assertTrue(any(r["target"] == "../../../src/task.py" and r["proposed_target"] == "../../../src/task.py" for r in refs))
        self.assertTrue(any(r["target"] == "docs/wiki_memory/入口.md" and r["proposed_target"] == "wiki_memory/README.md" for r in refs))
        self.assertEqual(len(report["required_state_work"]), 5)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.run_cli("plan-migration", "--memory-dir", "docs/wiki_memory", "--apply")[0], 2)
        self.assertEqual(before, self.snapshot())

    def test_migration_plan_reports_collisions_and_never_guesses_missing_log_kind(self):
        self.init()
        self.add_page("日志/old/a.md", "log", "archived", topic="a", extra="\nkind: bug")
        self.add_page("日志/other/a.md", "log", "archived", topic="b", extra="\nkind: bug")
        self.add_page("日志/看似功能.md", "log", "archived", topic="missing-kind")
        before = self.snapshot()
        code, output, _ = self.run_cli("plan-migration", "--mode", "standard")
        report = json.loads(output)
        self.assertEqual(code, 1)
        self.assertTrue(any(c["destination"] == "wiki_memory/日志/Bug处理/a.md" for c in report["conflicts"]))
        self.assertEqual(report["unclassified_logs"][0]["path"], "日志/看似功能.md")
        self.assertEqual(before, self.snapshot())

    def test_migration_plan_defaults_to_existing_standard_mode(self):
        self.init("--mode", "standard")
        self.populate_states("standard")
        self.assertEqual(json.loads(self.run_cli("plan-migration")[1])["target_mode"], "standard")
        self.assertEqual(self.run_cli("plan-migration", "--mode", "lite")[0], 1)

    def test_migration_plan_preserves_manual_navigation_and_external_reference_inventory(self):
        old = self.legacy_layout("docs/wiki_memory")
        (old / "README.md").write_text("# 自定义说明\n手写内容必须保留。", encoding="utf-8")
        (self.project / "README.md").write_text("[旧导航](docs/wiki_memory/入口.md#导航)", encoding="utf-8")
        (self.project / "unrelated.md").write_text("[模板示例](missing-template.md)", encoding="utf-8")
        excluded = self.project / "node_modules/package"
        excluded.mkdir(parents=True)
        (excluded / "README.md").write_text("[[missing]]", encoding="utf-8")
        before = self.snapshot()
        report = json.loads(self.run_cli("plan-migration", "--memory-dir", "docs/wiki_memory")[1])
        self.assertEqual(len(report["navigation_merges"][0]["sources"]), 2)
        self.assertTrue(any(r["file"] == "README.md" and r["proposed_target"] == "wiki_memory/README.md#导航" for r in report["affected_references"]))
        self.assertFalse(any("node_modules" in r["file"] for r in report["unresolved_references"]))
        self.assertFalse(any(r["file"] == "unrelated.md" for r in report["unresolved_references"]))
        self.assertEqual(before, self.snapshot())

    def test_migration_plan_refuses_competing_roots_and_reports_ambiguous_links(self):
        old = self.legacy_layout("docs/wiki_memory")
        for folder in ("a", "b"):
            path = old / "知识" / folder / "same.md"
            path.parent.mkdir(parents=True)
            path.write_text(memory.make_page("knowledge", "active", folder, folder, "正文", self.today), encoding="utf-8")
        (old / "知识/consumer.md").write_text(memory.make_page("knowledge", "active", "consumer", "使用方", "[[same]]", self.today), encoding="utf-8")
        self.root.mkdir()
        before = self.snapshot()
        code, output, _ = self.run_cli("plan-migration", "--memory-dir", "docs/wiki_memory")
        report = json.loads(output)
        self.assertEqual(code, 1)
        self.assertTrue(report["blockers"])
        self.assertTrue(any("ambiguous wiki link" in r["reason"] for r in report["unresolved_references"]))
        self.assertEqual(before, self.snapshot())


    def git(self, *args, project=None):
        if not shutil.which("git"):
            self.skipTest("Git is not installed")
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.autocrlf=false", *args],
            cwd=project or self.project, env=env, capture_output=True, text=True, encoding="utf-8", check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def git_init(self):
        self.git("init", "-q")
        self.git("config", "user.name", "Wiki Memory Test")
        self.git("config", "user.email", "test@example.invalid")

    def git_commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-qm", message)
        return self.git("rev-parse", "HEAD").strip()

    def analysis(self, *args):
        code, output, error = self.run_cli(*args)
        self.assertIn(code, (0, 1), error)
        report = json.loads(output)
        self.assertTrue(report["read_only"])
        return code, report

    def test_read_only_commands_preserve_project_and_git_bytes(self):
        self.git_init()
        source = self.project / "config.py"
        source.write_bytes(b"VALUE = 1\n")
        self.git_commit("before initialization")

        def unchanged(*args):
            status = self.git("status", "--porcelain=v1", "-z")
            before = self.snapshot()
            code, output, error = self.run_cli(*args)
            self.assertEqual(code, 0, error or output)
            self.assertEqual(self.git("status", "--porcelain=v1", "-z"), status)
            self.assertEqual(self.snapshot(), before)
            return json.loads(output)

        self.assertFalse(unchanged("init")["apply"])
        self.init()
        self.git_commit("initialized memory")
        source.write_bytes(b"VALUE = 2\n")
        self.git("add", "config.py")
        source.write_bytes(b"VALUE = 3\n")
        (self.project / "untracked.txt").write_bytes(b"local note\n")
        config = self.root / ".memory.json"
        data = json.loads(memory.read_text(config))
        data["link_style"] = "wiki"
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertTrue(unchanged("index")["files"])
        unchanged("check")
        unchanged("plan-migration")
        unchanged("impact", "--base", "HEAD", "--include-worktree")
        unchanged("tool-diff")

    def test_impact_compares_diverged_branch_tips_without_switching(self):
        self.init()
        self.git_init()
        source = self.project / "settings.py"
        source.write_bytes(b"VALUE = 1\n")
        base = self.git_commit("common base")
        self.git("checkout", "-qb", "left")
        source.write_bytes(b"VALUE = 2\n")
        left = self.git_commit("left tip")
        self.git("checkout", "-qb", "right", base)
        source.write_bytes(b"VALUE = 3\n")
        right = self.git_commit("right tip")
        self.add_page("知识/settings.md", sources=["settings.py"])
        source.write_bytes(b"VALUE = 4\n")
        status = self.git("status", "--porcelain=v1", "-z")
        before = self.snapshot()

        code, report = self.analysis("impact", "--base", "left", "--head", "right")
        self.assertEqual(code, 0, report)
        self.assertEqual((report["base"], report["head"]), (left, right))
        self.assertEqual(report["included_scopes"], ["commit"])
        self.assertEqual(report["affected_pages"][0]["page"], "知识/settings.md")
        self.assertEqual(self.git("branch", "--show-current").strip(), "right")
        self.assertEqual(self.git("status", "--porcelain=v1", "-z"), status)
        self.assertEqual(self.snapshot(), before)

    def test_impact_commit_renames_deletes_source_directories_and_verified_revisions(self):
        self.init()
        self.git_init()
        src = self.project / "src"
        src.mkdir()
        (src / "旧 文件.py").write_text("old\n", encoding="utf-8")
        (src / "deleted.py").write_text("remove\n", encoding="utf-8")
        (self.project / "-flag.py").write_text("before\n", encoding="utf-8")
        base = self.git_commit("before")
        (src / "旧 文件.py").rename(src / "新 文件.py")
        (src / "deleted.py").unlink()
        (self.project / "-flag.py").write_text("after\n", encoding="utf-8")
        head = self.git_commit("after")
        self.add_page("知识/old.md", sources=["src/旧 文件.py", "src/deleted.py"], topic="old",
                      extra=f'\nverified: {self.today}\nverified_rev: "{base[:12]}"')
        self.add_page("知识/new.md", sources=["[新路径](../../src/新%20文件.py)", "-flag.py"], topic="new",
                      extra=f'\nverified: {self.today}\nverified_rev: "{head}"')
        self.add_page("知识/folder.md", sources=["src"], topic="folder")
        self.add_page("知识/historical.md", sources=["src"], topic="archived", status="archived")
        self.add_page("知识/unresolved.md", sources=["src"], topic="unresolved",
                      extra=f'\nverified: {self.today}\nverified_rev: "0000000"')
        status = self.git("status", "--porcelain=v1", "-z")
        before = self.snapshot()
        args = ("impact", "--base", "HEAD~1", "--head", head)
        code, report = self.analysis(*args)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "complete")
        self.assertEqual((report["base"], report["head"]), (base, head))
        self.assertEqual(report["included_scopes"], ["commit"])
        changes = {change["path"]: change for change in report["changed_sources"]}
        self.assertEqual(changes["src/新 文件.py"]["previous_path"], "src/旧 文件.py")
        self.assertEqual(changes["src/新 文件.py"]["change"], "renamed")
        self.assertEqual(changes["src/deleted.py"]["change"], "deleted")
        self.assertEqual(changes["-flag.py"]["change"], "modified")
        pages = {row["page"]: row for row in report["affected_pages"]}
        self.assertEqual(pages["知识/old.md"]["matched_sources"], ["src/deleted.py", "src/旧 文件.py"])
        self.assertEqual(pages["知识/new.md"]["matched_sources"], ["-flag.py", "src/新 文件.py"])
        self.assertEqual(pages["知识/folder.md"]["matched_sources"], ["src"])
        self.assertNotIn("知识/historical.md", pages)
        self.assertTrue(all(row["action"] == "review" and not row["confirmed_stale"] for row in pages.values()))
        baselines = {row["page"]: row["status"] for row in report["page_baselines"]}
        self.assertEqual(baselines, {"知识/folder.md": "missing", "知识/new.md": "differs_from_base",
                                     "知识/old.md": "matches_base", "知识/unresolved.md": "unresolved"})
        self.assertEqual(self.analysis(*args), (code, report))
        code, other_head = self.analysis("impact", "--base", "HEAD", "--head", base, "--include-worktree")
        self.assertEqual((code, other_head["status"]), (1, "incomplete"))
        self.assertEqual(other_head["included_scopes"], ["commit"])
        self.assertIn("worktree_requires_current_head", other_head["limitations"])
        self.assertEqual(self.git("status", "--porcelain=v1", "-z"), status)
        self.assertEqual(self.snapshot(), before)

    def test_impact_worktree_includes_netcancel_staged_unstaged_and_untracked(self):
        self.init()
        self.git_init()
        tracked = self.project / "tracked.py"
        tracked.write_bytes(b"one\n")
        (self.project / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        self.git_commit("base")
        tracked.write_bytes(b"two\n")
        self.git("add", "tracked.py")
        tracked.write_bytes(b"one\n")
        for name in ("新的 文件.py", "ignored.py", ".private", "node_modules/cache.py", ".hidden/file.py"):
            path = self.project / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"untracked\n")
        self.add_page("知识/tracked.md", sources=["tracked.py", "新的 文件.py"])
        status = self.git("status", "--porcelain=v1", "-z")
        before = self.snapshot()
        _, clean = self.analysis("impact", "--base", "HEAD")
        self.assertEqual(clean["changed_sources"], [])
        self.assertFalse(clean["worktree_included"])
        with mock.patch.dict(os.environ, {"GIT_DIR": "malicious/nonexistent", "GIT_WORK_TREE": "malicious/nonexistent"}):
            code, report = self.analysis("impact", "--base", "HEAD", "--include-worktree")
        self.assertEqual(code, 0, report)
        self.assertTrue(report["worktree_included"])
        self.assertEqual(report["included_scopes"], ["commit", "staged", "unstaged", "untracked"])
        scopes = {(item["path"], item["scope"]) for item in report["changed_sources"]}
        self.assertTrue({("tracked.py", "staged"), ("tracked.py", "unstaged"), ("新的 文件.py", "untracked")} <= scopes)
        self.assertTrue({name for name, _ in scopes}.isdisjoint(
            {"ignored.py", ".private", "node_modules/cache.py", ".hidden/file.py"}))
        self.assertEqual(self.git("status", "--porcelain=v1", "-z"), status)
        self.assertEqual(self.snapshot(), before)

    def test_impact_handles_git_errors_invalid_revision_and_nonroot_scope(self):
        self.init()
        code, report = self.analysis("impact", "--base", "HEAD")
        self.assertEqual((code, report["status"]), (1, "unavailable"))
        self.git_init()
        self.git_commit("base")
        before = self.snapshot()
        for revision, reason in (("-C", "unsupported_revision"), ("HEAD:AGENTS.md", "unsupported_revision"),
                                 ("HEAD..HEAD", "unsupported_revision"), ("x" * 257, "unsupported_revision"),
                                 ("does-not-exist", "base_revision_unresolved")):
            with self.subTest(revision=revision):
                code, report = self.analysis("impact", f"--base={revision}")
                self.assertEqual((code, report["status"]), (1, "unavailable"))
                self.assertIn(reason, report["limitations"])
        for exc, reason in ((FileNotFoundError, "git_not_found"), (PermissionError, "git_could_not_run")):
            with mock.patch.object(memory.subprocess, "run", side_effect=exc):
                self.assertIn(reason, self.analysis("impact", "--base", "HEAD")[1]["limitations"])
        self.assertEqual(self.snapshot(), before)
        self.project = self.project / "subproject"
        self.project.mkdir()
        code, report = self.analysis("impact", "--base", "HEAD")
        self.assertEqual((code, report["status"]), (1, "unavailable"))
        self.assertIn("not_a_git_worktree_root", report["limitations"])

    def test_impact_does_not_run_a_diff_for_a_redirected_git_worktree(self):
        self.init()
        self.git_init()
        self.git_commit("base")
        with tempfile.TemporaryDirectory(prefix="wiki-memory-other-worktree-") as other:
            self.git("config", "core.worktree", str(Path(other).resolve()))
            before = self.snapshot()
            code, report = self.analysis("impact", "--base", "HEAD")
            self.assertEqual((code, report["status"]), (1, "unavailable"))
            self.assertIn("project_must_be_git_worktree_root", report["limitations"])
            self.assertEqual(self.snapshot(), before)

    def test_impact_shallow_missing_history_reports_unavailable(self):
        self.init()
        self.git_init()
        base = self.git_commit("base")
        (self.project / "new.py").write_bytes(b"new\n")
        self.git_commit("new")
        clone = tempfile.TemporaryDirectory(prefix="wiki-memory-shallow-")
        self.addCleanup(clone.cleanup)
        self.git("clone", "-q", "--depth", "1", self.project.as_uri(), clone.name)
        self.project = Path(clone.name).resolve()
        self.assertEqual(self.git("rev-parse", "--is-shallow-repository").strip(), "true")
        before = self.snapshot()
        code, report = self.analysis("impact", "--base", base)
        self.assertEqual((code, report["status"]), (1, "unavailable"))
        self.assertIn("shallow_repository_history_may_be_missing", report["limitations"])
        self.assertEqual(self.snapshot(), before)

    def test_impact_and_tool_diff_reject_external_symlink_paths(self):
        self.init()
        self.git_init()
        self.git_commit("base")
        with tempfile.TemporaryDirectory(prefix="wiki-memory-external-test-") as outside:
            external_file = Path(outside) / "outside.py"
            external_file.write_text('VERSION = "1.2.3"\n', encoding="utf-8")
            try:
                (self.project / "jump").symlink_to(external_file.parent, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks unavailable")
            self.add_page("知识/link.md", sources=["jump/outside.py"])
            real_open = os.open

            def restricted_open(path, *args, **kwargs):
                self.assertNotIn("jump", Path(path).parts)
                return real_open(path, *args, **kwargs)

            before = self.snapshot()
            with mock.patch.object(memory.os, "open", restricted_open):
                code, impact = self.analysis("impact", "--base", "HEAD")
                self.assertEqual((code, impact["status"]), (1, "incomplete"))
                self.assertEqual(impact["unassessable_pages"][0]["reasons"], ["symlink_or_reparse_point"])
                code, diff = self.analysis("tool-diff", "--reference-tool", "jump/outside.py")
                self.assertEqual((code, diff["status"]), (1, "not_comparable"))
                self.assertEqual(diff["reference_tool"]["issue"], "symlink_or_reparse_point")
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(external_file.read_text(encoding="utf-8"), 'VERSION = "1.2.3"\n')

    def test_impact_reports_unsafe_sources_and_unreadable_pages_without_opening_them(self):
        self.init()
        self.git_init()
        tracked = self.project / "tracked.py"
        tracked.write_bytes(b"base\n")
        self.git_commit("base")
        tracked.write_bytes(b"after\n")
        self.git_commit("after")
        self.add_page("知识/untrusted.md", sources=["../outside", "/absolute", r"C:\outside", r"\\host\share",
                                                   "https://example.invalid/source", "x" * 4097,
                                                   "[malformed](../../%E4)", "missing.py", "permission.py"])
        self.add_page("知识/good.md", sources=["tracked.py"], topic="good")
        damaged = self.root / "知识" / "malformed.md"
        damaged.write_bytes(b"\xff")
        before = self.snapshot()
        real_stat = Path.lstat

        def restricted_stat(path):
            if path.name == "permission.py":
                raise PermissionError
            self.assertTrue(path.is_relative_to(self.project), path)
            return real_stat(path)

        with mock.patch.object(Path, "lstat", restricted_stat):
            code, report = self.analysis("impact", "--base", "HEAD~1")
        self.assertEqual((code, report["status"]), (1, "incomplete"))
        self.assertEqual([item["page"] for item in report["affected_pages"]], ["知识/good.md"])
        reasons = {item["page"]: item["reasons"] for item in report["unassessable_pages"]}
        self.assertEqual(reasons["知识/malformed.md"], ["unreadable_page"])
        self.assertEqual(reasons["知识/untrusted.md"], ["invalid_source_encoding", "missing_source", "nonlocal_source",
                                                        "unreadable_source", "unsafe_source_path"])
        self.assertEqual(self.snapshot(), before)

    def test_impact_skips_unstaged_diff_when_git_clean_filters_are_configured(self):
        self.init()
        self.git_init()
        tracked = self.project / "tracked.py"
        tracked.write_bytes(b"base\n")
        (self.project / ".gitattributes").write_text("tracked.py filter=malicious\n", encoding="utf-8")
        self.git_commit("base")
        self.git("config", "filter.malicious.clean", "echo ran > filter-sentinel; cat")
        tracked.write_bytes(b"changed\n")
        before = self.snapshot()
        code, report = self.analysis("impact", "--base", "HEAD", "--include-worktree")
        self.assertEqual((code, report["status"]), (1, "incomplete"))
        self.assertIn("unstaged_skipped_to_avoid_git_filters", report["limitations"])
        self.assertEqual(report["included_scopes"], ["commit", "staged", "untracked"])
        self.assertFalse((self.project / "filter-sentinel").exists())
        self.assertEqual(self.snapshot(), before)

    def test_verified_revision_check_is_syntactic_and_does_not_require_git(self):
        self.init()
        (self.project / "fact.txt").write_bytes(b"fact")
        page = self.add_page("知识/verified.md", sources=["fact.txt"], extra=f"\nverified: {self.today}\nverified_rev: abc1234")
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        before = self.snapshot()
        with mock.patch.object(memory.subprocess, "run", side_effect=AssertionError("check must not call Git")):
            self.assertEqual(self.check()[0], 0)
        self.assertEqual(self.snapshot(), before)
        page.write_text(page.read_text(encoding="utf-8").replace("verified_rev: abc1234", "verified_rev: HEAD"), encoding="utf-8")
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertTrue(any("verified_rev" in error for error in report["errors"]))

    def test_tool_diff_compares_raw_bytes_version_and_config_without_executing(self):
        self.init()
        local = self.root / "工具/memory.py"
        before = self.snapshot()
        code, same = self.analysis("tool-diff")
        self.assertEqual((code, same["status"]), (0, "same"))
        self.assertEqual(same["running_tool"]["version"], memory.VERSION)
        self.assertEqual(same["project_tool"]["sha256"], hashlib.sha256(local.read_bytes()).hexdigest())
        self.assertEqual(same["configuration"]["link_style"], "markdown")
        self.assertEqual(self.snapshot(), before)
        local.write_text(f'VERSION = "{memory.VERSION}"\nopen("side-effect", "w").write("executed")\n', encoding="utf-8")
        config = self.root / ".memory.json"
        data = json.loads(config.read_text(encoding="utf-8"))
        data.update(tool_version="3.0.0")
        data.pop("link_style")
        config.write_text(json.dumps(data), encoding="utf-8")
        before = self.snapshot()
        code, custom = self.analysis("tool-diff")
        self.assertEqual((code, custom["status"]), (0, "different"))
        self.assertEqual(custom["project_tool"]["version"], memory.VERSION)
        self.assertEqual(custom["configuration"]["tool_version_relation"], "older")
        self.assertEqual(custom["configuration"]["link_style_compatibility"], "legacy_default")
        self.assertFalse((self.project / "side-effect").exists())
        self.assertEqual(self.snapshot(), before)
        local.write_text('VERSION = "2.0.0"\n', encoding="utf-8")
        self.assertEqual(self.analysis("tool-diff")[1]["project_tool"]["version"], "2.0.0")
        local.write_text("# Legacy file has no version declaration\n", encoding="utf-8")
        _, legacy = self.analysis("tool-diff")
        self.assertEqual(legacy["status"], "different")
        self.assertIsNone(legacy["project_tool"]["version"])

    def test_tool_diff_unreadable_unsupported_and_oversized_reference(self):
        self.init()
        reference = self.project / "reference.py"
        for content, issue in ((None, "missing_file"), (b"\xff", "invalid_utf8"),
                               (b"#" * (memory.MAX_TOOL_BYTES + 1), "file_too_large")):
            if content is not None:
                reference.write_bytes(content)
            before = self.snapshot()
            code, report = self.analysis("tool-diff", "--reference-tool", "reference.py")
            self.assertEqual((code, report["status"]), (1, "not_comparable"))
            self.assertEqual(report["reference_tool"]["issue"], issue)
            self.assertEqual(self.snapshot(), before)
        code, report = self.analysis("tool-diff", "--reference-tool", "../unsafe.py")
        self.assertEqual((code, report["issue"]), (1, "unsafe_reference_path"))

    def test_tool_diff_standalone_requires_explicit_reference_and_rejects_self(self):
        self.init()
        local = self.root / "工具/memory.py"
        before = self.snapshot()
        for options, expected_code, expected_status in (
            ([], 1, "not_comparable"),
            (["--reference-tool", str(local)], 1, "not_comparable"),
            (["--reference-tool", str(Path(memory.__file__).resolve())], 0, "same"),
        ):
            result = subprocess.run([sys.executable, "-B", str(local), "tool-diff", "--project", str(self.project), *options],
                                    capture_output=True, text=True, encoding="utf-8", check=False)
            self.assertEqual(result.returncode, expected_code, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], expected_status)
        self.assertEqual(self.snapshot(), before)

    def test_new_read_only_commands_reject_apply(self):
        before = self.snapshot()
        self.assertEqual(self.run_cli("impact", "--base", "HEAD", "--apply")[0], 2)
        self.assertEqual(self.run_cli("tool-diff", "--apply")[0], 2)
        self.assertEqual(self.run_cli("impact")[0], 2)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
