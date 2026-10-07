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
from urllib.parse import unquote

AUTO_START = "<!-- wiki-memory:auto:start -->"
AUTO_END = "<!-- wiki-memory:auto:end -->"
HOOK_START = "<!-- wiki-memory:start -->"
HOOK_END = "<!-- wiki-memory:end -->"
MANAGED = {"当前状态", "决策", "知识", "日志"}
REQUIRED = {"type", "status", "updated", "topic"}
TYPES = {"state", "decision", "knowledge", "log", "moc"}
STATUSES = {"active", "proposed", "deprecated", "superseded", "archived"}
KINDS = {"feature", "ui", "bug", "discussion", "test", "maintenance"}
ENTRY = Path("入口.md")
LOG_INDEX = Path("日志/MOC_工作日志.md")
VERSION = "2.0.0"
CATALOGS = {
    "state": (Path("当前状态/MOC_状态.md"), "历史状态目录"),
    "decision": (Path("决策/MOC_决策.md"), "工程决策目录"),
    "knowledge": (Path("知识/MOC_知识.md"), "稳定知识目录"),
}
STATE_TITLES = {
    "lite": ["当前状态"],
    "standard": ["项目概览", "系统架构", "当前约束", "当前待办", "已知问题"],
}


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
    for match in re.finditer(r"\[[^\]\n]*\]\((<[^>]+>|(?:[^()\n]|\([^()\n]*\))+)\)", text):
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
    paths = list(memory.glob("*.md"))
    for folder in sorted(MANAGED):
        base = memory / folder
        if base.is_symlink():
            raise ValueError(f"refusing symlinked memory section: {base}")
        if base.is_dir():
            paths.extend(base.rglob("*.md"))
    for path in sorted(set(paths)):
        if not within(path, memory):
            raise ValueError(f"memory page escapes memory directory: {path}")
    return sorted(set(paths))


def load_pages(memory: Path) -> list[Page]:
    return [parse_page(path.relative_to(memory), read_text(path)) for path in page_paths(memory)]


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
        candidates = {rel.name, rel.name + ".md"} if rel.suffix != ".md" else {rel.name}
        if not path.exists() and rel.suffix != ".md":
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


def inspect(project: Path, memory: Path, pages: list[Page], today: date, stale_days: int, metadata_only=False):
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
                    internal_page = within(path, memory) and path.suffix == ".md"
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
        if ENTRY.as_posix() in graph and category and page.fields.get("type") != "state" and page.rel not in graph.get(category[0].as_posix(), set()):
            errors.append(f"{page.rel}: missing from category MOC; refresh index")
    seed = ENTRY.as_posix() if ENTRY.as_posix() in graph else "README.md"
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
    if config.exists():
        try:
            if not within(config, memory):
                raise ValueError("configuration escapes memory directory")
            data = json.loads(read_text(config).lstrip("\ufeff"))
            if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("mode") not in {"lite", "standard"}:
                raise ValueError("unsupported schema_version or mode")
            if data.get("tool_version") not in {None, VERSION}:
                warnings.append(f"project tool version {data.get('tool_version')} differs from running version {VERSION}; review before upgrading")
            by_path = {p.path: p for p in pages}
            for title in STATE_TITLES[data["mode"]]:
                path = Path("当前状态") / f"{title}.md"
                if path not in by_path or by_path[path].fields.get("type") != "state":
                    errors.append(f"{path.as_posix()}: required state page missing for {data['mode']} mode")
                elif str(by_path[path].fields.get("status", "")) not in {"active", "proposed"}:
                    errors.append(f"{path.as_posix()}: required state page must be current (active/proposed)")
        except (ValueError, TypeError) as exc:
            errors.append(f".memory.json: {exc}")
        override = project / "AGENTS.override.md"
        agents = override if override.exists() and read_text(override).lstrip("\ufeff").strip() else project / "AGENTS.md"
        rel = memory.relative_to(project).as_posix()
        text = read_text(agents) if agents.exists() else ""
        if f"{rel}/AGENTS.md" not in text or f"{rel}/入口.md" not in text:
            warnings.append("effective root instructions lack memory hook; verify session discovery")
    return sorted(set(errors)), sorted(set(warnings))


def make_page(page_type, status, topic, title, body, today):
    return (f"---\ntype: {page_type}\nstatus: {status}\nupdated: {today.isoformat()}\n"
            f"topic: {topic}\nsources: []\n---\n\n# {title}\n\n{body.rstrip()}\n")


