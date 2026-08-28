#!/usr/bin/env python3
"""Safe, configurable PDF-book to Markdown knowledge-base pipeline.

The script deliberately keeps the PDF extraction layer conservative. It is a
local helper for the ``pdf-book-to-obsidian`` skill, not a general OCR system.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

try:  # PyMuPDF's modern import name.
    import pymupdf as fitz  # type: ignore
except ModuleNotFoundError:  # Codex's bundled runtime currently exposes fitz.
    try:
        import fitz  # type: ignore
    except ModuleNotFoundError:  # pragma: no cover - exercised in diagnostics.
        fitz = None  # type: ignore

try:
    from markdown_tables import transform_definition_lists
except ImportError:  # pragma: no cover - permits importing as a package.
    from .markdown_tables import transform_definition_lists  # type: ignore

try:
    from markdown_layout_repair import compact_unordered_list_spacing, repair_broken_emphasis
except ImportError:  # pragma: no cover - permits importing as a package.
    from .markdown_layout_repair import compact_unordered_list_spacing, repair_broken_emphasis  # type: ignore

try:
    from markdown_obsidian import (
        CALLOUT_TYPES,
        callout_style as resolve_callout_style,
        convert_callouts_text,
        inline_image_syntax as resolve_inline_image_syntax,
        markdown_baseline as resolve_markdown_baseline,
        render_file_embed,
        render_inline_file_embed,
        render_note_link,
    )
except ImportError:  # pragma: no cover - permits importing as a package.
    from .markdown_obsidian import (  # type: ignore
        CALLOUT_TYPES,
        callout_style as resolve_callout_style,
        convert_callouts_text,
        inline_image_syntax as resolve_inline_image_syntax,
        markdown_baseline as resolve_markdown_baseline,
        render_file_embed,
        render_inline_file_embed,
        render_note_link,
    )


GENERATOR = "pdf-book-to-obsidian"
VERSION = "0.8.0"
RESOURCE_DIRS = ("PDF", "Config", "Reports", "Backups", "Attachment")
DEFAULT_CHAPTER_PATTERN = re.compile(
    r"^chapter\s+(?P<number>[0-9]+|[ivxlcdm]+)\s*[:.\-–—]?\s*(?P<title>.+)$",
    re.IGNORECASE,
)
FIGURE_CAPTION_RE = re.compile(
    r"^Figure\s+\d+(?:\.\d+)?\s*[–—-]\s*.+$",
    re.IGNORECASE,
)
INLINE_IMAGE_POLICIES = {"auto", "block"}
VISUAL_TABLE_DISCOVERY_POLICIES = {"auto", "off"}
BOXED_CALLOUT_POLICIES = {"auto", "off"}
ROMAN_PAGE_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)


class PipelineError(RuntimeError):
    """Expected user-actionable pipeline failure."""


class ConflictError(PipelineError):
    """A write would overwrite an untrusted or manually edited file."""


@dataclass
class Chapter:
    number: str
    title: str
    part: str
    start_page: int
    end_page: int
    print_pages: str = ""


@dataclass
class Section:
    section_id: str
    title: str
    kind: str
    folder: str
    filename: str
    start_page: int
    end_page: int
    print_pages: str = ""
    part: str = ""


@dataclass
class OutputFile:
    relative_path: str
    content: bytes
    kind: str


def require_pdf_runtime() -> Any:
    if fitz is None:
        raise PipelineError(
            "PyMuPDF is unavailable. Run this script with the Codex bundled "
            "Python runtime or provide pymupdf/fitz in the selected environment."
        )
    return fitz


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_component(value: str, fallback: str = "Untitled") -> str:
    value = re.sub(r'[<>:"/\\|?*]', " - ", str(value))
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value or fallback


def as_posix(path: Path) -> str:
    return path.as_posix()


def vault_relative(vault: Path, path: Path) -> str:
    try:
        return as_posix(path.resolve().relative_to(vault.resolve()))
    except ValueError as exc:
        raise PipelineError(f"Path is outside the vault: {path}") from exc


def vault_path(vault: Path, relative: str | Path) -> Path:
    candidate = (vault / Path(str(relative).replace("/", os.sep))).resolve()
    try:
        candidate.relative_to(vault.resolve())
    except ValueError as exc:
        raise PipelineError(f"Refusing path outside vault: {relative}") from exc
    return candidate


def yaml_quote(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return yaml_quote(str(value))


def emit_frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, list):
            value_text = "[" + ", ".join(yaml_scalar(item) for item in value) + "]"
        else:
            value_text = yaml_scalar(value)
        lines.append(f"{key}: {value_text}")
    lines.extend(["---", ""])
    return "\n".join(lines)


def normalise_text(text: str) -> str:
    text = text.replace("\u00ad", "").replace("\ufeff", "").replace("\xa0", " ").replace("\ufffd", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    compact: list[str] = []
    blank_count = 0
    for line in lines:
        if line.strip():
            blank_count = 0
            compact.append(line)
        else:
            blank_count += 1
            if blank_count <= 2:
                compact.append("")
    return "\n".join(compact)


_SPLIT_URL_SUFFIX_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]*$"
)


def merge_split_inline_code_urls(text: str) -> str:
    """Join only adjacent inline-code spans that clearly form one URL.

    PDF extraction commonly splits a URL at a line or span boundary. The
    protocol prefix and URL-safe suffix checks deliberately avoid joining
    ordinary neighbouring code spans.
    """
    pattern = re.compile(
        r"`(?P<prefix>https?://[^`\n]*)`\s+`(?P<suffix>[^`\n]+)`",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        suffix = match.group("suffix")
        if not prefix.endswith(("/", "://")):
            return match.group(0)
        if not _SPLIT_URL_SUFFIX_RE.fullmatch(suffix):
            return match.group(0)
        return f"`{prefix}{suffix}`"

    previous = None
    current = text
    for _ in range(8):
        if current == previous:
            break
        previous = current
        current = pattern.sub(replace, current)
    return current


_PLAIN_URL_CHAR_RE = r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]"


def merge_split_plain_urls(text: str) -> str:
    """Join a URL split at a physical PDF line boundary only at a URL edge."""
    pattern = re.compile(
        rf"(?P<prefix>https?://|https?://{_PLAIN_URL_CHAR_RE}*?(?:/|://))\n(?P<suffix>[A-Za-z0-9])",
        re.IGNORECASE,
    )
    previous = None
    current = text
    for _ in range(8):
        if current == previous:
            break
        previous = current
        current = pattern.sub(lambda match: match.group("prefix") + match.group("suffix"), current)
    return current


def normalise_heading_text(text: str) -> str:
    """Collapse PDF outline/page-title wrapping without changing wording."""
    return re.sub(r"\s+", " ", str(text).replace("\u00a0", " ")).strip()


def format_page_range(start_page: int, end_page: int) -> str:
    return str(start_page) if start_page == end_page else f"{start_page}-{end_page}"


def merge_tags(*values: Any) -> list[str]:
    tags: list[str] = []
    for value in values:
        if isinstance(value, str):
            candidates = [value]
        elif isinstance(value, (list, tuple)):
            candidates = [str(item) for item in value]
        else:
            candidates = []
        for tag in candidates:
            tag = tag.strip()
            if tag and tag not in tags:
                tags.append(tag)
    return tags


def apply_line_filters(text: str, config: dict[str, Any]) -> str:
    filters = config.get("filters") or {}
    remove_lines = {str(item).strip() for item in filters.get("remove_lines", []) or []}
    remove_regexes = [re.compile(str(item)) for item in filters.get("remove_regexes", []) or []]
    if not remove_lines and not remove_regexes:
        return text
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped in remove_lines:
            continue
        if any(pattern.search(stripped) for pattern in remove_regexes):
            continue
        kept.append(line)
    return "\n".join(kept)


def strip_yaml_comments(line: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
            continue
        if char == "\\" and quote:
            escaped = True
            continue
        if char in ("'", '"'):
            quote = None if quote == char else char if quote is None else quote
        elif char == "#" and quote is None and (index == 0 or line[index - 1].isspace()):
            return line[:index].rstrip()
    return line.rstrip()


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return None
    if value in {"true", "True", "TRUE"}:
        return True
    if value in {"false", "False", "FALSE"}:
        return False
    if value in {"null", "Null", "NULL", "~"}:
        return None
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value[1:-1]
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            try:
                return ast.literal_eval(value)
            except (SyntaxError, ValueError):
                return value
    if re.fullmatch(r"[-+]?\d+", value):
        return int(value)
    if re.fullmatch(r"[-+]?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    return value


def minimal_yaml_load(text: str) -> Any:
    """Parse the small YAML subset used by book-config.yaml without PyYAML."""
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        clean = strip_yaml_comments(raw)
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        rows.append((indent, clean.strip()))
    if not rows:
        return {}
    root: Any = {}
    stack: list[tuple[int, Any]] = [(-1, root)]

    for index, (indent, content) in enumerate(rows):
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()
        parent = stack[-1][1]
        next_row = rows[index + 1] if index + 1 < len(rows) else None
        if content.startswith("-"):
            if not isinstance(parent, list):
                raise ValueError(f"YAML list has no list parent: {content}")
            rest = content[1:].strip()
            if not rest:
                child: Any = [] if next_row and next_row[0] > indent and next_row[1].startswith("-") else {}
                parent.append(child)
                stack.append((indent, child))
                continue
            if ":" in rest and not rest.startswith(("http://", "https://")):
                key, value = rest.split(":", 1)
                child = {key.strip(): parse_scalar(value)}
                parent.append(child)
                stack.append((indent, child))
            else:
                parent.append(parse_scalar(rest))
            continue

        if ":" not in content:
            raise ValueError(f"YAML mapping line has no colon: {content}")
        key, value = content.split(":", 1)
        key = key.strip()
        if not isinstance(parent, dict):
            raise ValueError(f"YAML mapping has no mapping parent: {content}")
        if value.strip():
            parent[key] = parse_scalar(value)
            continue
        is_list = bool(next_row and next_row[0] > indent and next_row[1].startswith("-"))
        child = [] if is_list else {}
        parent[key] = child
        stack.append((indent, child))
    return root


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        value = yaml.safe_load(text)
    except ModuleNotFoundError:
        value = minimal_yaml_load(text)
    except Exception as exc:
        raise PipelineError(f"Cannot parse configuration {path}: {exc}") from exc
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise PipelineError(f"Configuration must be a mapping: {path}")
    return value


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_config(book: str) -> dict[str, Any]:
    return {
        "modules": {
            "chapterize": True,
            "sections": False,
            "attachments": False,
            "code_blocks": False,
            "tables": False,
            "visual_tables": False,
            "lens": False,
            "moc": False,
            "topic_index": False,
        },
        "output": {
            "chapter_filename": "Chapter {number} - {title}.md",
            "section_filename": "{title}.md",
            "moc_filename": "MOC - {book}.md",
            "default_part": "00_Book",
            "markdown_baseline": "obsidian",
            "page_links": "chapter",
            "source_reference_style": "linked-blockquote",
            "figure_caption_style": "plain",
            "image_placement": "pdf-coordinate",
            "inline_image_policy": "auto",
            "inline_image_syntax": "obsidian-wiki",
        },
        "table_transform": {"enabled": False, "min_rows": 2},
        "visual_tables": {"enabled": False, "regions": []},
        "code_blocks": {"enabled": False, "inline": True, "min_lines": 2, "min_chars": 60},
        "attachments": {"include_section_kinds": ["part", "part-overview", "part_overview", "back-matter", "backmatter", "index"]},
        "frontmatter": {"type_field": "kind", "extra": {}},
        "book_metadata": {},
        "lens": {"enabled": False},
        "ocr": {"enabled": False},
        "chapters": [],
        "parts": [],
        "sections": [],
        "book": book,
        "book_specific_decisions": [],
    }


RESOURCE_PATH_KEYS = {
    "PDF": ("source_dir", "pdf_dir", "pdf"),
    "Reports": ("reports", "report_dir"),
    "Backups": ("backups", "backup_dir"),
    "Attachment": ("attachments", "attachment_dir"),
}


def resolve_configured_path(base: Path, value: Any) -> Path:
    raw = Path(str(value))
    return raw.resolve() if raw.is_absolute() else (base / raw).resolve()


def config_path_for(vault: Path, book: str, explicit: str | None) -> Path:
    if explicit:
        raw = Path(explicit)
        return raw if raw.is_absolute() else vault_path(vault, raw)
    return vault / "File" / "Config" / safe_component(book) / "book-config.yaml"


def resource_root(vault: Path, resource: str, book: str, config: dict[str, Any] | None = None) -> Path:
    paths = (config or {}).get("paths") or {}
    for key in RESOURCE_PATH_KEYS.get(resource, ()):
        value = paths.get(key)
        if value:
            return resolve_configured_path(vault, value)
    return vault / "File" / resource / safe_component(book)


def resolve_source(
    vault: Path,
    book: str,
    config: dict[str, Any],
    cli_source: str | None,
) -> tuple[Path, Path, bool]:
    source_config = cli_source or config.get("source_pdf")
    managed_dir = resource_root(vault, "PDF", book, config)
    if source_config:
        raw = Path(str(source_config))
        source = raw if raw.is_absolute() else vault_path(vault, raw)
    else:
        candidates = sorted(managed_dir.glob("*.pdf")) if managed_dir.exists() else []
        if len(candidates) != 1:
            if not candidates:
                raise PipelineError(
                    f"No PDF found in {managed_dir}. Put the source PDF there or pass --source."
                )
            raise PipelineError(f"Multiple PDFs found in {managed_dir}; specify --source.")
        source = candidates[0]
    source = source.resolve()
    if not source.exists() or not source.is_file():
        raise PipelineError(f"Source PDF does not exist: {source}")
    managed = False
    try:
        source.relative_to(managed_dir.resolve())
        managed = True
    except ValueError:
        pass
    target = managed_dir / source.name
    return source, target, managed


def inspect_pdf(source: Path) -> dict[str, Any]:
    pdf = require_pdf_runtime()
    document = pdf.open(str(source))
    try:
        text_pages = 0
        image_pages = 0
        character_count = 0
        for page in document:
            text = page.get_text("text") or ""
            if text.strip():
                text_pages += 1
                character_count += len(text)
            if page.get_images(full=True):
                image_pages += 1
        pages = int(document.page_count)
        blank_or_image_only = pages - text_pages
        scan_ratio = blank_or_image_only / pages if pages else 1.0
        return {
            "path": str(source),
            "sha256": sha256_file(source),
            "page_count": pages,
            "text_pages": text_pages,
            "image_pages": image_pages,
            "character_count": character_count,
            "non_text_page_ratio": round(scan_ratio, 6),
            "likely_scanned": text_pages == 0 or scan_ratio >= 0.2,
            "metadata": dict(document.metadata or {}),
        }
    finally:
        document.close()


def number_sort_key(value: str) -> tuple[int, str]:
    match = re.fullmatch(r"\d+", value)
    return (int(value), "") if match else (10**9, value.lower())


def chapter_from_mapping(item: dict[str, Any], page_count: int, index: int) -> Chapter:
    number = str(item.get("number", index))
    title = str(item.get("title") or f"Chapter {number}").strip()
    start = int(item.get("start_page", 1))
    end = int(item.get("end_page", page_count))
    if start < 1 or end < start or end > page_count:
        raise PipelineError(f"Invalid chapter page range for {title}: {start}-{end}")
    return Chapter(
        number=number,
        title=title,
        part=str(item.get("part") or ""),
        start_page=start,
        end_page=end,
        print_pages=str(item.get("print_pages") or ""),
    )


def section_from_mapping(item: dict[str, Any], page_count: int, index: int, config: dict[str, Any]) -> Section:
    section_id = str(item.get("id") or item.get("section_id") or f"section-{index}")
    title = str(item.get("title") or section_id).strip()
    kind = str(item.get("type") or item.get("kind") or "paratext").strip()
    start = int(item.get("start_page", 1))
    end = int(item.get("end_page", page_count))
    if start < 1 or end < start or end > page_count:
        raise PipelineError(f"Invalid section page range for {title}: {start}-{end}")
    output = config.get("output") or {}
    default_folder = "04_Back Matter" if kind in {"back-matter", "backmatter", "index"} else "00_Paratext"
    folder = str(item.get("folder") or default_folder)
    filename = str(item.get("filename") or output.get("section_filename") or "{title}.md")
    filename = filename.replace("{id}", section_id).replace("{title}", title).replace("{book}", str(config.get("book_title") or config.get("book") or "Book"))
    return Section(
        section_id=section_id,
        title=title,
        kind=kind,
        folder=safe_component(folder),
        filename=safe_component(filename),
        start_page=start,
        end_page=end,
        print_pages=str(item.get("print_pages") or ""),
        part=str(item.get("part") or ""),
    )


def parse_heading(line: str, pattern: re.Pattern[str] = DEFAULT_CHAPTER_PATTERN) -> tuple[str, str] | None:
    match = pattern.match(line.strip())
    if not match:
        return None
    groups = match.groupdict()
    number = groups.get("number") or (match.group(1) if match.lastindex else "")
    title = groups.get("title") or (match.group(2) if match.lastindex and match.lastindex >= 2 else "")
    if not number or not title:
        return None
    return number, title.strip()


def infer_chapters(document: Any, config: dict[str, Any]) -> list[Chapter]:
    page_count = int(document.page_count)
    headings: list[tuple[str, str, int]] = []
    configured_pattern = config.get("chapter_heading_regex")
    pattern = re.compile(str(configured_pattern), re.IGNORECASE) if configured_pattern else DEFAULT_CHAPTER_PATTERN

    try:
        toc = document.get_toc(simple=True)
    except Exception:
        toc = []
    for row in toc or []:
        if len(row) < 3:
            continue
        # PDF outline titles frequently wrap across visual lines. Normalize
        # that whitespace before applying the chapter pattern so a title such
        # as ``Chapter 1: Creating Your First Unreal\nC++ Game`` remains one
        # chapter heading.
        title = normalise_heading_text(row[1])
        parsed = parse_heading(title, pattern)
        if parsed:
            headings.append((parsed[0], parsed[1], int(row[2])))

    if not headings:
        for page_index in range(page_count):
            text = document[page_index].get_text("text", sort=True) or ""
            for line in text.splitlines():
                parsed = parse_heading(line, pattern)
                if parsed:
                    candidate = (parsed[0], parsed[1], page_index + 1)
                    if not headings or candidate[2] != headings[-1][2]:
                        headings.append(candidate)

    if not headings:
        return [Chapter("1", str(config.get("book_title") or config.get("book") or "Book"), "", 1, page_count)]

    unique: list[tuple[str, str, int]] = []
    seen_pages: set[int] = set()
    for heading in headings:
        if heading[2] not in seen_pages:
            unique.append(heading)
            seen_pages.add(heading[2])
    chapters: list[Chapter] = []
    for index, (number, title, start) in enumerate(unique):
        end = unique[index + 1][2] - 1 if index + 1 < len(unique) else page_count
        chapters.append(Chapter(number, title, "", start, end))
    return chapters


def resolve_chapters(document: Any, config: dict[str, Any]) -> list[Chapter]:
    configured = config.get("chapters") or []
    page_count = int(document.page_count)
    if configured:
        chapters = [
            chapter_from_mapping(item, page_count, index + 1)
            for index, item in enumerate(configured)
            if isinstance(item, dict)
        ]
    else:
        chapters = infer_chapters(document, config)

    parts = config.get("parts") or []
    for chapter in chapters:
        if chapter.part:
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            start_number = str(part.get("start_chapter", ""))
            end_number = str(part.get("end_chapter", ""))
            if start_number and end_number and number_sort_key(start_number) <= number_sort_key(chapter.number) <= number_sort_key(end_number):
                chapter.part = str(part.get("folder") or part.get("title") or "")
                break
        if not chapter.part:
            chapter.part = str((config.get("output") or {}).get("default_part") or "00_Book")
    return chapters


def resolve_sections(document: Any, config: dict[str, Any]) -> list[Section]:
    page_count = int(document.page_count)
    sections = config.get("sections") or []
    return [
        section_from_mapping(item, page_count, index + 1, config)
        for index, item in enumerate(sections)
        if isinstance(item, dict)
    ]


def format_output_name(pattern: str, book: str, chapter: Chapter) -> str:
    values = {"number": chapter.number, "title": chapter.title, "book": book}

    def replace(match: re.Match[str]) -> str:
        key = match.group("key")
        spec = match.group("spec") or ""
        value = values[key]
        if key == "number" and spec:
            try:
                return format(int(str(value)), spec)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    rendered = re.sub(
        r"\{(?P<key>number|title|book)(?::(?P<spec>[^}]+))?\}",
        replace,
        pattern,
    )
    return safe_component(rendered)


def relative_link(from_file: Path, target: Path, vault: Path) -> str:
    relative = os.path.relpath(target, start=from_file.parent)
    return Path(relative).as_posix()


def source_reference(
    page_number: int,
    config: dict[str, Any],
    *,
    output_path: Path | None = None,
    source_path: Path | None = None,
    vault: Path | None = None,
) -> str:
    """Render a source-page reference using the book's selected style.

    The historical linked-blockquote format remains the compatibility default;
    a book can select a compact plain blockquote without changing extraction.
    """
    style = str((config.get("output") or {}).get("source_reference_style") or "linked-blockquote")
    if style == "none":
        return ""
    if style == "plain-blockquote":
        return f"> Source PDF, p. {page_number}"
    if style != "linked-blockquote":
        raise PipelineError(
            "output.source_reference_style must be linked-blockquote, plain-blockquote, or none"
        )
    if output_path is None or source_path is None or vault is None:
        raise PipelineError("Linked source references require output_path, source_path, and vault")
    return f"> [Source PDF, p. {page_number}]({relative_link(output_path, source_path, vault)}#page={page_number})"


def frontmatter_type(config: dict[str, Any]) -> str:
    return str((config.get("frontmatter") or {}).get("type_field") or "kind")


def source_frontmatter(
    config: dict[str, Any],
    kind: str,
    book: str,
    title: str,
    source_path: Path,
    source_hash: str,
    vault: Path,
    start_page: int,
    end_page: int,
    *,
    part: str = "",
    number: str = "",
    print_pages: str = "",
    include_book_metadata: bool = False,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        frontmatter_type(config): kind,
        "book": book,
    }
    if part:
        fields["part"] = part
    if number:
        fields["chapter"] = int(number) if number.isdigit() else number
    fields["title"] = title
    metadata = config.get("book_metadata") or {}
    if include_book_metadata:
        for key in ("publisher", "published", "isbn"):
            if metadata.get(key) not in {None, ""}:
                fields[key] = metadata[key]
    else:
        for key in ("technology", "language"):
            if metadata.get(key) not in {None, ""}:
                fields[key] = metadata[key]
    if print_pages:
        fields["print_pages"] = print_pages
    fields["pdf_pages"] = format_page_range(start_page, end_page)
    fields["source_pages"] = [start_page, end_page]
    fields["source_pdf"] = vault_relative(vault, source_path) if source_path.is_relative_to(vault.resolve()) else str(source_path)
    fields["source_sha256"] = source_hash
    fields["generated_by"] = GENERATOR
    fields["generator_version"] = VERSION
    tags = merge_tags(metadata.get("tags"), (config.get("frontmatter") or {}).get("tags"))
    type_tag = f"type/{kind}"
    if type_tag not in tags:
        tags.append(type_tag)
    if tags:
        fields["tags"] = tags
    extra = (config.get("frontmatter") or {}).get("extra") or {}
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key not in fields:
                fields[str(key)] = value
    return fields


def resolve_inline_image_policy(config: dict[str, Any] | None) -> str:
    output = (config or {}).get("output") or {}
    value = str(output.get("inline_image_policy") or "auto").strip().lower()
    if value not in INLINE_IMAGE_POLICIES:
        raise PipelineError("output.inline_image_policy must be auto or block")
    return value


def resolve_visual_table_discovery(config: dict[str, Any] | None) -> str:
    """Resolve geometry-based table discovery without requiring page lists.

    Existing configurations may continue to provide explicit visual-table
    regions.  When visual tables are enabled, discovery defaults to ``auto``
    so clear grids are not silently lost merely because a page was not
    registered in advance.
    """
    settings = (config or {}).get("visual_tables") or {}
    value = str(settings.get("discovery") or "auto").strip().lower()
    if value not in VISUAL_TABLE_DISCOVERY_POLICIES:
        raise PipelineError("visual_tables.discovery must be auto or off")
    return value


def resolve_boxed_callout_policy(config: dict[str, Any] | None) -> str:
    """Resolve detection of clearly labelled bordered editorial boxes."""
    output = (config or {}).get("output") or {}
    value = str(output.get("boxed_callout_policy") or "auto").strip().lower()
    if value not in BOXED_CALLOUT_POLICIES:
        raise PipelineError("output.boxed_callout_policy must be auto or off")
    return value


def is_pdf_page_number(value: str) -> bool:
    """Return whether text is only a printed numeric or Roman page number."""
    token = value.strip()
    return bool(re.fullmatch(r"\d+", token) or ROMAN_PAGE_RE.fullmatch(token))


def page_text_lines(page: Any) -> list[dict[str, Any]]:
    """Return text-line geometry used to detect images embedded in prose."""
    try:
        blocks = page.get_text("dict", sort=True).get("blocks", [])
    except Exception:
        return []
    lines: list[dict[str, Any]] = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []) or []:
            if not isinstance(line, dict):
                continue
            bbox = line.get("bbox") or (0, 0, 0, 0)
            x0, y0, x1, y1 = (float(value) for value in bbox[:4])
            text = "".join(
                clean_span_text(span.get("text"))
                for span in line.get("spans", []) or []
                if isinstance(span, dict)
            )
            if text.strip() and x1 > x0 and y1 > y0:
                lines.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1})
    merged: list[dict[str, Any]] = []
    for line in sorted(lines, key=lambda item: (item["y0"], item["x0"])):
        if merged:
            previous = merged[-1]
            same_baseline = (
                abs(line["y0"] - previous["y0"]) <= 1.0
                and abs(line["y1"] - previous["y1"]) <= 1.0
            )
            gap = line["x0"] - previous["x1"]
            max_gap = max(16.0, (line["y1"] - line["y0"]) * 2.0)
            if same_baseline and gap <= max_gap:
                previous["x1"] = max(previous["x1"], line["x1"])
                previous["y0"] = min(previous["y0"], line["y0"])
                previous["y1"] = max(previous["y1"], line["y1"])
                continue
        merged.append(dict(line))
    return merged


def classify_inline_image(
    page: Any,
    image: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify a positioned PDF image without relying on book-specific names.

    An image is an inline icon only when it overlaps one text line by a useful
    amount and its displayed dimensions are close to that line's height. A
    boundary or geometry ambiguity remains a block image and is reported.
    """
    policy = resolve_inline_image_policy(config)
    if policy == "block":
        return {
            "image_role": "figure-image",
            "image_classification": "forced-block",
            "image_classification_reason": "inline image policy is block",
        }

    x0 = float(image.get("x0", 0.0))
    y0 = float(image.get("y0", 0.0))
    x1 = float(image.get("x1", 0.0))
    y1 = float(image.get("y1", 0.0))
    image_width = max(0.0, x1 - x0)
    image_height = max(0.0, y1 - y0)
    if image_width <= 0.0 or image_height <= 0.0:
        return {
            "image_role": "figure-image",
            "image_classification": "ambiguous",
            "image_classification_reason": "image has no usable display rectangle",
        }

    overlaps: list[dict[str, Any]] = []
    for line in page_text_lines(page):
        line_height = line["y1"] - line["y0"]
        vertical_overlap = min(y1, line["y1"]) - max(y0, line["y0"])
        horizontal_overlap = min(x1, line["x1"]) - max(x0, line["x0"])
        # Ignore sub-point contact at adjacent line boundaries. It is common
        # for PDF glyph boxes and image boxes to touch without overlapping.
        useful_overlap = max(0.75, min(line_height, image_height) * 0.1)
        if vertical_overlap > useful_overlap and horizontal_overlap > 0.0:
            overlaps.append({**line, "vertical_overlap": vertical_overlap})

    if not overlaps:
        return {
            "image_role": "figure-image",
            "image_classification": "clear-block",
            "image_classification_reason": "image does not overlap a text line",
        }
    if len(overlaps) != 1:
        return {
            "image_role": "figure-image",
            "image_classification": "ambiguous",
            "image_classification_reason": "image overlaps multiple text lines",
        }

    line = overlaps[0]
    line_height = line["y1"] - line["y0"]
    if image_width <= max(24.0, line_height * 3.0) and image_height <= max(24.0, line_height * 2.0):
        return {
            "image_role": "inline-icon",
            "image_classification": "clear-inline",
            "image_classification_reason": "small image overlaps one text line",
            "inline_line_x0": line["x0"],
            "inline_line_y0": line["y0"],
            "inline_line_x1": line["x1"],
            "inline_line_y1": line["y1"],
        }
    return {
        "image_role": "figure-image",
        "image_classification": "clear-block",
        "image_classification_reason": "image overlaps text but is not line-sized",
    }


