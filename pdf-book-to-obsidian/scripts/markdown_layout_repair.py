#!/usr/bin/env python3
"""Conservative repair of Markdown layout artifacts from PDF extraction.

The helper is intentionally separate from PDF generation.  It repairs an
existing Markdown knowledge base while preserving source wording and keeping
ambiguous structures unchanged for an agent/user review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

try:
    from markdown_obsidian import convert_callouts_text
except ImportError:  # pragma: no cover - permits importing as a package.
    from .markdown_obsidian import convert_callouts_text  # type: ignore


SOURCE_RE = re.compile(
    r"^\s*>\s*\[Source PDF, p\.\s*(?P<page>\d+)\]\((?P<url>.+)\)\s*$"
)
IMAGE_RE = re.compile(r"^\s*!\[\[(?P<target>[^\]]+)\]\]\s*$")
FIGURE_RE = re.compile(r"^\s*>?\s*(?P<label>Figure\s+\d+(?:\.\d+)?)\s*[–-]\s*(?P<title>.+?)\s*$")
HEADING_RE = re.compile(r"^(?P<level>#{1,6})(?P<space>\s+)(?P<title>.*?)\s*$")
ORDERED_RE = re.compile(r"^(?P<indent>\s*)(?P<number>\d+)[.)](?P<gap>\s+)(?P<body>.+?)\s*$")
UNORDERED_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-+*])(?P<gap>[ \t]+)(?P<body>\S.*?)\s*$")


@dataclass
class Change:
    kind: str
    line: int
    before: str
    after: str
    confidence: str = "high"


@dataclass
class FileRepair:
    relative_path: str
    original_sha256: str
    repaired_sha256: str
    changed: bool
    changes: list[Change] = field(default_factory=list)
    uncertain: list[dict[str, object]] = field(default_factory=list)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_content_markdown(path: Path, root: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    relative = path.relative_to(root)
    parts = {part.lower() for part in relative.parts}
    if parts.intersection({".obsidian", ".claudian", ".trash"}):
        return False
    if relative.parts and relative.parts[0].lower() == "file":
        return False
    return True


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.md") if is_content_markdown(path, root)
    )


def split_frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"\A(---\r?\n.*?\r?\n---(?:\r?\n|\Z))", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def normalise_line_endings(text: str, newline: str) -> str:
    if newline == "\r\n":
        return text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text.replace("\r\n", "\n")


def detected_newline(raw: bytes) -> str:
    return "\r\n" if b"\r\n" in raw else "\n"


def strip_heading_markup(title: str) -> str:
    """Remove emphasis syntax from headings, where it is only noise here."""
    cleaned = title.replace("\x08", "")
    cleaned = re.sub(r"\*+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def clean_heading_suffix(title: str, *, toc_file: bool) -> str:
    """Remove one unmistakable extracted page suffix from non-TOC headings."""
    if toc_file:
        return title
    # A control character followed by split emphasis and a short page number
    # is the characteristic artifact in this book's chapter headings.
    cleaned = re.sub(
        r"\s*\x08\s*(?:\*+\s*){1,3}\d{1,4}\s*\**\s*$",
        "",
        title,
    )
    return cleaned.strip()


def repair_heading(line: str, *, toc_file: bool) -> tuple[str, bool]:
    match = HEADING_RE.match(line)
    if not match:
        return line, False
    title = clean_heading_suffix(match.group("title"), toc_file=toc_file)
    title = strip_heading_markup(title)
    repaired = f"{match.group('level')} {title}" if title else match.group("level")
    return repaired, repaired != line.rstrip("\r\n")


def repair_broken_emphasis(line: str) -> tuple[str, bool]:
    """Repair only empty emphasis spans caused by split PDF font spans."""
    if line.lstrip().startswith("```"):
        return line, False
    repaired = line
    # The PDF text layer can carry a backspace control character at a span
    # boundary.  It has no readable meaning in Markdown and is safe to drop.
    repaired = repaired.replace("\x08", " ")
    # A list item can begin with a duplicated opening marker:
    # '- ** ****text**' -> '- **text**'.  Handle this before the generic rule.
    repaired = re.sub(r"^(\s*[-*+]\s+)\*\*\s+\*\*\*\*(?=\S)", r"\1**", repaired)
    # The PDF extractor emits '** **' between adjacent spans.  Only join it
    # when the preceding span ends in whitespace or a hyphen; this avoids
    # collapsing intentional adjacent emphasis such as '**Operator** **Name**'.
    repaired = re.sub(r"\*\*([^\r\n]*?(?:\s|-))\*\*\s+\*\*", r"**\1", repaired)
    # Empty emphasis spans between ordinary text blocks, e.g. 'C++ ** **scripting'.
    repaired = re.sub(r"(?<=\s)\*\*\s+\*\*", " ", repaired)
    # A closing marker can be separated from the last word of a span.  Track
    # whether the marker is closing so that '**Operator** **Name**' is left
    # alone while '**Desktop with C++ **group' is repaired.
    repaired = repair_trailing_bold_space(repaired)
    return repaired, repaired != line


def repair_trailing_bold_space(line: str) -> str:
    marker_re = re.compile(r"(?<!\*)\*\*(?!\*)")
    inside = False
    replacements: list[tuple[int, int, str]] = []
    for match in marker_re.finditer(line):
        position = match.start()
        if inside and position > 0 and line[position - 1].isspace():
            after = position + 2
            if after < len(line) and not line[after].isspace():
                start = position - 1
                while start > 0 and line[start - 1] == " ":
                    start -= 1
                replacements.append((start, after, "** "))
        inside = not inside
    if not replacements:
        return line
    output: list[str] = []
    cursor = 0
    for start, end, replacement in replacements:
        output.append(line[cursor:start])
        output.append(replacement)
        cursor = end
    output.append(line[cursor:])
    return "".join(output)


def is_source_line(line: str) -> re.Match[str] | None:
    return SOURCE_RE.match(line)


def is_image_line(line: str) -> re.Match[str] | None:
    return IMAGE_RE.match(line)


def is_figure_line(line: str) -> re.Match[str] | None:
    return FIGURE_RE.match(line)


def repair_figure_caption_prefix(line: str) -> tuple[str, bool]:
    """Remove an accidental blockquote marker from a Figure caption."""
    match = re.match(r"^(?P<indent>\s*)>\s*(?P<caption>Figure\s+\d+(?:\.\d+)?\s*[–-]\s*.+?)\s*$", line)
    if not match:
        return line, False
    return f"{match.group('indent')}{match.group('caption').rstrip()}", True


def nonblank_before(lines: list[str], index: int, distance: int = 3) -> int | None:
    found = 0
    for position in range(index - 1, max(-1, index - distance - 1), -1):
        if lines[position].strip():
            found += 1
            return position
    return None


def nonblank_after(lines: list[str], index: int, distance: int = 3) -> int | None:
    for position in range(index + 1, min(len(lines), index + distance + 1)):
        if lines[position].strip():
            return position
    return None


def append_source_to_caption(caption: str, page: str, url: str) -> str:
    if "[Source PDF, p." in caption:
        return caption
    return f"{caption.rstrip()} ([Source PDF, p. {page}]({url}))"


def repair_figure_sources(
    lines: list[str],
    changes: list[Change],
    uncertain: list[dict[str, object]],
) -> list[str]:
    """Move only locally unambiguous image source links to figure captions."""
    records: list[dict[str, object]] = []
    for image_index, image_line in enumerate(lines):
        if not is_image_line(image_line):
            continue

        caption_index: int | None = None
        after = nonblank_after(lines, image_index, distance=3)
        if after is not None and is_figure_line(lines[after]):
            caption_index = after

        source_index: int | None = None
        for candidate in (
            nonblank_before(lines, image_index, distance=4),
            nonblank_after(lines, image_index, distance=4),
        ):
            if candidate is not None and is_source_line(lines[candidate]):
                source_index = candidate
                break

        # A source line can sit between a caption and its image.  Accept that
        # shape only when the caption is the immediately preceding nonblank
        # block, avoiding guesses across ordinary prose.
        if caption_index is None and source_index is not None:
            before_source = nonblank_before(lines, source_index, distance=3)
            if before_source is not None and is_figure_line(lines[before_source]):
                caption_index = before_source

        if caption_index is None or source_index is None:
            if source_index is not None:
                uncertain.append(
                    {
                        "kind": "figure-source",
                        "line": image_index + 1,
                        "reason": "a nearby PDF source link has no unambiguous Figure caption",
                    }
                )
            continue
        source_match = is_source_line(lines[source_index])
        caption_match = is_figure_line(lines[caption_index])
        if not source_match or not caption_match:
            continue

        records.append(
            {
                "image_index": image_index,
                "caption_index": caption_index,
                "source_index": source_index,
                "page": source_match.group("page"),
                "url": source_match.group("url"),
            }
        )

    source_markers: set[str] = set()
    for ordinal, record in enumerate(records):
        caption_index = int(record["caption_index"])
        source_index = int(record["source_index"])
        marker = f"\x00PDF_BOOK_REPAIR_SOURCE_{ordinal}\x00"
        source_markers.add(marker)
        source_line = lines[source_index]
        lines[source_index] = marker + ("\r\n" if source_line.endswith("\r\n") else "\n" if source_line.endswith("\n") else "")
        old_caption = lines[caption_index]
        caption_match = is_figure_line(old_caption)
        if caption_match:
            old_caption = old_caption.lstrip()
        new_caption = append_source_to_caption(
            old_caption.rstrip("\r\n"), str(record["page"]), str(record["url"])
        )
        suffix = "\r\n" if old_caption.endswith("\r\n") else "\n" if old_caption.endswith("\n") else ""
        lines[caption_index] = new_caption + suffix
        changes.append(
            Change(
                kind="figure-source-to-caption",
                line=source_index + 1,
                before=source_line.rstrip("\r\n"),
                after=f"attached to line {caption_index + 1}",
            )
        )

    # Apply safe caption-before-image moves from right to left.  The marker
    # lines keep source positions stable until all moves are complete.
    for record in sorted(records, key=lambda item: int(item["caption_index"]), reverse=True):
        caption_index = int(record["caption_index"])
        image_index = int(record["image_index"])
        if caption_index >= image_index:
            continue
        block = lines[caption_index : image_index + 1]
        middle = [item.strip() for item in block[1:-1] if item.strip()]
        if not middle or all(item in source_markers for item in middle):
            caption_line = lines.pop(caption_index)
            lines.insert(image_index, caption_line)
            changes.append(
                Change(
                    kind="figure-order",
                    line=caption_index + 1,
                    before="caption before image",
                    after="image before caption",
                )
            )
        else:
            uncertain.append(
                {
                    "kind": "figure-order",
                    "line": caption_index + 1,
                    "reason": "caption and image are separated by prose or another block",
                }
            )

    # Keep the visual relationship readable after source removal or reordering.
    # A blank separator is part of the requested image -> caption presentation,
    # but do not add one inside a fenced code block or around unrelated content.
    for index in range(len(lines) - 1):
        if not is_image_line(lines[index]):
            continue
        caption_index = nonblank_after(lines, index, distance=2)
        if caption_index is None or not is_figure_line(lines[caption_index]):
            continue
        if caption_index == index + 1:
            line_ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
            lines.insert(index + 1, line_ending)
            changes.append(
                Change(
                    kind="figure-spacing",
                    line=index + 2,
                    before="image and caption were adjacent",
                    after="inserted one blank separator",
                )
            )

    result: list[str] = []
    removed_source = False
    for line in lines:
        if any(marker in line for marker in source_markers):
            removed_source = True
            continue
        if removed_source and not line.strip() and result and not result[-1].strip():
            removed_source = False
            continue
        removed_source = False
        result.append(line)
    return result


def indentation_width(indent: str) -> int:
    return len(indent.expandtabs(4))


def unordered_item_match(line: str) -> re.Match[str] | None:
    return UNORDERED_RE.match(line.rstrip("\r\n"))


def fence_states(lines: list[str]) -> list[bool]:
    """Return whether each line is inside a fenced code block before it."""
    states: list[bool] = []
    in_fence = False
    for line in lines:
        states.append(in_fence)
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
    return states


def list_item_body_reason(body: list[str], base_indent: int) -> str | None:
    """Explain why a blank list-item separator should be retained."""
    if any(not line.strip() for line in body):
        # A blank within the item is a paragraph/block boundary, not merely
        # the separator before the next sibling item.
        if any(
            line.strip()
            and indentation_width(re.match(r"^[ \t]*", line).group(0)) <= base_indent
            for line in body
        ):
            return "ambiguous paragraph/list boundary inside the item"
        return "the item contains an internal paragraph or block separator"
    for line in body:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("```", "~~~", "![[", "![", ">", "|")):
            return "the item contains structured Markdown content"
        unordered = unordered_item_match(line)
        ordered = ORDERED_RE.match(line.rstrip("\r\n"))
        if unordered and indentation_width(unordered.group("indent")) > base_indent:
            return "the item contains a nested unordered list"
        if ordered and indentation_width(ordered.group("indent")) > base_indent:
            return "the item contains a nested ordered list"
        # Unindented text between sibling list items is ambiguous. Keeping
        # its blank separator avoids changing a paragraph/list boundary.
        leading = re.match(r"^[ \t]*", line).group(0)
        if indentation_width(leading) <= base_indent:
            return "ambiguous paragraph/list boundary"
    return None


def list_item_body_is_structural(body: list[str], base_indent: int) -> bool:
    """Return whether a list item contains content needing a separator."""
    return list_item_body_reason(body, base_indent) is not None


def compact_unordered_list_spacing(
    lines: list[str],
    changes: list[Change] | None = None,
    uncertain: list[dict[str, object]] | None = None,
    *,
    line_offset: int = 0,
) -> list[str]:
    """Remove separators between simple sibling unordered-list items.

    The marker character is deliberately ignored for matching, so ``-``,
    ``*`` and ``+`` remain a single list while their original characters are
    preserved. Only trailing blank lines immediately before a same-level
    sibling are candidates. Internal blank lines and structural item content
    are retained.
    """
    states = fence_states(lines)
    starts: list[tuple[int, int]] = []
    for index, line in enumerate(lines):
        match = unordered_item_match(line)
        if match is None or states[index]:
            continue
        starts.append((index, indentation_width(match.group("indent"))))

    remove_indices: set[int] = set()
    for ordinal, (start, base_indent) in enumerate(starts):
        next_start: int | None = None
        for candidate, candidate_indent in starts[ordinal + 1 :]:
            if candidate_indent == base_indent:
                next_start = candidate
                break
        if next_start is None:
            continue

        separator_start = next_start - 1
        while separator_start > start and not lines[separator_start].strip():
            separator_start -= 1
        separator_indices = list(range(separator_start + 1, next_start))
        if not separator_indices:
            continue
        body = lines[start + 1 : separator_start + 1]
        reason = list_item_body_reason(body, base_indent)
        if reason is not None:
            if uncertain is not None and reason.startswith("ambiguous"):
                uncertain.append(
                    {
                        "kind": "unordered-list-spacing",
                        "line": next_start + 1 + line_offset,
                        "reason": reason,
                    }
                )
            continue
        for index in separator_indices:
            remove_indices.add(index)
            if changes is not None:
                changes.append(
                    Change(
                        kind="unordered-list-spacing",
                        line=index + 1 + line_offset,
                        before=lines[index].rstrip("\r\n"),
                        after="removed between consecutive same-level unordered-list items",
                    )
                )

    return [line for index, line in enumerate(lines) if index not in remove_indices]


def repair_ordered_list_spacing(lines: list[str], changes: list[Change]) -> list[str]:
    result = list(lines)
    index = 0
    while index < len(result) - 2:
        current = ORDERED_RE.match(result[index])
        blank = not result[index + 1].strip()
        following = ORDERED_RE.match(result[index + 2])
        if current and blank and following and current.group("indent") == following.group("indent"):
            before = result[index + 1]
            del result[index + 1]
            changes.append(
                Change(
                    kind="ordered-list-spacing",
                    line=index + 2,
                    before=before.rstrip("\r\n"),
                    after="removed between consecutive ordered-list items",
                )
            )
            continue
        index += 1
    return result


def collapse_excess_blank_lines(lines: list[str], changes: list[Change]) -> list[str]:
    """Keep one visual separator outside fenced code blocks."""
    result: list[str] = []
    in_fence = False
    blank_run = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            blank_run = 0
            result.append(line)
            continue
        if not stripped and not in_fence:
            blank_run += 1
            if blank_run > 1:
                changes.append(
                    Change(
                        kind="excess-blank-line",
                        line=index + 1,
                        before=line.rstrip("\r\n"),
                        after="removed from a repeated separator",
                    )
                )
                continue
        else:
            blank_run = 0
        result.append(line)
    return result


def repair_text(
    text: str,
    relative_path: str,
    *,
    callout_style: str = "obsidian-callout",
) -> tuple[str, list[Change], list[dict[str, object]]]:
    frontmatter, body = split_frontmatter(text)
    newline = "\r\n" if "\r\n" in body else "\n"
    lines = body.splitlines(keepends=True)
    changes: list[Change] = []
    uncertain: list[dict[str, object]] = []
    toc_file = Path(relative_path).name.lower() == "05_table of contents.md"

    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        repaired, changed = repair_heading(content, toc_file=toc_file)
        if changed:
            changes.append(
                Change(
                    kind="heading-markup",
                    line=index + 1 + (frontmatter.count("\n")),
                    before=content,
                    after=repaired,
                )
            )
            suffix = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = repaired + suffix
            continue

        repaired, changed = repair_figure_caption_prefix(content)
        if changed:
            changes.append(
                Change(
                    kind="figure-caption",
                    line=index + 1 + (frontmatter.count("\n")),
                    before=content,
                    after=repaired,
                )
            )
            suffix = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = repaired + suffix
            continue

        repaired, changed = repair_broken_emphasis(line)
        if changed:
            changes.append(
                Change(
                    kind="broken-emphasis",
                    line=index + 1 + (frontmatter.count("\n")),
                    before=content,
                    after=repaired.rstrip("\r\n"),
                )
            )
            lines[index] = repaired

    callout_text, callout_changes, callout_uncertain = convert_callouts_text(
        "".join(lines),
        style=callout_style,
        line_offset=frontmatter.count("\n"),
    )
    for item in callout_changes:
        changes.append(
            Change(
                kind=str(item["kind"]),
                line=int(item["line"]),
                before=str(item["before"]),
                after=str(item["after"]),
            )
        )
    uncertain.extend(callout_uncertain)
    lines = callout_text.splitlines(keepends=True)
    lines = repair_figure_sources(lines, changes, uncertain)
    lines = repair_ordered_list_spacing(lines, changes)
    lines = compact_unordered_list_spacing(
        lines,
        changes,
        uncertain,
        line_offset=frontmatter.count("\n"),
    )
    lines = collapse_excess_blank_lines(lines, changes)
    repaired_body = "".join(lines)
    return frontmatter + normalise_line_endings(repaired_body, newline), changes, uncertain


def read_text_bytes(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    return raw, raw.decode(encoding)


def preview(root: Path, *, callout_style: str = "obsidian-callout") -> dict[str, object]:
    files: list[dict[str, object]] = []
    total_changes = 0
    total_uncertain = 0
    for path in markdown_files(root):
        raw, text = read_text_bytes(path)
        repaired, changes, uncertain = repair_text(
            text,
            str(path.relative_to(root)),
            callout_style=callout_style,
        )
        repaired_raw = repaired.encode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
        relative = str(path.relative_to(root)).replace("\\", "/")
        item = FileRepair(
            relative_path=relative,
            original_sha256=sha256_bytes(raw),
            repaired_sha256=sha256_bytes(repaired_raw),
            changed=raw != repaired_raw,
            changes=changes,
            uncertain=uncertain,
        )
        files.append(
            {
                "relative_path": item.relative_path,
                "original_sha256": item.original_sha256,
                "repaired_sha256": item.repaired_sha256,
                "changed": item.changed,
                "changes": [change.__dict__ for change in item.changes],
                "uncertain": item.uncertain,
            }
        )
        total_changes += len(changes)
        total_uncertain += len(uncertain)
    return {
        "tool": "pdf-book-to-obsidian markdown layout repair",
        "version": "0.2.0",
        "book_root": str(root),
        "callout_style": callout_style,
        "files_scanned": len(files),
        "files_changed": sum(1 for item in files if item["changed"]),
        "changes": total_changes,
        "uncertain": total_uncertain,
        "files": files,
    }


def write_preview(report: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_baseline_check(report: dict[str, object], manifest_path: Path) -> None:
    """Compare scanned Markdown with a prior generator manifest when supplied."""
    raw = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    entries = raw.get("files", [])
    baseline: dict[str, str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        relative = entry.get("relative_path")
        after_sha256 = entry.get("after_sha256")
        if isinstance(relative, str) and isinstance(after_sha256, str):
            baseline[relative.replace("\\", "/")] = after_sha256

    conflicts: list[dict[str, str]] = []
    checked = 0
    for item in report["files"]:
        relative = str(item["relative_path"])
        expected = baseline.get(relative)
        if expected is None:
            continue
        checked += 1
        actual = str(item["original_sha256"])
        if actual != expected:
            conflicts.append(
                {
                    "relative_path": relative,
                    "expected_sha256": expected,
                    "actual_sha256": actual,
                    "reason": "current Markdown differs from the last recorded generated output",
                }
            )
    report["baseline_manifest"] = {
        "path": str(manifest_path),
        "files_checked": checked,
        "conflicts": conflicts,
    }


def backup_root(root: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise RuntimeError(f"Backup already exists: {destination}")
    destination_relative: Path | None = None
    try:
        destination_relative = destination.relative_to(root)
    except ValueError:
        pass
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if destination_relative is not None and relative == destination_relative:
                continue
            if any(part.lower() in {".trash"} for part in relative.parts):
                continue
            archive.write(path, relative.as_posix())
    return destination


def apply_repairs(root: Path, report: dict[str, object], backup: Path) -> dict[str, object]:
    backup_root(root, backup)
    changed_files: list[str] = []
    for item in report["files"]:
        if not item["changed"]:
            continue
        path = root / Path(str(item["relative_path"]))
        raw, text = read_text_bytes(path)
        expected = str(item["original_sha256"])
        if sha256_bytes(raw) != expected:
            raise RuntimeError(f"Source changed after preview: {path}")
        repaired, _, _ = repair_text(
            text,
            str(item["relative_path"]),
            callout_style=str(report.get("callout_style") or "obsidian-callout"),
        )
        encoded = repaired.encode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
        path.write_bytes(encoded)
        changed_files.append(str(item["relative_path"]))
    return {
        "backup": str(backup),
        "changed_files": changed_files,
        "files_changed": len(changed_files),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("preview", "apply"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--book-root", required=True, type=Path)
        sub.add_argument("--report", required=True, type=Path)
        sub.add_argument(
            "--callout-style",
            choices=("obsidian-callout", "plain", "none"),
            default="obsidian-callout",
            help="presentation style for explicit editorial callout labels",
        )
        sub.add_argument(
            "--baseline-manifest",
            type=Path,
            help="optional prior generator manifest used to detect manual file drift",
        )
    apply = subparsers.choices["apply"]
    apply.add_argument("--backup", required=True, type=Path)
    apply.add_argument("--confirm-apply", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    root = args.book_root.resolve()
    if not root.is_dir():
        print(f"Book root does not exist: {root}", file=sys.stderr)
        return 2
    report = preview(root, callout_style=args.callout_style)
    if args.baseline_manifest is not None:
        baseline_path = args.baseline_manifest.resolve()
        if not baseline_path.is_file():
            print(f"Baseline manifest does not exist: {baseline_path}", file=sys.stderr)
            return 2
        try:
            add_baseline_check(report, baseline_path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
            print(f"Could not read baseline manifest: {error}", file=sys.stderr)
            return 2
    if args.command == "preview":
        write_preview(report, args.report)
        print(json.dumps({key: report[key] for key in ("files_scanned", "files_changed", "changes", "uncertain")}, ensure_ascii=False))
        return 0
    if not args.confirm_apply:
        print("apply requires --confirm-apply", file=sys.stderr)
        return 2
    baseline_check = report.get("baseline_manifest", {})
    if isinstance(baseline_check, dict) and baseline_check.get("conflicts"):
        report["apply"] = {
            "status": "blocked",
            "reason": "baseline manifest detected possible manual Markdown changes",
        }
        write_preview(report, args.report)
        print(json.dumps(report["apply"], ensure_ascii=False), file=sys.stderr)
        return 3
    result = apply_repairs(root, report, args.backup.resolve())
    report["apply"] = result
    write_preview(report, args.report)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
