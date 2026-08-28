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
    r"^\s*>\s*(?:(?:\[Source PDF, p\.\s*(?P<link_page>\d+)\]\((?P<url>.+)\))|(?:Source PDF, p\.\s*(?P<plain_page>\d+)))\s*$"
)
IMAGE_RE = re.compile(r"^\s*!\[\[(?P<target>[^\]]+)\]\]\s*$")
FIGURE_RE = re.compile(r"^\s*>?\s*(?P<label>Figure\s+\d+(?:\.\d+)?)\s*[–-]\s*(?P<title>.+?)\s*$")
HEADING_RE = re.compile(r"^(?P<level>#{1,6})(?P<space>\s+)(?P<title>.*?)\s*$")
ORDERED_RE = re.compile(r"^(?P<indent>\s*)(?P<number>\d+)[.)](?P<gap>\s+)(?P<body>.+?)\s*$")
UNORDERED_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-+*])(?P<gap>[ \t]+)(?P<body>\S.*?)\s*$")
SHORTCUT_STYLES = {"preserve", "inline-code"}
SHORTCUT_SUBHEADINGS = {
    "copy and paste",
    "find and replace",
    "code block operations",
    "go to operations",
    "debugging",
}
SHORTCUT_TOKEN_RE = re.compile(
    r"\b(?:Ctrl|Shift|Alt|F(?:[1-9]|1[0-2])|Up|Down|Left|Right|Home|End|"
    r"Insert|Delete|Backspace|Tab|Page\s+(?:Up|Dn|Down)|Mouse\s+click)\b",
    re.IGNORECASE,
)
SOURCE_REFERENCE_STYLES = {"preserve", "plain-blockquote"}
SPLIT_INLINE_URL_RE = re.compile(r"`(?P<left>https?://[^`]*?)`\s+`(?P<right>[^`]+)`", re.IGNORECASE)


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


def markdown_files(root: Path, include: Iterable[str] | None = None) -> list[Path]:
    """Return content Markdown files, optionally limited to relative paths."""
    if include is None:
        return sorted(
            path for path in root.rglob("*.md") if is_content_markdown(path, root)
        )

    selected: list[Path] = []
    seen: set[Path] = set()
    for relative_value in include:
        relative = Path(relative_value)
        if relative.is_absolute():
            raise ValueError(f"--include must use a path relative to --book-root: {relative}")
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as error:
            raise ValueError(f"--include escapes --book-root: {relative}") from error
        if not path.is_file() or not is_content_markdown(path, root):
            raise ValueError(f"Included content Markdown file does not exist: {relative}")
        if path not in seen:
            selected.append(path)
            seen.add(path)
    return sorted(selected)


