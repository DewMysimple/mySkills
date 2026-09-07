#!/usr/bin/env python3
"""检查工程记忆页面并重建工作日志索引。仅使用 Python 标准库。"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


MANAGED_DIRS = {"当前状态", "决策", "知识", "日志"}
REQUIRED_FIELDS = {"type", "status", "kind", "importance", "updated", "topic"}
ALLOWED_TYPES = {"state", "decision", "knowledge", "log", "moc"}
ALLOWED_STATUSES = {"active", "proposed", "deprecated", "superseded", "archived"}
ALLOWED_KINDS = {
    "feature", "ui", "bug", "discussion", "test", "maintenance",
    "architecture", "process", "module", "operations",
}


@dataclass
class Page:
    path: Path
    fields: dict[str, str]
    body: str

    @property
    def rel(self) -> str:
        return self.path.as_posix()


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return {}, text

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            fields[match.group(1)] = match.group(2).strip()
    return fields, "\n".join(lines[end + 1 :])


def is_context_page(path: Path) -> bool:
    return bool(path.parts) and (
        path.parts[0] in MANAGED_DIRS
        or (len(path.parts) == 1 and path.name in {"README.md", "AGENTS.md"})
    )


def load_pages(root: Path) -> list[Page]:
    pages: list[Page] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root)
        if is_context_page(rel):
            fields, body = parse_frontmatter(path.read_text(encoding="utf-8"))
            pages.append(Page(rel, fields, body))
    return pages


def links_in(text: str) -> list[str]:
    text = re.sub(r"\x60\x60\x60.*?\x60\x60\x60", "", text, flags=re.DOTALL)
    text = re.sub(r"\x60[^\x60\n]*\x60", "", text)
    links: list[str] = []
    for match in re.finditer(r"\[\[([^\]]+)\]\]", text):
        target = match.group(1).split("|", 1)[0].strip()
        if target:
            links.append(target)
    for match in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = match.group(1).strip().strip("<>")
        if target and not re.match(r"^(?:https?|mailto):", target):
            links.append(target)
    return links


def resolve_link(source: Path, target: str) -> Path | None:
    target = target.split("#", 1)[0].replace("\\", "/")
    if not target or target.startswith(("http:", "https:", "mailto:")):
        return None
    candidate = Path(target)
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".md")
    if target.startswith(("./", "../")):
        return source.parent / candidate
    return candidate


def validate(root: Path, pages: list[Page]) -> list[str]:
    errors: list[str] = []
    by_path = {page.rel: page for page in pages}
    incoming = {page.rel: 0 for page in pages}

    for page in pages:
        if page.path.parts[0] in MANAGED_DIRS:
            missing = sorted(REQUIRED_FIELDS - page.fields.keys())
            if missing:
                errors.append(f"{page.rel}: missing frontmatter fields: {', '.join(missing)}")
        if page.fields.get("type") and page.fields["type"] not in ALLOWED_TYPES:
            errors.append(f"{page.rel}: invalid type {page.fields['type']}")
        if page.fields.get("status") and page.fields["status"] not in ALLOWED_STATUSES:
            errors.append(f"{page.rel}: invalid status {page.fields['status']}")
        if page.fields.get("kind") and page.fields["kind"] not in ALLOWED_KINDS:
            errors.append(f"{page.rel}: invalid kind {page.fields['kind']}")

        for target in links_in(page.body):
            resolved = resolve_link(page.path, target)
            if resolved is None:
                continue
            normalized = resolved.as_posix().lstrip("./")
            if normalized not in by_path and normalized not in {"README.md", "AGENTS.md"}:
                errors.append(f"{page.rel}: broken link {target}")
            elif normalized in incoming and normalized != page.rel:
                incoming[normalized] += 1

    active_topics: dict[tuple[str, str], list[str]] = {}
    for page in pages:
        if page.fields.get("status") == "active" and page.fields.get("type") in {"state", "decision"}:
            topic = page.fields.get("topic", "")
            if topic:
                active_topics.setdefault((page.fields["type"], topic), []).append(page.rel)
    for (page_type, topic), paths in active_topics.items():
        if len(paths) > 1:
            errors.append(f"multiple active {page_type} pages for topic {topic}: {', '.join(paths)}")

    for page in pages:
        if page.fields.get("type") in {"state", "decision", "knowledge", "log"} and incoming[page.rel] == 0:
            errors.append(f"orphan page: {page.rel}")

    return errors


def page_title(page: Page) -> str:
    for line in page.body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return page.path.stem


def index_logs(root: Path, pages: list[Page]) -> Path:
    logs = [
        page for page in pages
        if page.path.parts[0] == "日志" and page.fields.get("type") == "log"
        and page.path.name not in {"README.md", "MOC_工作日志.md"}
    ]
    logs.sort(key=lambda page: (page.fields.get("updated", ""), page.rel), reverse=True)
    lines = [
        "---",
        "type: moc",
        "status: active",
        "kind: process",
        "importance: high",
        f"updated: {logs[0].fields.get('updated', '2026-09-07') if logs else '2026-09-07'}",
        "topic: work-log-index",
        "source_logs: []",
        "supersedes: null",
        "---",
        "",
        "# 工作日志 MOC",
        "",
        "> 单一工作日志索引，按更新时间倒序。任务类型通过 kind 元数据区分。",
        "",
        "| 时间 | 类型 | 目标 | 状态 | 主题 | 日志 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    if not logs:
        lines.append("| - | - | 暂无记录 | - | - | - |")
    else:
        for page in logs:
            goal = "-"
            for line in page.body.splitlines():
                if "目标：" in line:
                    goal = line.split("目标：", 1)[1].strip().replace("|", "\\|")
                    break
            title = page_title(page).replace("|", "\\|")
            link = f"[[日志/{page.path.name}|{title}]]"
            lines.append(
                f"| {page.fields.get('updated', '-')} | {page.fields.get('kind', '-')} | "
                f"{goal} | {page.fields.get('status', '-')} | {page.fields.get('topic', '-')} | {link} |"
            )
    lines.extend([
        "",
        "## 使用方式",
        "",
        "- 由 python wiki_memory/工具/memory_lint.py index 生成或刷新。",
        "- 查询时先阅读当前状态，再按关键词定位日志。",
        "- 历史日志是审计记录，不应直接覆盖当前状态。",
        "",
        "## 入口",
        "",
        "- [[README|工程 Agent 记忆]]",
        "- [[AGENTS|记忆维护协议]]",
        "- [[日志/README|工作日志说明]]",
        "- [[当前状态/项目概览|当前项目概览]]",
        "- [[当前状态/系统架构|当前系统架构]]",
        "",
    ])
    output = root / "日志" / "MOC_工作日志.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("check", "index"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        print(f"记忆根目录不存在：{root}", file=sys.stderr)
        return 2

    pages = load_pages(root)
    if args.command == "index":
        output = index_logs(root, pages)
        print(f"已生成日志索引：{output}")
        return 0

    errors = validate(root, pages)
    if errors:
        print(f"发现 {len(errors)} 个问题：")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"记忆体检通过：检查 {len(pages)} 个 Markdown 页面。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