def extract_images(
    document: Any,
    chapters: Iterable[Chapter],
    attachment_root: Path,
    book: str,
    link_root: Path | None = None,
    config: dict[str, Any] | None = None,
) -> tuple[dict[int, list[dict[str, Any]]], list[dict[str, Any]]]:
    by_page: dict[int, list[dict[str, Any]]] = {}
    records: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for chapter in chapters:
        for page_number in range(chapter.start_page, chapter.end_page + 1):
            page = document[page_number - 1]
            for image in page.get_images(full=True):
                xref = int(image[0])
                identity = (page_number, xref)
                if identity in seen:
                    continue
                seen.add(identity)
                try:
                    extracted = document.extract_image(xref)
                except Exception:
                    continue
                data = extracted.get("image")
                if not data:
                    continue
                extension = str(extracted.get("ext") or "bin")
                filename = f"Figure-p{page_number:04d}-{xref}.{extension}"
                target = (attachment_root / filename).resolve()
                root = (link_root or attachment_root).resolve()
                try:
                    relative = as_posix(target.relative_to(root))
                except ValueError as exc:
                    raise PipelineError(
                        "The configured attachment directory must be inside the Markdown output root "
                        f"so generated links remain portable: {target}"
                    ) from exc
                rects: list[Any] = []
                try:
                    rects = list(page.get_image_rects(xref))
                except Exception:
                    rects = []
                if rects:
                    x0 = min(float(rect.x0) for rect in rects)
                    y0 = min(float(rect.y0) for rect in rects)
                    x1 = max(float(rect.x1) for rect in rects)
                    y1 = max(float(rect.y1) for rect in rects)
                    placement = "pdf-coordinate"
                else:
                    page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
                    x0, y0, x1, y1 = 0.0, page_height + 1.0, 0.0, page_height + 1.0
                    placement = "fallback-page-end"
                item = {
                    "relative_path": relative,
                    "data": data,
                    "page": page_number,
                    "xref": xref,
                    "x0": x0,
                    "y0": y0,
                    "x1": x1,
                    "y1": y1,
                    "placement": placement,
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                }
                item.update(classify_inline_image(page, item, config))
                if item.get("image_role") == "inline-icon":
                    item["placement"] = "inline-text"
                by_page.setdefault(page_number, []).append(item)
                records.append({key: value for key, value in item.items() if key != "data"})
    return by_page, records


MONOSPACE_FONT_RE = re.compile(r"(?:courier|mono|consolas|menlo|code|source ?code)", re.IGNORECASE)
BULLET_CHARS = "●•▪‣◦"


def clean_span_text(value: Any) -> str:
    return str(value or "").replace("\u00ad", "").replace("\xa0", " ").replace("\ufffd", "")


def span_is_monospace(span: dict[str, Any]) -> bool:
    return bool(MONOSPACE_FONT_RE.search(str(span.get("font") or "")))


def span_style(span: dict[str, Any]) -> tuple[bool, bool]:
    font = str(span.get("font") or "").lower()
    flags = int(span.get("flags") or 0)
    return bool(flags & 16) or "bold" in font, bool(flags & 2) or "italic" in font or "oblique" in font


def styled_span_text(span: dict[str, Any], *, inline_code: bool = False) -> str:
    text = clean_span_text(span.get("text"))
    if not text:
        return ""
    if inline_code and span_is_monospace(span):
        stripped = text.strip()
        return f"`{stripped}`" if stripped else ""
    is_bold, is_italic = span_style(span)
    if is_bold and is_italic:
        return f"***{text}***"
    if is_bold:
        return f"**{text}**"
    if is_italic:
        return f"*{text}*"
    return text


def join_line_spans(
    spans: list[dict[str, Any]],
    *,
    inline_code: bool = False,
    inline_markers: list[dict[str, Any]] | None = None,
) -> tuple[str, str, float, float]:
    formatted: list[str] = []
    raw_parts: list[str] = []
    previous_end: float | None = None
    previous_raw = ""
    first_x = 0.0
    last_x = 0.0
    markers = sorted(inline_markers or [], key=lambda item: (float(item.get("x0", 0.0)), int(item.get("xref", 0))))
    marker_index = 0

    def append_marker(marker: dict[str, Any]) -> None:
        """Keep a small image inside the prose line instead of making a block."""
        if formatted and not str(formatted[-1]).endswith((" ", "\t")):
            formatted.append(" ")
        formatted.append(str(marker["inline_markdown"]))
        formatted.append(" ")
        if raw_parts and not str(raw_parts[-1]).endswith((" ", "\t")):
            raw_parts.append(" ")
        raw_parts.append(" ")

    for index, span in enumerate(spans):
        raw = clean_span_text(span.get("text"))
        if not raw:
            continue
        bbox = span.get("bbox") or (0, 0, 0, 0)
        x0, x1 = float(bbox[0]), float(bbox[2])
        while marker_index < len(markers) and float(markers[marker_index].get("x0", 0.0)) <= x0:
            append_marker(markers[marker_index])
            marker_index += 1
            previous_end = float(markers[marker_index - 1].get("x1", x0))
            previous_raw = " "
            last_x = previous_end
        if index == 0 or not formatted:
            first_x = x0
        needs_space = False
        if formatted and previous_end is not None and previous_raw and raw:
            gap = x0 - previous_end
            if not previous_raw[-1].isspace() and not raw[0].isspace():
                # InDesign often drops a text-space between differently styled
                # spans. Reinsert it only when the PDF geometry shows a gap.
                needs_space = gap > max(0.65, float(span.get("size") or 10.0) * 0.045)
        if needs_space:
            formatted.append(" ")
            raw_parts.append(" ")
        formatted.append(styled_span_text(span, inline_code=inline_code))
        raw_parts.append(raw)
        previous_end = x1
        previous_raw = raw
        last_x = x1
    while marker_index < len(markers):
        append_marker(markers[marker_index])
        marker_index += 1
        last_x = float(markers[marker_index - 1].get("x1", last_x))
    formatted_text = "".join(formatted)
    if markers:
        # PDF text spans often retain a trailing space on one side of an
        # inline icon and a leading space on the other.  Collapse only the
        # whitespace on a line that contains an icon; ordinary prose keeps
        # its existing extraction result.
        formatted_text = re.sub(r"[ \t]{2,}", " ", formatted_text)
    return formatted_text, "".join(raw_parts), first_x, last_x


