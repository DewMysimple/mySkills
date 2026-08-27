#!/usr/bin/env python3
"""Safe, configurable PDF-book to Obsidian pipeline.

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


GENERATOR = "pdf-book-to-obsidian"
VERSION = "0.1.0"
RESOURCE_DIRS = ("PDF", "Config", "Reports", "Backups", "Attachment")
DEFAULT_CHAPTER_PATTERN = re.compile(
    r"^chapter\s+(?P<number>[0-9]+|[ivxlcdm]+)\s*[:.\-–—]?\s*(?P<title>.+)$",
    re.IGNORECASE,
)


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
    text = text.replace("\u00ad", "").replace("\xa0", " ").replace("\ufffd", "")
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
            "attachments": False,
            "tables": False,
            "lens": False,
            "moc": False,
        },
        "output": {
            "chapter_filename": "Chapter {number} - {title}.md",
            "moc_filename": "MOC - {book}.md",
            "default_part": "00_Book",
        },
        "table_transform": {"enabled": False, "min_rows": 2},
        "lens": {"enabled": False},
        "ocr": {"enabled": False},
        "chapters": [],
        "parts": [],
        "book": book,
    }


def config_path_for(vault: Path, book: str, explicit: str | None) -> Path:
    if explicit:
        raw = Path(explicit)
        return raw if raw.is_absolute() else vault_path(vault, raw)
    return vault / "File" / "Config" / safe_component(book) / "book-config.yaml"


def resource_root(vault: Path, resource: str, book: str) -> Path:
    return vault / "File" / resource / safe_component(book)


def resolve_source(
    vault: Path,
    book: str,
    config: dict[str, Any],
    cli_source: str | None,
) -> tuple[Path, Path, bool]:
    source_config = cli_source or config.get("source_pdf")
    managed_dir = resource_root(vault, "PDF", book)
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
        title = str(row[1]).strip()
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
        return [Chapter("1", str(config.get("book") or "Book"), "", 1, page_count)]

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


def format_output_name(pattern: str, book: str, chapter: Chapter) -> str:
    values = {"number": chapter.number, "title": chapter.title, "book": book}
    rendered = pattern
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    rendered = re.sub(r"\{number(?::[^}]+)?\}", chapter.number, rendered)
    return safe_component(rendered)


def relative_link(from_file: Path, target: Path, vault: Path) -> str:
    relative = os.path.relpath(target, start=from_file.parent)
    return Path(relative).as_posix()


def extract_images(document: Any, chapters: Iterable[Chapter], attachment_root: Path, book: str) -> tuple[dict[int, list[tuple[str, bytes]]], list[dict[str, Any]]]:
    by_page: dict[int, list[tuple[str, bytes]]] = {}
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
                relative = as_posix(Path("File") / "Attachment" / safe_component(book) / filename)
                by_page.setdefault(page_number, []).append((relative, data))
                records.append({
                    "relative_path": relative,
                    "page": page_number,
                    "xref": xref,
                    "bytes": len(data),
                    "sha256": sha256_bytes(data),
                })
    return by_page, records


def styled_span_text(span: dict[str, Any]) -> str:
    text = normalise_text(str(span.get("text") or ""))
    if not text:
        return ""
    font = str(span.get("font") or "").lower()
    flags = int(span.get("flags") or 0)
    is_bold = bool(flags & 16) or "bold" in font
    is_italic = bool(flags & 2) or "italic" in font or "oblique" in font
    if is_bold:
        return f"**{text}**"
    if is_italic:
        return f"*{text}*"
    return text


def page_markdown_from_spans(page: Any, chapter_title: str = "") -> str:
    """Restore only reliable PDF styling needed for Markdown structure.

    PDF text extraction commonly loses bold labels and bullet glyphs. Font
    flags are stable enough to restore those two structures without guessing
    headings, prose, or semantic emphasis.
    """
    blocks = page.get_text("dict", sort=True).get("blocks", [])
    block_entries: list[dict[str, Any]] = []
    for block_index, block in enumerate(blocks):
        lines = block.get("lines", []) if isinstance(block, dict) else []
        if not lines:
            continue
        first_bbox = lines[0].get("bbox") or (0, 0, 0, 0)
        raw_parts: list[str] = []
        formatted_lines: list[str] = []
        previous_soft_hyphen = False
        for line in lines:
            spans = line.get("spans", [])
            raw_line = "".join(str(span.get("text") or "") for span in spans)
            formatted_line = "".join(styled_span_text(span) for span in spans)
            formatted_line = normalise_text(formatted_line)
            if not formatted_line:
                continue
            formatted_lines.append(formatted_line)
            raw_parts.append(raw_line)
            previous_soft_hyphen = raw_line.endswith("\u00ad")
        if not formatted_lines:
            continue
        raw_text = "".join(raw_parts)
        if any(re.match(r"\s*-\s+\*\*", line) for line in formatted_lines):
            block_text = "\n".join(formatted_lines)
        else:
            joined: list[str] = []
            previous_soft_hyphen = False
            for line_index, formatted_line in enumerate(formatted_lines):
                if line_index:
                    joined.append("" if previous_soft_hyphen else " ")
                joined.append(formatted_line)
                previous_soft_hyphen = raw_parts[line_index].endswith("\u00ad")
            block_text = "".join(joined)
        bullet_prefix = re.match(r"^(?:\s*[●•▪‣◦])+\s*", raw_text)
        is_bullet_only = bool(raw_text.strip()) and all(
            token in {"●", "•", "▪", "‣", "◦"}
            for token in raw_text.strip()
        )
        has_bullet_prefix = bool(bullet_prefix)
        if has_bullet_prefix:
            block_text = re.sub(r"^(?:\s*[●•▪‣◦])+\s*", "", block_text)
        block_entries.append({
            "y": float(first_bbox[1]),
            "x": float(first_bbox[0]),
            "index": block_index,
            "text": block_text,
            "raw_text": raw_text,
            "is_bullet_only": is_bullet_only,
            "has_bullet_prefix": has_bullet_prefix,
        })
    block_entries.sort(key=lambda item: (item["y"], item["x"], item["index"]))

    bullet_ys = [float(entry["y"]) for entry in block_entries if entry["is_bullet_only"]]
    rendered: list[str] = []
    page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
    for entry in block_entries:
        if entry["is_bullet_only"]:
            continue
        line_text = str(entry["text"])
        plain_line = re.sub(r"[*_`]", "", line_text).strip()
        near_page_edge = page_height and (
            entry["y"] <= page_height * 0.2 or entry["y"] >= page_height * 0.8
        )
        if plain_line.isdigit() and near_page_edge:
            continue
        has_list_content = "- " in line_text or "**" in line_text
        if (
            chapter_title
            and plain_line.lower().startswith("chapter ")
            and chapter_title.lower() in plain_line.lower()
            and not has_list_content
        ):
            continue
        if entry["has_bullet_prefix"] or any(abs(float(entry["y"]) - bullet_y) <= 3.0 for bullet_y in bullet_ys):
            line_text = "- " + line_text
        rendered.append(line_text)
    return normalise_text("\n\n".join(rendered))


def render_chapter(
    document: Any,
    chapter: Chapter,
    book: str,
    source_path: Path,
    source_hash: str,
    vault: Path,
    output_path: Path,
    config: dict[str, Any],
    images_by_page: dict[int, list[tuple[str, bytes]]],
) -> str:
    source_rel = vault_relative(vault, source_path) if source_path.is_relative_to(vault.resolve()) else str(source_path)
    fields = {
        "kind": "chapter",
        "book": book,
        "title": chapter.title,
        "source_pdf": source_rel,
        "source_sha256": source_hash,
        "source_pages": [chapter.start_page, chapter.end_page],
        "generated_by": GENERATOR,
        "generator_version": VERSION,
    }
    lines = [emit_frontmatter(fields).rstrip("\n"), f"# {chapter.title}", ""]
    page_link_mode = str((config.get("output") or {}).get("page_links") or "chapter")
    if page_link_mode not in {"chapter", "every-page", "none"}:
        raise PipelineError("output.page_links must be chapter, every-page, or none")
    if page_link_mode == "chapter":
        lines.append(
            f"> [Source PDF, p. {chapter.start_page}]({relative_link(output_path, source_path, vault)}#page={chapter.start_page})"
        )
        lines.append("")
    for page_number in range(chapter.start_page, chapter.end_page + 1):
        page = document[page_number - 1]
        text = page_markdown_from_spans(page, chapter.title)
        text = apply_line_filters(text, config)
        if page_link_mode == "every-page":
            lines.append(f"> [Source PDF, p. {page_number}]({relative_link(output_path, source_path, vault)}#page={page_number})")
        if text:
            lines.extend(["", text])
        for relative, _ in images_by_page.get(page_number, []):
            lines.extend(["", f"![[{relative}]]"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


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


def make_moc(book: str, chapters: list[tuple[Chapter, Path]], lens_outputs: list[OutputFile], config: dict[str, Any]) -> OutputFile:
    output_config = config.get("output") or {}
    pattern = str(output_config.get("moc_filename") or "MOC - {book}.md")
    relative = format_output_name(pattern, book, Chapter("", "", "", 1, 1))
    relative = relative.replace("{book}", safe_component(book))
    lines = [
        emit_frontmatter({
            "kind": "moc",
            "book": book,
            "generated_by": GENERATOR,
            "generator_version": VERSION,
        }).rstrip("\n"),
        f"# {book}",
        "",
        "## Chapters",
        "",
    ]
    for chapter, path in chapters:
        lines.append(f"- [[{as_posix(path.with_suffix(''))}|{chapter.title}]]")
    if lens_outputs:
        lines.extend(["", "## Lenses", ""])
        for output in lens_outputs:
            path = Path(output.relative_path).with_suffix("")
            lines.append(f"- [[{as_posix(path)}]]")
    return OutputFile(relative, ("\n".join(lines).rstrip() + "\n").encode("utf-8"), "moc")


def stages_from_config(config: dict[str, Any], requested: str | None) -> list[str]:
    valid = ("chapterize", "attachments", "tables", "lens", "moc")
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


def previous_manifest(vault: Path, book: str) -> dict[str, Any]:
    path = resource_root(vault, "Reports", book) / "latest-manifest.json"
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
        text = data[:4096].decode("utf-8")
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
) -> tuple[list[OutputFile], dict[str, Any]]:
    pdf = require_pdf_runtime()
    document = pdf.open(str(source))
    try:
        chapters = resolve_chapters(document, config)
        attachment_root = resource_root(vault, "Attachment", book)
        images_by_page: dict[int, list[tuple[str, bytes]]] = {}
        image_records: list[dict[str, Any]] = []
        if "attachments" in stages:
            images_by_page, image_records = extract_images(document, chapters, attachment_root, book)

        output_config = config.get("output") or {}
        chapter_pattern = str(output_config.get("chapter_filename") or "Chapter {number} - {title}.md")
        chapter_outputs: list[tuple[Chapter, Path, str]] = []
        outputs: list[OutputFile] = []
        table_audits: list[dict[str, Any]] = []
        for chapter in chapters:
            part_folder = safe_component(chapter.part or "00_Book")
            filename = format_output_name(chapter_pattern, book, chapter)
            relative = Path(part_folder) / filename
            chapter_path = vault / relative
            content = render_chapter(
                document, chapter, book, source_for_output, source_hash, vault, chapter_path, config, images_by_page
            )
            if "tables" in stages:
                table_config = config.get("table_transform") or {}
                min_rows = int(table_config.get("min_rows", 2))
                content, table_audit = transform_definition_lists(content, min_rows=min_rows)
                table_audits.append({"relative_path": as_posix(relative), **table_audit})
            output = OutputFile(as_posix(relative), content.encode("utf-8"), "chapter")
            outputs.append(output)
            chapter_outputs.append((chapter, relative, content))

        lens_outputs: list[OutputFile] = []
        if "lens" in stages:
            lens_outputs = extract_lens_outputs(chapter_outputs, config, vault, book, source_hash)
            outputs.extend(lens_outputs)

        if "attachments" in stages:
            for record in image_records:
                match = next(
                    (data for relative, values in images_by_page.items() for item_relative, data in values if item_relative == record["relative_path"]),
                    None,
                )
                if match is not None:
                    outputs.append(OutputFile(record["relative_path"], match, "attachment"))

        if "moc" in stages:
            chapter_paths = [(chapter, relative) for chapter, relative, _ in chapter_outputs]
            outputs.append(make_moc(book, chapter_paths, lens_outputs, config))

        details = {
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
            "images": image_records,
            "table_audits": table_audits,
            "tables_count": sum(int(item.get("tables_count", 0)) for item in table_audits),
            "rows_transformed": sum(int(item.get("rows_transformed", 0)) for item in table_audits),
            "skipped_blocks": [
                {"path": item["relative_path"], **skipped}
                for item in table_audits
                for skipped in item.get("skipped", [])
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
) -> tuple[Path | None, dict[str, Any]]:
    changed = [item for item in classifications if item["action"] in {"create", "update"}]
    report_root = resource_root(vault, "Reports", book)
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

    backup_root = resource_root(vault, "Backups", book)
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


def write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def prepare_context(args: argparse.Namespace) -> dict[str, Any]:
    vault = Path(args.vault).resolve()
    if not vault.exists() or not vault.is_dir():
        raise PipelineError(f"Vault directory does not exist: {vault}")
    book = str(args.book)
    config_path = config_path_for(vault, book, getattr(args, "config", None))
    raw_config = load_config(config_path)
    config = deep_merge(default_config(book), raw_config)
    source, managed_target, managed = resolve_source(vault, book, config, getattr(args, "source", None))
    source_info = inspect_pdf(source)
    if source_info["likely_scanned"] and not bool((config.get("ocr") or {}).get("enabled", False)):
        source_info["status"] = "ocr-required-before-apply"
    else:
        source_info["status"] = "text-extraction-available"
    return {
        "vault": vault,
        "book": book,
        "config_path": config_path,
        "config": config,
        "source": source,
        "managed_target": managed_target,
        "managed": managed,
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
    if not context["managed"]:
        source_for_output = context["managed_target"]
    outputs, details = build_outputs(
        context["vault"], context["book"], context["config"], context["source"],
        source_for_output, context["source_info"]["sha256"], stages,
    )
    classifications = classify_outputs(context["vault"], outputs, previous_manifest(context["vault"], context["book"]))
    conflicts = [item for item in classifications if item.get("conflict")]
    if not context["managed"] and not copy_source:
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
    if not context["managed"] and not args.copy_source:
        raise PipelineError(
            "The source PDF is outside File/PDF/<book>. Use --copy-source only after authorizing the managed copy."
        )
    stages = stages_from_config(context["config"], getattr(args, "stages", None))
    source_for_output = context["managed_target"] if not context["managed"] else context["source"]
    outputs, details = build_outputs(
        context["vault"], context["book"], context["config"], context["source"],
        source_for_output, context["source_info"]["sha256"], stages,
    )
    adjusted = [adjust_text_line_endings(context["vault"], output) for output in outputs]
    manifest_before = previous_manifest(context["vault"], context["book"])
    classifications = classify_outputs(context["vault"], adjusted, manifest_before)
    conflicts = [item for item in classifications if item.get("conflict")]
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
    if conflicts:
        raise ConflictError(json.dumps({"conflicts": conflicts}, ensure_ascii=False, indent=2))

    timestamp = utc_stamp()
    backup_classifications = list(classifications)
    if source_classification:
        backup_classifications.append(source_classification)
    backup_path, backup_manifest = make_backup(context["vault"], context["book"], backup_classifications, timestamp)
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

    reports = resource_root(context["vault"], "Reports", context["book"])
    reports.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 1,
        "generator": GENERATOR,
        "generator_version": VERSION,
        "book": context["book"],
        "applied_at": timestamp,
        "source_sha256": context["source_info"]["sha256"],
        "config_sha256": sha256_file(context["config_path"]) if context["config_path"].exists() else None,
        "files": file_records,
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
        "stages": stages,
        "backup_path": str(backup_path) if backup_path else None,
        "backup_manifest": backup_manifest,
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
    for match in re.finditer(r"\[[^]]*\]\(([^)]+)\)", text):
        target = match.group(1).strip().split("#", 1)[0]
        if not target or re.match(r"^(?:https?|mailto):", target, re.IGNORECASE):
            continue
        candidate = (path.parent / target).resolve()
        if not candidate.exists():
            candidate = (vault / target.lstrip("/"))
        if not candidate.exists():
            issues.append(f"broken-markdown-link:{target}")
    for match in re.finditer(r"!\?\[\[([^]|#]+)", text):
        target = match.group(1).strip()
        candidate = vault / target
        if not candidate.exists():
            issues.append(f"missing-attachment:{target}")
    return issues


def command_audit(args: argparse.Namespace) -> int:
    context = prepare_context(args)
    reports = resource_root(context["vault"], "Reports", context["book"])
    manifest_path = reports / "latest-manifest.json"
    issues: list[dict[str, Any]] = []
    manifest = previous_manifest(context["vault"], context["book"])
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
    vault = Path(args.vault).resolve()
    book = str(args.book)
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
    parser.add_argument("vault", help="Obsidian vault root")
    parser.add_argument("--book", required=True, help="Book folder/display name")
    if source:
        parser.add_argument("--source", help="Optional PDF path; managed PDFs live under File/PDF/<book>")
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
    dry_parser.add_argument("--stages", help="Comma-separated stages: chapterize,attachments,tables,lens,moc")
    dry_parser.add_argument("--copy-source", action="store_true", help="Plan copying an external source into File/PDF")
    dry_parser.add_argument("--report-out")
    dry_parser.set_defaults(handler=command_dry_run)

    apply_parser = commands.add_parser("apply", help="Apply an authorized dry-run")
    add_common(apply_parser)
    apply_parser.add_argument("--stages", help="Comma-separated stages: chapterize,attachments,tables,lens,moc")
    apply_parser.add_argument("--copy-source", action="store_true", help="Copy an external PDF into File/PDF before writing")
    apply_parser.add_argument("--confirm-apply", action="store_true", help="Required explicit write confirmation")
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
