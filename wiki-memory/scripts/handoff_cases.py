#!/usr/bin/env python3
"""Create isolated, runnable projects for fresh-session memory evaluation.

Requires Git and Python 3.10+. No network or model API calls.
Default output is a new directory under the OS temporary directory.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.dont_write_bytecode = True
import memory

SOURCE = '''import csv
import io
import json
from pathlib import Path

def settings():
    return json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text(encoding="utf-8"))

def export_tasks(tasks):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["id", "title"])
    for task in tasks:
        writer.writerow([task["id"], task["title"]])
    return output.getvalue()
'''
TESTS = '''import csv
import io
import unittest
from src.exporter import export_tasks

class ExportTests(unittest.TestCase):
    def test_header(self):
        self.assertEqual(next(csv.reader(io.StringIO(export_tasks([])))), ["id", "title"])

    def test_single_task(self):
        rows = list(csv.reader(io.StringIO(export_tasks([{"id": 1, "title": "Read"}]))))
        self.assertEqual(rows, [["id", "title"], ["1", "Read"]])
'''
PROMPTS = {
    "interrupted": "接续当前任务，先说明已经完成、还剩什么、应该从哪些文件和命令开始。这轮只诊断，不修改文件。",
    "source_conflict": "查清当前工程的分页大小是多少，现有记忆是否准确，并给出依据。这轮只读。",
    "branch_change": "检查当前分支的存储行为与已有决策是否一致，给出接续建议，并说明历史验证能否代表现在。这轮只读。",
    "upgrade": "将这个工程的 lite 记忆升级为 standard，完成有证据的五页内容、日志分类和导航，保留现有源码与历史；在此临时工程内验证结果，不提交或推送。",
}


def run(project, *args):
    result = subprocess.run(args, cwd=project, capture_output=True, text=True, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"command failed {args!r}: {result.stdout}{result.stderr}")
    return result


def git(project, *args):
    return run(project, "git", "-c", "user.name=Memory Fixture", "-c", "user.email=fixture@example.invalid", *args)


def create_case(root: Path, name: str, today: date):
    project = root / name
    project.mkdir()
    (project / "src").mkdir()
    (project / "tests").mkdir()
    (project / "src/__init__.py").write_text("", encoding="utf-8")
    (project / "src/exporter.py").write_text(SOURCE, encoding="utf-8")
    (project / "tests/test_exporter.py").write_text(TESTS, encoding="utf-8")
    (project / "config.json").write_text(json.dumps({"page_size": 25, "storage": "sqlite"}), encoding="utf-8")
    (project / "README.md").write_text("# Task Export\n\n任务导出原型。测试：python -B -m unittest discover -s tests -q\n", encoding="utf-8")
    (project / "AGENTS.md").write_text("# 临时评测工程\n\n只在此工程内工作，保持源文件与历史。没有远程交付授权，不提交或推送。按当前任务的读写范围维护记忆。\n", encoding="utf-8")
    git(project, "init", "--quiet", "--initial-branch=main")
    git(project, "add", "--", ".")
    git(project, "commit", "--quiet", "-m", "Create task export prototype")
    revision = git(project, "rev-parse", "HEAD").stdout.strip()
    result = run(project, sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-q")
    with contextlib.redirect_stdout(io.StringIO()):
        plan, agents, previous = memory.initialize(project, project / "wiki_memory", "lite", today)
        memory.apply_plan(plan, project, True, agents, previous, new_root=project / "wiki_memory")
    page_size = 50 if name == "source_conflict" else 25
    progress = f"CSV 表头和单条导出已经实现；分页配置记录为 {page_size}。"
    body = {
        "项目目标与阶段": "任务导出原型，当前推进 CSV 导出的边界验证。",
        "关键入口与运行命令": "入口 src/exporter.py；配置 config.json；测试 tests/test_exporter.py。运行 python -B -m unittest discover -s tests -q。",
        "约束与已确认选择": "仅本地操作。已采用 SQLite 存储配置；实现与选择不一致时记录差异，不静默改成新决策。",
        "当前进度与已知问题": progress + "现有测试未覆盖逗号、引号和换行标题；尚未发现已复现的导出缺陷。",
        "恢复位置与下一步": "从 tests/test_exporter.py 增加特殊字符回归测试，必要时修改 src/exporter.py，再执行完整的本地测试。没有外部阻塞。",
        "证据与未核实项": f"本次初始化实际执行 python -B -m unittest discover -s tests -q，退出码 0，2 项通过；Python {sys.version.split()[0]}，revision {revision}，main 分支，测试时源码无本地改动。该结果是记忆写入时的验证，接续时重新检查分支和源码。",
    }
    text = "\n\n".join("## " + heading + "\n\n" + content for heading, content in body.items())
    state = memory.make_page("state", "active", "project-state", "当前状态", text, today)
    state = state.replace("sources: []", 'sources: ["src/exporter.py", "config.json", "tests/test_exporter.py", "AGENTS.md"]')
    (project / "wiki_memory/当前状态/当前状态.md").write_text(state, encoding="utf-8")
    log = memory.make_page("log", "archived", "csv-export-progress", "CSV 导出阶段验证",
                           "已实现表头和单条任务导出，特殊字符回归尚未覆盖。\n\n实际验证：python -B -m unittest discover -s tests -q\n\n"
                           + result.stdout + result.stderr + f"\nrevision: {revision}\n",
                           today, extra_fields={"kind": "feature", "task_status": "in_progress"})
    (project / "wiki_memory/日志" / (str(today) + "-导出阶段.md")).write_text(log, encoding="utf-8")
    if name == "branch_change":
        decisions = project / "wiki_memory/决策"
        decisions.mkdir()
        decision = memory.make_page("decision", "active", "storage-choice", "采用 SQLite", "工程已采用 SQLite 配置；JSON 仅为未决实验，不能用实现漂移替代有效选择。", today)
        decision = decision.replace("sources: []", 'sources: ["config.json"]')
        (decisions / "ADR-001-SQLite.md").write_text(decision, encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        code = memory.main(["index", "--project", str(project), "--apply", "--date", str(today)])
    if code:
        raise RuntimeError("fixture index failed")
    git(project, "add", "--", "wiki_memory", "AGENTS.md")
    git(project, "commit", "--quiet", "-m", "Record current engineering memory")
    if name == "branch_change":
        git(project, "switch", "--quiet", "-c", "experiment/json")
        (project / "config.json").write_text(json.dumps({"page_size": 25, "storage": "json"}), encoding="utf-8")
        git(project, "add", "--", "config.json")
        git(project, "commit", "--quiet", "-m", "Try JSON storage configuration")
    return {"case": name, "project": str(project), "request": PROMPTS[name]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="new directory; existing paths are refused")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)
    root = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="wiki-memory-handoff-")).resolve()
    if args.output:
        root.mkdir(parents=True, exist_ok=False)
    cases = [create_case(root, name, args.date) for name in PROMPTS]
    manifest = {"fixture_root": str(root), "cases": cases, "note": "isolated teaching projects; not real user task history"}
    (root / "cases.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
