#!/usr/bin/env python3
"""Project-local Markdown memory: initialize, check, index and review changes.

Python 3.10+, standard library only. Mutations require --apply.
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import posixpath
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PureWindowsPath
from urllib.parse import quote, unquote

AUTO_START = "<!-- wiki-memory:auto:start -->"
AUTO_END = "<!-- wiki-memory:auto:end -->"
HOOK_START = "<!-- wiki-memory:start -->"
HOOK_END = "<!-- wiki-memory:end -->"
MANAGED = {"当前状态", "决策", "知识", "日志"}
REQUIRED = {"type", "status", "updated", "topic"}
TYPES = {"state", "decision", "knowledge", "log", "moc"}
STATUSES = {"active", "proposed", "deprecated", "superseded", "archived"}
LOG_CATEGORIES = {
    "feature": "功能添加", "ui": "UI修改", "bug": "Bug处理",
    "discussion": "工程讨论", "test": "测试验证", "maintenance": "工程维护",
}
KINDS = set(LOG_CATEGORIES)
ENTRY = Path("README.md")
LEGACY_ENTRY = Path("入口.md")
LOG_INDEX = Path("日志/MOC_工作日志.md")
VERSION = "3.4.0"
LINK_STYLES = ("markdown", "wiki")
READ_BUDGET = {"startup_chars": 16000, "page_chars": 6000, "todo_items": 20}
CATALOGS = {
    "state": (Path("当前状态/MOC_状态.md"), "历史状态目录"),
    "decision": (Path("决策/MOC_决策.md"), "工程决策目录"),
    "knowledge": (Path("知识/MOC_知识.md"), "稳定知识目录"),
}
STATE_TITLES = {
    "lite": ["当前状态"],
    "standard": ["项目概览", "系统架构", "当前约束", "当前待办", "已知问题"],
}
STATE_SECTIONS = {
    "当前状态": ["项目目标与阶段", "关键入口与运行命令", "约束与已确认选择", "当前进度与已知问题", "恢复位置与下一步", "证据与未核实项"],
    "项目概览": ["项目目标与阶段", "核心入口", "工作区背景", "证据与未核实项"],
    "系统架构": ["模块职责与边界", "数据流与依赖", "运行与部署", "证据与未核实项"],
    "当前约束": ["用户要求与技术约束", "兼容性与操作边界", "证据与未核实项"],
    "当前待办": ["进行中", "下一步", "阻塞与恢复位置", "证据与未核实项"],
    "已知问题": ["未解决问题与影响", "复现与临时处理", "证据与未核实项"],
}
STATE_TOPICS = {
    "当前状态": "project-state", "项目概览": "project-overview", "系统架构": "system-architecture",
    "当前约束": "project-constraints", "当前待办": "current-todos", "已知问题": "known-issues",
}
STATE_PROMPTS = {
    "项目目标与阶段": "待核实：项目要解决的问题、当前阶段及完成边界；区分需求与已实现行为。",
    "核心入口": "待核实：源码、配置、启动命令和项目规则的实际入口；命令未执行时明确说明。",
    "工作区背景": "待核实：当前分支、revision、未提交改动及其归属；历史检查不能代表当前工作区。",
    "模块职责与边界": "待核实：实际模块入口、职责和接口边界；标明设计与实现差异。",
    "数据流与依赖": "待核实：实际调用或数据流、内部依赖和外部依赖；就近引用代码或配置。",
    "运行与部署": "待核实：运行环境、配置和部署方式；区分配置中的命令与实际运行结果。",
    "用户要求与技术约束": "待核实：用户明确要求、现行有效选择与技术限制，注明提出者和依据。",
    "兼容性与操作边界": "待核实：兼容目标、现有工作区保护和操作授权范围。",
    "进行中": "待核实：当前正在推进的焦点及实际完成程度；已完成事项留在日志。",
    "下一步": "待核实：可执行的下一步与验收条件；完整 backlog 链接原计划。",
    "阻塞与恢复位置": "待核实：具体阻塞、恢复文件或命令与接续条件；没有阻塞也说明核实范围。",
    "未解决问题与影响": "待核实：尚未解决的问题、影响范围和已观察证据；未知风险与已复现问题分开。",
    "复现与临时处理": "待核实：复现步骤、实际结果、环境和可用的临时处理；未复现则明确说明。",
    "关键入口与运行命令": "待核实：源码、配置及实际运行命令；未执行的命令不能记为验证结果。",
    "约束与已确认选择": "待核实：明确用户要求、现行决策及授权边界，注明依据。",
    "当前进度与已知问题": "待核实：已实现行为、进行中的焦点和具体未解决问题。",
    "恢复位置与下一步": "待核实：接续文件、命令、阻塞条件和可执行下一步。",
    "证据与未核实项": "待核实：列出事实来源与核实日期、环境、revision、未提交改动背景、实际验证结果及未验证范围；填写 sources/source_logs 后逐项核实。",
}
_UNREAD = object()


@dataclass
class Page:
    path: Path
    fields: dict
    body: str
    errors: list[str]
    original: bytes = b""

    @property
    def rel(self):
        return self.path.as_posix()

    @property
    def title(self):
        match = re.search(r"^# (.+)$", self.body, re.MULTILINE)
        return match.group(1).strip() if match else self.path.stem


def read_text(path: Path) -> str:
    # Decode bytes directly to preserve BOM and CRLF outside generated regions.
    return path.read_bytes().decode("utf-8")


def scalar(raw: str):
    raw = raw.strip()
    if raw in {"null", "Null", "NULL", "~"}:
        return None
    if raw.startswith(('"', "[")):
        value = json.loads(raw)
        if not isinstance(value, (str, list)):
            raise ValueError("expected string or string list")
        if isinstance(value, list) and not all(isinstance(x, str) for x in value):
            raise ValueError("list items must be strings")
        return value
    if raw.startswith("'"):
        if not raw.endswith("'") or len(raw) < 2:
            raise ValueError("unclosed quoted scalar")
        return raw[1:-1].replace("''", "'")
    if raw.startswith(("|", ">", "&", "*", "!", "{")):
        raise ValueError("complex YAML is unsupported")
    return raw


def parse_page(path: Path, text: str) -> Page:
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        return Page(path, {}, text, [], text.encode("utf-8"))
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return Page(path, {}, text, ["unclosed frontmatter"], text.encode("utf-8"))
    fields, errors, current = {}, [], None
    for number, line in enumerate(lines[1:end], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            item = re.fullmatch(r"\s+-\s+(.+)", line)
            if item and current:
                value = scalar(item.group(1))
                if not isinstance(value, str):
                    raise ValueError("list item must be a string")
                fields[current].append(value)
                continue
            match = re.fullmatch(r"([A-Za-z_][\w-]*):\s*(.*)", line)
            if not match:
                raise ValueError("unsupported YAML; use scalars or string lists")
            key, raw = match.groups()
            if key in fields:
                raise ValueError(f"duplicate field {key}")
            fields[key] = scalar(raw) if raw else []
            current = key if not raw else None
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(f"frontmatter line {number}: {exc}")
            current = None
    return Page(path, fields, "\n".join(lines[end + 1:]), errors, text.encode("utf-8"))


def without_code(text: str) -> str:
    result, fence, length = [], None, 0
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if match:
            marker, tail = match.groups()
            if fence is None:
                fence, length = marker[0], len(marker)
            elif marker[0] == fence and len(marker) >= length and not tail.strip():
                fence = None
            continue
        if fence is None:
            result.append(line)
    prose = re.sub(r"<!--[\s\S]*?(?:-->|$)", "", "\n".join(result))
    return re.sub(r"(`+).*?\1", "", prose)


def links(text: str):
    text = without_code(text)
    for match in re.finditer(r"\[\[([^\]]+)\]\]", text):
        yield "wiki", match.group(1).split("|", 1)[0].rstrip("\\").strip()
    for match in re.finditer(r"\[(?:\\.|[^\]\\\n])*\]\((<[^>]+>|(?:[^()\n]|\([^()\n]*\))+)\)", text):
        target = match.group(1).strip()
        if not target.startswith("<"):
            target = re.split(r'\s+[\"\']', target, maxsplit=1)[0]
        yield "markdown", target.strip("<>")
    for match in re.finditer(r"^\s*\[[^\]]+\]:\s*(<[^>]+>|\S+)", text, re.MULTILINE):
        yield "markdown", match.group(1).strip("<>")


def within(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def linked_entry(info) -> bool:
    return bool(stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


def read_scoped_bytes(path: Path, root: Path):
    # Compare with the canonical boundary established by locations().
    try:
        inside = path.resolve().is_relative_to(root)
    except RuntimeError:
        inside = False
    if not inside:
        raise ValueError(f"read target escapes {root.name}: {path.name}")
    if os.path.lexists(path) and not path.is_file():
        raise ValueError(f"read target is not a regular file: {path.name}")
    return observed_bytes(path)


def read_memory_config(memory: Path):
    return read_scoped_bytes(memory / ".memory.json", memory)


def effective_root_instructions(project: Path):
    override = project / "AGENTS.override.md"
    raw = read_scoped_bytes(override, project)
    if raw and raw.decode("utf-8").lstrip("\ufeff").strip():
        return override, raw
    agents = project / "AGENTS.md"
    return agents, read_scoped_bytes(agents, project)


def safe_write_target(path: Path, project: Path):
    if not within(path, project):
        raise ValueError(f"write target escapes project: {path}")
    cursor = path
    while cursor != project:
        if os.path.lexists(cursor) and linked_entry(cursor.lstat()):
            raise ValueError(f"refusing write through symlink or reparse point: {cursor}")
        if cursor == cursor.parent:
            raise ValueError("invalid project boundary")
        cursor = cursor.parent


def locations(project_arg: str, memory_arg: str):
    project = Path(project_arg).resolve()
    if not project.is_dir():
        raise ValueError(f"project directory does not exist: {project}")
    normalized = memory_arg.replace("\\", "/")
    parts = normalized.split("/")
    if any(p in {"", ".", ".."} or not re.fullmatch(r"[\w .-]+", p) for p in parts):
        raise ValueError("memory-dir must be a safe project-relative directory")
    memory = project.joinpath(*parts)
    safe_write_target(memory, project)
    return project, memory


def scan_folder(name: str) -> bool:
    return not name.startswith(".") and name.casefold() not in {
        "node_modules", "vendor", "venv", "env", "dist", "build", "__pycache__",
    }


def memory_items(root: Path):
    """Inventory memory files without descending through linked directories."""
    def walk_error(exc):
        raise exc

    for directory, folders, files in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(directory)
        descend = []
        for name in sorted(folders):
            if name.startswith("."):
                continue
            path = parent / name
            info = path.lstat()
            if not linked_entry(info):
                descend.append(name)
            yield path, info
        folders[:] = descend
        for name in sorted(files):
            if not name.startswith(".") or name in {".memory.json", ".gitkeep"}:
                path = parent / name
                yield path, path.lstat()


def page_paths(memory: Path) -> list[Path]:
    if not memory.is_dir():
        raise ValueError(f"memory directory does not exist: {memory}")
    candidates = [path for path in memory.iterdir() if not path.name.startswith(".")]
    for folder in sorted(MANAGED):
        base = memory / folder
        try:
            info = base.lstat()
        except FileNotFoundError:
            continue
        if linked_entry(info):
            raise ValueError(f"refusing symlinked memory section: {base}")
        if stat.S_ISDIR(info.st_mode):
            candidates.extend(path for path, _ in memory_items(base))
    paths = []
    for path in candidates:
        if path.suffix.lower() != ".md":
            continue
        if not path.resolve().is_relative_to(memory):
            raise ValueError(f"memory page escapes memory directory: {path}")
        if path.is_file():
            paths.append(path)
    return sorted(paths)


def load_pages(memory: Path) -> list[Page]:
    return [parse_page(path.relative_to(memory), read_text(path)) for path in page_paths(memory)]


def refuse_competing_memory(project: Path, memory: Path, instructions: str):
    candidates = {project / "wiki_memory", project / "docs/wiki_memory"}
    tokens = [(token, False) for token in re.findall(r"`([^`\r\n]+)`", instructions)]
    tokens.extend((target, kind == "markdown") for kind, target in links(instructions))
    tokens.extend((token, False) for token in re.findall(r"(?<![\w./\\-])(?:[\w.-]+[/\\])+(?:AGENTS\.md|入口\.md|README\.md|\.memory\.json)", instructions))
    for token, encoded in tokens:
        token = (unquote(token) if encoded else token).replace("\\", "/").rstrip("/")
        if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", token) or token.startswith("/") or re.search(r'[<>:"|?*]', token):
            continue
        if token.endswith(("/AGENTS.md", "/入口.md", "/README.md", "/.memory.json")):
            token = token.rsplit("/", 1)[0]
        candidate = project / token
        try:
            if within(candidate, project):
                candidates.add(candidate)
        except (OSError, ValueError):
            continue
    for candidate in sorted(candidates):
        if candidate.resolve() == memory.resolve() or not candidate.is_dir():
            continue
        if (candidate / ".memory.json").is_file() or ((candidate / "AGENTS.md").is_file() and (candidate / "当前状态").is_dir()):
            rel = candidate.relative_to(project).as_posix()
            raise ValueError(f"existing memory found at {rel}; inspect/migrate it instead of initializing another location")


def instruction_prose(text: str) -> str:
    """Keep inline path literals and hook markers, exclude documentation examples."""
    lines, fence, length, comment = [], None, 0, False
    for line in text.splitlines():
        if fence is None:
            visible, position = [], 0
            while position < len(line):
                if comment:
                    end = line.find("-->", position)
                    if end < 0:
                        break
                    comment, position = False, end + 3
                else:
                    start = line.find("<!--", position)
                    if start < 0:
                        visible.append(line[position:])
                        break
                    visible.append(line[position:start])
                    end = line.find("-->", start)
                    marker = line[start:end + 3] if end >= 0 else ""
                    if marker in {HOOK_START, HOOK_END} and line.strip() == marker:
                        visible.append(marker)
                        position = end + 3
                    else:
                        comment, position = True, start + 4
            line = "".join(visible)
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker:
            chars, tail = marker.groups()
            if fence is None:
                fence, length = chars[0], len(chars)
            elif chars[0] == fence and len(chars) >= length and not tail.strip():
                fence = None
            continue
        if fence is None and not re.match(r"^(?: {4}|\t|\s*>)", line):
            lines.append(line)
    return "\n".join(lines)


def memory_hook_status(text: str, relative: str, entry: Path = ENTRY):
    normalized = instruction_prose(text).replace("\\", "/")
    flags = re.IGNORECASE if os.name == "nt" else 0
    def references(prose):
        # Natural-language directives remain a manual-review concern. Obvious
        # negative examples must not count as affirmative discovery instructions.
        clauses = re.split(r"[;\n；。]|(?<=[.!?])\s+", prose)
        eligible = "\n".join(line for line in clauses if not re.search(
            r"不要|禁止|不得|无需|不必|\b(?:never|do\s+not|don't|must\s+not)\b", line, re.IGNORECASE))
        return (bool(re.search(r"读取|阅读|\b(?:read|load)\b", eligible, re.IGNORECASE))
                and all(re.search(r"(?<![\w./-])(?:\./)?" + re.escape(relative + "/" + name)
                                  + r"(?![\w/-]|\.[\w.-])", eligible, flags)
                        for name in ("AGENTS.md", entry.as_posix())))
    starts, ends = normalized.count(HOOK_START), normalized.count(HOOK_END)
    if starts or ends:
        if starts != 1 or ends != 1 or normalized.index(HOOK_START) > normalized.index(HOOK_END):
            return "invalid"
        block = normalized.split(HOOK_START, 1)[1].split(HOOK_END, 1)[0]
        return "managed" if references(block) else "invalid"
    return "legacy" if references(normalized) else "missing"


def has_memory_hook(text: str, relative: str, entry: Path = ENTRY):
    return memory_hook_status(text, relative, entry) in {"managed", "legacy"}


def read_budget_config(data: dict):
    overrides = data.get("read_budget", {})
    if (not isinstance(overrides, dict) or set(overrides) - READ_BUDGET.keys()
            or any(type(value) is not int or value < 0 for value in overrides.values())):
        raise ValueError("read_budget supports nonnegative integer startup_chars/page_chars/todo_items; 0 disables a limit")
    return {**READ_BUDGET, **overrides}


def read_budget_report(project: Path, memory: Path, pages: list[Page], data: dict, *, instructions=None):
    limits = read_budget_config(data)
    mode = data.get("mode", "lite")
    titles = ["项目概览", "当前约束", "当前待办"] if mode == "standard" else ["当前状态"]
    agents, raw = effective_root_instructions(project) if instructions is None else instructions
    startup = [Path("AGENTS.md"), ENTRY, *(Path("当前状态") / (title + ".md") for title in titles)]
    sizes = {p.path: len(p.original.decode("utf-8").lstrip("\ufeff")) for p in pages}
    startup_sizes = {agents.relative_to(project).as_posix(): len(raw.decode("utf-8").lstrip("\ufeff"))} if raw is not None else {}
    startup_sizes.update({(memory / p).relative_to(project).as_posix(): sizes[p] for p in startup if p in sizes})
    todo_title = "当前待办" if mode == "standard" else "当前状态"
    todo = next((p for p in pages if p.path == Path("当前状态") / (todo_title + ".md")), None)
    items = 0
    if todo:
        sections = {"进行中", "下一步", "阻塞与恢复位置"} if mode == "standard" else {"当前进度与已知问题", "恢复位置与下一步"}
        current = None
        for line in without_code(todo.body).splitlines():
            heading = re.fullmatch(r"##\s+(.+?)\s*", line)
            if heading:
                current = heading.group(1)
            elif current in sections and re.match(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", line) and not re.match(r"^\s*[-*+]\s+\[[xX]\]", line):
                items += 1
    warnings = []
    total = sum(startup_sizes.values())
    if limits["startup_chars"] and total > limits["startup_chars"]:
        warnings.append(f"read budget: startup pages total {total} characters exceeds {limits['startup_chars']}; keep navigation short and move detail to task-specific pages")
    for path, size in sizes.items():
        if limits["page_chars"] and size > limits["page_chars"]:
            warnings.append(f"{path.as_posix()}: read budget: {size} characters exceeds {limits['page_chars']}; split stable topics or move completed detail to logs")
    if limits["todo_items"] and items > limits["todo_items"]:
        warnings.append(f"read budget: pending todo entries {items} exceeds {limits['todo_items']}; retain the current focus and link the backlog")
    return {"unit": "characters (not model tokens)", "limits": limits, "startup_pages": startup_sizes,
            "startup_chars": total, "todo_items": items, "warnings": warnings}


def project_markdown_paths(project: Path):
    """Reference inventory, excluding dependencies, build output and symlinks."""
    for directory, folders, files in os.walk(project, followlinks=False):
        parent = Path(directory)
        folders[:] = sorted(name for name in folders if scan_folder(name)
                            and not linked_entry((parent / name).lstat()))
        for name in sorted(files):
            path = parent / name
            if name.startswith(".") or path.suffix.lower() != ".md":
                continue
            info = path.lstat()
            if stat.S_ISREG(info.st_mode) and not linked_entry(info) and within(path, project):
                yield path


def migration_plan(project: Path, memory: Path, mode: str | None):
    """Inventory only: no writes, guessed classifications or automatic link edits."""
    destination = project / "wiki_memory"
    safe_write_target(destination, project)
    pages = load_pages(memory)
    blockers, observations = [], []
    try:
        raw = read_memory_config(memory)
        data = json.loads(raw.decode("utf-8-sig")) if raw is not None else {}
        if not isinstance(data, dict):
            raise ValueError("configuration must be an object")
    except (ValueError, OSError) as exc:
        data = {}
        blockers.append(f".memory.json: {exc}")
    current_mode = data.get("mode")
    if not isinstance(current_mode, str) or current_mode not in {"lite", "standard"}:
        current_mode = "standard" if all(any(p.path == Path("当前状态") / (title + ".md") for p in pages)
                                          for title in STATE_TITLES["standard"]) else "lite"
        observations.append(f"mode not configured; inferred {current_mode} from state filenames; verify the choice")
    selected_mode = mode or current_mode
    if current_mode == "standard" and selected_mode == "lite":
        blockers.append("standard to lite requires an explicit content consolidation decision; this planner does not downgrade it")
    if destination != memory and destination.exists():
        blockers.append("target wiki_memory already exists; reconcile competing roots before moving files")
    files = []
    for path, info in memory_items(memory):
        if linked_entry(info) or not within(path, memory):
            blockers.append(f"refusing symlinked or escaping migration item: {path.relative_to(memory).as_posix()}")
        elif stat.S_ISREG(info.st_mode):
            files.append(path)
    mapping = {path.resolve(): destination / path.relative_to(memory) for path in files}
    by_path = {p.path: p for p in pages}
    unclassified = []
    for page in pages:
        if page.errors:
            blockers.extend(f"{page.rel}: {error}" for error in page.errors)
        if selected_mode != "standard" or page.fields.get("type") != "log":
            continue
        kind = page.fields.get("kind")
        if not isinstance(kind, str) or kind not in LOG_CATEGORIES:
            unclassified.append({"path": page.rel, "kind": kind, "reason": "read the task record and select its primary kind; do not infer from the filename"})
            continue
        # Keep subtask paths, replacing an old category rather than nesting it.
        tail = page.path.parts[2:] if len(page.path.parts) > 2 and page.path.parts[0] == "日志" else (page.path.name,)
        mapping[(memory / page.path).resolve()] = destination / "日志" / LOG_CATEGORIES[kind] / Path(*tail)
    merges = []
    old_entry = memory / LEGACY_ENTRY
    if old_entry in files:
        sources = [old_entry]
        if memory / ENTRY in files:
            sources.insert(0, memory / ENTRY)
        mapping[old_entry.resolve()] = destination / ENTRY
        merges.append({"sources": [p.relative_to(project).as_posix() for p in sources],
                       "destination": (destination / ENTRY).relative_to(project).as_posix(),
                       "action": "merge manual explanations outside the generated region, repair references, then retire 入口.md; preserve all nonduplicate content"})
    grouped = {}
    for source, target in mapping.items():
        grouped.setdefault(target, []).append(source)
    conflicts = []
    for target, sources in sorted(grouped.items()):
        navigation_merge = target == destination / ENTRY and set(sources) <= {(memory / ENTRY).resolve(), old_entry.resolve()}
        if len(sources) > 1 and not navigation_merge:
            conflicts.append({"destination": target.relative_to(project).as_posix(),
                              "sources": [p.relative_to(project).as_posix() for p in sources], "reason": "multiple source files map to the same destination"})
        if target.exists() and target.resolve() not in sources and not navigation_merge:
            conflicts.append({"destination": target.relative_to(project).as_posix(),
                              "sources": [p.relative_to(project).as_posix() for p in sources], "reason": "destination is occupied; never overwrite it"})
    references, unresolved = [], []
    scanned = 0
    reference_paths = set(project_markdown_paths(project))
    reference_paths.update(memory / page.path for page in pages)
    for path in sorted(reference_paths):
        scanned += 1
        source_path = path.resolve()
        page = by_path.get(path.relative_to(memory)) if within(path, memory) else None
        if page is None:
            try:
                page = parse_page(Path(os.path.relpath(path, memory)), read_text(path))
            except (OSError, UnicodeError) as exc:
                observations.append(f"reference scan skipped {path.relative_to(project).as_posix()}: {exc}; inspect its encoding/access manually")
                continue
        new_source = mapping.get(source_path, path)
        targets = [(kind, raw, "body") for kind, raw in links(page.body)]
        for field in ("sources", "source_logs", "supersedes"):
            values = page.fields.get(field, [])
            if not isinstance(values, list):
                values = [values]
            for value in values:
                if isinstance(value, str) and value.strip():
                    nested = list(links(value)) or [("source" if field == "sources" else "wiki", value)]
                    targets.extend((kind, raw, field) for kind, raw in nested)
        for kind, raw, field in targets:
            try:
                target = resolve_target(kind, raw, page, project, memory, pages, require_exists=False)
                if target is None:
                    continue
                if not target.exists():
                    if source_path in mapping or within(target, memory):
                        unresolved.append({"file": path.relative_to(project).as_posix(), "field": field, "target": raw, "reason": "target is already missing; manually trace its revision or repair it"})
                    continue
                new_target = mapping.get(target, target)
                if kind == "source":
                    proposed = new_target.relative_to(project).as_posix()
                    changed = new_target != target
                elif kind == "wiki":
                    if not within(new_target, destination):
                        if new_source != source_path:
                            unresolved.append({"file": path.relative_to(project).as_posix(), "field": field, "target": raw, "reason": "wiki target outside the new memory root; replace with a project-relative Markdown link"})
                        continue
                    proposed = new_target.relative_to(destination).as_posix()
                    proposed = "".join(quote(char, safe="") if char in "%#?[]|" else char for char in proposed)
                    changed = new_target != target or memory != destination
                else:
                    proposed = quote(Path(os.path.relpath(new_target, new_source.parent)).as_posix(), safe="/")
                    changed = new_target != target or new_source.parent != source_path.parent
                if not changed:
                    continue
                if kind != "source":
                    suffix = re.search(r"[#?].*$", raw)
                    if suffix:
                        proposed += suffix.group()
                references.append({"file": path.relative_to(project).as_posix(), "file_after": new_source.relative_to(project).as_posix(),
                                   "field": field, "kind": kind, "target": raw, "proposed_target": proposed})
            except (ValueError, OSError) as exc:
                unresolved.append({"file": path.relative_to(project).as_posix(), "field": field, "target": raw, "reason": str(exc)})
        # Root hooks often use inline code literals, which are not Markdown links.
        if path.parent == project and path.name in {"AGENTS.md", "AGENTS.override.md", "README.md"}:
            prose = instruction_prose(read_text(path)).replace("\\", "/")
            old_relative = memory.relative_to(project).as_posix()
            for name in ("AGENTS.md", ENTRY.as_posix(), LEGACY_ENTRY.as_posix()):
                old = old_relative + "/" + name
                new = "wiki_memory/" + (ENTRY.as_posix() if name == LEGACY_ENTRY.as_posix() else name)
                if old != new and re.search(r"(?<![\w./-])(?:\./)?" + re.escape(old) + r"(?![\w.-])", prose):
                    references.append({"file": path.name, "file_after": path.name, "field": "instruction prose",
                                       "kind": "literal", "target": old, "proposed_target": new})
    required = []
    for title in STATE_TITLES[selected_mode]:
        page = by_path.get(Path("当前状态") / (title + ".md"))
        issues = state_readiness(page, title) if page else ["missing state page"]
        if issues:
            required.append({"path": "当前状态/" + title + ".md", "sections": STATE_SECTIONS[title], "issues": issues})
    return {"read_only": True, "source": memory.relative_to(project).as_posix(), "destination": "wiki_memory",
            "current_mode": current_mode, "target_mode": selected_mode,
            "moves": [{"source": p.relative_to(project).as_posix(), "destination": target.relative_to(project).as_posix()}
                      for p, target in sorted(mapping.items()) if p != target],
            "navigation_merges": merges, "conflicts": conflicts, "unclassified_logs": unclassified,
            "affected_references": references, "unresolved_references": unresolved,
            "reference_scan": {"markdown_files": scanned, "scope": "project Markdown, metadata sources and root instruction literals; dependencies/build output/symlinks excluded; code/config literals require manual review"},
            "configuration_changes": {"schema_version": 2, "mode": selected_mode, "navigation": "README.md", "tool_version": VERSION},
            "required_state_work": required,
            "required_log_directories": ["日志/" + name for name in LOG_CATEGORIES.values()] if selected_mode == "standard" else [],
            "blockers": blockers, "observations": observations,
            "manual_steps": ["re-read files and resolve conflicts/unclassified logs before executing this advisory plan",
                             "preserve history, dates, recorded commands and custom configuration/protocol fields",
                             "populate required state content from project evidence; retire duplicate active lite state only after consolidation",
                             "update root hooks and the project tool/protocol without overwriting custom rules",
                             "preview/apply index, run check --require-ready, then review content and diff"]}


def resolve_target(kind, raw, source: Page, project: Path, memory: Path, pages: list[Page], require_exists=True):
    raw_path = raw.strip() if kind == "source" else raw.strip().split("#", 1)[0].split("?", 1)[0]
    # Literal legacy separators are portable; an encoded backslash in a URL
    # remains a filename character on systems that permit it.
    target = raw_path.replace("\\", "/")
    if kind != "source":
        target = unquote(target, errors="strict")
    if not target:
        return None
    if target.startswith(("用户指令：", "用户确认：", "user:")):
        return None
    if re.match(r"^[A-Za-z]:", target) or target.startswith(("/", "\\", "file:")):
        raise ValueError(f"machine-specific or absolute link: {raw}")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    if kind == "wiki":
        rel = Path(target)
        path = memory / rel
        candidates = {rel.name, rel.name + ".md"} if rel.suffix.lower() != ".md" else {rel.name}
        if not path.exists() and rel.suffix.lower() != ".md":
            path = memory / Path(target + ".md")
        if not path.exists() and "/" not in target:
            matches = [memory / p.path for p in pages if p.path.name in candidates]
            if len(matches) > 1:
                raise ValueError(f"ambiguous wiki link: {raw}")
            if matches:
                path = matches[0]
    elif kind == "source":
        path = project / target
    else:
        path = memory / source.path.parent / target
    path = path.resolve()
    if not within(path, project):
        raise ValueError(f"link escapes project: {raw}")
    if require_exists and not path.exists():
        raise ValueError(f"missing link/source: {raw}")
    return path


def page_links(page: Page):
    yield from links(page.body)
    for field in ("sources", "source_logs", "supersedes"):
        values = page.fields.get(field, [])
        if values is None:
            continue
        if not isinstance(values, list):
            values = [values]
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            nested = list(links(value))
            yield from nested or [("source" if field == "sources" else "wiki", value)]


def iso_date(value):
    parsed = date.fromisoformat(str(value))
    if parsed.isoformat() != value:
        raise ValueError("expected YYYY-MM-DD")
    return parsed


def is_verified_revision(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{7,64}", value) is not None


def supersession_errors(project, memory, pages):
    errors, edges = [], {}
    by_path = {p.path: p for p in pages}
    for page in pages:
        raw = page.fields.get("supersedes")
        if raw is None:
            continue
        if not isinstance(raw, str) or not raw.strip():
            errors.append(f"{page.rel}: supersedes must be a nonempty link or null")
            continue
        references = list(links(raw)) or [("wiki", raw)]
        if len(references) != 1:
            errors.append(f"{page.rel}: supersedes must reference one memory page")
            continue
        try:
            target = resolve_target(*references[0], page, project, memory, pages)
            other = by_path.get(target.relative_to(memory)) if target and within(target, memory) else None
            if other is None or other.fields.get("type") != page.fields.get("type"):
                raise ValueError("supersedes must reference a memory page of the same type")
            edges[page.rel] = other.rel
            if page.fields.get("status") == "active" and page.fields.get("type") != "log" and other.fields.get("status") != "superseded":
                errors.append(f"{page.rel}: active replacement requires {other.rel} to be superseded")
        except ValueError as exc:
            errors.append(f"{page.rel}: {exc}")
    for start in edges:
        seen, current = set(), start
        while current in edges:
            if current in seen:
                errors.append(f"supersession cycle involving {current}")
                break
            seen.add(current)
            current = edges[current]
    return errors


def state_readiness(page: Page, title: str) -> list[str]:
    """Structural delivery checks; a pass still requires human semantic review."""
    issues = []
    if page.fields.get("status") != "active":
        issues.append(f"{page.rel}: required state is not active; establish project facts before delivery")
    if not page.fields.get("sources") and not page.fields.get("source_logs"):
        issues.append(f"{page.rel}: required state has no evidence references")
    sections, current, content, fence, length = {}, None, [], None, 0
    for line in page.body.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if marker:
            chars, tail = marker.groups()
            if fence is None:
                fence, length = chars[0], len(chars)
            elif chars[0] == fence and len(chars) >= length and not tail.strip():
                fence = None
        heading = re.fullmatch(r"##\s+(.+?)\s*", line) if fence is None else None
        if heading:
            if current is not None:
                sections[current] = "\n".join(content).strip()
            current, content = heading.group(1), []
        elif current is not None:
            content.append(line)
    if current is not None:
        sections[current] = "\n".join(content).strip()
    for heading in STATE_SECTIONS[title]:
        if heading not in sections:
            issues.append(f"{page.rel}: required section missing: {heading}")
        else:
            visible = re.sub(r"<!--[\s\S]*?(?:-->|$)", "", sections[heading])
            visible = re.sub(r"^\s*(?:#{1,6}\s+.*|`{3,}.*|~{3,}.*)$", "", visible, flags=re.MULTILINE).strip()
            if visible in {"", "-", "- 待核实。", "- " + STATE_PROMPTS[heading]}:
                issues.append(f"{page.rel}: required section is still scaffold: {heading}")
    return issues


def standard_log_issues(memory: Path, pages: list[Page]) -> list[str]:
    """Standard mode stores every log under its primary kind's directory."""
    issues = []
    for folder in LOG_CATEGORIES.values():
        directory = memory / "日志" / folder
        try:
            info = safe_path_stat(directory, memory)
        except ValueError:
            info = None
        if info is None or not stat.S_ISDIR(info.st_mode):
            issues.append(f"日志/{folder}: required standard log directory missing, symlinked or escaping memory root; explicitly migrate the log layout")
    for page in pages:
        if page.fields.get("type") != "log":
            continue
        kind = page.fields.get("kind")
        if not isinstance(kind, str) or kind not in LOG_CATEGORIES:
            issues.append(f"{page.rel}: standard log requires a valid kind before classification")
            continue
        expected = ("日志", LOG_CATEGORIES[kind])
        if len(page.path.parts) < 3 or page.path.parts[:2] != expected:
            issues.append(f"{page.rel}: standard log kind {kind} requires 日志/{expected[1]}/; explicitly migrate and repair references")
    return issues