def wiki(page: Page):
    title = page.title.replace("|", "\\|").replace("[", "").replace("]", "")
    return f"[[{page.rel}|{title}]]"


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
        logs.append("| " + " | ".join(cells + [wiki(p)]) + " |")
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
    if memory.exists():
        raise ValueError("memory directory already exists; inspect/migrate it without init")
    override = project / "AGENTS.override.md"
    agents = override if override.exists() and read_text(override).lstrip("\ufeff").strip() else project / "AGENTS.md"
    safe_write_target(agents, project)
    previous = agents.read_bytes() if agents.exists() else b""
    try:
        previous.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("root instructions are not UTF-8; preserve them and adapt encoding before init") from exc
    if b"wiki-memory:start" in previous or b"wiki-memory:end" in previous:
        raise ValueError("existing memory hook found; inspect before changing it")
    protocol = Path(__file__).resolve().parents[1] / "assets/protocol.md"
    if not protocol.is_file():
        raise ValueError("init must run from the Skill package, which contains assets/protocol.md")
    rel = memory.relative_to(project).as_posix()
    content = read_text(protocol).replace("__MEMORY_DIR__", rel).replace("__MODE__", mode).replace("__VERSION__", VERSION)
    plan = {memory / "AGENTS.md": content.encode("utf-8")}
    summary = "> 初始化结构，尚未核实项目事实；填写证据后改为 active。\n\n"
    if mode == "lite":
        states = [("当前状态", "project-state", ["项目目标与阶段", "关键入口与运行命令", "约束与已确认选择", "当前进度与已知问题", "恢复位置与下一步", "证据与未核实项"])]
    else:
        states = [
            ("项目概览", "project-overview", ["项目目标与阶段", "核心入口", "证据与未核实项"]),
            ("系统架构", "system-architecture", ["模块职责与边界", "数据流与依赖", "运行与部署", "证据与未核实项"]),
            ("当前约束", "project-constraints", ["用户要求与技术约束", "兼容性与操作边界", "证据与未核实项"]),
            ("当前待办", "current-todos", ["进行中", "下一步", "阻塞与恢复位置", "证据与未核实项"]),
            ("已知问题", "known-issues", ["未解决问题与影响", "复现与临时处理", "证据与未核实项"]),
        ]
    for title, topic, sections in states:
        body = summary + "\n\n".join(f"## {section}\n\n- 待核实。" for section in sections)
        plan[memory / "当前状态" / f"{title}.md"] = make_page("state", "proposed", topic, title, body, today).encode("utf-8")
    entry_body = (f"初始布局：`{mode}`（当前布局以 `.memory.json` 为准）。先读当前状态，按任务定位决策、知识与历史。\n\n"
                  "- [记忆维护协议](AGENTS.md)\n- [工作日志 MOC](日志/MOC_工作日志.md)\n\n"
                  f"{AUTO_START}\n\n{AUTO_END}\n")
    plan[memory / ENTRY] = make_page("moc", "active", "memory-entry", "工程记忆入口", entry_body, today).encode("utf-8")
    plan[memory / LOG_INDEX] = make_page("moc", "active", "work-log-index", "工作日志 MOC", f"{AUTO_START}\n\n{AUTO_END}\n", today).encode("utf-8")
    pages = [parse_page(p.relative_to(memory), data.decode("utf-8")) for p, data in plan.items() if p.suffix == ".md"]
    for path, generated in index_contents(pages).items():
        target = memory / path
        plan[target] = replace_auto(plan[target].decode("utf-8"), generated, path).encode("utf-8")
    plan[memory / ".memory.json"] = (json.dumps({"schema_version": 1, "mode": mode, "tool_version": VERSION}, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    plan[memory / "工具/memory.py"] = Path(__file__).read_bytes()
    newline = "\r\n" if b"\r\n" in previous else "\n"
    block = (f"{HOOK_START}\n## 工程记忆\n\n"
             f"本项目使用 `{rel}/`。开始任务前读取 `{rel}/AGENTS.md` 和 `{rel}/入口.md`，按协议读取当前状态与全局约束，再定位相关决策和模块知识。\n"
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
    manifest = {p for p, original in baseline.items() if original is not None and p.suffix == ".md" and page_root and within(p, page_root)}

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
                if page_root is not None and path.suffix == ".md" and within(path, page_root):
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
    args = parser.parse_args(argv)
    try:
        if args.command == "check" and args.apply:
            raise ValueError("check is read-only; --apply is not accepted")
        if args.stale_days < 0:
            raise ValueError("stale-days must be nonnegative")
        project, memory = locations(args.project, args.memory_dir)
        if args.command == "init":
            plan, agents, previous = initialize(project, memory, args.mode, args.date)
            apply_plan(plan, project, args.apply, agents, previous, new_root=memory)
            return 0
        pages = load_pages(memory)
        if args.command == "check":
            errors, warnings = inspect(project, memory, pages, args.date, args.stale_days)
            print(json.dumps({"pages": len(pages), "errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
            return 1 if errors else 0
        errors, _ = inspect(project, memory, pages, args.date, args.stale_days, metadata_only=True)
        if errors:
            raise ValueError("fix metadata/decision relationships before indexing: " + "; ".join(errors))
        snapshots = {memory / p.path: p.original for p in pages}
        config = memory / ".memory.json"
        if config.exists():
            snapshots[config] = config.read_bytes()
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
                                 f"{AUTO_START}\n\n{AUTO_END}\n", args.date)
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
