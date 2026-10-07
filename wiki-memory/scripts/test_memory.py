"""Behavioral tests; all writes stay in temporary projects."""

import contextlib
import hashlib
import io
import json
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
        result = subprocess.run([sys.executable, str(self.root / "工具/memory.py"), "check", "--project", str(self.project), "--date", str(self.today)], capture_output=True, text=True, encoding="utf-8")
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

    def test_custom_nested_memory_location(self):
        self.init("--memory-dir", "docs/工程 记忆")
        code, output, error = self.run_cli("check", "--memory-dir", "docs/工程 记忆")
        self.assertEqual(code, 0, error)
        self.assertFalse(any("root instructions" in x for x in json.loads(output)["warnings"]))

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