def legacy_log_layout(data: dict) -> bool:
    """A missing/old version enables read-only compatibility, never delivery."""
    if data["schema_version"] == 1:
        return True
    version = data.get("tool_version")
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version) if isinstance(version, str) else None
    return version is None or bool(match and tuple(map(int, match.groups())) < (3, 1, 0))


def inspect(project: Path, memory: Path, pages: list[Page], today: date, stale_days: int, metadata_only=False, *, config_bytes=_UNREAD, require_ready=False):
    errors, warnings, active, numbers = [], [], {}, {}
    if not pages:
        errors.append("memory directory contains no Markdown pages")
    graph = {p.rel: set() for p in pages}
    for page in pages:
        errors.extend(f"{page.rel}: {error}" for error in page.errors)
        f = page.fields
        page_type = str(f.get("type", ""))
        if page.path.parts[0] in MANAGED or f:
            missing = [k for k in sorted(REQUIRED) if not isinstance(f.get(k), str) or not f[k].strip()]
            if missing:
                errors.append(f"{page.rel}: missing/invalid fields: {', '.join(missing)}")
            for key, allowed in (("type", TYPES), ("status", STATUSES)):
                if f.get(key) is not None and str(f[key]) not in allowed:
                    errors.append(f"{page.rel}: invalid {key}: {f[key]}")
            try:
                updated = iso_date(f.get("updated", ""))
                if updated > today:
                    warnings.append(f"{page.rel}: future updated date; verify clock or evidence")
                verified = iso_date(f["verified"]) if "verified" in f else None
                if verified and (verified > updated or verified > today):
                    errors.append(f"{page.rel}: verified date cannot be later than updated or today")
                if f.get("status") == "active" and page_type in {"state", "knowledge"} and (today - (verified or updated)).days > stale_days:
                    label = "verification" if verified else "edit"
                    warnings.append(f"{page.rel}: old {label} date; review relevant sources")
            except ValueError:
                errors.append(f"{page.rel}: invalid updated/verified date")
            if "verified_rev" in f and (not is_verified_revision(f["verified_rev"]) or "verified" not in f):
                errors.append(f"{page.rel}: verified_rev requires verified and a 7–64 digit hexadecimal commit ID")
            for field in ("sources", "source_logs"):
                value = f.get(field, [])
                if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
                    errors.append(f"{page.rel}: {field} must be a string list")
            if f.get("supersedes") is not None and not isinstance(f["supersedes"], str):
                errors.append(f"{page.rel}: supersedes must be a link or null")
            if f.get("type") == "log":
                if f.get("kind") is not None and str(f["kind"]) not in KINDS:
                    errors.append(f"{page.rel}: invalid log kind")
                if f.get("task_status") is not None and str(f["task_status"]) not in {"completed", "in_progress", "blocked", "abandoned"}:
                    errors.append(f"{page.rel}: invalid task_status")
            if f.get("status") == "active" and page_type in {"state", "decision", "knowledge"}:
                active.setdefault((str(f["type"]), str(f.get("topic", ""))), []).append(page.rel)
                if not f.get("sources") and not f.get("source_logs"):
                    warnings.append(f"{page.rel}: active page has no evidence references")
        match = re.match(r"ADR-(\d+)-", page.path.name)
        if match and f.get("type") == "decision":
            numbers.setdefault(int(match.group(1)), []).append(page.rel)
        for kind, target in ([] if metadata_only else page_links(page)):
            try:
                path = resolve_target(kind, target, page, project, memory, pages, require_exists=False)
                if path is not None and not path.exists():
                    historical = page_type == "log" or str(f.get("status", "")) in {"archived", "superseded", "deprecated"}
                    internal_page = within(path, memory) and path.suffix.lower() == ".md"
                    if historical and not internal_page:
                        warnings.append(f"{page.rel}: historical source no longer exists: {target}; trace its recorded revision")
                        continue
                    raise ValueError(f"missing link/source: {target}")
                if path is not None and within(path, memory):
                    rel = path.relative_to(memory).as_posix()
                    if rel in graph:
                        graph[page.rel].add(rel)
            except ValueError as exc:
                errors.append(f"{page.rel}: {exc}")
    for key, paths in active.items():
        if len(paths) > 1:
            errors.append(f"multiple active {key}: {', '.join(paths)}")
    for number, paths in numbers.items():
        if len(paths) > 1:
            errors.append(f"duplicate ADR-{number}: {', '.join(paths)}")
    errors.extend(supersession_errors(project, memory, pages))
    if not metadata_only and not any(p.fields.get("type") == "state" and p.fields.get("status") == "active" for p in pages):
        warnings.append("no active current state; initial project facts are not yet established")
    for page in ([] if metadata_only else pages):
        if page.fields.get("type") == "log" and page.rel not in graph.get(LOG_INDEX.as_posix(), set()):
            errors.append(f"{page.rel}: missing from log MOC; refresh index")
        category = CATALOGS.get(str(page.fields.get("type", "")))
        if any(p.as_posix() in graph for p in (ENTRY, LEGACY_ENTRY)) and category and page.fields.get("type") != "state" and page.rel not in graph.get(category[0].as_posix(), set()):
            errors.append(f"{page.rel}: missing from category MOC; refresh index")
    # Older projects may also have a human README beside their actual entry.
    seed = LEGACY_ENTRY.as_posix() if LEGACY_ENTRY.as_posix() in graph else ENTRY.as_posix()
    reachable, pending = set(), [seed]
    while pending:
        current = pending.pop()
        if current not in reachable:
            reachable.add(current)
            pending.extend(graph.get(current, set()) - reachable)
    for page in ([] if metadata_only else pages):
        if str(page.fields.get("type", "")) in {"state", "decision", "knowledge", "log"} and page.rel not in reachable:
            warnings.append(f"{page.rel}: unreachable from memory entry")
    config = memory / ".memory.json"
    if config_bytes is _UNREAD:
        try:
            config_bytes = read_memory_config(memory)
        except (ValueError, OSError) as exc:
            errors.append(f".memory.json: {exc}")
            return sorted(set(errors)), sorted(set(warnings))
    entry = ENTRY
    if memory != project / "wiki_memory":
        message = "legacy memory location; migrate to <project>/wiki_memory before delivery or index writes"
        (errors if require_ready else warnings).append(message)
    if config_bytes is not None:
        try:
            instructions = effective_root_instructions(project)
            instruction_text = (instructions[1] or b"").decode("utf-8")
        except (ValueError, OSError) as exc:
            errors.append(f"root instructions: {exc}")
            instructions = None
        try:
            if not within(config, memory):
                raise ValueError("configuration escapes memory directory")
            data = json.loads(config_bytes.decode("utf-8-sig"))
            if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
                    or data.get("schema_version") not in {1, 2} or data.get("mode") not in {"lite", "standard"}):
                raise ValueError("unsupported schema_version or mode")
            if data["schema_version"] == 1:
                entry = LEGACY_ENTRY
                message = "legacy schema_version 1; check is read-only compatible, migrate to schema_version 2 and README.md before delivery or index writes"
                (errors if require_ready else warnings).append(message)
            elif data.get("navigation") != ENTRY.as_posix():
                raise ValueError("schema_version 2 requires navigation: README.md")
            elif any(p.path == LEGACY_ENTRY for p in pages):
                errors.append("legacy 入口.md remains; merge its navigation into README.md and repair references before indexing")
            memory_link_style(data)
            if data.get("tool_version") not in {None, VERSION}:
                warnings.append(f"project tool version {data.get('tool_version')} differs from running version {VERSION}; review before upgrading")
            if data["mode"] == "standard":
                issues = standard_log_issues(memory, pages)
                compatible = not metadata_only and not require_ready and legacy_log_layout(data)
                (warnings if compatible else errors).extend(issues)
                if issues and compatible:
                    warnings.append("legacy standard log layout is read-only compatible; explicitly classify logs and repair references before delivery or index writes")
            defaults = data.get("moc_defaults", {})
            if (not isinstance(defaults, dict) or any(k not in {"kind", "importance"} for k in defaults)
                    or any(not isinstance(v, str) or not v.strip() for v in defaults.values())):
                raise ValueError("moc_defaults supports only nonempty kind/importance strings")
            read_budget_config(data)
            if not metadata_only and instructions is not None:
                warnings.extend(read_budget_report(project, memory, pages, data, instructions=instructions)["warnings"])
            by_path = {p.path: p for p in pages}
            for path in (entry, LOG_INDEX, *(item[0] for item in CATALOGS.values())):
                page = by_path.get(path)
                if page is None:
                    if path in {entry, LOG_INDEX}:
                        errors.append(f"{path.as_posix()}: required navigation page missing")
                    continue
                if page.fields.get("type") != "moc" or page.fields.get("status") != "active":
                    errors.append(f"{page.rel}: navigation must be an active MOC page")
                text = page.original.decode("utf-8")
                if text.count(AUTO_START) != 1 or text.count(AUTO_END) != 1 or text.index(AUTO_START) > text.index(AUTO_END):
                    errors.append(f"{page.rel}: invalid auto region; preserve manual content and repair markers")
            for title in STATE_TITLES[data["mode"]]:
                path = Path("当前状态") / f"{title}.md"
                if path not in by_path or by_path[path].fields.get("type") != "state":
                    errors.append(f"{path.as_posix()}: required state page missing for {data['mode']} mode")
                elif str(by_path[path].fields.get("status", "")) not in {"active", "proposed"}:
                    errors.append(f"{path.as_posix()}: required state page must be current (active/proposed)")
                if not metadata_only and data["schema_version"] == 2 and path in by_path:
                    (errors if require_ready else warnings).extend(state_readiness(by_path[path], title))
        except (ValueError, TypeError) as exc:
            errors.append(f".memory.json: {exc}")
        if instructions is not None:
            rel = memory.relative_to(project).as_posix()
            hook = memory_hook_status(instruction_text, rel, entry)
            if hook not in {"managed", "legacy"}:
                (errors if require_ready else warnings).append("effective root instructions lack memory hook; verify session discovery")
            elif hook == "legacy":
                warnings.append("effective root instructions use an unmarked legacy memory hook; manually verify affirmative reading instructions and nested overrides")
    elif require_ready:
        errors.append("configuration missing; --require-ready requires schema_version 2 and README.md navigation")
    return sorted(set(errors)), sorted(set(warnings))