def merge_inline_image_fragments(
    entries: list[dict[str, Any]],
    inline_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join prose fragments split by an inline PDF image.

    PDF text extraction commonly returns the words on either side of a small
    inline UI icon as separate text blocks.  The icon is not necessarily
    inside either block's bounding box, so ``extract_page_blocks`` cannot
    safely insert it while processing an individual block.  This pass joins
    only same-baseline, ordinary prose fragments when the image geometry
    proves that the icon occupies their horizontal gap.
    """

    def images_between(first: dict[str, Any], second: dict[str, Any]) -> list[dict[str, Any]]:
        first_y0 = float(first.get("y0", 0.0))
        first_y1 = float(first.get("y1", 0.0))
        second_y0 = float(second.get("y0", 0.0))
        second_y1 = float(second.get("y1", 0.0))
        if (
            abs(first_y0 - second_y0) > 1.0
            or abs(first_y1 - second_y1) > 1.0
        ):
            return []
        first_x1 = float(first.get("x1", 0.0))
        second_x0 = float(second.get("x0", 0.0))
        gap = second_x0 - first_x1
        line_height = max(first_y1 - first_y0, second_y1 - second_y0, 1.0)
        if gap < -0.75 or gap > max(16.0, line_height * 2.0):
            return []
        matches: list[dict[str, Any]] = []
        for image in inline_images:
            image_y0 = float(image.get("inline_line_y0", image.get("y0", 0.0)))
            image_y1 = float(image.get("inline_line_y1", image.get("y1", 0.0)))
            image_x0 = float(image.get("x0", 0.0))
            image_x1 = float(image.get("x1", 0.0))
            if (
                abs(image_y0 - first_y0) <= 1.0
                and abs(image_y1 - first_y1) <= 1.0
                and image_x1 > image_x0
                and image_x0 <= second_x0 + 0.75
                and image_x1 >= first_x1 - 0.75
            ):
                matches.append(image)
        return sorted(matches, key=lambda item: (float(item.get("x0", 0.0)), int(item.get("xref", 0))))

    def can_merge(first: dict[str, Any], second: dict[str, Any]) -> bool:
        if any(
            first.get(key) or second.get(key)
            for key in (
                "is_code",
                "code_candidate",
                "has_bullet_prefix",
                "is_bullet_only",
                "heading_level",
                "is_running_header",
                "is_chapter_title",
            )
        ):
            return False
        return bool(images_between(first, second))

    merged: list[dict[str, Any]] = []
    index = 0
    while index < len(entries):
        current = dict(entries[index])
        while index + 1 < len(entries) and can_merge(current, entries[index + 1]):
            following = entries[index + 1]
            gap_images = images_between(current, following)
            formatted_parts = [str(current.get("text", "")).rstrip()]
            raw_parts = [str(current.get("raw", current.get("raw_text", ""))).rstrip()]
            plain_parts = [str(current.get("plain", "")).rstrip()]
            spans = list(current.get("spans", []) or [])
            for image in gap_images:
                marker = str(image.get("inline_markdown") or "").strip()
                if marker:
                    formatted_parts.extend([" ", marker, " "])
                spans.extend(list(image.get("spans", []) or []))
            formatted_parts.append(str(following.get("text", "")).lstrip())
            raw_parts.append(str(following.get("raw", following.get("raw_text", ""))).lstrip())
            plain_parts.append(str(following.get("plain", "")).lstrip())
            current["text"] = "".join(formatted_parts)
            current["raw"] = " ".join(part for part in raw_parts if part)
            current["raw_text"] = " ".join(
                part for part in (
                    str(current.get("raw_text", "")).rstrip(),
                    str(following.get("raw_text", following.get("raw", ""))).lstrip(),
                )
                if part
            )
            current["plain"] = normalise_heading_text(" ".join(part for part in plain_parts if part))
            current["x0"] = min(float(current.get("x0", 0.0)), float(following.get("x0", 0.0)))
            current["x1"] = max(float(current.get("x1", 0.0)), float(following.get("x1", 0.0)))
            current["y0"] = min(float(current.get("y0", 0.0)), float(following.get("y0", 0.0)))
            current["y1"] = max(float(current.get("y1", 0.0)), float(following.get("y1", 0.0)))
            current["y"] = min(float(current.get("y", current["y0"])), float(following.get("y", current["y0"])))
            current["index"] = min(int(current.get("index", 0)), int(following.get("index", 0)))
            current["spans"] = spans
            for key in ("is_code", "is_inline_code", "code_candidate", "is_bullet_only", "has_bullet_prefix"):
                current[key] = False
            current["heading_level"] = None
            index += 1
        merged.append(current)
        index += 1
    return merged


def merge_inline_pdf_text_blocks(
    blocks: list[dict[str, Any]],
    inline_images: list[dict[str, Any]],
) -> None:
    """Merge PDF text lines separated by a classified inline image.

    A PDF producer may store the text before and after an icon in different
    text blocks.  Merging only the final Markdown entries is too late for a
    block that also contains the following wrapped line.  This pass therefore
    joins the source line records first, while retaining their original spans
    and coordinates for the normal renderer.
    """
    if not inline_images:
        return

    records: list[dict[str, Any]] = []
    block_line_counts: dict[int, int] = {}
    for block_index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("type", 0) != 0:
            continue
        source_lines = block.get("lines", []) or []
        text_lines = 0
        for line_index, line in enumerate(source_lines):
            if not isinstance(line, dict):
                continue
            bbox = line.get("bbox") or (0, 0, 0, 0)
            x0, y0, x1, y1 = (float(value) for value in bbox[:4])
            text = "".join(
                clean_span_text(span.get("text"))
                for span in line.get("spans", []) or []
                if isinstance(span, dict)
            )
            if not text.strip() or x1 <= x0 or y1 <= y0:
                continue
            text_lines += 1
            records.append({
                "block_index": block_index,
                "line_index": line_index,
                "line": line,
                "x0": x0,
                "y0": y0,
                "x1": x1,
                "y1": y1,
                "spans": list(line.get("spans", []) or []),
            })
        if text_lines:
            block_line_counts[block_index] = text_lines

    active = list(records)
    removed_line_ids: set[int] = set()
    synthetic_by_block: dict[int, list[dict[str, Any]]] = {}

    def same_baseline(first: dict[str, Any], second: dict[str, Any]) -> bool:
        return (
            abs(float(first["y0"]) - float(second["y0"])) <= 1.0
            and abs(float(first["y1"]) - float(second["y1"])) <= 1.0
        )

    def image_between(
        image: dict[str, Any],
        first: dict[str, Any],
        second: dict[str, Any],
    ) -> bool:
        if not same_baseline(first, second):
            return False
        first_x1 = float(first["x1"])
        second_x0 = float(second["x0"])
        gap = second_x0 - first_x1
        line_height = max(float(first["y1"]) - float(first["y0"]), 1.0)
        if gap < -0.75 or gap > max(16.0, line_height * 2.0):
            return False
        image_x0 = float(image.get("x0", 0.0))
        image_x1 = float(image.get("x1", 0.0))
        return (
            image_x1 > image_x0
            and image_x0 <= second_x0 + 0.75
            and image_x1 >= first_x1 - 0.75
        )

    for image in sorted(
        inline_images,
        key=lambda item: (float(item.get("y0", 0.0)), float(item.get("x0", 0.0))),
    ):
        candidates = sorted(
            active,
            key=lambda item: (float(item["y0"]), float(item["x0"]), int(item["block_index"])),
        )
        pair: tuple[dict[str, Any], dict[str, Any]] | None = None
        for first, second in zip(candidates, candidates[1:]):
            if image_between(image, first, second):
                pair = (first, second)
                break
        if pair is None:
            continue

        first, second = pair
        owner_candidates = (first["block_index"], second["block_index"])
        owner = max(
            owner_candidates,
            key=lambda index: (block_line_counts.get(index, 0), -index),
        )
        synthetic_line = {
            "bbox": (
                min(float(first["x0"]), float(second["x0"])),
                min(float(first["y0"]), float(second["y0"])),
                max(float(first["x1"]), float(second["x1"])),
                max(float(first["y1"]), float(second["y1"])),
            ),
            "spans": [*first["spans"], *second["spans"]],
        }
        synthetic_record = {
            "block_index": owner,
            "line_index": min(int(first["line_index"]), int(second["line_index"])),
            "line": synthetic_line,
            "x0": synthetic_line["bbox"][0],
            "y0": synthetic_line["bbox"][1],
            "x1": synthetic_line["bbox"][2],
            "y1": synthetic_line["bbox"][3],
            "spans": synthetic_line["spans"],
        }
        removed_line_ids.update({id(first["line"]), id(second["line"])})
        active.remove(first)
        active.remove(second)
        active.append(synthetic_record)
        synthetic_by_block.setdefault(owner, []).append(synthetic_line)

    if not removed_line_ids:
        return
    for block_index, block in enumerate(blocks):
        if not isinstance(block, dict) or "lines" not in block:
            continue
        remaining = [
            line for line in block.get("lines", []) or []
            if id(line) not in removed_line_ids
        ]
        remaining.extend(synthetic_by_block.get(block_index, []))
        remaining.sort(
            key=lambda line: (
                float((line.get("bbox") or (0, 0, 0, 0))[1]),
                float((line.get("bbox") or (0, 0, 0, 0))[0]),
            )
        )
        block["lines"] = remaining


def normalise_heading_lookup(value: str) -> str:
    value = normalise_heading_text(re.sub(r"[*_`]", "", value))
    return re.sub(r"[\s.]+$", "", value).casefold()


def toc_heading_index(document: Any) -> dict[int, dict[str, int]]:
    index: dict[int, dict[str, int]] = {}
    try:
        toc = document.get_toc(simple=True)
    except Exception:
        toc = []
    for row in toc or []:
        if len(row) < 3:
            continue
        level = int(row[0])
        if level > 3:
            continue
        page = int(row[2])
        title = normalise_heading_text(row[1])
        if title:
            index.setdefault(page, {})[normalise_heading_lookup(title)] = level
    return index


def toc_heading_titles(document: Any) -> set[str]:
    titles: set[str] = set()
    try:
        toc = document.get_toc(simple=True)
    except Exception:
        toc = []
    for row in toc or []:
        if len(row) >= 2 and int(row[0]) <= 3:
            title = normalise_heading_text(row[1])
            if title:
                titles.add(normalise_heading_lookup(title))
    return titles


def is_list_marker(text: str) -> bool:
    return bool(re.match(rf"^\s*(?:[-*+]\s+|[{re.escape(BULLET_CHARS)}](?:\s|\t|$))", text))


def infer_code_language(text: str, config: dict[str, Any]) -> str:
    language_config = (config.get("code_blocks") or {}).get("languages") or {}
    lower = text.lower()
    if any(token in text for token in ("#include", "UCLASS", "UPROPERTY", "UFUNCTION", "std::", "::", "public:", "private:", "protected:")):
        return str(language_config.get("cpp") or "cpp")
    if re.search(r"(?:^|\n)\s*(?:PS>|\.\\|\$\s|sudo\s|npm\s|cmake\s|git\s)", text, re.IGNORECASE):
        return str(language_config.get("shell") or "bash")
    if re.search(r"^\s*\[[^\]]+\]\s*$|^\s*[A-Za-z_][\w.-]*\s*=", text, re.MULTILINE):
        return str(language_config.get("ini") or "ini")
    if "command" in lower or "console" in lower:
        return str(language_config.get("shell") or "bash")
    return str(language_config.get("default") or "text")


def extract_page_blocks(
    page: Any,
    chapter_title: str = "",
    *,
    heading_levels: dict[str, int] | None = None,
    code_enabled: bool = False,
    inline_code_enabled: bool = True,
    code_min_lines: int = 2,
    code_min_chars: int = 60,
    known_heading_titles: set[str] | None = None,
    skip_regions: list[tuple[float, float]] | None = None,
    inline_images: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    blocks = page.get_text("dict", sort=True).get("blocks", [])
    entries: list[dict[str, Any]] = []
    skip_regions = skip_regions or []
    merge_inline_pdf_text_blocks(blocks, inline_images or [])
    for block_index, block in enumerate(blocks):
        lines = block.get("lines", []) if isinstance(block, dict) else []
        if not lines:
            continue
        bbox = block.get("bbox") or (0, 0, 0, 0)
        block_y0, block_y1 = float(bbox[1]), float(bbox[3])
        if any(block_y0 < region_y1 and block_y1 > region_y0 for region_y0, region_y1 in skip_regions):
            continue
        line_entries: list[dict[str, Any]] = []
        for line in lines:
            spans = line.get("spans", [])
            line_bbox = line.get("bbox") or (0, 0, 0, 0)
            line_y0, line_y1 = float(line_bbox[1]), float(line_bbox[3])
            markers = []
            for image in inline_images or []:
                if abs(float(image.get("inline_line_y0", -10000.0)) - line_y0) > 1.0:
                    continue
                if abs(float(image.get("inline_line_y1", -10000.0)) - line_y1) > 1.0:
                    continue
                image_x0 = float(image.get("x0", 0.0))
                image_x1 = float(image.get("x1", 0.0))
                horizontal_overlap = min(image_x1, float(line_bbox[2])) - max(image_x0, float(line_bbox[0]))
                if horizontal_overlap > max(0.75, (image_x1 - image_x0) * 0.05):
                    markers.append(image)
            formatted, raw, x0, x1 = join_line_spans(
                spans,
                inline_code=code_enabled,
                inline_markers=markers,
            )
            if not formatted.strip():
                continue
            line_entries.append({
                "text": formatted,
                "raw": raw,
                "x0": x0,
                "x1": x1,
                "y0": float((line.get("bbox") or (0, 0, 0, 0))[1]),
                "y1": float((line.get("bbox") or (0, 0, 0, 0))[3]),
                "spans": spans,
            })
        if not line_entries:
            continue
        groups: list[list[dict[str, Any]]] = []
        current_group: list[dict[str, Any]] = []
        for item in line_entries:
            if is_list_marker(item["raw"]) and current_group:
                groups.append(current_group)
                current_group = []
            current_group.append(item)
        if current_group:
            groups.append(current_group)
        for group in groups:
            raw_text = "\n".join(item["raw"] for item in group)
            plain_text = normalise_heading_text(" ".join(item["raw"] for item in group))
            mono_chars = sum(len(clean_span_text(span.get("text"))) for item in group for span in item["spans"] if span_is_monospace(span))
            all_chars = sum(len(clean_span_text(span.get("text"))) for item in group for span in item["spans"])
            code_candidate = code_enabled and all_chars > 0 and mono_chars / all_chars >= 0.72 and not any(is_list_marker(item["raw"]) for item in group)
            is_code = code_candidate and (len(group) >= max(1, code_min_lines) or all_chars >= max(1, code_min_chars))
            is_inline_code = bool(code_candidate and not is_code and inline_code_enabled)
            has_bullet_prefix = any(is_list_marker(item["raw"]) for item in group)
            is_bullet_only = bool(raw_text.strip()) and all(token in BULLET_CHARS or token.isspace() for token in raw_text.strip())
            if has_bullet_prefix:
                for item in group:
                    item["text"] = re.sub(rf"^\s*(?:[-*+]\s+|[{re.escape(BULLET_CHARS)}](?:\s|\t)*)", "", item["text"])
                    item["raw"] = re.sub(rf"^\s*(?:[-*+]\s+|[{re.escape(BULLET_CHARS)}](?:\s|\t)*)", "", item["raw"])
            if is_code:
                block_text = "\n".join(item["raw"].replace("\u202f", " ") for item in group)
            elif is_inline_code:
                inline_text = raw_text.strip().replace("`", "\\`")
                block_text = f"`{inline_text}`"
            elif has_bullet_prefix:
                block_text = " ".join(item["text"].strip() for item in group)
            else:
                has_inline_marker = any(
                    marker.get("inline_markdown") and marker["inline_markdown"] in item["text"]
                    for item in group
                    for marker in (inline_images or [])
                )
                if has_inline_marker:
                    # Wrapped lines around a UI icon may carry whitespace at
                    # both the end of the previous line and the start of the
                    # next one. Strip only this icon-containing paragraph's
                    # line boundaries so the rendered sentence has stable
                    # spacing without changing unrelated PDF text.
                    block_text = " ".join(item["text"].strip() for item in group)
                else:
                    pieces: list[str] = []
                    for item_index, item in enumerate(group):
                        if item_index:
                            previous_raw = group[item_index - 1]["raw"]
                            pieces.append("" if previous_raw.endswith("\u00ad") else " ")
                        pieces.append(item["text"])
                    block_text = "".join(pieces)
            plain_line = normalise_heading_lookup(plain_text)
            heading_level = (heading_levels or {}).get(plain_line)
            sizes = [float(span.get("size") or 0.0) for item in group for span in item["spans"] if span.get("size")]
            max_size = max(sizes, default=0.0)
            if heading_level is None and not is_code and not has_bullet_prefix and len(plain_text) <= 140 and max_size >= 12.0:
                if not re.search(r"[.!?,;:]$", plain_text):
                    heading_level = 2 if max_size < 17.0 else 3
            first_y = float((lines[0].get("bbox") or (0, 0, 0, 0))[1])
            if group:
                first_y = float(group[0]["y0"])
            entries.append({
                "y": first_y,
                "x": float(group[0]["x0"]),
                "x0": float(group[0]["x0"]),
                "x1": float(group[-1]["x1"]),
                "y0": first_y,
                "y1": float(group[-1]["y1"]),
                "index": block_index,
                "text": block_text,
                "plain": plain_text,
                "raw_text": raw_text,
                "is_code": is_code,
                "is_inline_code": is_inline_code,
                "code_candidate": code_candidate,
                "code_language": infer_code_language(block_text, {}) if is_code else "",
                "is_bullet_only": is_bullet_only,
                "has_bullet_prefix": has_bullet_prefix,
                "heading_level": heading_level,
            })
    entries.sort(key=lambda item: (item["y"], item["x"], item["index"]))
    known_heading_titles = set(known_heading_titles or set())
    if chapter_title:
        known_heading_titles.add(normalise_heading_lookup(chapter_title))
    for entry in entries:
        plain = normalise_heading_text(str(entry["plain"]))
        running_match = re.match(r"^(?P<title>.+?)\s+(?P<number>(?:[0-9]+|[ivxlcdm]+))$", plain, re.IGNORECASE)
        if float(entry["y"]) < 60.0 and running_match:
            if normalise_heading_lookup(running_match.group("title")) in known_heading_titles:
                entry["is_running_header"] = True
    if code_enabled:
        merged_entries: list[dict[str, Any]] = []
        for entry in entries:
            if merged_entries:
                previous = merged_entries[-1]
                close_enough = (
                    previous.get("code_candidate")
                    and entry.get("code_candidate")
                    and float(entry["y"]) - float(previous["y1"]) <= 24.0
                    and abs(float(entry["x"]) - float(previous["x"])) <= 36.0
                )
                if close_enough:
                    previous["raw_text"] = f'{previous["raw_text"]}\n{entry["raw_text"]}'
                    previous["text"] = previous["raw_text"].replace("\u202f", " ")
                    previous["plain"] = normalise_heading_text(previous["raw_text"].replace("\n", " "))
                    previous["y1"] = entry["y1"]
                    previous["is_code"] = (
                        len(previous["raw_text"].splitlines()) >= max(1, code_min_lines)
                        or len(previous["raw_text"]) >= max(1, code_min_chars)
                    )
                    previous["is_inline_code"] = bool(not previous["is_code"] and inline_code_enabled)
                    if previous["is_inline_code"]:
                        inline_text = previous["raw_text"].replace("`", "\\`").replace("\n", " ").strip()
                        previous["text"] = f"`{inline_text}`"
                    continue
            merged_entries.append(entry)
        entries = merged_entries
    entries = merge_inline_image_fragments(entries, inline_images or [])
    if chapter_title:
        target_title = normalise_heading_lookup(chapter_title)
        for start_index, candidate in enumerate(entries[:6]):
            if not candidate.get("heading_level") or candidate.get("is_code"):
                continue
            combined: list[dict[str, Any]] = []
            for end_index in range(start_index, min(len(entries), start_index + 5)):
                item = entries[end_index]
                if not item.get("heading_level") or item.get("is_code"):
                    break
                if combined and float(item["y"]) - float(combined[-1]["y1"]) > 110.0:
                    break
                combined.append(item)
                candidate_text = normalise_heading_lookup(" ".join(str(item["plain"]) for item in combined))
                variants = {
                    candidate_text,
                    re.sub(r"^(?:chapter\s+[0-9ivxlcdm]+\s*[:.\-–—]?|[0-9]+)\s*", "", candidate_text, flags=re.IGNORECASE),
                }
                if target_title in variants:
                    for matched in combined:
                        matched["is_chapter_title"] = True
                    break
            if any(item.get("is_chapter_title") for item in entries):
                break
    return entries


def page_markdown_from_spans(
    page: Any,
    chapter_title: str = "",
    *,
    heading_levels: dict[str, int] | None = None,
    config: dict[str, Any] | None = None,
    skip_regions: list[tuple[float, float]] | None = None,
) -> str:
    """Extract a page while restoring conservative Markdown structure."""
    config = config or {}
    blocks = extract_page_blocks(
        page,
        chapter_title,
        heading_levels=heading_levels,
        code_enabled=bool((config.get("code_blocks") or {}).get("enabled", False)),
        inline_code_enabled=bool((config.get("code_blocks") or {}).get("inline", True)),
        code_min_lines=int((config.get("code_blocks") or {}).get("min_lines", 2)),
        code_min_chars=int((config.get("code_blocks") or {}).get("min_chars", 60)),
        skip_regions=skip_regions,
    )
    rendered: list[str] = []
    page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
    bullet_ys = [float(entry["y"]) for entry in blocks if entry["is_bullet_only"]]
    for entry in blocks:
        if entry["is_bullet_only"]:
            continue
        if entry.get("is_running_header"):
            continue
        if entry.get("is_chapter_title"):
            continue
        plain_line = str(entry["plain"]).strip()
        near_page_edge = page_height and (entry["y"] <= page_height * 0.2 or entry["y"] >= page_height * 0.8)
        if is_pdf_page_number(plain_line) and near_page_edge:
            continue
        if chapter_title and plain_line.lower().startswith("chapter ") and chapter_title.lower() in plain_line.lower() and not entry["is_code"]:
            continue
        line_text = str(entry["text"])
        if entry["heading_level"] and not entry["is_code"]:
            line_text = f"{'#' * int(entry['heading_level'])} {re.sub(r'[*_`]', '', line_text).strip()}"
        elif entry["is_code"]:
            language = infer_code_language(line_text, config)
            line_text = f"```{language}\n{line_text.rstrip()}\n```"
        elif entry["has_bullet_prefix"] or any(abs(float(entry["y"]) - bullet_y) <= 3.0 for bullet_y in bullet_ys):
            line_text, _ = repair_broken_emphasis("- " + line_text.lstrip())
        else:
            line_text, _ = repair_broken_emphasis(line_text)
        rendered.append(line_text)
    joined = "\n\n".join(rendered)
    joined_lines = compact_unordered_list_spacing(joined.splitlines(keepends=True))
    page_text = merge_split_plain_urls(
        merge_split_inline_code_urls(normalise_text("".join(joined_lines)))
    )
    try:
        selected_callout_style = resolve_callout_style(config)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
    page_text, _, _ = convert_callouts_text(page_text, style=selected_callout_style)
    page_text = merge_split_inline_code_urls(page_text)
    page_text = merge_split_plain_urls(page_text)
    return page_text


def escape_table_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\r", " ").replace("\n", "<br>").strip()


def visual_table_specs(config: dict[str, Any]) -> list[dict[str, Any]]:
    settings = config.get("visual_tables") or {}
    if not bool(settings.get("enabled", False)):
        return []
    regions = settings.get("regions") or []
    return [item for item in regions if isinstance(item, dict)]


def _drawn_grid_segments(page: Any) -> tuple[list[tuple[float, float, float]], list[tuple[float, float, float]]]:
    """Return horizontal and vertical line segments from the PDF drawing layer."""
    horizontal: list[tuple[float, float, float]] = []
    vertical: list[tuple[float, float, float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return horizontal, vertical
    for drawing in drawings:
        for item in drawing.get("items", []) if isinstance(drawing, dict) else []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            first = point_xy(item[1])
            second = point_xy(item[2])
            if first is None or second is None:
                continue
            x1, y1 = first
            x2, y2 = second
            if abs(y1 - y2) <= 1.0 and abs(x2 - x1) >= 30.0:
                horizontal.append((min(x1, x2), max(x1, x2), (y1 + y2) / 2.0))
            elif abs(x1 - x2) <= 1.0 and abs(y2 - y1) >= 12.0:
                vertical.append((x1, min(y1, y2), max(y1, y2)))
    return horizontal, vertical


def _horizontal_grid_boundaries(
    page: Any,
    horizontal: list[tuple[float, float, float]],
) -> list[dict[str, float]]:
    """Cluster long horizontal lines and ignore the repeated running rule."""
    if not horizontal:
        return []
    page_width = float(getattr(page.rect, "width", 0.0) or 0.0)
    by_y: dict[float, list[tuple[float, float]]] = {}
    for y in cluster_positions((item[2] for item in horizontal), 1.5):
        segments = [
            (x0, x1)
            for x0, x1, segment_y in horizontal
            if abs(segment_y - y) <= 1.5
        ]
        if segments:
            by_y[y] = segments
    result: list[dict[str, float]] = []
    for y, segments in sorted(by_y.items()):
        # The page header rule is a long line but is not a table boundary.
        if y <= 60.0:
            continue
        x0 = min(segment[0] for segment in segments)
        x1 = max(segment[1] for segment in segments)
        if x1 - x0 < max(160.0, page_width * 0.45):
            continue
        result.append({"y": y, "x0": x0, "x1": x1})
    return result


def _grid_span_matches(first: dict[str, float], second: dict[str, float]) -> bool:
    overlap = min(first["x1"], second["x1"]) - max(first["x0"], second["x0"])
    width = min(first["x1"] - first["x0"], second["x1"] - second["x0"])
    return (
        abs(first["x0"] - second["x0"]) <= 12.0
        and abs(first["x1"] - second["x1"]) <= 12.0
        and overlap >= max(120.0, width * 0.82)
    )


def _grid_runs(
    boundaries: list[dict[str, float]],
    vertical: list[tuple[float, float, float]] | None = None,
) -> list[list[dict[str, float]]]:
    """Group boundaries that describe one table rather than unrelated lines."""
    runs: list[list[dict[str, float]]] = []
    current: list[dict[str, float]] = []
    for boundary in boundaries:
        if not current:
            current = [boundary]
            continue
        previous = current[-1]
        gap = boundary["y"] - previous["y"]
        has_vertical_bridge = any(
            segment_y0 <= previous["y"] + 3.0
            and segment_y1 >= boundary["y"] - 3.0
            and min(previous["x1"], boundary["x1"]) - max(previous["x0"], boundary["x0"]) >= 120.0
            for _, segment_y0, segment_y1 in vertical or []
        )
        continues_grid = gap <= 35.0 or has_vertical_bridge
        if gap <= 90.0 and continues_grid and _grid_span_matches(previous, boundary):
            current.append(boundary)
        else:
            if len(current) >= 3:
                runs.append(current)
            current = [boundary]
    if len(current) >= 3:
        runs.append(current)
    return runs


def _grid_columns(
    vertical: list[tuple[float, float, float]],
    run: list[dict[str, float]],
) -> list[float]:
    y0 = run[0]["y"]
    y1 = run[-1]["y"]
    span = y1 - y0
    candidates = [
        (x, segment_y1 - segment_y0)
        for x, segment_y0, segment_y1 in vertical
        if segment_y1 - segment_y0 >= 8.0
        and segment_y1 >= y0 - 3.0
        and segment_y0 <= y1 + 3.0
        and run[0]["x0"] - 6.0 <= x <= run[0]["x1"] + 6.0
    ]
    positions = cluster_positions((x for x, _ in candidates), 3.0)
    stable: list[float] = []
    for position in positions:
        matching = [length for candidate, length in candidates if abs(candidate - position) <= 3.0]
        required_repeats = 1 if any(length >= span * 0.55 for length in matching) else 2
        repeats = len(matching)
        if repeats >= required_repeats:
            stable.append(position)
    return stable


def _grid_text_rows(
    page: Any,
    run: list[dict[str, float]],
    columns: list[float],
) -> tuple[list[dict[str, Any]], int, int]:
    """Place PDF text lines into detected grid cells."""
    rows: list[dict[str, Any]] = []
    text_lines = 0
    monospace_chars = 0
    all_chars = 0
    boundaries = [item["y"] for item in run]
    x0 = run[0]["x0"] - 2.0
    x1 = run[0]["x1"] + 2.0
    y0 = boundaries[0] - 2.0
    y1 = boundaries[-1] + 2.0
    cells_by_row: list[list[list[str]]] = [
        [[] for _ in range(len(columns) - 1)]
        for _ in range(len(boundaries) - 1)
    ]
    for block in page.get_text("dict", sort=True).get("blocks", []):
        for line in block.get("lines", []) if isinstance(block, dict) else []:
            bbox = line.get("bbox") or (0, 0, 0, 0)
            line_x0, line_y0, line_x1, line_y1 = (float(value) for value in bbox[:4])
            center_y = (line_y0 + line_y1) / 2.0
            if line_x1 < x0 or line_x0 > x1 or center_y < y0 or center_y > y1:
                continue
            text = line_cell_text(line)
            if not text:
                continue
            row_index = next(
                (
                    index
                    for index in range(len(boundaries) - 1)
                    if boundaries[index] - 1.5 <= center_y < boundaries[index + 1] + 1.5
                ),
                None,
            )
            column_index = next(
                (
                    index
                    for index in range(len(columns) - 1)
                    if columns[index] - 1.5 <= line_x0 < columns[index + 1] + 1.5
                ),
                None,
            )
            if row_index is None or column_index is None:
                continue
            cells_by_row[row_index][column_index].append(text)
            text_lines += 1
            for span in line.get("spans", []) or []:
                span_text = clean_span_text(span.get("text"))
                all_chars += len(span_text)
                if span_is_monospace(span):
                    monospace_chars += len(span_text)
    for row_index, cells in enumerate(cells_by_row):
        values = [" ".join(cell).strip() for cell in cells]
        if any(values):
            rows.append({"anchor": boundaries[row_index], "cells": values})
    return rows, monospace_chars, all_chars


def _grid_overlaps_image(page: Any, region: tuple[float, float]) -> bool:
    """Reject text-only table reconstruction when cells contain images."""
    y0, y1 = region
    try:
        images = page.get_images(full=True)
    except Exception:
        return False
    for image in images:
        try:
            xref = int(image[0])
            rects = page.get_image_rects(xref)
        except Exception:
            continue
        for rect in rects:
            if float(rect.y0) < y1 and float(rect.y1) > y0:
                return True
    return False


def discover_visual_tables(
    document: Any,
    config: dict[str, Any],
    occupied_regions: dict[int, list[tuple[float, float]]] | None = None,
) -> list[dict[str, Any]]:
    """Find high-confidence drawn tables without book-specific page entries.

    This detector deliberately rejects one-column boxes, code-like regions,
    missing headers, and sparse grids.  Rejected candidates are returned in
    the audit list so an Agent can inspect them instead of silently losing
    the structure.
    """
    settings = config.get("visual_tables") or {}
    if not bool(settings.get("enabled", False)) or resolve_visual_table_discovery(config) == "off":
        return []
    min_rows = max(1, int(settings.get("min_rows", 2)))
    occupied_regions = occupied_regions or {}
    candidates: list[dict[str, Any]] = []
    for page_number in range(1, int(document.page_count) + 1):
        page = document[page_number - 1]
        horizontal, vertical = _drawn_grid_segments(page)
        boundaries = _horizontal_grid_boundaries(page, horizontal)
        for run_index, run in enumerate(_grid_runs(boundaries, vertical), start=1):
            region = (run[0]["y"] - 2.0, run[-1]["y"] + 2.0)
            if any(
                region[0] < existing[1] and region[1] > existing[0]
                for existing in occupied_regions.get(page_number, [])
            ):
                continue
            columns = _grid_columns(vertical, run)
            base = {
                "id": f"auto-visual-table-p{page_number:04d}-{run_index}",
                "start_page": page_number,
                "end_page": page_number,
                "headers": [],
                "rows": [],
                "page_regions": {page_number: region},
                "y": region[0],
                "detection": "geometry-auto",
                "columns": columns,
            }
            if _grid_overlaps_image(page, region):
                candidates.append({
                    **base,
                    "status": "skipped",
                    "reason": "image-overlap-ambiguous-table-cells",
                })
                continue
            if len(columns) < 3:
                candidates.append({**base, "status": "skipped", "reason": "only-one-column-box-or-unstable-column-lines"})
                continue
            rows, monospace_chars, all_chars = _grid_text_rows(page, run, columns)
            base["rows"] = [row["cells"] for row in rows]
            if len(rows) < min_rows + 1:
                candidates.append({**base, "status": "skipped", "reason": "missing-header-or-minimum-data-rows"})
                continue
            headers = rows[0]["cells"]
            base["headers"] = headers
            if len(headers) != len(columns) - 1 or sum(bool(cell) for cell in headers) < len(headers):
                candidates.append({**base, "status": "skipped", "reason": "missing-explicit-header-or-stable-columns"})
                continue
            if all_chars and monospace_chars / all_chars >= 0.60:
                candidates.append({**base, "status": "skipped", "reason": "code-like-text-region"})
                continue
            data_rows = [row["cells"] for row in rows[1:]]
            if any(len(row) != len(headers) or not any(cell for cell in row) for row in data_rows):
                candidates.append({**base, "status": "skipped", "reason": "unstable-column-count-or-empty-data-row"})
                continue
            lines = [
                "| " + " | ".join(escape_table_cell(header) for header in headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
            ]
            lines.extend(
                "| " + " | ".join(escape_table_cell(cell) for cell in row) + " |"
                for row in data_rows
            )
            candidates.append({
                **base,
                "status": "converted",
                "headers": headers,
                "rows": data_rows,
                "markdown": "\n".join(lines),
                "confidence": "high",
                "reason": "closed-grid-with-explicit-header-and-stable-cell-text",
            })
    return merge_discovered_visual_tables(candidates)


def merge_discovered_visual_tables(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent auto-detected pages that repeat the same table header."""
    merged: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda item: (int(item["start_page"]), float(item.get("y", 0.0)))):
        if (
            candidate.get("status") == "converted"
            and merged
            and merged[-1].get("status") == "converted"
            and int(merged[-1]["end_page"]) + 1 == int(candidate["start_page"])
            and [normalise_heading_lookup(str(cell)) for cell in merged[-1].get("headers", [])]
            == [normalise_heading_lookup(str(cell)) for cell in candidate.get("headers", [])]
            and len(merged[-1].get("columns", [])) == len(candidate.get("columns", []))
            and all(
                abs(float(left) - float(right)) <= 12.0
                for left, right in zip(merged[-1].get("columns", []), candidate.get("columns", []))
            )
        ):
            merged[-1]["end_page"] = candidate["end_page"]
            merged[-1]["rows"].extend(candidate.get("rows", []))
            merged[-1]["page_regions"].update(candidate.get("page_regions", {}))
            merged[-1]["markdown"] = "\n".join(
                [
                    "| " + " | ".join(escape_table_cell(header) for header in merged[-1]["headers"]) + " |",
                    "| " + " | ".join("---" for _ in merged[-1]["headers"]) + " |",
                    *(
                        "| " + " | ".join(escape_table_cell(cell) for cell in row) + " |"
                        for row in merged[-1]["rows"]
                    ),
                ]
            )
            continue
        merged.append(candidate)
    return merged


