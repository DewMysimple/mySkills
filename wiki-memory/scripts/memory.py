#!/usr/bin/env python3
"""Project-local Markdown memory: preview/init, read-only check, marked index refresh.

Python 3.10+, standard library only. Mutations require --apply.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote, unquote

AUTO_START = "<!-- wiki-memory:auto:start -->"
AUTO_END = "<!-- wiki-memory:auto:end -->"
HOOK_START = "<!-- wiki-memory:start -->"
HOOK_END = "<!-- wiki-memory:end -->"
MANAGED = {"当前状态", "决策", "知识", "日志"}
REQUIRED = {"type", "status", "updated", "topic"}
TYPES = {"state", "decision", "knowledge", "log", "moc"}
STATUSES = {"active", "proposed", "deprecated", "superseded", "archived"}
KINDS = {"feature", "ui", "bug", "discussion", "test", "maintenance"}
ENTRY = Path("README.md")
LEGACY_ENTRY = Path("入口.md")
LOG_INDEX = Path("日志/MOC_工作日志.md")
VERSION = "3.0.0"
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
    return re.sub(r"(`+).*?\1", "", "\n".join(result))


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


def safe_write_target(path: Path, project: Path):
    if not within(path, project):
        raise ValueError(f"write target escapes project: {path}")
    cursor = path
    while cursor != project:
        if cursor.is_symlink():
            raise ValueError(f"refusing write through symlink: {cursor}")
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


def page_paths(memory: Path) -> list[Path]:
    if not memory.is_dir():
        raise ValueError(f"memory directory does not exist: {memory}")
    paths = [p for p in memory.iterdir() if p.is_file() and p.suffix.lower() == ".md"]
    for folder in sorted(MANAGED):
        base = memory / folder
        if base.is_symlink():
            raise ValueError(f"refusing symlinked memory section: {base}")
        if base.is_dir():
            paths.extend(p for p in base.rglob("*") if p.is_file() and p.suffix.lower() == ".md")
    for path in sorted(set(paths)):
        if not within(path, memory):
            raise ValueError(f"memory page escapes memory directory: {path}")
    return sorted(set(paths))


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


def has_memory_hook(text: str, relative: str, entry: Path = ENTRY):
    normalized = text.replace("\\", "/")
    flags = re.IGNORECASE if os.name == "nt" else 0
    return all(re.search(r"(?<![\w./-])(?:\./)?" + re.escape(relative + "/" + name) + r"(?![\w.-])", normalized, flags)
               for name in ("AGENTS.md", entry.as_posix()))


def resolve_target(kind, raw, source: Page, project: Path, memory: Path, pages: list[Page], require_exists=True):
    target = raw.strip() if kind == "source" else unquote(raw.strip().split("#", 1)[0].split("?", 1)[0])
    if not target:
        return None
    if target.startswith(("用户指令：", "用户确认：", "user:")):
        return None
    if re.match(r"^[A-Za-z]:", target) or target.startswith(("/", "\\", "file:")):
        raise ValueError(f"machine-specific or absolute link: {raw}")
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target):
        return None
    target = target.replace("\\", "/")
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
        elif sections[heading] in {"", "- 待核实。", "- " + STATE_PROMPTS[heading]}:
            issues.append(f"{page.rel}: required section is still scaffold: {heading}")
    return issues


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
        config_bytes = observed_bytes(config)
    entry = ENTRY
    if memory != project / "wiki_memory":
        message = "legacy memory location; migrate to <project>/wiki_memory before delivery or index writes"
        (errors if require_ready else warnings).append(message)
    if config_bytes is not None:
        try:
            if not within(config, memory):
                raise ValueError("configuration escapes memory directory")
            data = json.loads(config_bytes.decode("utf-8-sig"))
            if not isinstance(data, dict) or data.get("schema_version") not in {1, 2} or data.get("mode") not in {"lite", "standard"}:
                raise ValueError("unsupported schema_version or mode")
            if data["schema_version"] == 1:
                entry = LEGACY_ENTRY
                message = "legacy schema_version 1; check is read-only compatible, migrate to schema_version 2 and README.md before delivery or index writes"
                (errors if require_ready else warnings).append(message)
            elif data.get("navigation") != ENTRY.as_posix():
                raise ValueError("schema_version 2 requires navigation: README.md")
            elif any(p.path == LEGACY_ENTRY for p in pages):
                errors.append("legacy 入口.md remains; merge its navigation into README.md and repair references before indexing")
            if data.get("tool_version") not in {None, VERSION}:
                warnings.append(f"project tool version {data.get('tool_version')} differs from running version {VERSION}; review before upgrading")
            defaults = data.get("moc_defaults", {})
            if (not isinstance(defaults, dict) or any(k not in {"kind", "importance"} for k in defaults)
                    or any(not isinstance(v, str) or not v.strip() for v in defaults.values())):
                raise ValueError("moc_defaults supports only nonempty kind/importance strings")
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
        override = project / "AGENTS.override.md"
        agents = override if override.exists() and read_text(override).lstrip("\ufeff").strip() else project / "AGENTS.md"
        rel = memory.relative_to(project).as_posix()
        text = read_text(agents) if agents.exists() else ""
        if not has_memory_hook(text, rel, entry):
            (errors if require_ready else warnings).append("effective root instructions lack memory hook; verify session discovery")
    elif require_ready:
        errors.append("configuration missing; --require-ready requires schema_version 2 and README.md navigation")
    return sorted(set(errors)), sorted(set(warnings))


def make_page(page_type, status, topic, title, body, today, *, extra_fields=None):
    extra = "".join(f"{key}: {json.dumps(value, ensure_ascii=False)}\n" for key, value in (extra_fields or {}).items())
    return (f"---\ntype: {page_type}\nstatus: {status}\nupdated: {today.isoformat()}\n"
            f"topic: {topic}\n{extra}sources: []\n---\n\n# {title}\n\n{body.rstrip()}\n")


def wiki(page: Page):
    title = page.title.replace("|", "\\|").replace("[", "").replace("]", "")
    # Escape syntax characters once, while keeping Chinese names readable.
    target = "".join(quote(char, safe="") if char in "%#?[]|" else char for char in page.rel)
    return f"[[{target}|{title}]]"


def log_table_link(page: Page):
    title = page.title.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]").replace("|", "\\|")
    relative = Path(os.path.relpath(page.path, LOG_INDEX.parent)).as_posix()
    return f"[{title}]({quote(relative, safe='/')})"


def index_contents(pages: list[Page]):
    entry, catalogs = ["## 当前状态", ""], {}
    existing = {p.path for p in pages}
    for page_type, (catalog_path, label) in CATALOGS.items():
        selected = sorted((p for p in pages if p.fields.get("type") == page_type), key=lambda p: (p.fields.get("status") != "active", p.rel))
        if page_type == "state":
            current = [p for p in selected if p.fields.get("status") in {"active", "proposed"}]
            entry.extend(f"- {wiki(p)} — {p.fields.get('status', '?')}" for p in current)
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
                    lines.extend(f"- {wiki(p)} — {p.fields.get('status', '?')} · {p.fields.get('topic', '?')}" for p in group)
                    lines.append("")
            catalogs[catalog_path] = "\n".join(lines).rstrip() or "暂无页面。"
            entry.append(f"- [[{catalog_path.as_posix()}|{label}]] — {len(selected)} 页，按主题或模块检索。")
    entry.append("")
    logs = ["| 日期 | 类型 | 任务结果 | 日志 |", "| --- | --- | --- | --- |"]
    selected = sorted((p for p in pages if p.fields.get("type") == "log"), key=lambda p: (str(p.fields.get("updated", "")), p.rel), reverse=True)
    for p in selected:
        cells = [str(p.fields.get(k, "未记录")).replace("|", "\\|") for k in ("updated", "kind", "task_status")]
        logs.append("| " + " | ".join(cells + [log_table_link(p)]) + " |")
    if not selected:
        logs.append("| - | - | - | 暂无记录 |")
    return {ENTRY: "\n".join(entry).rstrip(), LOG_INDEX: "\n".join(logs), **catalogs}


def replace_auto(text: str, generated: str, path: Path):
    if text.count(AUTO_START) != 1 or text.count(AUTO_END) != 1:
        raise ValueError(f"{path}: expected one auto region; preserve existing content and migrate manually")
    start, end = text.index(AUTO_START) + len(AUTO_START), text.index(AUTO_END)
    if start > end:
        raise ValueError(f"{path}: invalid auto marker order")
    return text[:start] + "\n\n" + generated + "\n\n" + text[end:]


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


def initialize(project: Path, memory: Path, mode: str, today: date):
    if memory != project / "wiki_memory":
        raise ValueError("new memory must be <project>/wiki_memory; nested/custom memory-dir is only accepted by read-only check for migration")
    if memory.exists():
        raise ValueError("memory directory already exists; inspect/migrate it without init")
    override = project / "AGENTS.override.md"
    agents = override if override.exists() and read_text(override).lstrip("\ufeff").strip() else project / "AGENTS.md"
    safe_write_target(agents, project)
    previous = agents.read_bytes() if agents.exists() else b""
    try:
        instruction_text = previous.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("root instructions are not UTF-8; preserve them and adapt encoding before init") from exc
    if b"wiki-memory:start" in previous or b"wiki-memory:end" in previous:
        raise ValueError("existing memory hook found; inspect before changing it")
    refuse_competing_memory(project, memory, instruction_text)
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
    entry_body = (f"初始布局：`{mode}`（当前布局以 `.memory.json` 为准）。先读当前状态，按任务定位决策、知识与历史。\n\n"
                  "- [记忆维护协议](AGENTS.md)\n- [工作日志 MOC](日志/MOC_工作日志.md)\n\n"
                  f"{AUTO_START}\n\n{AUTO_END}\n")
    plan[memory / ENTRY] = make_page("moc", "active", "memory-entry", "工程记忆导航", entry_body, today).encode("utf-8")
    plan[memory / LOG_INDEX] = make_page("moc", "active", "work-log-index", "工作日志 MOC", f"{AUTO_START}\n\n{AUTO_END}\n", today).encode("utf-8")
    pages = [parse_page(p.relative_to(memory), data.decode("utf-8")) for p, data in plan.items() if p.suffix == ".md"]
    for path, generated in index_contents(pages).items():
        target = memory / path
        plan[target] = replace_auto(plan[target].decode("utf-8"), generated, path).encode("utf-8")
    plan[memory / ".memory.json"] = (json.dumps({"schema_version": 2, "mode": mode, "tool_version": VERSION, "navigation": ENTRY.as_posix()}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    plan[memory / "工具/memory.py"] = Path(__file__).read_bytes()
    newline = "\r\n" if b"\r\n" in previous else "\n"
    block = (f"{HOOK_START}\n## 工程记忆\n\n"
             f"本项目使用工程根目录下的 `{rel}/`。开始任务前读取 `{rel}/AGENTS.md` 和 `{rel}/README.md`，按协议读取当前状态与全局约束，再定位相关决策和模块知识。\n"
             "在已授权开发任务完成或中断时，按协议同步有证据的状态、验证和恢复下一步；只读任务遵守只读范围。\n"
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
               expected: bytes = b"", *, snapshots=None, page_root=None, new_root=None):
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
    print(json.dumps({"apply": apply, "files": [p.relative_to(project).as_posix() for p in plan]}, ensure_ascii=False, indent=2))
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


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"wiki-memory {VERSION}")
    parser.add_argument("command", choices=("init", "check", "index"))
    parser.add_argument("--project", default=".")
    parser.add_argument("--memory-dir", default="wiki_memory")
    parser.add_argument("--mode", choices=("lite", "standard"), default="lite")
    parser.add_argument("--date", type=date.fromisoformat, default=date.today(), help="local verification date (YYYY-MM-DD)")
    parser.add_argument("--stale-days", type=int, default=90)
    parser.add_argument("--apply", action="store_true", help="write the previewed init/index files")
    parser.add_argument("--require-ready", action="store_true", help="check only: require populated, active state pages with evidence before configuration delivery")
    args = parser.parse_args(argv)
    try:
        if args.command == "check" and args.apply:
            raise ValueError("check is read-only; --apply is not accepted")
        if args.require_ready and args.command != "check":
            raise ValueError("--require-ready is accepted only by read-only check")
        if args.stale_days < 0:
            raise ValueError("stale-days must be nonnegative")
        project, memory = locations(args.project, args.memory_dir)
        if args.command == "init":
            plan, agents, previous = initialize(project, memory, args.mode, args.date)
            apply_plan(plan, project, args.apply, agents, previous, new_root=memory)
            return 0
        pages = load_pages(memory)
        if args.command == "check":
            errors, warnings = inspect(project, memory, pages, args.date, args.stale_days, require_ready=args.require_ready)
            print(json.dumps({"pages": len(pages), "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        config = memory / ".memory.json"
        config_snapshot = observed_bytes(config)
        config_data = json.loads(config_snapshot.decode("utf-8-sig")) if config_snapshot is not None else {}
        if (memory != project / "wiki_memory" or not isinstance(config_data, dict)
                or config_data.get("schema_version") != 2 or config_data.get("navigation") != ENTRY.as_posix()
                or (memory / LEGACY_ENTRY).exists()):
            raise ValueError("legacy memory cannot be indexed by this version; migrate to <project>/wiki_memory, merge navigation into README.md, repair references and set schema_version 2/navigation README.md first")
        errors, _ = inspect(project, memory, pages, args.date, args.stale_days, metadata_only=True, config_bytes=config_snapshot)
        if errors:
            raise ValueError("fix metadata/decision relationships before indexing: " + "; ".join(errors))
        snapshots = {memory / p.path: p.original for p in pages}
        snapshots[config] = config_snapshot
        moc_defaults = config_data.get("moc_defaults", {})
        plan = {}
        for path, generated in index_contents(pages).items():
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
        apply_plan(plan, project, args.apply, snapshots=snapshots, page_root=memory)
        return 0
    except KeyboardInterrupt:
        print("ERROR: interrupted; inspect current files before retrying", file=sys.stderr)
        return 130
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