def make_page(page_type, status, topic, title, body, today, *, extra_fields=None):
    extra = "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in (extra_fields or {}).items())
    return (f"---\ntype: {page_type}\nstatus: {status}\nupdated: {today.isoformat()}\n"
            f"topic: {topic}\n{extra}sources: []\n---\n\n# {title}\n\n{body.rstrip()}\n")


def memory_link_style(data: dict) -> str:
    style = data.get("link_style", "wiki")
    if style not in LINK_STYLES:
        raise ValueError("link_style must be markdown or wiki")
    return style


def render_memory_link(target: Path, title: str, source: Path, style: str, *, legacy_log=False):
    if style == "wiki" and not legacy_log:
        title = title.replace("|", "\\|").replace("[", "").replace("]", "")
        path = "".join(quote(char, safe="") if char in "%#?[]|\\" else char for char in target.as_posix())
        return f"[[{path}|{title}]]"
    relative = Path(os.path.relpath(target, source.parent)).as_posix()
    if legacy_log:
        # The old Wiki index already used Markdown in its log table. Preserve
        # its byte format when link_style is missing or explicitly wiki.
        path = quote(relative, safe="/")
        title = title.translate(str.maketrans({char: "\\" + char for char in "\\[]|"}))
    else:
        if relative.startswith("\\") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", relative):
            relative = "./" + relative
        path = "".join(char if char.isalnum() else quote(char, safe="/") for char in relative)
        title = title.translate(str.maketrans({
            **{char: "\\" + char for char in "\\[]|*_~&<>"},
            "`": "&#96;",
        }))
    return f"[{title}]({path})"