def split_frontmatter(text: str) -> tuple[str, str]:
    match = re.match(r"\A(---\r?\n.*?\r?\n---(?:\r?\n|\Z))", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def frontmatter_title(frontmatter: str) -> str:
    match = re.search(r"^title:\s*[\"']?(.*?)[\"']?\s*$", frontmatter, re.MULTILINE)
    return match.group(1).strip() if match else ""


def remove_page_chrome(
    lines: list[str],
    frontmatter: str,
    changes: list[Change],
    *,
    line_offset: int = 0,
) -> list[str]:
    """Remove a standalone running header matching the declared file title."""
    title = frontmatter_title(frontmatter)
    if not title:
        return lines
    title_key = re.sub(r"\s+", " ", title).strip().casefold()
    page_chrome = re.compile(r"^(?P<label>.+?)\s+(?P<page>(?:\d{1,4}|[ivxlcdm]{1,12}))$")
    result: list[str] = []
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        match = page_chrome.match(content.strip())
        label_key = (
            re.sub(r"\s+", " ", match.group("label")).strip().casefold()
            if match else ""
        )
        if match and label_key == title_key:
            changes.append(Change(
                kind="page-chrome",
                line=index + 1 + line_offset,
                before=content,
                after="removed high-confidence running header",
            ))
            continue
        result.append(line)
    return result


def remove_standalone_roman_page_chrome(
    lines: list[str],
    changes: list[Change],
    *,
    line_offset: int = 0,
) -> list[str]:
    """Remove isolated Roman page numbers when a source marker follows.

    A Roman numeral by itself can be real book content, so this deliberately
    requires the strong PDF-extraction pattern seen in front matter: the
    numeral is a standalone line and the next non-empty line is an explicit
    Source PDF marker.  Other isolated numbers remain untouched.
    """
    roman_re = re.compile(r"^[ivxlcdm]{1,12}$", re.IGNORECASE)
    result: list[str] = []
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        if not roman_re.fullmatch(content.strip()):
            result.append(line)
            continue
        next_nonempty = next(
            (
                candidate.strip()
                for candidate in lines[index + 1 : index + 4]
                if candidate.strip()
            ),
            "",
        )
        if not SOURCE_RE.match(next_nonempty):
            result.append(line)
            continue
        changes.append(Change(
            kind="page-chrome",
            line=index + 1 + line_offset,
            before=content,
            after="removed isolated Roman page footer before Source PDF marker",
        ))
    return result


def normalise_line_endings(text: str, newline: str) -> str:
    if newline == "\r\n":
        return text.replace("\r\n", "\n").replace("\n", "\r\n")
    return text.replace("\r\n", "\n")


def merge_split_inline_code_urls(text: str) -> tuple[str, int]:
    """Join adjacent code spans only when the left span ends at a URL edge."""
    count = 0
    while True:
        def replace(match: re.Match[str]) -> str:
            nonlocal count
            left = match.group("left")
            right = match.group("right")
            if not re.fullmatch(r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", right):
                return match.group(0)
            if not (left.endswith(("/", "://", "?", "&", "=", "#", "-", "."))):
                return match.group(0)
            count += 1
            return f"`{left}{right}`"

        repaired = SPLIT_INLINE_URL_RE.sub(replace, text)
        if repaired == text:
            return text, count
        text = repaired


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


def clean_toc_heading(title: str) -> str:
    """Clean a TOC heading without inferring its nested entry structure."""
    cleaned = strip_heading_markup(title)
    if re.search(r"\s+[—-]\s+p\.\s*\d+\s*$", cleaned):
        return re.sub(r"\s+", " ", cleaned).strip()
    page = re.search(r"\s+(\d{1,4})\s*$", cleaned)
    if page:
        cleaned = f"{cleaned[:page.start()].rstrip()} — p. {page.group(1)}"
    return cleaned


def repair_heading(line: str, *, toc_file: bool) -> tuple[str, bool]:
    match = HEADING_RE.match(line)
    if not match:
        return line, False
    title = (
        clean_toc_heading(match.group("title"))
        if toc_file
        else strip_heading_markup(clean_heading_suffix(match.group("title"), toc_file=False))
    )
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
    # A PDF list bullet can split an italic label at the opening marker:
    # '- * Chapter 1*' -> '- *Chapter 1*'.  Only repair this unambiguous
    # list-start form; ordinary emphasis elsewhere remains untouched.
    repaired = re.sub(
        r"^(\s*[-*+]\s+)\*\s+(?=[^*\r\n]+\*(?:\s*[,.;:]|\s*$))",
        r"\1*",
        repaired,
    )
    # A long italic phrase can be split across adjacent PDF font spans:
    # '*Unreal Engine ... C++ * *Scripting*'.
    for _ in range(4):
        joined = re.sub(
            r"\*(?P<left>[^*\r\n]+?)\s+\*\s+\*(?P<right>[^*\r\n]+?)\*",
            lambda match: f"*{match.group('left').rstrip()} {match.group('right').lstrip()}*",
            repaired,
        )
        if joined == repaired:
            break
        repaired = joined
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
    # Some PDF spans omit the space before the opening marker and duplicate
    # the marker between adjacent bold spans, e.g. ``the** Find**** calculator**``.
    # These forms are only repaired when the marker boundary and whitespace
    # pattern make the extraction artifact unambiguous.
    repaired = re.sub(
        r"(?P<prefix>\w)\*\*\s+(?P<first>[^*\r\n]+?)\*{4}\s+(?P<second>[^*\r\n]+?)\*\*",
        lambda match: (
            f"{match.group('prefix')} **{match.group('first').strip()} "
            f"{match.group('second').strip()}**"
        ),
        repaired,
    )
    repaired = re.sub(
        r"(?P<prefix>\w)\*\*\s+(?P<text>[^*\r\n]+?)\*\*(?=$|[\s.,;:!?)}\]])",
        lambda match: f"{match.group('prefix')} **{match.group('text').strip()}**",
        repaired,
    )
    return repaired, repaired != line


def shortcut_label_parts(label: str) -> list[str]:
    """Split a shortcut label into alternatives without retaining PDF emphasis."""
    cleaned = re.sub(r"\*+", "", label)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return []
    # Commas in these labels separate alternative shortcuts.  Parentheses are
    # part of one key label, so only split commas outside parentheses.
    parts: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(cleaned):
        if character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character == "," and depth == 0:
            part = cleaned[start:index].strip()
            if part:
                parts.append(part)
            start = index + 1
    final = cleaned[start:].strip()
    if final:
        parts.append(final)
    return parts


def repair_shortcut_list_item(
    line: str,
    *,
    style: str,
) -> tuple[str, bool]:
    """Render a clearly extracted keyboard-shortcut list label as inline code."""
    if style not in SHORTCUT_STYLES:
        raise ValueError("shortcut style must be preserve or inline-code")
    if style == "preserve":
        return line, False
    match = unordered_item_match(line)
    if match is None:
        return line, False
    body = match.group("body")
    label, separator, description = body.partition(":")
    if not separator:
        return line, False
    # Require both a keyboard-like token and the characteristic leading PDF
    # emphasis fragment.  This prevents ordinary bold/italic list entries
    # such as ``- **C++** ...`` from being reformatted.
    if not SHORTCUT_TOKEN_RE.search(label):
        return line, False
    if not re.match(r"\s*\*+\s+\*{1,4}", label):
        return line, False
    alternatives = shortcut_label_parts(label)
    if not alternatives:
        return line, False
    formatted = ", ".join(f"`{part}`" for part in alternatives)
    repaired = (
        f"{match.group('indent')}{match.group('marker')}{match.group('gap')}"
        f"{formatted}:{description}"
    )
    return repaired, repaired != line.rstrip("\r\n")


def repair_shortcut_subheading(
    line: str,
    *,
    parent_heading_level: int | None,
    style: str,
) -> tuple[str, bool]:
    """Turn a known standalone shortcut label into the next heading level."""
    if style not in SHORTCUT_STYLES:
        raise ValueError("shortcut style must be preserve or inline-code")
    if style == "preserve" or parent_heading_level is None or parent_heading_level >= 6:
        return line, False
    match = re.match(r"^(?P<indent>\s*)\*{3}\s*(?P<title>[^*\r\n]+?)\s*\*{3}\s*$", line)
    if not match:
        return line, False
    title = re.sub(r"\s+", " ", match.group("title")).strip()
    if title.casefold() not in SHORTCUT_SUBHEADINGS:
        return line, False
    repaired = f"{match.group('indent')}{'#' * (parent_heading_level + 1)} {title}"
    return repaired, repaired != line.rstrip("\r\n")


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


def source_page(match: re.Match[str]) -> str:
    return match.group("link_page") or match.group("plain_page")


def source_url(match: re.Match[str]) -> str | None:
    return match.group("url")


def normalize_source_references(
    lines: list[str],
    changes: list[Change],
    *,
    style: str,
    line_offset: int = 0,
) -> list[str]:
    """Normalize legacy source links while preserving page numbers."""
    if style not in SOURCE_REFERENCE_STYLES:
        raise ValueError("source reference style must be preserve or plain-blockquote")
    if style == "preserve":
        return lines
    result = list(lines)
    for index, line in enumerate(result):
        match = is_source_line(line)
        if match is None or source_url(match) is None:
            continue
        ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        repaired = f"> Source PDF, p. {source_page(match)}{ending}"
        if repaired == line:
            continue
        changes.append(
            Change(
                kind="source-reference-style",
                line=index + 1 + line_offset,
                before=line.rstrip("\r\n"),
                after=repaired.rstrip("\r\n"),
            )
        )
        result[index] = repaired
    return result


def deduplicate_local_source_references(
    lines: list[str],
    changes: list[Change],
    *,
    line_offset: int = 0,
) -> list[str]:
    """Remove only repeated same-page refs separated by heading metadata."""
    remove: set[int] = set()
    last_source: tuple[int, str] | None = None
    for index, line in enumerate(lines):
        match = is_source_line(line)
        if match is None:
            continue
        page = source_page(match)
        if last_source is not None:
            previous_index, previous_page = last_source
            between = [
                line
                for position, line in enumerate(lines[previous_index + 1 : index], previous_index + 1)
                if position not in remove
            ]
            meaningful = [item for item in between if item.strip()]
            if (
                page == previous_page
                and meaningful
                and all(HEADING_RE.match(item.rstrip("\r\n")) for item in meaningful)
            ):
                remove.add(index)
                changes.append(
                    Change(
                        kind="duplicate-source-reference",
                        line=index + 1 + line_offset,
                        before=line.rstrip("\r\n"),
                        after=f"removed duplicate of line {previous_index + 1 + line_offset}",
                    )
                )
                continue
        last_source = (index, page)
    return [line for index, line in enumerate(lines) if index not in remove]


def repair_toc_line(line: str) -> tuple[str, bool]:
    """Remove only explicit PDF emphasis/control fragments from TOC text."""
    if not ("**" in line or "\x08" in line):
        return line, False
    ending = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
    cleaned = line.rstrip("\r\n").replace("\x08", "")
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    repaired = cleaned + ending
    return repaired, repaired != line


def heading_key(line: str) -> str | None:
    match = HEADING_RE.match(line.rstrip("\r\n"))
    if match is None:
        return None
    title = strip_heading_markup(match.group("title"))
    title = re.sub(r"[–—]", "-", title)
    return re.sub(r"\s+", " ", title).strip().casefold()


def remove_redundant_leading_heading(
    lines: list[str],
    changes: list[Change],
    *,
    line_offset: int = 0,
) -> list[str]:
    """Remove a duplicate generated/source heading at the start of a note."""
    positions = [
        index
        for index, line in enumerate(lines[:16])
        if HEADING_RE.match(line.rstrip("\r\n"))
    ]
    if len(positions) < 2:
        return lines
    first, second = positions[0], positions[1]
    first_key = heading_key(lines[first])
    second_key = heading_key(lines[second])
    if not first_key or first_key != second_key:
        return lines
    between = [line for line in lines[first + 1 : second] if line.strip()]
    if not all(is_source_line(line) or HEADING_RE.match(line.rstrip("\r\n")) for line in between):
        return lines
    changes.append(
        Change(
            kind="duplicate-heading",
            line=second + 1 + line_offset,
            before=lines[second].rstrip("\r\n"),
            after=f"removed duplicate of line {first + 1 + line_offset}",
        )
    )
    return [line for index, line in enumerate(lines) if index != second]


def is_image_line(line: str) -> re.Match[str] | None:
    return IMAGE_RE.match(line)


def is_figure_line(line: str) -> re.Match[str] | None:
    return FIGURE_RE.match(line)


def repair_figure_caption_prefix(
    line: str,
    *,
    style: str = "blockquote",
) -> tuple[str, bool]:
    """Apply the selected presentation style to a clear Figure caption."""
    if style not in {"plain", "blockquote"}:
        raise ValueError("figure caption style must be plain or blockquote")
    match = re.match(
        r"^(?P<indent>\s*)(?P<quote>>\s*)?(?P<caption>Figure\s+\d+(?:\.\d+)?\s*[–-]\s*.+?)\s*$",
        line,
    )
    if not match:
        return line, False
    caption = match.group("caption").rstrip()
    if style == "blockquote":
        repaired = f"{match.group('indent')}> {caption}"
    else:
        repaired = f"{match.group('indent')}{caption}"
    return repaired, repaired != line.rstrip("\r\n")


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

        if source_url(source_match) is None:
            # Plain source references intentionally stay before the image.
            # Only a linked source line can be safely moved into a caption,
            # because the caption needs a URL to preserve the original link.
            continue
        records.append(
            {
                "image_index": image_index,
                "caption_index": caption_index,
                "source_index": source_index,
                "page": source_page(source_match),
                "url": source_url(source_match),
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
    figure_caption_style: str = "blockquote",
    shortcut_style: str = "preserve",
    source_reference_style: str = "preserve",
) -> tuple[str, list[Change], list[dict[str, object]]]:
    if shortcut_style not in SHORTCUT_STYLES:
        raise ValueError("shortcut style must be preserve or inline-code")
    if source_reference_style not in SOURCE_REFERENCE_STYLES:
        raise ValueError("source reference style must be preserve or plain-blockquote")
    frontmatter, body = split_frontmatter(text)
    newline = "\r\n" if "\r\n" in body else "\n"
    lines = body.splitlines(keepends=True)
    changes: list[Change] = []
    uncertain: list[dict[str, object]] = []
    toc_file = Path(relative_path).name.lower() == "05_table of contents.md"
    parent_heading_level: int | None = None

    lines = remove_page_chrome(
        lines,
        frontmatter,
        changes,
        line_offset=frontmatter.count("\n"),
    )
    lines = remove_standalone_roman_page_chrome(
        lines,
        changes,
        line_offset=frontmatter.count("\n"),
    )

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
            parent_heading_level = len(repaired.split(None, 1)[0])
            continue

        heading_match = HEADING_RE.match(content)
        if heading_match:
            parent_heading_level = len(heading_match.group("level"))

        if toc_file:
            repaired, changed = repair_toc_line(content)
            if changed:
                changes.append(
                    Change(
                        kind="toc-format",
                        line=index + 1 + (frontmatter.count("\n")),
                        before=content,
                        after=repaired.rstrip("\r\n"),
                    )
                )
                lines[index] = repaired
                continue

        repaired, changed = repair_shortcut_subheading(
            content,
            parent_heading_level=parent_heading_level,
            style=shortcut_style,
        )
        if changed:
            changes.append(
                Change(
                    kind="shortcut-subheading",
                    line=index + 1 + (frontmatter.count("\n")),
                    before=content,
                    after=repaired,
                )
            )
            suffix = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = repaired + suffix
            continue

        repaired, changed = repair_shortcut_list_item(content, style=shortcut_style)
        if changed:
            changes.append(
                Change(
                    kind="shortcut-inline-code",
                    line=index + 1 + (frontmatter.count("\n")),
                    before=content,
                    after=repaired,
                )
            )
            repaired_after_emphasis, emphasis_changed = repair_broken_emphasis(repaired)
            if emphasis_changed:
                changes.append(
                    Change(
                        kind="broken-emphasis",
                        line=index + 1 + (frontmatter.count("\n")),
                        before=repaired,
                        after=repaired_after_emphasis.rstrip("\r\n"),
                    )
                )
                repaired = repaired_after_emphasis.rstrip("\r\n")
            suffix = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
            lines[index] = repaired + suffix
            continue

        repaired, changed = repair_figure_caption_prefix(
            content,
            style=figure_caption_style,
        )
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
    lines = normalize_source_references(
        lines,
        changes,
        style=source_reference_style,
        line_offset=frontmatter.count("\n"),
    )
    lines = repair_figure_sources(lines, changes, uncertain)
    lines = deduplicate_local_source_references(
        lines,
        changes,
        line_offset=frontmatter.count("\n"),
    )
    lines = remove_redundant_leading_heading(
        lines,
        changes,
        line_offset=frontmatter.count("\n"),
    )
    lines = repair_ordered_list_spacing(lines, changes)
    lines = compact_unordered_list_spacing(
        lines,
        changes,
        uncertain,
        line_offset=frontmatter.count("\n"),
    )
    lines = collapse_excess_blank_lines(lines, changes)
    repaired_body = "".join(lines)
    repaired_body, joined_urls = merge_split_inline_code_urls(repaired_body)
    if joined_urls:
        changes.append(Change(
            kind="url-join",
            line=1 + frontmatter.count("\n"),
            before=f"joined {joined_urls} coordinate-confirmed URL fragment pair(s)",
            after="inline URL code spans merged",
        ))
    return frontmatter + normalise_line_endings(repaired_body, newline), changes, uncertain


def read_text_bytes(path: Path) -> tuple[bytes, str]:
    raw = path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    return raw, raw.decode(encoding)


def preview(
    root: Path,
    *,
    callout_style: str = "obsidian-callout",
    figure_caption_style: str = "blockquote",
    shortcut_style: str = "preserve",
    source_reference_style: str = "preserve",
    include: Iterable[str] | None = None,
) -> dict[str, object]:
    root = root.resolve()
    files: list[dict[str, object]] = []
    total_changes = 0
    total_uncertain = 0
    for path in markdown_files(root, include=include):
        raw, text = read_text_bytes(path)
        repaired, changes, uncertain = repair_text(
            text,
            str(path.relative_to(root)),
            callout_style=callout_style,
            figure_caption_style=figure_caption_style,
            shortcut_style=shortcut_style,
            source_reference_style=source_reference_style,
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
        "version": "0.5.0",
        "book_root": str(root),
        "callout_style": callout_style,
        "figure_caption_style": figure_caption_style,
        "shortcut_style": shortcut_style,
        "source_reference_style": source_reference_style,
        "scope": "selected files" if include is not None else "all content Markdown",
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
            # A backup is a rollback point for the current book state, not a
            # recursive archive of earlier rollback points.  Excluding all
            # backup trees keeps repeated maintenance backups bounded and
            # avoids copying historical ZIPs into every new ZIP.
            if any(part.casefold() in {".trash", "backups"} for part in relative.parts):
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
            figure_caption_style=str(report.get("figure_caption_style") or "blockquote"),
            shortcut_style=str(report.get("shortcut_style") or "preserve"),
            source_reference_style=str(report.get("source_reference_style") or "preserve"),
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
            "--figure-caption-style",
            choices=("blockquote", "plain"),
            default="blockquote",
            help="presentation style for clear Figure captions",
        )
        sub.add_argument(
            "--shortcut-style",
            choices=("preserve", "inline-code"),
            default="preserve",
            help="presentation style for clearly identified keyboard-shortcut list items",
        )
        sub.add_argument(
            "--source-reference-style",
            choices=("preserve", "plain-blockquote"),
            default="preserve",
            help="presentation style for PDF source references in existing Markdown",
        )
        sub.add_argument(
            "--baseline-manifest",
            type=Path,
            help="optional prior generator manifest used to detect manual file drift",
        )
        sub.add_argument(
            "--include",
            action="append",
            help=(
                "limit the repair to a content Markdown path relative to --book-root; "
                "repeat for multiple files"
            ),
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
    try:
        report = preview(
            root,
            callout_style=args.callout_style,
            figure_caption_style=args.figure_caption_style,
            shortcut_style=args.shortcut_style,
            source_reference_style=args.source_reference_style,
            include=args.include,
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
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
