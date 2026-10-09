"""Behavioral tests; all writes stay in temporary projects."""

import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
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
        self.assertFalse(json.loads(output)["apply"])
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

        def new_log(pages):
            self.add_page("日志/concurrent.md", "log", "archived")
            return original(pages)

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

    def test_plain_source_path_can_contain_hash(self):
        self.init()
        source = self.project / "src/config#prod.py"
        source.parent.mkdir()
        source.write_text("VALUE = 1\n", encoding="utf-8")
        self.add_page("知识/config.md", sources=["src/config#prod.py"])
        self.assertEqual(self.run_cli("index", "--apply")[0], 0)
        self.assertEqual(self.check()[1]["errors"], [])

    def test_generated_wiki_paths_encode_hash_and_literal_percent_once(self):
        self.init()
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