def index_contents(pages: list[Page], link_style="wiki"):
    entry, catalogs = ["## 当前状态", ""], {}
    existing = {p.path for p in pages}
    for page_type, (catalog_path, label) in CATALOGS.items():
        selected = sorted((p for p in pages if p.fields.get("type") == page_type), key=lambda p: (p.fields.get("status") != "active", p.rel))
        if page_type == "state":
            current = [p for p in selected if p.fields.get("status") in {"active", "proposed"}]
            entry.extend(f"- {render_memory_link(p.path, p.title, ENTRY, link_style)} — {p.fields.get('status', '?')}" for p in current)
            if not current:
                entry.append("- 尚无当前状态，先核实项目事实。")
            entry.append("")
            selected = [p for p in selected if p.fields.get("status") not in {"active", "proposed"}]
        if selected or catalog_path in existing:
            lines = []
            for statuses, heading in (({"active"}, "当前有效"), ({"proposed"}, "候选待核实"), ({"superseded", "deprecated", "archived"}, "历史与替代")):
                group = [p for p in selected if p.fields.get("status") in statuses]
                if group:
                    lines.extend([f"## {heading}", ""])
                    lines.extend(f"- {render_memory_link(p.path, p.title, catalog_path, link_style)} — {p.fields.get('status', '?')} · {p.fields.get('topic', '?')}" for p in group)
                    lines.append("")
            catalogs[catalog_path] = "\n".join(lines).rstrip() or "暂无页面。"
            entry.append(f"- {render_memory_link(catalog_path, label, ENTRY, link_style)} — {len(selected)} 页，按主题或模块检索。")
    entry.append("")
    logs = ["| 日期 | 类型 | 任务结果 | 日志 |", "| --- | --- | --- | --- |"]
    selected = sorted((p for p in pages if p.fields.get("type") == "log"), key=lambda p: (str(p.fields.get("updated", "")), p.rel), reverse=True)
    for p in selected:
        cells = [str(p.fields.get(k, "未记录")).replace("|", "\\|") for k in ("updated", "kind", "task_status")]
        link = render_memory_link(p.path, p.title, LOG_INDEX, link_style, legacy_log=link_style == "wiki")
        logs.append("| " + " | ".join(cells + [link]) + " |")
    if not selected:
        logs.append("| - | - | - | 暂无记录 |")
    return {ENTRY: "\n".join(entry).rstrip(), LOG_INDEX: "\n".join(logs), **catalogs}