def line_cell_text(line: dict[str, Any]) -> str:
    _, raw, _, _ = join_line_spans(line.get("spans", []))
    return normalise_text(raw).replace("\n", " ").strip()


def point_xy(point: Any) -> tuple[float, float] | None:
    """Return coordinates from PyMuPDF Point-like values."""
    if hasattr(point, "x") and hasattr(point, "y"):
        return float(point.x), float(point.y)
    try:
        return float(point[0]), float(point[1])
    except (IndexError, TypeError, ValueError):
        return None


def cluster_positions(values: Iterable[float], tolerance: float = 1.5) -> list[float]:
    clusters: list[list[float]] = []
    for value in sorted(float(item) for item in values):
        if clusters and value - clusters[-1][-1] <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])
    return [sum(cluster) / len(cluster) for cluster in clusters]


def visual_table_grid(
    page: Any,
    spec: dict[str, Any],
    page_number: int,
) -> tuple[list[float], list[float]]:
    """Read stable row/column boundaries from the page's drawn table lines.

    The configured coordinates are a safety constraint and fallback. A visual
    table is only accepted when the PDF drawing layer confirms a sufficiently
    wide set of horizontal grid lines inside the configured page region.
    """
    columns = [float(value) for value in spec.get("columns", []) or []]
    if len(columns) < 4:
        return [], []
    page_ranges = spec.get("page_y_ranges") or {}
    y_range = page_ranges.get(page_number) or page_ranges.get(str(page_number)) or spec.get("y_range") or []
    y_min = float(y_range[0]) if len(y_range) >= 1 else 0.0
    y_max = float(y_range[1]) if len(y_range) >= 2 else float(getattr(page.rect, "height", 10000.0) or 10000.0)
    table_width = columns[-1] - columns[0]
    horizontal_segments: list[tuple[float, float, float]] = []
    vertical_segments: list[tuple[float, float, float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return [], []
    for drawing in drawings:
        for item in drawing.get("items", []) if isinstance(drawing, dict) else []:
            if not item or item[0] != "l" or len(item) < 3:
                continue
            first = point_xy(item[1])
            second = point_xy(item[2])
            if first is None or second is None:
                continue
            x1, y1 = first
            x2, y2 = second
            if abs(y1 - y2) <= 1.0:
                y = (y1 + y2) / 2.0
                if y_min - 3.0 <= y <= y_max + 3.0 and abs(x2 - x1) >= 12.0:
                    horizontal_segments.append((min(x1, x2), max(x1, x2), y))
            elif abs(x1 - x2) <= 1.0:
                y0, y1_value = min(y1, y2), max(y1, y2)
                if y1_value >= y_min - 3.0 and y0 <= y_max + 3.0 and y1_value - y0 >= 12.0:
                    vertical_segments.append((x1, y0, y1_value))

    horizontal_by_y: dict[float, list[tuple[float, float]]] = {}
    horizontal_clusters = cluster_positions((item[2] for item in horizontal_segments), 1.5)
    for x0, x1, y in horizontal_segments:
        key = min(horizontal_clusters, key=lambda value: abs(value - y))
        horizontal_by_y.setdefault(key, []).append((x0, x1))
    horizontal_boundaries: list[float] = []
    for y, segments in horizontal_by_y.items():
        merged: list[list[float]] = []
        for x0, x1 in sorted(segments):
            if merged and x0 - merged[-1][1] <= 3.0:
                merged[-1][1] = max(merged[-1][1], x1)
            else:
                merged.append([x0, x1])
        union_width = max((interval[1] - interval[0] for interval in merged), default=0.0)
        if merged:
            span = max(interval[1] for interval in merged) - min(interval[0] for interval in merged)
            if span >= max(80.0, table_width * 0.70) and union_width >= max(40.0, table_width * 0.40):
                horizontal_boundaries.append(y)
    horizontal_boundaries = cluster_positions(horizontal_boundaries, 2.0)
    horizontal_boundaries = [y for y in horizontal_boundaries if y_min - 3.0 <= y <= y_max + 3.0]
    if len(horizontal_boundaries) < 3:
        return [], []

    vertical_positions = cluster_positions(
        (
            x for x, y0, y1 in vertical_segments
            if y1 - y0 >= 12.0 and y1 >= y_min - 3.0 and y0 <= y_max + 3.0
        ),
        2.0,
    )
    stable_columns: list[float] = []
    for configured in columns:
        match = min(vertical_positions, key=lambda value: abs(value - configured), default=None)
        stable_columns.append(match if match is not None and abs(match - configured) <= 12.0 else configured)
    return horizontal_boundaries, stable_columns


def visual_table_page_rows(page: Any, spec: dict[str, Any], page_number: int) -> tuple[list[dict[str, Any]], tuple[float, float] | None]:
    columns = [float(value) for value in spec.get("columns", []) or []]
    if len(columns) < 4:
        return [], None
    page_ranges = spec.get("page_y_ranges") or {}
    y_range = page_ranges.get(page_number) or page_ranges.get(str(page_number)) or spec.get("y_range") or []
    y_min = float(y_range[0]) if len(y_range) >= 1 else 0.0
    y_max = float(y_range[1]) if len(y_range) >= 2 else float(getattr(page.rect, "height", 10000.0) or 10000.0)
    horizontal_boundaries, detected_columns = visual_table_grid(page, spec, page_number)
    if len(horizontal_boundaries) < 3:
        return [], None
    columns = detected_columns or columns
    lines: list[dict[str, Any]] = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        for line in block.get("lines", []) if isinstance(block, dict) else []:
            bbox = line.get("bbox") or (0, 0, 0, 0)
            line_y0, line_y1 = float(bbox[1]), float(bbox[3])
            if line_y1 < y_min or line_y0 > y_max:
                continue
            text = line_cell_text(line)
            if not text:
                continue
            x0 = float(bbox[0])
            column = next((index for index in range(len(columns) - 1) if columns[index] <= x0 < columns[index + 1]), None)
            if column is None:
                continue
            center_y = (line_y0 + line_y1) / 2.0
            row = next((index for index in range(len(horizontal_boundaries) - 1)
                        if horizontal_boundaries[index] - 1.5 <= center_y < horizontal_boundaries[index + 1] + 1.5), None)
            if row is None:
                continue
            lines.append({"column": column, "row": row, "y0": line_y0, "y1": line_y1, "text": text})
    if not lines:
        return [], None
    rows: list[dict[str, Any]] = []
    for row_index in range(len(horizontal_boundaries) - 1):
        cells: list[list[str]] = [[] for _ in range(len(columns) - 1)]
        selected = [line for line in lines if line["row"] == row_index]
        for line in sorted(selected, key=lambda item: (item["column"], item["y0"])):
            cells[line["column"]].append(line["text"])
        if any(cells):
            rows.append({
                "anchor": horizontal_boundaries[row_index],
                "cells": [" ".join(cell).strip() for cell in cells],
            })
    if not rows:
        return [], None
    region = (horizontal_boundaries[0] - 2.0, horizontal_boundaries[-1] + 2.0)
    return rows, region


def extract_visual_tables(document: Any, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, list[tuple[float, float]]]]:
    tables: list[dict[str, Any]] = []
    skip_regions: dict[int, list[tuple[float, float]]] = {}
    for index, spec in enumerate(visual_table_specs(config), start=1):
        start_page = int(spec.get("start_page", 1))
        end_page = int(spec.get("end_page", start_page))
        headers = [str(item) for item in spec.get("headers", []) or []]
        all_rows: list[list[str]] = []
        page_regions: dict[int, tuple[float, float]] = {}
        for page_number in range(start_page, end_page + 1):
            rows, region = visual_table_page_rows(document[page_number - 1], spec, page_number)
            if rows:
                if region:
                    page_regions[page_number] = region
            all_rows.extend(
                row["cells"]
                for row in rows
                if [normalise_heading_lookup(cell) for cell in row["cells"]]
                != [normalise_heading_lookup(header) for header in headers]
            )
        if not headers or not all_rows:
            tables.append({
                "id": str(spec.get("id") or f"visual-table-{index}"),
                "start_page": start_page,
                "end_page": end_page,
                "headers": headers,
                "rows": [],
                "status": "skipped",
                "reason": "missing-explicit-header-or-stable-rows",
                "page_regions": page_regions,
                "y": page_regions.get(start_page, (0.0, 0.0))[0],
            })
            continue
        column_count = len(headers)
        if any(len(row) != column_count or not all(cell for cell in row) for row in all_rows):
            tables.append({
                "id": str(spec.get("id") or f"visual-table-{index}"),
                "start_page": start_page,
                "end_page": end_page,
                "headers": headers,
                "rows": all_rows,
                "status": "skipped",
                "reason": "unstable-column-count-or-empty-cell",
                "page_regions": page_regions,
                "y": page_regions.get(start_page, (0.0, 0.0))[0],
            })
            continue
        lines = ["| " + " | ".join(escape_table_cell(header) for header in headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
        lines.extend("| " + " | ".join(escape_table_cell(cell) for cell in row) + " |" for row in all_rows)
        table = {
            "id": str(spec.get("id") or f"visual-table-{index}"),
            "start_page": start_page,
            "end_page": end_page,
            "headers": headers,
            "rows": all_rows,
            "status": "converted",
            "markdown": "\n".join(lines),
            "page_regions": page_regions,
            "y": page_regions.get(start_page, (0.0, 0.0))[0],
        }
        tables.append(table)
        for page_number, region in page_regions.items():
            skip_regions.setdefault(page_number, []).append(region)
    if bool((config.get("visual_tables") or {}).get("enabled", False)):
        discovered = discover_visual_tables(document, config, skip_regions)
        tables.extend(discovered)
        for table in discovered:
            if table.get("status") != "converted":
                continue
            for page_number, region in (table.get("page_regions") or {}).items():
                skip_regions.setdefault(int(page_number), []).append(
                    (float(region[0]), float(region[1]))
                )
    return tables, skip_regions


def boxed_callout_label(text: str) -> tuple[str, str] | None:
    """Return a supported callout type and preserved title for a box label."""
    label = re.sub(r"[*_`]+", "", text).strip()
    label = re.sub(r"\s+", " ", label).rstrip(":").strip()
    normalized = label.casefold()
    if normalized in {"tips or important notes", "tips or important note"}:
        return "NOTE", label
    key = normalized
    if key in CALLOUT_TYPES:
        callout_type = CALLOUT_TYPES[key]
        return callout_type, label if key not in {callout_type.casefold()} else ""
    if key.endswith("s") and key[:-1] in CALLOUT_TYPES:
        callout_type = CALLOUT_TYPES[key[:-1]]
        return callout_type, label if key[:-1] != callout_type.casefold() else ""
    return None


def _bordered_box_rects(page: Any) -> list[tuple[float, float, float, float]]:
    """Recover rounded unfilled box fragments from PDF drawing objects."""
    rects: list[tuple[float, float, float, float]] = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return rects
    for drawing in drawings:
        rect = drawing.get("rect") if isinstance(drawing, dict) else None
        items = drawing.get("items", []) if isinstance(drawing, dict) else []
        if rect is None or drawing.get("fill") is not None:
            continue
        if not any(item and item[0] == "c" for item in items):
            continue
        if rect.width < 180.0 or rect.height < 20.0 or rect.height > 180.0:
            continue
        rects.append((float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)))
    return rects


def _merge_bordered_box_rects(
    rects: list[tuple[float, float, float, float]],
) -> list[tuple[float, float, float, float]]:
    merged: list[list[float]] = []
    for rect in sorted(rects, key=lambda item: (item[1], item[0])):
        if not merged:
            merged.append(list(rect))
            continue
        previous = merged[-1]
        same_horizontal = abs(previous[0] - rect[0]) <= 10.0 and abs(previous[2] - rect[2]) <= 10.0
        overlapping = rect[1] <= previous[3] + 4.0 and rect[3] >= previous[1] - 4.0
        if same_horizontal and overlapping:
            previous[0] = min(previous[0], rect[0])
            previous[1] = min(previous[1], rect[1])
            previous[2] = max(previous[2], rect[2])
            previous[3] = max(previous[3], rect[3])
        else:
            merged.append(list(rect))
    return [tuple(item) for item in merged]


def _box_text_lines(page: Any, rect: tuple[float, float, float, float]) -> list[str]:
    x0, y0, x1, y1 = rect
    lines: list[tuple[float, str]] = []
    for block in page.get_text("dict", sort=True).get("blocks", []):
        for line in block.get("lines", []) if isinstance(block, dict) else []:
            bbox = line.get("bbox") or (0, 0, 0, 0)
            line_x0, line_y0, line_x1, line_y1 = (float(value) for value in bbox[:4])
            if line_x0 < x0 + 4.0 or line_x1 > x1 - 4.0 or line_y0 < y0 + 2.0 or line_y1 > y1 - 2.0:
                continue
            text = line_cell_text(line)
            if text:
                lines.append((line_y0, text))
    return [text for _, text in sorted(lines)]


def render_boxed_callout(
    label: str,
    body: list[str],
    config: dict[str, Any],
    callout_type: str,
) -> str:
    style = resolve_callout_style(config)
    if style == "none":
        return "\n\n".join([label, *body]).strip()
    if style == "plain":
        return "\n".join([f"> **{label}**", *(f"> {line}" for line in body)]).strip()
    title = f" {label}" if label else ""
    return "\n".join([f"> [!{callout_type}]{title}", *(f"> {line}" for line in body)]).strip()


def extract_boxed_callouts(
    document: Any,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[int, list[tuple[float, float]]]]:
    """Detect clearly labelled rounded editorial boxes, not code rectangles."""
    if resolve_boxed_callout_policy(config) == "off":
        return [], {}
    callouts: list[dict[str, Any]] = []
    skip_regions: dict[int, list[tuple[float, float]]] = {}
    for page_number in range(1, int(document.page_count) + 1):
        page = document[page_number - 1]
        rects = _bordered_box_rects(page)
        for index, rect in enumerate(_merge_bordered_box_rects(rects), start=1):
            text_lines = _box_text_lines(page, rect)
            if not text_lines:
                continue
            label_match = boxed_callout_label(text_lines[0])
            base = {
                "id": f"boxed-callout-p{page_number:04d}-{index}",
                "page": page_number,
                "region": [rect[1], rect[3]],
                "label": text_lines[0],
                "body": text_lines[1:],
                "detection": "bordered-box-auto",
            }
            if label_match is None or not text_lines[1:]:
                callouts.append({**base, "status": "skipped", "reason": "unlabelled-or-empty-box"})
                continue
            callout_type, title = label_match
            callout = {
                **base,
                "status": "converted",
                "callout_type": callout_type,
                "title": title,
                "markdown": render_boxed_callout(
                    title,
                    merge_split_plain_urls("\n".join(text_lines[1:])).splitlines(),
                    config,
                    callout_type,
                ),
                "y": rect[1],
                "x": rect[0],
            }
            callouts.append(callout)
            skip_regions.setdefault(page_number, []).append((rect[1] - 2.0, rect[3] + 2.0))
    return callouts, skip_regions


def render_entry(entry: dict[str, Any], config: dict[str, Any]) -> str:
    line_text = str(entry["text"])
    if entry["heading_level"] and not entry["is_code"]:
        heading_text = re.sub(r"[*_`]", "", line_text).strip()
        return f"{'#' * int(entry['heading_level'])} {heading_text}"
    if entry["is_code"]:
        language = infer_code_language(line_text, config)
        return f"```{language}\n{line_text.rstrip()}\n```"
    if entry.get("is_inline_code"):
        return line_text
    if entry["has_bullet_prefix"]:
        repaired, _ = repair_broken_emphasis("- " + line_text.lstrip())
        return repaired
    if FIGURE_CAPTION_RE.match(line_text.strip()):
        caption_style = str((config.get("output") or {}).get("figure_caption_style") or "plain")
        if caption_style == "blockquote":
            return f"> {line_text.strip()}"
        if caption_style not in {"plain", "blockquote"}:
            raise PipelineError("output.figure_caption_style must be plain or blockquote")
    repaired, _ = repair_broken_emphasis(line_text)
    return repaired


def render_page_content(
    page: Any,
    chapter_title: str,
    config: dict[str, Any],
    *,
    heading_levels: dict[str, int] | None = None,
    known_heading_titles: set[str] | None = None,
    skip_regions: list[tuple[float, float]] | None = None,
    table_insertions: list[dict[str, Any]] | None = None,
    image_insertions: list[dict[str, Any]] | None = None,
    inline_images: list[dict[str, Any]] | None = None,
    source_link: str | None = None,
) -> str:
    blocks = extract_page_blocks(
        page,
        chapter_title,
        heading_levels=heading_levels,
        code_enabled=bool((config.get("code_blocks") or {}).get("enabled", False)),
        inline_code_enabled=bool((config.get("code_blocks") or {}).get("inline", True)),
        code_min_lines=int((config.get("code_blocks") or {}).get("min_lines", 2)),
        code_min_chars=int((config.get("code_blocks") or {}).get("min_chars", 60)),
        known_heading_titles=known_heading_titles,
        skip_regions=skip_regions,
        inline_images=inline_images,
    )
    page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
    bullet_ys = [float(entry["y"]) for entry in blocks if entry["is_bullet_only"]]
    events = sorted(
        [*(table_insertions or []), *(image_insertions or [])],
        key=lambda item: (
            float(item.get("y", 0.0)),
            float(item.get("x", 0.0)),
            int(item.get("priority", 0)),
        ),
    )
    rendered: list[str] = []
    event_index = 0
    page_link_mode = str((config.get("output") or {}).get("page_links") or "chapter")
    for entry in blocks:
        while event_index < len(events) and float(events[event_index].get("y", 0.0)) <= float(entry["y"]):
            rendered.append(str(events[event_index]["markdown"]))
            event_index += 1
        if entry["is_bullet_only"]:
            continue
        if entry.get("is_running_header"):
            continue
        if entry.get("is_chapter_title"):
            continue
        plain_line = str(entry["plain"]).strip()
        near_page_edge = page_height and (entry["y"] <= page_height * 0.2 or entry["y"] >= page_height * 0.8)
        if is_pdf_page_number(plain_line) and near_page_edge:
            continue
        if chapter_title and plain_line.lower().startswith("chapter ") and chapter_title.lower() in plain_line.lower() and not entry["is_code"]:
            continue
        item = render_entry(entry, config)
        if page_link_mode == "headings-and-code" and source_link and (entry["heading_level"] or entry["is_code"]):
            rendered.append(source_link)
        elif entry["has_bullet_prefix"] or any(abs(float(entry["y"]) - bullet_y) <= 3.0 for bullet_y in bullet_ys):
            item = "- " + item.lstrip("- ")
        rendered.append(item)
    while event_index < len(events):
        rendered.append(str(events[event_index]["markdown"]))
        event_index += 1
    joined = "\n\n".join(rendered)
    joined_lines = compact_unordered_list_spacing(joined.splitlines(keepends=True))
    page_text = merge_split_plain_urls(
        merge_split_inline_code_urls(normalise_text("".join(joined_lines)))
    )
    try:
        selected_callout_style = resolve_callout_style(config)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
    page_text, _, _ = convert_callouts_text(page_text, style=selected_callout_style)
    page_text = merge_split_inline_code_urls(page_text)
    page_text = merge_split_plain_urls(page_text)
    return page_text


def merge_adjacent_code_fences(markdown: str) -> str:
    """Merge a code fence continued on the next PDF page.

    This is deliberately limited to two matching fences separated only by the
    generated page link. Any intervening prose, image, or different language
    leaves both fences untouched.
    """
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        opening = lines[index]
        if not opening.startswith("```"):
            index += 1
            continue
        closing = next((candidate for candidate in range(index + 1, len(lines)) if lines[candidate] == "```"), None)
        if closing is None:
            index += 1
            continue
        link_index = closing + 1
        while link_index < len(lines) and not lines[link_index].strip():
            link_index += 1
        if link_index >= len(lines) or not is_source_reference_line(lines[link_index]):
            index = closing + 1
            continue
        next_open = link_index + 1
        while next_open < len(lines) and not lines[next_open].strip():
            next_open += 1
        if next_open >= len(lines) or lines[next_open] != opening:
            index = closing + 1
            continue
        next_close = next((candidate for candidate in range(next_open + 1, len(lines)) if lines[candidate] == "```"), None)
        if next_close is None:
            index = next_open + 1
            continue
        lines = lines[:closing] + lines[next_open + 1 : next_close + 1] + lines[next_close + 1 :]
        index = 0
    return "\n".join(lines)


def is_source_reference_line(line: str) -> bool:
    return bool(
        re.match(
            r"^>\s*(?:\[Source PDF, p\.\s*\d+\]|Source PDF, p\.\s*\d+)",
            line.strip(),
        )
    )


def render_pages(
    document: Any,
    title: str,
    start_page: int,
    end_page: int,
    source_path: Path,
    vault: Path,
    output_path: Path,
    config: dict[str, Any],
    images_by_page: dict[int, list[dict[str, Any]]],
    visual_tables: list[dict[str, Any]] | None = None,
    visual_skip_regions: dict[int, list[tuple[float, float]]] | None = None,
    boxed_callouts: list[dict[str, Any]] | None = None,
) -> str:
    page_link_mode = str((config.get("output") or {}).get("page_links") or "chapter")
    if page_link_mode not in {"chapter", "every-page", "headings-and-code", "none"}:
        raise PipelineError("output.page_links must be chapter, every-page, headings-and-code, or none")
    heading_index = toc_heading_index(document)
    known_heading_titles = toc_heading_titles(document)
    tables = [table for table in (visual_tables or []) if table.get("status") == "converted"]
    events_by_page: dict[int, list[dict[str, Any]]] = {}
    for table in tables:
        if start_page <= int(table["start_page"]) <= end_page:
            source_link = source_reference(
                int(table["start_page"]), config,
                output_path=output_path, source_path=source_path, vault=vault,
            )
            events_by_page.setdefault(int(table["start_page"]), []).append({
                "y": float(table.get("y", 0.0)),
                "x": 0.0,
                "priority": 1,
                "markdown": source_link + "\n\n" + str(table["markdown"]),
            })
    for callout in (boxed_callouts or []):
        if start_page <= int(callout.get("page", 0)) <= end_page and callout.get("status") == "converted":
            page_number = int(callout["page"])
            source_link = source_reference(
                page_number, config,
                output_path=output_path, source_path=source_path, vault=vault,
            )
            events_by_page.setdefault(page_number, []).append({
                "y": float(callout.get("y", 0.0)),
                "x": float(callout.get("x", 0.0)),
                "priority": 1,
                "markdown": (source_link + "\n\n" if source_link else "") + str(callout["markdown"]),
            })
    lines: list[str] = []
    for page_number in range(start_page, end_page + 1):
        page = document[page_number - 1]
        source_link = source_reference(
            page_number, config,
            output_path=output_path, source_path=source_path, vault=vault,
        )
        page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
        image_placement = str((config.get("output") or {}).get("image_placement") or "pdf-coordinate")
        if image_placement not in {"pdf-coordinate", "append"}:
            raise PipelineError("output.image_placement must be pdf-coordinate or append")
        image_insertions: list[dict[str, Any]] = []
        inline_images: list[dict[str, Any]] = []
        for image in sorted(
            images_by_page.get(page_number, []),
            key=lambda item: (
                float(item.get("y0", page_height + 1.0)),
                float(item.get("x0", 0.0)),
                int(item.get("xref", 0)),
            ),
        ):
            image_target = relative_link(
                output_path,
                vault_path(vault, str(image["relative_path"])),
                vault,
            )
            if image.get("image_role") == "inline-icon":
                image["inline_markdown"] = render_inline_file_embed(
                    str(image["relative_path"]),
                    config,
                    markdown_target=image_target,
                )
                inline_images.append(image)
                continue
            y = page_height + 1.0 if image_placement == "append" else float(image.get("y0", page_height + 1.0))
            image_markdown = render_file_embed(
                str(image["relative_path"]),
                config,
                markdown_target=image_target,
            )
            image_insertions.append({
                "y": y,
                "x": float(image.get("x0", 0.0)),
                "priority": 0,
                "markdown": (source_link + "\n\n" if source_link else "") + image_markdown,
            })
        text = render_page_content(
            page,
            title,
            config,
            heading_levels=heading_index.get(page_number, {}),
            known_heading_titles=known_heading_titles,
            skip_regions=(visual_skip_regions or {}).get(page_number, []),
            table_insertions=events_by_page.get(page_number, []),
            image_insertions=image_insertions,
            inline_images=inline_images,
            source_link=source_link,
        )
        text = apply_line_filters(text, config)
        if page_link_mode == "chapter" and page_number == start_page:
            lines.extend([source_link, ""])
        elif page_link_mode == "every-page":
            lines.extend([source_link, ""])
        if text:
            lines.extend([text, ""])
    return merge_adjacent_code_fences("\n".join(lines).rstrip()) + "\n"


def render_chapter(
    document: Any,
    chapter: Chapter,
    book: str,
    source_path: Path,
    source_hash: str,
    vault: Path,
    output_path: Path,
    config: dict[str, Any],
    images_by_page: dict[int, list[dict[str, Any]]],
    visual_tables: list[dict[str, Any]] | None = None,
    visual_skip_regions: dict[int, list[tuple[float, float]]] | None = None,
    boxed_callouts: list[dict[str, Any]] | None = None,
) -> str:
    fields = source_frontmatter(
        config,
        "chapter",
        book,
        chapter.title,
        source_path,
        source_hash,
        vault,
        chapter.start_page,
        chapter.end_page,
        part=chapter.part,
        number=chapter.number,
        print_pages=chapter.print_pages,
    )
    body = render_pages(
        document,
        chapter.title,
        chapter.start_page,
        chapter.end_page,
        source_path,
        vault,
        output_path,
        config,
        images_by_page,
        visual_tables,
        visual_skip_regions,
        boxed_callouts,
    )
    header = f"# Chapter {chapter.number}: {chapter.title}"
    if str((config.get("output") or {}).get("page_links") or "chapter") == "headings-and-code":
        header_reference = source_reference(
            chapter.start_page, config,
            output_path=output_path, source_path=source_path, vault=vault,
        )
        header = header_reference + "\n\n" + header
    return emit_frontmatter(fields) + header + "\n\n" + body


def render_section(
    document: Any,
    section: Section,
    book: str,
    source_path: Path,
    source_hash: str,
    vault: Path,
    output_path: Path,
    config: dict[str, Any],
    images_by_page: dict[int, list[dict[str, Any]]],
    visual_tables: list[dict[str, Any]] | None = None,
    visual_skip_regions: dict[int, list[tuple[float, float]]] | None = None,
    boxed_callouts: list[dict[str, Any]] | None = None,
) -> str:
    fields = source_frontmatter(
        config,
        section.kind,
        book,
        section.title,
        source_path,
        source_hash,
        vault,
        section.start_page,
        section.end_page,
        part=section.part,
        print_pages=section.print_pages,
    )
    body = render_pages(
        document,
        section.title,
        section.start_page,
        section.end_page,
        source_path,
        vault,
        output_path,
        config,
        images_by_page,
        visual_tables,
        visual_skip_regions,
        boxed_callouts,
    )
    header = f"# {section.title}"
    if str((config.get("output") or {}).get("page_links") or "chapter") == "headings-and-code":
        header_reference = source_reference(
            section.start_page, config,
            output_path=output_path, source_path=source_path, vault=vault,
        )
        header = header_reference + "\n\n" + header
    return emit_frontmatter(fields) + header + "\n\n" + body


def extract_lens_outputs(
    chapter_outputs: list[tuple[Chapter, Path, str]],
    config: dict[str, Any],
    vault: Path,
    book: str,
    source_hash: str,
) -> list[OutputFile]:
    lens_config = config.get("lens") or {}
    pattern_text = lens_config.get("heading_regex")
    if not pattern_text:
        pattern_text = r"^#{2,6}\s+Lens\s+(?P<number>[0-9∞]+)\s*[—:-]\s*(?P<title>.+)$"
    try:
        pattern = re.compile(str(pattern_text))
    except re.error as exc:
        raise PipelineError(f"Invalid lens.heading_regex: {exc}") from exc
    lens_dir = safe_component(str(lens_config.get("output_dir") or "Lenses"))
    outputs: list[OutputFile] = []
    for chapter, chapter_path, text in chapter_outputs:
        lines = text.splitlines()
        for index, line in enumerate(lines):
            match = pattern.match(line.strip())
            if not match:
                continue
            number = match.groupdict().get("number") or (match.group(1) if match.lastindex else "")
            title = match.groupdict().get("title") or (match.group(2) if match.lastindex and match.lastindex >= 2 else "Lens")
            body: list[str] = []
            for candidate in lines[index + 1 :]:
                if re.match(r"^#{2,6}\s+", candidate):
                    break
                body.append(candidate)
            relative = as_posix(Path(lens_dir) / f"Lens {safe_component(str(number))} - {safe_component(str(title))}.md")
            fields = {
                "kind": "lens",
                "book": book,
                "title": str(title),
                "lens_number": str(number),
                "chapter": chapter.title,
                "source_sha256": source_hash,
                "generated_by": GENERATOR,
                "generator_version": VERSION,
            }
            content = emit_frontmatter(fields) + f"# Lens {number} — {title}\n\n" + "\n".join(body).strip() + "\n"
            outputs.append(OutputFile(relative, content.encode("utf-8"), "lens"))
    return outputs


def make_moc(
    book: str,
    chapters: list[tuple[Chapter, Path]],
    section_outputs: list[tuple[Section, Path, str]],
    lens_outputs: list[OutputFile],
    topic_index: OutputFile | None,
    config: dict[str, Any],
) -> OutputFile:
    output_config = config.get("output") or {}
    pattern = str(output_config.get("moc_filename") or "MOC - {book}.md")
    relative = format_output_name(pattern, book, Chapter("", "", "", 1, 1))
    relative = relative.replace("{book}", safe_component(book))
    metadata = config.get("book_metadata") or {}
    fields: dict[str, Any] = {
        frontmatter_type(config): "moc",
        "book": book,
        "generated_by": GENERATOR,
        "generator_version": VERSION,
    }
    for key in ("publisher", "published", "isbn"):
        if metadata.get(key) not in {None, ""}:
            fields[key] = metadata[key]
    tags = merge_tags(metadata.get("tags"), (config.get("frontmatter") or {}).get("tags"), "type/moc")
    if tags:
        fields["tags"] = tags
    lines = [
        emit_frontmatter(fields).rstrip("\n"),
        f"# {book}",
        "",
    ]
    if any(metadata.get(key) not in {None, ""} for key in ("technology", "language", "publisher", "published", "isbn")):
        lines.extend(["## Book metadata", ""])
        for key in ("technology", "language", "publisher", "published", "isbn"):
            if metadata.get(key) not in {None, ""}:
                lines.append(f"- {key}: {metadata[key]}")

    paratext = [item for item in section_outputs if item[0].kind not in {"back-matter", "backmatter", "index", "part", "part-overview", "part_overview"}]
    part_overviews = [item for item in section_outputs if item[0].kind in {"part", "part-overview", "part_overview"}]
    backmatter = [item for item in section_outputs if item[0].kind in {"back-matter", "backmatter", "index"}]
    if paratext:
        lines.extend(["", "## Paratext", ""])
        for section, path, _ in paratext:
            lines.append(f"- {render_note_link(path, section.title, config)}")

    chapter_groups: dict[str, list[tuple[Chapter, Path]]] = {}
    for chapter, path in chapters:
        chapter_groups.setdefault(chapter.part or "00_Book", []).append((chapter, path))
    for part, group in chapter_groups.items():
        lines.extend(["", f"## {part}", ""])
        for section, path, _ in part_overviews:
            if section.part == part:
                lines.append(f"- {render_note_link(path, section.title, config)}")
        for chapter, path in group:
            label = f"Chapter {chapter.number}: {chapter.title}"
            lines.append(f"- {render_note_link(path, label, config)}")

    if backmatter:
        lines.extend(["", "## Back Matter", ""])
        for section, path, _ in backmatter:
            lines.append(f"- {render_note_link(path, section.title, config)}")
    if lens_outputs:
        lines.extend(["", "## Lenses", ""])
        for output in lens_outputs:
            path = Path(output.relative_path)
            lines.append(f"- {render_note_link(path, None, config)}")
    if topic_index is not None:
        lines.extend(["", "## Topic index", ""])
        path = Path(topic_index.relative_path)
        lines.append(f"- {render_note_link(path, 'Topic and term index', config)}")
    return OutputFile(relative, ("\n".join(lines).rstrip() + "\n").encode("utf-8"), "moc")


def make_topic_index(
    book: str,
    chapters: list[tuple[Chapter, Path, str]],
    section_outputs: list[tuple[Section, Path, str]],
    config: dict[str, Any],
) -> OutputFile:
    """Create a compact heading/topic index without inventing topic notes."""
    output_config = config.get("output") or {}
    filename = str(output_config.get("topic_index_filename") or "Topic Index.md")
    relative = Path(filename)
    fields: dict[str, Any] = {
        frontmatter_type(config): "topic-index",
        "book": book,
        "generated_by": GENERATOR,
        "generator_version": VERSION,
    }
    lines = [emit_frontmatter(fields).rstrip("\n"), "# Topic and Term Index", ""]
    entries: list[tuple[str, str, str]] = []
    for chapter, path, text in chapters:
        entries.append((chapter.title.casefold(), chapter.title, as_posix(path)))
        for heading in re.findall(r"^#{2,4}\s+(.+?)\s*$", text, re.MULTILINE):
            clean = re.sub(r"\s+#.*$", "", heading).strip()
            if clean:
                entries.append((clean.casefold(), clean, as_posix(path.with_suffix(""))))
    for section, path, text in section_outputs:
        for heading in re.findall(r"^#{2,4}\s+(.+?)\s*$", text, re.MULTILINE):
            clean = re.sub(r"\s+#.*$", "", heading).strip()
            if clean:
                entries.append((clean.casefold(), clean, as_posix(path)))
    seen: set[tuple[str, str]] = set()
    for _, title, path in sorted(entries, key=lambda item: (item[0], item[2])):
        identity = (title.casefold(), path)
        if identity in seen:
            continue
        seen.add(identity)
        lines.append(f"- {render_note_link(path, title, config, fragment=title)}")
    if not seen:
        lines.append("No explicit topic headings were identified.")
    return OutputFile(as_posix(relative), ("\n".join(lines).rstrip() + "\n").encode("utf-8"), "topic-index")


def stages_from_config(config: dict[str, Any], requested: str | None) -> list[str]:
    valid = ("chapterize", "sections", "attachments", "code_blocks", "tables", "visual_tables", "lens", "moc", "topic_index")
    if requested:
        values = [item.strip() for item in requested.split(",") if item.strip()]
        invalid = [item for item in values if item not in valid]
        if invalid:
            raise PipelineError(f"Unknown stage(s): {', '.join(invalid)}")
        stages = list(dict.fromkeys(values))
    else:
        modules = config.get("modules") or {}
        stages = [name for name in valid if bool(modules.get(name, False))]
    if any(stage != "chapterize" for stage in stages) and "chapterize" not in stages:
        stages.insert(0, "chapterize")
    return stages


def select_chapters(
    chapters: list[Chapter], selection: str | None,
) -> tuple[list[Chapter], list[str] | None]:
    """Return chapters in source order, optionally restricted by number."""
    if selection is None:
        return chapters, None
    requested = [item.strip() for item in selection.split(",") if item.strip()]
    if not requested:
        raise PipelineError("--only-chapters requires one or more chapter numbers")
    requested_keys = {str(int(item)) if item.isdigit() else item.casefold() for item in requested}
    selected = [
        chapter for chapter in chapters
        if (str(int(chapter.number)) if chapter.number.isdigit() else chapter.number.casefold()) in requested_keys
    ]
    found_keys = {
        str(int(chapter.number)) if chapter.number.isdigit() else chapter.number.casefold()
        for chapter in selected
    }
    missing = [item for item in requested if (str(int(item)) if item.isdigit() else item.casefold()) not in found_keys]
    if missing:
        raise PipelineError(f"Requested chapter(s) not found: {', '.join(missing)}")
    return selected, requested


def select_sections(
    sections: list[Section], selection: str | None,
) -> tuple[list[Section], list[str] | None]:
    """Return sections in source order, optionally restricted by stable id."""
    if selection is None:
        return sections, None
    requested = [item.strip() for item in selection.split(",") if item.strip()]
    if not requested:
        raise PipelineError("--only-sections requires one or more section ids")
    requested_keys = {item.casefold() for item in requested}
    selected = [
        section for section in sections
        if section.section_id.casefold() in requested_keys
    ]
    found_keys = {section.section_id.casefold() for section in selected}
    missing = [item for item in requested if item.casefold() not in found_keys]
    if missing:
        raise PipelineError(f"Requested section(s) not found: {', '.join(missing)}")
    return selected, requested


def previous_manifest(vault: Path, book: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    path = resource_root(vault, "Reports", book, config) / "latest-manifest.json"
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def existing_file_hash(path: Path) -> str | None:
    return sha256_file(path) if path.exists() and path.is_file() else None


def has_generator_marker(data: bytes) -> bool:
    if not data.startswith(b"---"):
        return False
    try:
        # The byte limit may cut through a multibyte character in a large
        # frontmatter-adjacent line; marker detection should not reject a
        # valid UTF-8 Markdown file for that reason.
        text = data[:4096].decode("utf-8", errors="ignore")
    except UnicodeDecodeError:
        return False
    return bool(re.search(r"^generated_by:\s*['\"]?pdf-book-to-obsidian['\"]?\s*$", text, re.MULTILINE))


def classify_outputs(vault: Path, outputs: list[OutputFile], manifest: dict[str, Any]) -> list[dict[str, Any]]:
    previous = {
        str(item.get("relative_path")): item
        for item in manifest.get("files", [])
        if isinstance(item, dict) and item.get("relative_path")
    }
    classified: list[dict[str, Any]] = []
    for output in outputs:
        target = vault_path(vault, output.relative_path)
        desired = output.content
        current_hash = existing_file_hash(target)
        desired_hash = sha256_bytes(desired)
        item: dict[str, Any] = {
            "relative_path": output.relative_path,
            "kind": output.kind,
            "desired_sha256": desired_hash,
            "current_sha256": current_hash,
            "exists": target.exists(),
            "action": "create" if current_hash is None else "update",
            "conflict": None,
        }
        if current_hash == desired_hash:
            item["action"] = "unchanged"
        elif current_hash is not None:
            prior = previous.get(output.relative_path)
            trusted = bool(prior and prior.get("after_sha256") == current_hash)
            if output.kind != "attachment":
                trusted = trusted and has_generator_marker(target.read_bytes())
            if not trusted:
                item["conflict"] = "existing-file-is-manual-or-hash-drifted"
        classified.append(item)
    return classified


def adjust_text_line_endings(vault: Path, output: OutputFile) -> OutputFile:
    if output.kind == "attachment":
        return output
    target = vault_path(vault, output.relative_path)
    if not target.exists():
        return output
    try:
        existing = target.read_bytes()
    except OSError:
        return output
    if b"\r\n" in existing:
        content = output.content.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        return OutputFile(output.relative_path, content, output.kind)
    return output


def build_outputs(
    vault: Path,
    book: str,
    config: dict[str, Any],
    source: Path,
    source_for_output: Path,
    source_hash: str,
    stages: list[str],
    only_chapters: str | None = None,
    only_sections: str | None = None,
) -> tuple[list[OutputFile], dict[str, Any]]:
    pdf = require_pdf_runtime()
    document = pdf.open(str(source))
    try:
        if only_chapters is not None and only_sections is not None:
            raise PipelineError("--only-chapters and --only-sections are mutually exclusive")
        display_book = str(config.get("book_title") or book)
        all_chapters = resolve_chapters(document, config)
        chapters, selected_chapter_numbers = select_chapters(all_chapters, only_chapters)
        all_sections = resolve_sections(document, config) if "sections" in stages else []
        if only_sections is not None and "sections" not in stages:
            raise PipelineError("--only-sections requires the sections stage")
        if only_sections is not None:
            sections, selected_section_ids = select_sections(all_sections, only_sections)
            chapters = []
        elif selected_chapter_numbers is not None:
            sections, selected_section_ids = [], None
        else:
            sections, selected_section_ids = all_sections, None
        scoped = selected_chapter_numbers is not None or selected_section_ids is not None
        attachment_root = resource_root(vault, "Attachment", book, config)
        try:
            attachment_root.relative_to(vault.resolve())
        except ValueError as exc:
            raise PipelineError(
                "The attachment directory must be inside the Markdown output root "
                f"for portable generated links: {attachment_root}"
            ) from exc
        images_by_page: dict[int, list[dict[str, Any]]] = {}
        image_records: list[dict[str, Any]] = []
        if "attachments" in stages and selected_section_ids is None:
            attachment_config = config.get("attachments") or {}
            included_section_kinds = {
                str(item).strip().lower()
                for item in attachment_config.get("include_section_kinds", []) or []
            }
            attachment_ranges = [
                *chapters,
                *[
                    section for section in sections
                    if section.kind.strip().lower() in included_section_kinds
                ],
            ]
            images_by_page, image_records = extract_images(
                document,
                attachment_ranges,
                attachment_root,
                book,
                link_root=vault,
                config=config,
            )

        visual_tables: list[dict[str, Any]] = []
        visual_skip_regions: dict[int, list[tuple[float, float]]] = {}
        if "visual_tables" in stages:
            visual_tables, visual_skip_regions = extract_visual_tables(document, config)
        boxed_callouts: list[dict[str, Any]] = []
        if "callouts" in stages or "sections" in stages or "chapters" in stages:
            boxed_callouts, boxed_skip_regions = extract_boxed_callouts(document, config)
            for page_number, regions in boxed_skip_regions.items():
                visual_skip_regions.setdefault(page_number, []).extend(regions)

        output_config = config.get("output") or {}
        chapter_pattern = str(output_config.get("chapter_filename") or "Chapter {number} - {title}.md")
        chapter_outputs: list[tuple[Chapter, Path, str]] = []
        section_outputs: list[tuple[Section, Path, str]] = []
        outputs: list[OutputFile] = []
        table_audits: list[dict[str, Any]] = []
        for chapter in chapters:
            part_folder = safe_component(chapter.part or "00_Book")
            filename = format_output_name(chapter_pattern, str(config.get("book_title") or book), chapter)
            relative = Path(part_folder) / filename
            chapter_path = vault / relative
            content = render_chapter(
                document,
                chapter,
                display_book,
                source_for_output,
                source_hash,
                vault,
                chapter_path,
                config,
                images_by_page,
                visual_tables,
                visual_skip_regions,
                boxed_callouts,
            )
            if "tables" in stages:
                table_config = config.get("table_transform") or {}
                min_rows = int(table_config.get("min_rows", 2))
                content, table_audit = transform_definition_lists(content, min_rows=min_rows)
                table_audits.append({"relative_path": as_posix(relative), **table_audit})
            output = OutputFile(as_posix(relative), content.encode("utf-8"), "chapter")
            outputs.append(output)
            chapter_outputs.append((chapter, relative, content))

        if "sections" in stages:
            section_pattern = str(output_config.get("section_filename") or "{title}.md")
            for section in sections:
                filename = section.filename or format_output_name(section_pattern, str(config.get("book_title") or book), Chapter("", section.title, "", 1, 1))
                relative = Path(section.folder) / filename
                section_path = vault / relative
                content = render_section(
                    document,
                    section,
                    display_book,
                    source_for_output,
                    source_hash,
                    vault,
                    section_path,
                    config,
                    images_by_page,
                    visual_tables,
                    visual_skip_regions,
                    boxed_callouts,
                )
                output = OutputFile(as_posix(relative), content.encode("utf-8"), "section")
                outputs.append(output)
                section_outputs.append((section, relative, content))

        visual_table_audits = [
            {
                "id": table.get("id"),
                "start_page": table.get("start_page"),
                "end_page": table.get("end_page"),
                "headers": table.get("headers", []),
                "rows": len(table.get("rows", [])),
                "status": table.get("status"),
                "reason": table.get("reason"),
                "confidence": table.get("confidence"),
                "detection": table.get("detection"),
                "page_regions": table.get("page_regions", {}),
            }
            for table in visual_tables
        ]
        boxed_callout_audits = [
            {
                "id": callout.get("id"),
                "page": callout.get("page"),
                "label": callout.get("label"),
                "title": callout.get("title"),
                "body_lines": len(callout.get("body", [])),
                "status": callout.get("status"),
                "reason": callout.get("reason"),
                "detection": callout.get("detection"),
                "region": callout.get("region"),
            }
            for callout in boxed_callouts
        ]

        lens_outputs: list[OutputFile] = []
        if "lens" in stages and not scoped:
            lens_outputs = extract_lens_outputs(chapter_outputs, config, vault, display_book, source_hash)
            outputs.extend(lens_outputs)

        if "attachments" in stages and selected_section_ids is None:
            for record in image_records:
                target = vault_path(vault, record["relative_path"])
                if scoped and target.exists():
                    # A scoped chapter regeneration must not rewrite an
                    # existing attachment merely because it was discovered
                    # while rebuilding the selected pages.
                    continue
                match = next(
                    (
                        item["data"]
                        for values in images_by_page.values()
                        for item in values
                        if item["relative_path"] == record["relative_path"]
                    ),
                    None,
                )
                if match is not None:
                    outputs.append(OutputFile(record["relative_path"], match, "attachment"))

        topic_index_output: OutputFile | None = None
        if "topic_index" in stages and not scoped:
            topic_index_output = make_topic_index(
                display_book, chapter_outputs, section_outputs, config
            )
            outputs.append(topic_index_output)

        if "moc" in stages and not scoped:
            chapter_paths = [(chapter, relative) for chapter, relative, _ in chapter_outputs]
            outputs.append(make_moc(
                display_book, chapter_paths, section_outputs, lens_outputs,
                topic_index_output, config,
            ))

        inline_records = [
            record for record in image_records
            if record.get("image_role") == "inline-icon"
        ]
        ambiguous_image_records = [
            record for record in image_records
            if record.get("image_classification") == "ambiguous"
        ]

        details = {
            "scope": {
                "only_chapters": selected_chapter_numbers,
                "selected_chapters": [chapter.number for chapter in chapters],
                "only_sections": selected_section_ids,
                "selected_sections": [
                    {
                        "id": section.section_id,
                        "title": section.title,
                        "relative_path": as_posix(Path(section.folder) / (section.filename or "")),
                    }
                    for section in sections
                ],
                "skipped_nonchapter_outputs": scoped,
                "skipped_nonsection_outputs": selected_section_ids is not None,
            },
            "chapters": [
                {
                    "number": chapter.number,
                    "title": chapter.title,
                    "part": chapter.part,
                    "start_page": chapter.start_page,
                    "end_page": chapter.end_page,
                }
                for chapter in chapters
            ],
            "sections": [
                {
                    "id": section.section_id,
                    "kind": section.kind,
                    "title": section.title,
                    "folder": section.folder,
                    "relative_path": as_posix(relative),
                    "start_page": section.start_page,
                    "end_page": section.end_page,
                    "print_pages": section.print_pages,
                }
                for section, relative, _ in section_outputs
            ],
            "images": image_records,
            "image_classification": {
                "policy": resolve_inline_image_policy(config),
                "syntax": resolve_inline_image_syntax(config),
                "total": len(image_records),
                "inline": len(inline_records),
                "block": len(image_records) - len(inline_records),
                "ambiguous": len(ambiguous_image_records),
                "ambiguous_records": ambiguous_image_records,
            },
            "table_audits": table_audits,
            "visual_table_audits": visual_table_audits,
            "visual_table_discovery": resolve_visual_table_discovery(config),
            "boxed_callout_policy": resolve_boxed_callout_policy(config),
            "boxed_callout_audits": boxed_callout_audits,
            "structure_preview": {
                "visual_tables": [
                    {
                        "id": item.get("id"),
                        "start_page": item.get("start_page"),
                        "end_page": item.get("end_page"),
                        "markdown": item.get("markdown"),
                    }
                    for item in visual_tables
                    if item.get("status") == "converted"
                ],
                "boxed_callouts": [
                    {
                        "id": item.get("id"),
                        "page": item.get("page"),
                        "markdown": item.get("markdown"),
                    }
                    for item in boxed_callouts
                    if item.get("status") == "converted"
                ],
            },
            "tables_count": sum(int(item.get("tables_count", 0)) for item in table_audits) + sum(1 for item in visual_table_audits if item.get("status") == "converted"),
            "rows_transformed": sum(int(item.get("rows_transformed", 0)) for item in table_audits) + sum(int(item.get("rows", 0)) for item in visual_table_audits if item.get("status") == "converted"),
            "definition_tables_count": sum(int(item.get("tables_count", 0)) for item in table_audits),
            "definition_rows_transformed": sum(int(item.get("rows_transformed", 0)) for item in table_audits),
            "visual_tables_count": sum(1 for item in visual_table_audits if item.get("status") == "converted"),
            "visual_rows_transformed": sum(int(item.get("rows", 0)) for item in visual_table_audits if item.get("status") == "converted"),
            "skipped_blocks": [
                {"path": item["relative_path"], **skipped}
                for item in table_audits
                for skipped in item.get("skipped", [])
            ] + [
                {
                    "kind": "visual-table",
                    "id": item.get("id"),
                    "start_page": item.get("start_page"),
                    "end_page": item.get("end_page"),
                    "reason": item.get("reason"),
                }
                for item in visual_table_audits
                if item.get("status") != "converted"
            ] + [
                {
                    "kind": "boxed-callout",
                    "id": item.get("id"),
                    "page": item.get("page"),
                    "reason": item.get("reason"),
                    "detection": item.get("detection"),
                }
                for item in boxed_callout_audits
                if item.get("status") != "converted"
            ],
        }
        return outputs, details
    finally:
        document.close()


def make_backup(
    vault: Path,
    book: str,
    classifications: list[dict[str, Any]],
    timestamp: str,
    config: dict[str, Any] | None = None,
    full: bool = False,
) -> tuple[Path | None, dict[str, Any]]:
    if full:
        backup_root = resource_root(vault, "Backups", book, config)
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_path = backup_root / f"pre-{timestamp}.zip"
        backup_root_resolved = backup_root.resolve()
        entries: list[dict[str, Any]] = []
        with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for target in sorted(vault.rglob("*")):
                resolved_target = target.resolve()
                try:
                    relative_parts = resolved_target.relative_to(vault.resolve()).parts
                except ValueError:
                    relative_parts = ()
                under_backup_tree = any(
                    part.casefold() == "backups"
                    for part in relative_parts[:-1]
                )
                if (
                    not target.is_file()
                    or resolved_target == backup_path.resolve()
                    or resolved_target.is_relative_to(backup_root_resolved)
                    or under_backup_tree
                ):
                    continue
                relative = vault_relative(vault, target)
                archive_name = f"files/{relative}"
                archive.write(target, archive_name)
                entries.append({
                    "relative_path": relative,
                    "archive_path": archive_name,
                    "previous_sha256": sha256_file(target),
                    "after_sha256": None,
                    "kind": "full-backup",
                })
            manifest = {
                "backup_version": 1,
                "generator": GENERATOR,
                "generator_version": VERSION,
                "book": book,
                "created_at": timestamp,
                "scope": "full-book",
                "files": entries,
                "created_paths": [],
                "created_after_sha256": {},
            }
            archive.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return backup_path, manifest

    changed = [item for item in classifications if item["action"] in {"create", "update"}]
    report_root = resource_root(vault, "Reports", book, config)
    for path in (report_root / "latest-manifest.json", report_root / "latest-report.json"):
        if path.exists():
            changed.append({
                "relative_path": vault_relative(vault, path),
                "action": "update",
                "current_sha256": sha256_file(path),
                "kind": "metadata",
            })
    if not changed:
        return None, {"created": [], "restored": []}

    backup_root = resource_root(vault, "Backups", book, config)
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / f"pre-{timestamp}.zip"
    entries: list[dict[str, Any]] = []
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in changed:
            relative = str(item["relative_path"])
            target = vault_path(vault, relative)
            if not target.exists():
                continue
            archive_name = f"files/{relative}"
            archive.write(target, archive_name)
            entries.append({
                "relative_path": relative,
                "archive_path": archive_name,
                "previous_sha256": sha256_file(target),
                "after_sha256": item.get("desired_sha256"),
                "kind": item.get("kind", "metadata"),
            })
        manifest = {
            "backup_version": 1,
            "generator": GENERATOR,
            "generator_version": VERSION,
            "book": book,
            "created_at": timestamp,
            "files": entries,
            "created_paths": [
                item["relative_path"] for item in classifications if item["action"] == "create"
            ],
            "created_after_sha256": {
                item["relative_path"]: item.get("desired_sha256")
                for item in classifications
                if item["action"] == "create"
            },
        }
        archive.writestr("backup-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return backup_path, manifest


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def merge_manifest_files(
    previous: dict[str, Any], current: list[dict[str, Any]], scoped: bool,
    *, include_new: bool = True,
) -> list[dict[str, Any]]:
    """Preserve file records for untouched outputs during a scoped apply.

    Section-only maintenance can keep its records in the dedicated apply
    report without adding them to a legacy chapter manifest.
    """
    if not scoped:
        return current
    current_by_path = {str(item.get("relative_path")): item for item in current}
    merged: list[dict[str, Any]] = []
    for item in previous.get("files", []):
        if not isinstance(item, dict) or not item.get("relative_path"):
            continue
        path = str(item["relative_path"])
        merged.append(current_by_path.pop(path, item))
    if include_new:
        merged.extend(current_by_path.values())
    return merged


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def prepare_context(args: argparse.Namespace) -> dict[str, Any]:
    explicit_vault = getattr(args, "vault", None)
    output_root_arg = getattr(args, "output_root", None)
    explicit_config = getattr(args, "config", None)
    source_arg = getattr(args, "source", None)
    if explicit_config:
        config_candidate = Path(str(explicit_config))
        if not config_candidate.is_absolute():
            config_base = Path(str(explicit_vault)).resolve() if explicit_vault else Path.cwd()
            config_candidate = config_base / config_candidate
        config_path = config_candidate.resolve()
    else:
        config_path = None

    source_hint = Path(str(source_arg)).resolve() if source_arg else None
    if explicit_vault:
        vault = Path(str(explicit_vault)).resolve()
    elif output_root_arg:
        vault = Path(str(output_root_arg)).resolve()
    elif config_path:
        vault = config_path.parent.resolve()
    elif source_hint and getattr(args, "command", "") == "inspect":
        vault = source_hint.parent
    else:
        raise PipelineError(
            "Specify an output root (or legacy vault), or provide --config with output.root."
        )
    if not vault.exists() or not vault.is_dir():
        raise PipelineError(f"Output root does not exist: {vault}")

    if config_path is None and explicit_vault and getattr(args, "book", None):
        config_path = config_path_for(
            Path(str(explicit_vault)).resolve(), str(getattr(args, "book")), None
        )
    raw_config = load_config(config_path) if config_path else {}
    configured_root = (raw_config.get("output") or {}).get("root") or raw_config.get("output_root")
    if output_root_arg:
        vault = Path(str(output_root_arg)).resolve()
    elif not explicit_vault and configured_root:
        vault = resolve_configured_path(config_path.parent if config_path else Path.cwd(), configured_root)
    elif not explicit_vault and config_path and getattr(args, "command", "") != "inspect":
        vault = config_path.parent.resolve()
    if not vault.exists() or not vault.is_dir():
        raise PipelineError(f"Output root does not exist: {vault}")

    source_config = source_arg or raw_config.get("source_pdf")
    book_value = getattr(args, "book", None) or raw_config.get("book_title") or raw_config.get("book")
    if not book_value and source_config:
        book_value = Path(str(source_config)).stem
    if not book_value:
        book_value = vault.name
    book = str(book_value)
    if config_path is None:
        if explicit_vault:
            config_path = config_path_for(vault, book, None)
        else:
            config_path = vault / ".pdf-book-config.yaml"

    portable_mode = bool(output_root_arg or (not explicit_vault and configured_root))
    base_config = default_config(book)
    if portable_mode:
        base_config = deep_merge(base_config, {
            "modules": {
                "chapterize": True,
                "sections": True,
                "attachments": True,
                "code_blocks": True,
                "tables": True,
                "visual_tables": True,
                "moc": True,
                "topic_index": True,
            },
            "output": {
                "root": str(vault),
                "chapter_filename": "Chapter {number:02d} - {title}.md",
                "moc_filename": "00_MOC.md",
                "topic_index_filename": "01_Topic Index.md",
                "default_part": "Chapters",
                "page_links": "headings-and-code",
            },
            "paths": {
                "source_dir": ".conversion/source",
                "attachments": "Assets",
                "reports": ".conversion/reports",
                "backups": ".conversion/backups",
            },
    })
    config = deep_merge(base_config, raw_config)
    config.setdefault("output", {})["root"] = str(vault)
    try:
        resolve_markdown_baseline(config)
        resolve_callout_style(config)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
    source, managed_target, managed = resolve_source(vault, book, config, getattr(args, "source", None))
    source_info = inspect_pdf(source)
    if source_info["likely_scanned"] and not bool((config.get("ocr") or {}).get("enabled", False)):
        source_info["status"] = "ocr-required-before-apply"
    else:
        source_info["status"] = "text-extraction-available"
    return {
        "vault": vault,
        "output_root": vault,
        "book": book,
        "config_path": config_path,
        "config": config,
        "source": source,
        "managed_target": managed_target,
        "managed": managed,
        "portable_mode": portable_mode,
        "source_info": source_info,
    }


def print_or_write_report(value: dict[str, Any], report_out: str | None) -> None:
    if report_out:
        output = Path(report_out).resolve()
        write_json(output, value)
        print(json.dumps({"report": str(output), "mode": value.get("mode")}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(value, ensure_ascii=False, indent=2))


def command_inspect(args: argparse.Namespace) -> int:
    context = prepare_context(args)
    source_info = dict(context["source_info"])
    source_info.update({
        "mode": "inspect",
        "book": context["book"],
        "vault": str(context["vault"]),
        "managed_source": context["managed"],
        "managed_target": str(context["managed_target"]),
        "config_path": str(context["config_path"]),
    })
    print_or_write_report(source_info, getattr(args, "report_out", None))
    return 0


def build_dry_run(args: argparse.Namespace) -> dict[str, Any]:
    context = prepare_context(args)
    if context["source_info"]["likely_scanned"] and not bool((context["config"].get("ocr") or {}).get("enabled", False)):
        raise PipelineError(
            "The PDF appears to be scanned or mostly without a text layer. "
            "Review the inspect result and explicitly enable OCR before continuing."
        )
    if context["source_info"]["text_pages"] == 0:
        raise PipelineError(
            "The PDF has no extractable text. This Skill does not run OCR itself; "
            "supply an OCR-processed PDF and record the explicit OCR decision in the book configuration."
        )
    stages = stages_from_config(context["config"], getattr(args, "stages", None))
    source_for_output = context["source"]
    copy_source = bool(getattr(args, "copy_source", False))
    if not context["managed"] and copy_source:
        source_for_output = context["managed_target"]
    outputs, details = build_outputs(
        context["vault"], context["book"], context["config"], context["source"],
        source_for_output, context["source_info"]["sha256"], stages,
        getattr(args, "only_chapters", None),
        getattr(args, "only_sections", None),
    )
    classifications = classify_outputs(
        context["vault"], outputs,
        previous_manifest(context["vault"], context["book"], context["config"]),
    )
    conflicts = [item for item in classifications if item.get("conflict")]
    if not context["managed"] and not copy_source and not context["portable_mode"]:
        conflicts.append({
            "type": "external-source-not-managed",
            "source": str(context["source"]),
            "required_target": str(context["managed_target"]),
            "resolution": "rerun with --copy-source after authorizing the managed PDF copy",
        })
    summary = {
        "mode": "dry-run",
        "timestamp": utc_stamp(),
        "generator": GENERATOR,
        "generator_version": VERSION,
        "vault": str(context["vault"]),
        "book": context["book"],
        "config_path": str(context["config_path"]),
        "config_sha256": sha256_file(context["config_path"]) if context["config_path"].exists() else None,
        "source": context["source_info"],
        "managed_source": context["managed"],
        "copy_source_requested": copy_source,
        "copy_source_target": str(context["managed_target"]) if not context["managed"] and copy_source else None,
        "book_specific_decisions": context["config"].get("book_specific_decisions", []),
        "stages": stages,
        "outputs": classifications,
        "conflicts": conflicts,
        **details,
    }
    return summary


def command_dry_run(args: argparse.Namespace) -> int:
    summary = build_dry_run(args)
    print_or_write_report(summary, getattr(args, "report_out", None))
    return 3 if summary["conflicts"] else 0


def command_apply(args: argparse.Namespace) -> int:
    if not args.confirm_apply:
        raise PipelineError("apply requires --confirm-apply after the dry-run has been reviewed.")
    context = prepare_context(args)
    if context["source_info"]["likely_scanned"] and not bool((context["config"].get("ocr") or {}).get("enabled", False)):
        raise PipelineError("Refusing apply for a scanned PDF until OCR is explicitly enabled.")
    if context["source_info"]["text_pages"] == 0:
        raise PipelineError(
            "The PDF has no extractable text. This Skill does not run OCR itself; "
            "supply an OCR-processed PDF before apply."
        )
    if not context["managed"] and not args.copy_source and not context["portable_mode"]:
        raise PipelineError(
            "The source PDF is outside File/PDF/<book>. Use --copy-source only after authorizing the managed copy."
        )
    stages = stages_from_config(context["config"], getattr(args, "stages", None))
    source_for_output = (
        context["managed_target"]
        if not context["managed"] and args.copy_source
        else context["source"]
    )
    outputs, details = build_outputs(
        context["vault"], context["book"], context["config"], context["source"],
        source_for_output, context["source_info"]["sha256"], stages,
        getattr(args, "only_chapters", None),
        getattr(args, "only_sections", None),
    )
    adjusted = [adjust_text_line_endings(context["vault"], output) for output in outputs]
    manifest_before = previous_manifest(
        context["vault"], context["book"], context["config"]
    )
    classifications = classify_outputs(context["vault"], adjusted, manifest_before)
    conflicts = [item for item in classifications if item.get("conflict")]
    authorized_conflicts: list[dict[str, Any]] = []
    source_classification: dict[str, Any] | None = None
    if not context["managed"] and args.copy_source:
        source_target = context["managed_target"]
        current_hash = existing_file_hash(source_target)
        source_hash = context["source_info"]["sha256"]
        source_classification = {
            "relative_path": vault_relative(context["vault"], source_target),
            "kind": "source",
            "desired_sha256": source_hash,
            "current_sha256": current_hash,
            "exists": source_target.exists(),
            "action": "unchanged" if current_hash == source_hash else "create" if current_hash is None else "update",
            "conflict": None if current_hash in {None, source_hash} else "managed-source-hash-drift",
        }
        if source_classification["conflict"]:
            conflicts.append(source_classification)
    scope_selection = getattr(args, "only_chapters", None) or getattr(args, "only_sections", None)
    selected_output_kinds = {"chapter"} if getattr(args, "only_chapters", None) else {"section"}
    if conflicts and getattr(args, "allow_generated_drift", False):
        if not scope_selection:
            raise ConflictError(
                "--allow-generated-drift is only valid with --only-chapters or --only-sections "
                "and cannot authorize a full regeneration."
            )
        remaining: list[dict[str, Any]] = []
        selected_paths = {
            output.relative_path for output in adjusted if output.kind in selected_output_kinds
        }
        for item in conflicts:
            target = vault_path(context["vault"], str(item.get("relative_path", "")))
            if (
                item.get("kind") in selected_output_kinds
                and item.get("relative_path") in selected_paths
                and target.exists()
                and has_generator_marker(target.read_bytes())
            ):
                authorized_conflicts.append(item)
                item["conflict"] = None
            else:
                remaining.append(item)
        conflicts = remaining
    if conflicts:
        raise ConflictError(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2))

    timestamp = utc_stamp()
    backup_classifications = list(classifications)
    if source_classification:
        backup_classifications.append(source_classification)
    backup_path, backup_manifest = make_backup(
        context["vault"], context["book"], backup_classifications, timestamp, context["config"],
        full=bool(scope_selection),
    )
    if not context["managed"] and args.copy_source:
        target = context["managed_target"]
        if not target.exists():
            atomic_write(target, context["source"].read_bytes())
        if sha256_file(target) != context["source_info"]["sha256"]:
            raise PipelineError(f"Managed source copy verification failed: {target}")

    file_records: list[dict[str, Any]] = []
    for output, classification in zip(adjusted, classifications):
        target = vault_path(context["vault"], output.relative_path)
        if classification["action"] != "unchanged":
            atomic_write(target, output.content)
        actual_hash = sha256_file(target)
        if actual_hash != sha256_bytes(output.content):
            raise PipelineError(f"Post-write hash verification failed: {target}")
        file_records.append({
            "relative_path": output.relative_path,
            "kind": output.kind,
            "action": classification["action"],
            "before_sha256": classification.get("current_sha256"),
            "after_sha256": actual_hash,
        })
    if source_classification:
        file_records.append({
            "relative_path": source_classification["relative_path"],
            "kind": "source",
            "action": source_classification["action"],
            "before_sha256": source_classification.get("current_sha256"),
            "after_sha256": sha256_file(context["managed_target"]),
        })

    reports = resource_root(context["vault"], "Reports", context["book"], context["config"])
    reports.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 1,
        "generator": GENERATOR,
        "generator_version": VERSION,
        "book": context["book"],
        "applied_at": timestamp,
        "source_sha256": context["source_info"]["sha256"],
        "config_sha256": sha256_file(context["config_path"]) if context["config_path"].exists() else None,
        "book_specific_decisions": context["config"].get("book_specific_decisions", []),
        "files": merge_manifest_files(
            manifest_before,
            file_records,
            bool(scope_selection),
            include_new=getattr(args, "only_sections", None) is None,
        ),
        "scope": details.get("scope"),
    }
    report = {
        "mode": "apply",
        "timestamp": timestamp,
        "generator": GENERATOR,
        "generator_version": VERSION,
        "vault": str(context["vault"]),
        "book": context["book"],
        "config_path": str(context["config_path"]),
        "source": context["source_info"],
        "managed_source": context["managed"] or bool(args.copy_source),
        "managed_source_path": str(context["managed_target"] if not context["managed"] else context["source"]),
        "book_specific_decisions": context["config"].get("book_specific_decisions", []),
        "stages": stages,
        "backup_path": str(backup_path) if backup_path else None,
        "backup_manifest": backup_manifest,
        "authorized_conflicts": authorized_conflicts,
        "files": file_records,
        "outputs_changed": sum(item["action"] != "unchanged" for item in file_records),
        **details,
    }
    report_path = reports / f"apply-{timestamp}.json"
    write_json(report_path, report)
    write_json(reports / "latest-manifest.json", manifest)
    write_json(reports / "latest-report.json", report)
    print(json.dumps({
        "mode": "apply",
        "report": str(report_path),
        "backup": str(backup_path) if backup_path else None,
        "files": len(file_records),
        "changed": report["outputs_changed"],
        "tables": report["tables_count"],
        "rows_transformed": report["rows_transformed"],
    }, ensure_ascii=False, indent=2))
    return 0


def markdown_issues(path: Path, vault: Path) -> list[str]:
    issues: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ["not-utf8"]
    if not text.startswith("---\n") or "\n---\n" not in text:
        issues.append("missing-frontmatter")
    if not has_generator_marker(text.encode("utf-8")):
        issues.append("missing-generator-marker")
    if len(re.findall(r"^\s*```", text, re.MULTILINE)) % 2:
        issues.append("unclosed-code-fence")
    lines = text.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.startswith("|") and lines[index + 1].startswith("|"):
            if not re.match(r"^\|\s*:?-{3,}:?\s*\|", lines[index + 1]):
                continue
            for row in lines[index + 2 :]:
                if not row.strip():
                    break
                if not row.startswith("|") or row.count("|") < 3:
                    issues.append(f"invalid-table-row:{index + 1}")
                    break
    for raw_target in markdown_link_targets(text):
        target = raw_target.strip().split("#", 1)[0]
        if not target or re.match(r"^(?:https?|mailto):", target, re.IGNORECASE):
            continue
        candidate = (path.parent / target).resolve()
        if not candidate.exists():
            candidate = (vault / target.lstrip("/"))
        if not candidate.exists():
            issues.append(f"broken-markdown-link:{target}")
    def local_exists(target: str) -> bool:
        candidates = [
            (path.parent / target).resolve(),
            (vault / target.lstrip("/\\")).resolve(),
        ]
        if "." not in Path(target).name:
            candidates.extend([candidate.with_suffix(".md") for candidate in list(candidates)])
        return any(candidate.exists() and candidate.is_file() for candidate in candidates)

    for match in re.finditer(r"!\[\[([^|\]#]+)(?:#[^|\]]+)?(?:\|[^\]]+)?\]\]", text):
        target = match.group(1).strip()
        if not local_exists(target):
            issues.append(f"missing-attachment:{target}")
    for match in re.finditer(r"(?<!\!)\[\[([^|\]#]+)(?:#[^|\]]+)?(?:\|[^\]]+)?\]\]", text):
        target = match.group(1).strip()
        if not local_exists(target):
            issues.append(f"broken-wikilink:{target}")
    return issues


def markdown_link_targets(text: str) -> Iterable[str]:
    """Yield Markdown link destinations while allowing parentheses in paths."""
    cursor = 0
    while True:
        opener = text.find("](", cursor)
        if opener < 0:
            return
        target_start = opener + 2
        depth = 1
        index = target_start
        while index < len(text):
            if text[index] == "\\":
                index += 2
                continue
            if text[index] == "(":
                depth += 1
            elif text[index] == ")":
                depth -= 1
                if depth == 0:
                    yield text[target_start:index]
                    cursor = index + 1
                    break
            index += 1
        else:
            return


def command_audit(args: argparse.Namespace) -> int:
    context = prepare_context(args)
    reports = resource_root(context["vault"], "Reports", context["book"], context["config"])
    manifest_path = reports / "latest-manifest.json"
    issues: list[dict[str, Any]] = []
    manifest = previous_manifest(context["vault"], context["book"], context["config"])
    if not manifest:
        issues.append({"type": "missing-manifest", "path": str(manifest_path)})
    else:
        if manifest.get("source_sha256") != context["source_info"]["sha256"]:
            issues.append({"type": "source-hash-drift", "expected": manifest.get("source_sha256"), "actual": context["source_info"]["sha256"]})
        for item in manifest.get("files", []):
            if not isinstance(item, dict):
                continue
            relative = str(item.get("relative_path", ""))
            target = vault_path(context["vault"], relative)
            if not target.exists():
                issues.append({"type": "missing-generated-file", "path": relative})
                continue
            actual = sha256_file(target)
            if actual != item.get("after_sha256"):
                issues.append({"type": "generated-file-hash-drift", "path": relative, "expected": item.get("after_sha256"), "actual": actual})
            if target.suffix.lower() == ".md":
                for issue in markdown_issues(target, context["vault"]):
                    issues.append({"type": issue.split(":", 1)[0], "path": relative, "detail": issue})
    result = {
        "mode": "audit",
        "timestamp": utc_stamp(),
        "generator": GENERATOR,
        "generator_version": VERSION,
        "vault": str(context["vault"]),
        "book": context["book"],
        "source": context["source_info"],
        "manifest": str(manifest_path),
        "issues": issues,
        "ok": not issues,
    }
    print_or_write_report(result, getattr(args, "report_out", None))
    return 0 if not issues else 4


def read_backup_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        value = json.loads(archive.read("backup-manifest.json").decode("utf-8"))
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError("Invalid rollback archive: missing backup-manifest.json") from exc
    if not isinstance(value, dict) or value.get("generator") != GENERATOR:
        raise PipelineError("Rollback archive was not created by this Skill.")
    return value


def command_rollback(args: argparse.Namespace) -> int:
    if not args.confirm_rollback:
        raise PipelineError("rollback requires --confirm-rollback after reviewing the target archive.")
    root_arg = getattr(args, "vault", None) or getattr(args, "output_root", None)
    if not root_arg:
        raise PipelineError("rollback requires a legacy vault or --output-root.")
    vault = Path(str(root_arg)).resolve()
    book = str(getattr(args, "book", None) or vault.name)
    backup_path = Path(args.backup).resolve()
    if not backup_path.exists() or backup_path.suffix.lower() != ".zip":
        raise PipelineError(f"Rollback ZIP does not exist: {backup_path}")
    with zipfile.ZipFile(backup_path, "r") as archive:
        backup = read_backup_manifest(archive)
        if backup.get("book") != book:
            raise PipelineError(f"Backup belongs to {backup.get('book')!r}, not {book!r}.")
        conflicts: list[str] = []
        for item in backup.get("files", []):
            relative = str(item.get("relative_path", ""))
            target = vault_path(vault, relative)
            expected_after = item.get("after_sha256")
            if target.exists() and expected_after and sha256_file(target) != expected_after:
                conflicts.append(relative)
        for relative in backup.get("created_paths", []):
            target = vault_path(vault, str(relative))
            expected_after = (backup.get("created_after_sha256") or {}).get(str(relative))
            if target.exists() and expected_after and sha256_file(target) != expected_after:
                conflicts.append(str(relative))
        if conflicts:
            raise ConflictError(json.dumps({"rollback_conflicts": conflicts}, ensure_ascii=False, indent=2))

        for relative in backup.get("created_paths", []):
            target = vault_path(vault, str(relative))
            if target.exists():
                target.unlink()
        restored: list[str] = []
        for item in backup.get("files", []):
            relative = str(item.get("relative_path", ""))
            archive_name = str(item.get("archive_path", ""))
            target = vault_path(vault, relative)
            if archive_name not in archive.namelist():
                continue
            atomic_write(target, archive.read(archive_name))
            if sha256_file(target) != item.get("previous_sha256"):
                raise PipelineError(f"Rollback hash verification failed: {target}")
            restored.append(relative)
    print(json.dumps({
        "mode": "rollback",
        "timestamp": utc_stamp(),
        "book": book,
        "backup": str(backup_path),
        "deleted_created_files": backup.get("created_paths", []),
        "restored_files": restored,
    }, ensure_ascii=False, indent=2))
    return 0


def add_common(parser: argparse.ArgumentParser, *, source: bool = True) -> None:
    parser.add_argument(
        "vault",
        nargs="?",
        help="Legacy Obsidian vault root; omit when using --output-root.",
    )
    parser.add_argument("--book", help="Book display name; defaults to the PDF name")
    parser.add_argument("--output-root", help="Markdown output root for non-Obsidian conversions")
    if source:
        parser.add_argument("--source", help="PDF path; may be outside the output root")
        parser.add_argument("--config", help="Optional book-config.yaml path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=f"{GENERATOR} {VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)

    inspect_parser = commands.add_parser("inspect", help="Inspect PDF text-layer quality and metadata")
    add_common(inspect_parser)
    inspect_parser.add_argument("--report-out")
    inspect_parser.set_defaults(handler=command_inspect)

    dry_parser = commands.add_parser("dry-run", help="Plan changes without writing the vault")
    add_common(dry_parser)
    dry_parser.add_argument("--stages", help="Comma-separated conversion stages")
    dry_parser.add_argument("--only-chapters", help="Comma-separated chapter numbers to preview")
    dry_parser.add_argument("--only-sections", help="Comma-separated section ids to preview")
    dry_parser.add_argument("--copy-source", action="store_true", help="Plan copying an external source into the configured source directory")
    dry_parser.add_argument("--report-out")
    dry_parser.set_defaults(handler=command_dry_run)

    apply_parser = commands.add_parser("apply", help="Apply an authorized dry-run")
    add_common(apply_parser)
    apply_parser.add_argument("--stages", help="Comma-separated conversion stages")
    apply_parser.add_argument("--only-chapters", help="Comma-separated chapter numbers to regenerate")
    apply_parser.add_argument("--only-sections", help="Comma-separated section ids to regenerate")
    apply_parser.add_argument("--copy-source", action="store_true", help="Copy an external PDF into the configured source directory before writing")
    apply_parser.add_argument("--confirm-apply", action="store_true", help="Required explicit write confirmation")
    apply_parser.add_argument(
        "--allow-generated-drift",
        action="store_true",
        help="Authorize replacing selected generated chapter or section files whose prior hash drifted",
    )
    apply_parser.set_defaults(handler=command_apply)

    audit_parser = commands.add_parser("audit", help="Audit the latest applied manifest")
    add_common(audit_parser)
    audit_parser.add_argument("--report-out")
    audit_parser.set_defaults(handler=command_audit)

    rollback_parser = commands.add_parser("rollback", help="Restore one verified ZIP backup")
    add_common(rollback_parser, source=False)
    rollback_parser.add_argument("--backup", required=True, help="Rollback ZIP path")
    rollback_parser.add_argument("--confirm-rollback", action="store_true", help="Required explicit rollback confirmation")
    rollback_parser.set_defaults(handler=command_rollback)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except ConflictError as exc:
        print(f"CONFLICT: {exc}", file=sys.stderr)
        return 3
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