def replace_auto(text: str, generated: str, path: Path):
    if text.count(AUTO_START) != 1 or text.count(AUTO_END) != 1:
        raise ValueError(f"{path}: expected one auto region; preserve existing content and migrate manually")
    start, end = text.index(AUTO_START) + len(AUTO_START), text.index(AUTO_END)
    if start > end:
        raise ValueError(f"{path}: invalid auto marker order")
    newline = "\r\n" if text[start:end].startswith("\r\n") else "\n"
    region = "\n\n" + generated + "\n\n"
    return text[:start] + region.replace("\n", newline) + text[end:]


def refresh_index(text: str, generated: str, path: Path, today: date):
    page = parse_page(path, text)
    if page.errors or page.fields.get("type") != "moc":
        raise ValueError(f"{path}: generated navigation must be a valid MOC page")
    updated = replace_auto(text, generated, path)
    if updated == text:
        return text
    # Only the generated region and the MOC edit date belong to this tool.
    lines = updated.splitlines(keepends=True)
    end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    for i in range(1, end):
        if lines[i].startswith("updated:"):
            newline = "\r\n" if lines[i].endswith("\r\n") else "\n"
            lines[i] = f"updated: {today.isoformat()}{newline}"
            break
    else:
        raise ValueError(f"{path}: MOC requires updated metadata")
    return "".join(lines)


def initialize(project: Path, memory: Path, mode: str, today: date, link_style="markdown"):
    if memory != project / "wiki_memory":
        raise ValueError("new memory must be <project>/wiki_memory; nested/custom memory-dir is only accepted by read-only check for migration")
    if memory.exists():
        raise ValueError("memory directory already exists; inspect/migrate it without init")
    agents, raw = effective_root_instructions(project)
    safe_write_target(agents, project)
    previous = raw or b""
    try:
        instruction_text = previous.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("root instructions are not UTF-8; preserve them and adapt encoding before init") from exc
    visible = instruction_prose(instruction_text)
    if HOOK_START in visible or HOOK_END in visible:
        raise ValueError("existing memory hook found; inspect before changing it")
    refuse_competing_memory(project, memory, visible)
    protocol = Path(__file__).resolve().parents[1] / "assets/protocol.md"
    if not protocol.is_file():
        raise ValueError("init must run from the Skill package, which contains assets/protocol.md")
    rel = memory.relative_to(project).as_posix()
    content = read_text(protocol).replace("__MEMORY_DIR__", rel).replace("__MODE__", mode).replace("__VERSION__", VERSION)
    plan = {memory / "AGENTS.md": content.encode("utf-8")}
    summary = "> 初始化结构，尚未核实项目事实；填写证据后改为 active。\n\n"
    for title in STATE_TITLES[mode]:
        body = summary + "\n\n".join(f"## {section}\n\n- {STATE_PROMPTS[section]}" for section in STATE_SECTIONS[title])
        plan[memory / "当前状态" / f"{title}.md"] = make_page("state", "proposed", STATE_TOPICS[title], title, body, today).encode("utf-8")
    entry_body = (f"初始布局：`{mode}`（当前布局以 `.memory.json` 为准）。按项目协议选择读取路径，按需定位当前状态、决策、知识与历史。\n\n"
                  "日常开发直接遵循项目内协议，不调用 wiki-memory Skill；仅用户明确要求记忆管理时使用 Skill。\n\n"
                  "- [记忆维护协议](AGENTS.md)\n- [工作日志 MOC](日志/MOC_工作日志.md)\n\n"
                  f"{AUTO_START}\n\n{AUTO_END}\n")
    plan[memory / ENTRY] = make_page("moc", "active", "memory-entry", "工程记忆导航", entry_body, today).encode("utf-8")
    plan[memory / LOG_INDEX] = make_page("moc", "active", "work-log-index", "工作日志 MOC", f"{AUTO_START}\n\n{AUTO_END}\n", today).encode("utf-8")
    if mode == "standard":
        for folder in LOG_CATEGORIES.values():
            plan[memory / "日志" / folder / ".gitkeep"] = b""
    pages = [parse_page(p.relative_to(memory), data.decode("utf-8")) for p, data in plan.items() if p.suffix == ".md"]
    for path, generated in index_contents(pages, link_style).items():
        target = memory / path
        plan[target] = replace_auto(plan[target].decode("utf-8"), generated, path).encode("utf-8")
    config = {"schema_version": 2, "mode": mode, "tool_version": VERSION, "navigation": ENTRY.as_posix(),
              "link_style": link_style, "read_budget": READ_BUDGET}
    plan[memory / ".memory.json"] = (json.dumps(config, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    plan[memory / "工具/memory.py"] = Path(__file__).read_bytes()
    newline = "\r\n" if b"\r\n" in previous else "\n"
    block = (f"{HOOK_START}\n## 工程记忆\n\n"
             f"本项目使用工程根目录下的 `{rel}/`。新会话读取 `{rel}/AGENTS.md` 和 `{rel}/README.md`。按协议区分只读窄查询与修改、接续等任务，后者先读取规定的当前状态与全局约束。已读且未变的内容可复用。\n"
             "在已授权开发任务完成或中断时，按协议同步有证据的状态、验证和恢复下一步；只读任务遵守只读范围。\n"
             "日常读取、同步和交接直接遵循项目协议，不调用 wiki-memory Skill。仅用户明确要求配置、迁移、体检等记忆管理时加载 Skill；检查频率按项目协议，不把完整验收用于每轮收尾。\n"
             f"{HOOK_END}\n").replace("\n", newline).encode("utf-8")
    separator = (newline * 2).encode("utf-8") if previous else b""
    plan[agents] = previous + separator + block
    return plan, agents, previous


def observed_bytes(path: Path):
    return path.read_bytes() if os.path.lexists(path) else None


@contextlib.contextmanager
def mutation_lock(project: Path):
    lock = project / ".wiki-memory.lock"
    safe_write_target(lock, project)
    token = f"pid={os.getpid()} token={uuid.uuid4().hex}\n".encode()
    try:
        with lock.open("xb") as stream:
            stream.write(token)
    except FileExistsError as exc:
        raise ValueError("memory writer lock exists; inspect the process or leftover lock before retrying") from exc
    try:
        yield
    finally:
        # Never unlink a lock that an external process has replaced.
        if observed_bytes(lock) == token:
            lock.unlink()


def atomic_write(path: Path, data: bytes, *, create=False):
    old_mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    descriptor, name = tempfile.mkstemp(prefix=".wiki-memory-write-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if old_mode is not None:
            os.chmod(temporary, old_mode)
        if create:
            # Hard-link publication is atomic and refuses an existing file.
            os.link(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except PermissionError:
                os.chmod(temporary, stat.S_IREAD | stat.S_IWRITE)
                temporary.unlink()


def apply_plan(plan: dict[Path, bytes], project: Path, apply: bool, append_target: Path | None = None,
               expected: bytes = b"", *, snapshots=None, page_root=None, new_root=None, required_dirs=(),
               init_options=None):
    baseline = dict(snapshots or {})
    for path in plan:
        safe_write_target(path, project)
        if append_target is not None:
            if path == append_target:
                baseline[path] = expected if expected or path.exists() else None
            else:
                baseline[path] = None
        elif path not in baseline:
            baseline[path] = observed_bytes(path)
    manifest = {p for p, original in baseline.items() if original is not None and p.suffix.lower() == ".md" and page_root and within(p, page_root)}

    def verify():
        for directory in required_dirs:
            safe_write_target(directory, project)
            if not directory.is_dir() or (page_root is not None and not within(directory, page_root)):
                raise ValueError(f"required standard log directory changed while generating indexes; inspect and retry: {directory}")
        for path, original in baseline.items():
            safe_write_target(path, project)
            if observed_bytes(path) != original:
                raise ValueError(f"file changed after it was read; preserve new contents and retry: {path}")
        if page_root is not None and set(page_paths(page_root)) != manifest:
            raise ValueError("memory page set changed while generating indexes; inspect and retry")

    # Check conflicts on a preview too, without creating a lock or directories.
    verify()
    if new_root is not None and os.path.lexists(new_root):
        raise ValueError("memory directory appeared after planning; inspect without init")
    files = [p.relative_to(project).as_posix() for p in plan]
    report = {"apply": apply, "files": files}
    if init_options is not None:
        report.update(init_options)
        report["changes"] = [{"path": rel, "action": "create" if baseline[path] is None else "append"}
                             for path, rel in zip(plan, files)]
        report["blockers"] = (["existing .wiki-memory.lock; inspect its owner before applying"]
                              if os.path.lexists(project / ".wiki-memory.lock") else [])
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not apply:
        return
    created_dirs, written = [], []

    def ensure_parent(path):
        missing, cursor = [], path
        while not cursor.exists():
            safe_write_target(cursor, project)
            missing.append(cursor)
            cursor = cursor.parent
        for folder in reversed(missing):
            folder.mkdir()
            created_dirs.append(folder)

    with mutation_lock(project):
        verify()
        try:
            if new_root is not None:
                ensure_parent(new_root.parent)
                # Exclusive directory creation prevents initializing another tree.
                new_root.mkdir()
                created_dirs.append(new_root)
            for path, data in plan.items():
                verify()
                ensure_parent(path.parent)
                old = baseline[path]
                atomic_write(path, data, create=old is None)
                written.append((path, old, data))
                baseline[path] = data
                if page_root is not None and path.suffix.lower() == ".md" and within(path, page_root):
                    manifest.add(path)
            verify()
        except BaseException as exc:
            incomplete = []
            for path, old, ours in reversed(written):
                try:
                    safe_write_target(path, project)
                    if observed_bytes(path) != ours:
                        incomplete.append(str(path))
                    elif old is None:
                        path.unlink()
                    else:
                        atomic_write(path, old)
                except (OSError, ValueError):
                    incomplete.append(str(path))
            # Only remove empty directories created by this call. Never recurse.
            for folder in reversed(created_dirs):
                try:
                    safe_write_target(folder, project)
                    folder.rmdir()
                except (OSError, ValueError):
                    pass
            if incomplete:
                raise ValueError(f"write interrupted; preserved changed files requiring review: {', '.join(incomplete)}") from exc
            raise


def safe_path_stat(path: Path, boundary: Path):
    """Inspect path components without following symlinks or Windows reparse points."""
    current = boundary
    info = None
    for part in path.relative_to(boundary).parts:
        current /= part
        try:
            info = current.lstat()
        except (FileNotFoundError, NotADirectoryError):
            return None
        if linked_entry(info):
            raise ValueError("symlink_or_reparse_point")
    return info


def local_source_path(project, raw):
    """Accept a normalized Git-relative pathname without opening its contents."""
    if (not raw or len(raw) > 4096 or re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", raw)
            or any(part in {"", ".", ".."} or ":" in part for part in raw.split("/"))):
        raise ValueError("unsafe_path")
    if os.name == "nt" and any(
        re.search(r'[\\*?"<>|]', part) or part.endswith((" ", "."))
        or (os.path.isreserved(part) if hasattr(os.path, "isreserved") else PureWindowsPath(part).is_reserved())
        for part in raw.split("/")
    ):
        raise ValueError("unsupported_windows_path")
    return project.joinpath(*raw.split("/"))


class GitReadError(ValueError):
    pass


def git_read(project, *args, allowed=(0,)):
    # Ambient repository/config overrides can silently redirect a Git invocation.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0",
               GIT_NO_LAZY_FETCH="1", GIT_ALLOW_PROTOCOL="", GIT_TERMINAL_PROMPT="0")
    command = ["git", "--no-optional-locks", "--no-replace-objects", "-c", "core.fsmonitor=false",
               "-c", f"core.attributesFile={os.devnull}", "-c", f"core.excludesFile={os.devnull}", *args]
    try:
        result = subprocess.run(command, cwd=project, env=env, capture_output=True, timeout=30, shell=False)
    except FileNotFoundError as exc:
        raise GitReadError("git_not_found") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitReadError("git_timeout") from exc
    except OSError as exc:
        raise GitReadError("git_could_not_run") from exc
    if result.returncode not in allowed:
        # Avoid returning Git diagnostics that can contain untrusted names/configuration.
        raise GitReadError(f"git_{args[0]}_failed")
    return result


def git_revision(project, revision):
    if (not isinstance(revision, str) or not 1 <= len(revision) <= 256
            or revision.startswith("-") or ".." in revision
            or re.fullmatch(r"[\w./@~^+{}-]+", revision) is None):
        raise GitReadError("unsupported_revision")
    result = git_read(project, "rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}", allowed=(0, 128))
    commit = result.stdout.strip()
    if result.returncode or re.fullmatch(rb"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is None:
        return None
    return commit.decode("ascii")


def git_changes(raw, scope):
    """Decode NUL-delimited name-status records, including both rename endpoints."""
    values = raw.decode("utf-8", errors="surrogateescape").split("\x00")
    if values.pop():
        raise GitReadError("unterminated_git_path_list")
    if scope == "untracked":
        return [{"path": path, "previous_path": None, "change": "untracked", "scope": scope} for path in values]
    changes, position = [], 0
    kinds = {"A": "added", "M": "modified", "D": "deleted", "R": "renamed", "C": "copied",
             "T": "type_changed", "U": "unmerged", "X": "unknown", "B": "broken_pair"}
    while position < len(values):
        code = values[position]
        if re.fullmatch(r"(?:[ADTUXB]|[MRC][0-9]{0,3})", code) is None:
            raise GitReadError("unsupported_git_change_record")
        paired = code[0] in "RC"
        end = position + (3 if paired else 2)
        if end > len(values):
            raise GitReadError("truncated_git_change_record")
        changes.append({"path": values[end - 1], "previous_path": values[end - 2] if paired else None,
                        "change": kinds[code[0]], "scope": scope})
        position = end
    return changes


DIFF_OPTIONS = ("--no-ext-diff", "--no-textconv", "--no-relative", "--ignore-submodules=dirty",
                "-O", os.devnull, "--name-status", "--find-renames", "-z")
UNTRACKED_EXCLUDES = (".*", "node_modules/", "vendor/", "venv/", "env/", "dist/", "build/", "__pycache__/")


def impact_source_options(raw, kind, page, memory, project, page_names):
    if len(raw) > 4096:
        raise ValueError("unsafe_source_path")
    target = raw.strip().replace("\\", "/")
    if kind != "source":
        target = unquote(target.split("#", 1)[0].split("?", 1)[0], errors="strict")
    if target.startswith(("用户指令：", "用户确认：", "user:")):
        raise ValueError("nonlocal_source")
    if target.startswith(("/", "\\", "file:")) or re.match(r"^[A-Za-z]:", target):
        raise ValueError("unsafe_source_path")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        raise ValueError("nonlocal_source")
    if not target or kind == "source" and ".." in target.split("/"):
        raise ValueError("unsafe_source_path")
    directory = memory.relative_to(project).as_posix()
    if kind == "markdown":
        directory = posixpath.join(directory, page.path.parent.as_posix())
    relative = posixpath.normpath(target if kind == "source" else posixpath.join(directory, target))
    if kind != "wiki":
        return [relative]
    preferred = [relative]
    if not relative.lower().endswith(".md"):
        preferred.append(relative + ".md")
    if "/" not in target:
        matches = sorted({name for suffix in preferred for name in page_names.get(posixpath.basename(suffix), ())
                          if name not in preferred})
        if len(matches) > 1:
            return preferred + [None]
        preferred.extend(matches)
    return preferred


def impact_baseline(project, page, base, cache):
    revision = page.fields.get("verified_rev")
    if "verified_rev" not in page.fields:
        return {"page": page.rel, "verified_rev": None, "resolved": None, "status": "missing"}
    try:
        iso_date(page.fields.get("verified"))
        if not is_verified_revision(revision):
            raise ValueError
    except ValueError:
        return {"page": page.rel, "verified_rev": None, "resolved": None, "status": "invalid"}
    if revision not in cache:
        try:
            cache[revision] = git_revision(project, revision)
        except GitReadError:
            cache[revision] = None
    resolved = cache[revision]
    status = "unresolved" if resolved is None else "matches_base" if resolved == base else "differs_from_base"
    return {"page": page.rel, "verified_rev": revision, "resolved": resolved, "status": status}


def map_impact_sources(project, memory, report):
    try:
        paths = page_paths(memory)
    except (OSError, ValueError):
        report["limitations"].append("memory_inventory_unavailable")
        return
    if not paths:
        report["limitations"].append("memory_has_no_pages")
    page_names, changes_by_source, changes_below = {}, {}, {}
    for path in paths:
        page_names.setdefault(path.name, []).append(path.relative_to(project).as_posix())
    for change in report["changed_sources"]:
        for path in {change["path"], change["previous_path"]} - {None}:
            changes_by_source.setdefault(os.path.normcase(path), []).append(change)
            parent = posixpath.dirname(path)
            while parent:
                changes_below.setdefault(os.path.normcase(parent), []).append(change)
                parent = posixpath.dirname(parent)
    baseline_cache = {}
    for path in paths:
        relative = path.relative_to(memory)
        if relative.parts[0] == "日志":
            continue
        try:
            page = parse_page(relative, bounded_read(path, memory).decode("utf-8"))
        except (OSError, ValueError):
            report["unassessable_pages"].append({"page": relative.as_posix(), "reasons": ["unreadable_page"]})
            continue
        if page.errors:
            report["unassessable_pages"].append({"page": page.rel, "reasons": ["invalid_frontmatter"]})
            continue
        if page.fields.get("status") != "active" or page.fields.get("type") not in ("state", "knowledge", "decision"):
            continue
        report["page_baselines"].append(impact_baseline(project, page, report["base"], baseline_cache))
        sources = page.fields.get("sources")
        if not isinstance(sources, list) or not sources:
            report["unassessable_pages"].append({"page": page.rel, "reasons": ["no_local_sources"]})
            continue
        matches, reasons = {}, set()
        for value in sources:
            if not isinstance(value, str) or len(value) > 4096:
                reasons.add("unsafe_source_path")
                continue
            for kind, raw in list(links(value)) or [("source", value)]:
                try:
                    options = impact_source_options(raw, kind, page, memory, project, page_names)
                    for source in options:
                        if source is None:
                            raise ValueError("ambiguous_wiki_source")
                        source_path = local_source_path(project, source)
                        info = safe_path_stat(source_path, project)
                        if info and not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                            raise ValueError("unsupported_source_type")
                        source_key = os.path.normcase(source)
                        hits = changes_by_source.get(source_key, [])
                        if info is None or stat.S_ISDIR(info.st_mode):
                            hits = hits + changes_below.get(source_key, [])
                        if hits or info:
                            if hits:
                                matches[source] = hits
                            break
                    else:
                        reasons.add("missing_source")
                except UnicodeError:
                    reasons.add("invalid_source_encoding")
                except (OSError, ValueError) as exc:
                    safe_reasons = {"ambiguous_wiki_source", "nonlocal_source", "unsafe_source_path", "unsafe_path",
                                    "symlink_or_reparse_point", "unsupported_windows_path", "unsupported_source_type"}
                    reasons.add(str(exc) if isinstance(exc, ValueError) and str(exc) in safe_reasons else "unreadable_source")
        if matches:
            report["affected_pages"].append({"page": page.rel, "matched_sources": sorted(matches),
                                              "matched_changes": {source: unique_changes(hits)
                                                                  for source, hits in sorted(matches.items())},
                                              "reason": "source_changed", "action": "review", "confirmed_stale": False})
        if reasons:
            report["unassessable_pages"].append({"page": page.rel, "reasons": sorted(reasons)})


def unique_changes(changes):
    unique = {(item["path"], item["previous_path"] or "", item["scope"], item["change"]): item for item in changes}
    return [unique[key] for key in sorted(unique)]


def impact_report(project, memory, base, head, include_worktree):
    report = {"read_only": True, "status": "unavailable", "base": None, "head": None,
              "worktree_requested": include_worktree, "worktree_included": False, "included_scopes": [],
              "untracked_policy": "project_nonignored_excluding_dot_paths_and_dependency_or_build_directories" if include_worktree else "excluded",
              "submodule_policy": "tracked_pointer_only",
              "changed_sources": [], "affected_pages": [], "unassessable_pages": [], "page_baselines": [],
              "limitations": [], "summary": {}}
    try:
        if safe_path_stat(project / ".git", project) is None:
            raise GitReadError("not_a_git_worktree_root")
        root = git_read(project, "rev-parse", "--show-toplevel", allowed=(0, 128))
        if root.returncode or Path(root.stdout.decode("utf-8").rstrip("\r\n")).resolve() != project:
            raise GitReadError("project_must_be_git_worktree_root")
        report["base"] = git_revision(project, base)
        report["head"] = git_revision(project, head)
        if not report["base"] or not report["head"]:
            if git_read(project, "rev-parse", "--is-shallow-repository").stdout.strip() == b"true":
                report["limitations"].append("shallow_repository_history_may_be_missing")
            raise GitReadError("base_revision_unresolved" if not report["base"] else "head_revision_unresolved")
        scopes = {"commit": ("diff", *DIFF_OPTIONS, report["base"], report["head"], "--", ".")}
        if include_worktree:
            if report["head"] != git_revision(project, "HEAD"):
                report["limitations"].append("worktree_requires_current_head")
            else:
                scopes["staged"] = ("diff", *DIFF_OPTIONS, "--cached", report["head"], "--", ".")
                try:
                    filters = git_read(project, "config", "--null", "--name-only", "--get-regexp",
                                       r"^filter\..*\.(clean|process)$", allowed=(0, 1))
                    if filters.returncode == 1 and not filters.stdout:
                        scopes["unstaged"] = ("diff", *DIFF_OPTIONS, "--", ".")
                    else:
                        report["limitations"].append("unstaged_skipped_to_avoid_git_filters")
                except GitReadError as exc:
                    report["limitations"].append(f"unstaged: {exc}")
                scopes["untracked"] = ("ls-files", "--others", "--exclude-standard", "-z",
                                       *(f"--exclude={pattern}" for pattern in UNTRACKED_EXCLUDES), "--", ".")
        rejected = 0
        for scope, args in scopes.items():
            try:
                changes = git_changes(git_read(project, *args).stdout, scope)
                report["included_scopes"].append(scope)
                for change in changes:
                    try:
                        for path in (change["path"], change["previous_path"]):
                            if path is not None:
                                safe_path_stat(local_source_path(project, path), project)
                        report["changed_sources"].append(change)
                    except (OSError, ValueError):
                        rejected += 1
            except GitReadError as exc:
                report["limitations"].append(f"{scope}: {exc}")
        if rejected:
            report["limitations"].append(f"unsafe_or_unreadable_changed_paths: {rejected}")
        report["worktree_included"] = set(scopes) == {"commit", "staged", "unstaged", "untracked"} and (
            len(report["included_scopes"]) == 4 and not rejected)
        report["changed_sources"] = unique_changes(report["changed_sources"])
        if report["included_scopes"]:
            map_impact_sources(project, memory, report)
            report["status"] = ("incomplete" if report["limitations"] or report["unassessable_pages"] else "complete")
    except (OSError, ValueError) as exc:
        report["limitations"].append(str(exc) if isinstance(exc, GitReadError) else "git_worktree_unreadable_or_unsafe")
    report["summary"] = {key: len(report[key]) for key in ("changed_sources", "affected_pages", "unassessable_pages")}
    return report


MAX_TOOL_BYTES = 2 * 1024 * 1024


def bounded_read(path, boundary):
    info = safe_path_stat(path, boundary)
    if info is None:
        raise ValueError("missing_file")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("not_a_regular_file")
    if info.st_size > MAX_TOOL_BYTES:
        raise ValueError("file_too_large")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        if not os.path.samestat(info, os.fstat(handle.fileno())):
            raise ValueError("file_changed_during_open")
        data = handle.read(MAX_TOOL_BYTES + 1)
    if len(data) > MAX_TOOL_BYTES:
        raise ValueError("file_too_large")
    return data


def declared_tool_version(text):
    try:
        syntax = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return None
    values = [node.value.value for node in syntax.body
              if isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "VERSION"
              and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    return values[0] if len(values) == 1 and re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}", values[0]) else None


def tool_description(path, boundary):
    info = {"path": str(path), "version": None, "sha256": None, "issue": None}
    try:
        data = bounded_read(path, boundary)
        info["sha256"] = hashlib.sha256(data).hexdigest()
        info["version"] = declared_tool_version(data.decode("utf-8-sig"))
        if info["version"] is None:
            info["issue"] = "version_not_declared_or_unparseable"
    except UnicodeError:
        info["issue"] = "invalid_utf8"
    except OSError:
        info["issue"] = "unreadable_file"
    except ValueError as exc:
        info["issue"] = str(exc)
    return info


def tool_configuration(project, memory):
    result = {"schema_version": None, "schema_compatibility": "unknown", "tool_version": None,
              "tool_version_relation": "unknown", "link_style": None, "link_style_compatibility": "unknown", "issue": None}
    try:
        data = json.loads(bounded_read(memory / ".memory.json", project).decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, UnicodeError, ValueError, RecursionError):
        result["issue"] = "configuration_missing_unreadable_or_invalid"
        return result
    schema = data.get("schema_version")
    if type(schema) is int:
        result["schema_version"] = schema
        result["schema_compatibility"] = {1: "legacy_read_only", 2: "supported"}.get(schema, "unsupported")
    version = data.get("tool_version")
    if isinstance(version, str) and re.fullmatch(r"[0-9]{1,5}\.[0-9]{1,5}\.[0-9]{1,5}", version):
        result["tool_version"] = version
        declared = tuple(map(int, version.split(".")))
        current = tuple(map(int, VERSION.split(".")))
        result["tool_version_relation"] = "same" if declared == current else "older" if declared < current else "newer"
    try:
        result["link_style"] = memory_link_style(data)
        result["link_style_compatibility"] = "supported" if "link_style" in data else "legacy_default"
    except ValueError:
        result["link_style_compatibility"] = "unsupported"
    return result


def tool_diff_report(project, memory, reference_arg):
    running = Path(__file__).resolve()
    running_tool = tool_description(running, Path(running.anchor))
    local = memory / "工具" / "memory.py"
    reference, issue = None, None
    if reference_arg:
        specified = Path(reference_arg)
        if (".." in specified.parts or specified.anchor and not specified.is_absolute()
                or reference_arg.startswith(("//", "\\\\")) or re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", reference_arg)):
            issue = "unsafe_reference_path"
        else:
            reference = specified if specified.is_absolute() else project / specified
    elif running.parent.name == "scripts" and (running.parent.parent / "SKILL.md").is_file():
        reference = running
    else:
        issue = "explicit_reference_required_for_standalone_tool"
    local_tool = running_tool if running == local else tool_description(local, project)
    reference_tool = None
    if reference is not None:
        reference_tool = running_tool if reference == running else tool_description(reference, Path(reference.anchor))
    if reference is not None:
        try:
            if reference == local or (local_tool["sha256"] and reference_tool["sha256"] and reference.samefile(local)):
                issue = "reference_is_project_tool"
        except OSError:
            issue = "tool_identity_unavailable"
    if not issue and any(tool["sha256"] is None or tool["issue"] == "invalid_utf8" for tool in (local_tool, reference_tool)):
        issue = "unreadable_or_unsupported_tool"
    identical = None if issue else local_tool["sha256"] == reference_tool["sha256"]
    return {"read_only": True, "status": "not_comparable" if identical is None else "same" if identical else "different",
            "identical": identical, "issue": issue, "running_tool": running_tool,
            "project_tool": local_tool, "reference_tool": reference_tool, "configuration": tool_configuration(project, memory),
            "notes": ["Version declarations do not establish byte identity.",
                      "Review project customizations and validate compatibility before manually upgrading."]}


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"wiki-memory {VERSION}")
    parser.add_argument("command", choices=("init", "check", "index", "plan-migration", "impact", "tool-diff"))
    parser.add_argument("--project", default=".")
    parser.add_argument("--memory-dir", default="wiki_memory")
    parser.add_argument("--mode", choices=("lite", "standard"), help="init: default lite; plan-migration: default existing mode")
    parser.add_argument("--link-style", choices=LINK_STYLES, help="init only: navigation style (default markdown)")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="local verification date (YYYY-MM-DD)")
    parser.add_argument("--stale-days", type=int, default=90)
    parser.add_argument("--apply", action="store_true", help="write the previewed init/index files")
    parser.add_argument("--require-ready", action="store_true", help="check only: require populated active states with evidence and the selected mode's log layout")
    parser.add_argument("--base", help="impact: required starting Git revision")
    parser.add_argument("--head", help="impact: ending Git revision (default HEAD)")
    parser.add_argument("--include-worktree", action="store_true",
                        help="impact: include staged, unstaged and eligible untracked paths at current HEAD")
    parser.add_argument("--reference-tool", help="tool-diff: path to a reference script, read as data only")
    args = parser.parse_args(argv)
    try:
        if args.command not in {"init", "index"} and args.apply:
            raise ValueError(f"{args.command} is read-only; --apply is not accepted")
        if args.command == "impact" and args.base is None:
            raise ValueError("impact requires --base")
        if args.command != "impact" and (args.base is not None or args.head is not None or args.include_worktree):
            raise ValueError("--base, --head and --include-worktree are accepted only by impact")
        if args.reference_tool is not None and args.command != "tool-diff":
            raise ValueError("--reference-tool is accepted only by tool-diff")
        if args.mode is not None and args.command not in {"init", "plan-migration"}:
            raise ValueError("--mode is accepted only by init and plan-migration")
        if args.link_style is not None and args.command != "init":
            raise ValueError("--link-style is accepted only by init; change .memory.json to switch an existing project's generated navigation")
        if args.require_ready and args.command != "check":
            raise ValueError("--require-ready is accepted only by read-only check")
        if args.stale_days < 0:
            raise ValueError("stale-days must be nonnegative")
        project, memory = locations(args.project, args.memory_dir)
        if args.command == "impact":
            report = impact_report(project, memory, args.base, args.head if args.head is not None else "HEAD", args.include_worktree)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["status"] == "complete" else 1
        if args.command == "tool-diff":
            report = tool_diff_report(project, memory, args.reference_tool)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if report["status"] == "not_comparable" else 0
        if args.command == "init":
            mode, link_style = args.mode or "lite", args.link_style or "markdown"
            plan, agents, previous = initialize(project, memory, mode, args.date, link_style)
            apply_plan(plan, project, args.apply, agents, previous, new_root=memory,
                       init_options={"mode": mode, "link_style": link_style})
            return 0
        if args.command == "plan-migration":
            report = migration_plan(project, memory, args.mode)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1 if report["blockers"] or report["conflicts"] or report["unclassified_logs"] else 0
        pages = load_pages(memory)
        if args.command == "check":
            errors, warnings = inspect(project, memory, pages, args.date, args.stale_days, require_ready=args.require_ready)
            budget = None
            try:
                raw = read_memory_config(memory)
                config_data = json.loads(raw.decode("utf-8-sig")) if raw is not None else None
                if isinstance(config_data, dict):
                    budget = read_budget_report(project, memory, pages, config_data)
            except (OSError, ValueError, TypeError, UnicodeError):
                pass  # Configuration errors already appear in the check report.
            print(json.dumps({"pages": len(pages), "errors": errors, "warnings": warnings, "read_budget": budget}, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        config = memory / ".memory.json"
        config_snapshot = read_memory_config(memory)
        config_data = json.loads(config_snapshot.decode("utf-8-sig")) if config_snapshot is not None else {}
        if (memory != project / "wiki_memory" or not isinstance(config_data, dict)
                or type(config_data.get("schema_version")) is not int
                or config_data.get("schema_version") != 2 or config_data.get("navigation") != ENTRY.as_posix()
                or (memory / LEGACY_ENTRY).exists()):
            raise ValueError("legacy memory cannot be indexed by this version; migrate to <project>/wiki_memory, merge navigation into README.md, repair references and set schema_version 2/navigation README.md first")
        errors, _ = inspect(project, memory, pages, args.date, args.stale_days, metadata_only=True, config_bytes=config_snapshot)
        if errors:
            raise ValueError("fix metadata/decision relationships or explicitly migrate the standard log layout before indexing: " + "; ".join(errors))
        snapshots = {memory / p.path: p.original for p in pages}
        snapshots[config] = config_snapshot
        moc_defaults = config_data.get("moc_defaults", {})
        plan = {}
        for path, generated in index_contents(pages, memory_link_style(config_data)).items():
            target = memory / path
            previous = snapshots.get(target)
            if previous is None:
                # Only optional category MOCs may be created by index.
                if path not in {item[0] for item in CATALOGS.values()}:
                    raise ValueError(f"{path}: required navigation page missing; migrate manually")
                snapshots[target] = None
                text = make_page("moc", "active", f"catalog-{path.parent.as_posix()}", path.stem,
                                 f"{AUTO_START}\n\n{AUTO_END}\n", args.date, extra_fields=moc_defaults)
            else:
                text = previous.decode("utf-8")
            updated = refresh_index(text, generated, path, args.date).encode("utf-8")
            if updated != previous:
                plan[target] = updated
        required_dirs = tuple(memory / "日志" / folder for folder in LOG_CATEGORIES.values()) if config_data.get("mode") == "standard" else ()
        apply_plan(plan, project, args.apply, snapshots=snapshots, page_root=memory, required_dirs=required_dirs)
        return 0
    except KeyboardInterrupt:
        print("ERROR: interrupted; inspect current files before retrying", file=sys.stderr)
        return 130
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
