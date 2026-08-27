#!/usr/bin/env python3
"""Small, shared Obsidian Markdown presentation helpers.

The PDF extractor and the existing-Markdown repair pass both use this module
so that generated notes and later maintenance follow the same syntax policy.
It deliberately does not parse all Markdown: uncertain or nested structures
are left to the caller/Agent rather than rewritten heuristically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


CALLOUT_TYPES = {
    "note": "NOTE",
    "notes": "NOTE",
    "tip": "TIP",
    "hint": "TIP",
    "warning": "WARNING",
    "caution": "WARNING",
    "important": "IMPORTANT",
    "danger": "DANGER",
    "error": "DANGER",
    "example": "EXAMPLE",
}

CALLOUT_STYLES = {"obsidian-callout", "plain", "none"}
MARKDOWN_BASELINES = {"obsidian", "commonmark"}

_LABEL_RE = re.compile(
    r"^(?P<label>note|notes|tip|hint|warning|caution|important|danger|error|example)"
    r"(?P<colon>\s*:\s*)?(?P<body>.*)$",
    re.IGNORECASE,
)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
_LIST_RE = re.compile(r"^(?:[-+*]\s+|\d+[.)]\s+)")
_SOURCE_RE = re.compile(r"^>\s*(?:\[)?Source PDF,\s*p\.\s*\d+", re.IGNORECASE)
_FIGURE_RE = re.compile(r"^>?\s*Figure\s+\d+(?:\.\d+)?\s*[–—-]\s+", re.IGNORECASE)


@dataclass(frozen=True)
class CalloutLead:
    """A high-confidence editorial label at the start of a Markdown block."""

    indent: str
    callout_type: str
    body: str


def markdown_baseline(config: dict[str, object] | None) -> str:
    output = (config or {}).get("output") or {}
    value = str(output.get("markdown_baseline") or "obsidian").strip().lower()
    if value not in MARKDOWN_BASELINES:
        raise ValueError("output.markdown_baseline must be obsidian or commonmark")
    return value


def callout_style(config: dict[str, object] | None) -> str:
    output = (config or {}).get("output") or {}
    value = str(output.get("callout_style") or "").strip().lower()
    if not value:
        return "obsidian-callout" if markdown_baseline(config) == "obsidian" else "plain"
    if value not in CALLOUT_STYLES:
        raise ValueError("output.callout_style must be obsidian-callout, plain, or none")
    return value


def parse_callout_lead(line: str) -> CalloutLead | None:
    """Parse only explicit label forms, avoiding ordinary prose such as 'Note that'."""
    raw = line.rstrip("\r\n")
    indent_match = re.match(r"^[ \t]*", raw)
    indent = indent_match.group(0) if indent_match else ""
    text = raw[len(indent) :]
    if not text or text.startswith((">", "#", "|")) or _LIST_RE.match(text):
        return None

    for marker in ("**", "__", "*", "_"):
        if not text.startswith(marker):
            continue
        closing = text.find(marker, len(marker))
        if closing <= len(marker):
            continue
        label_text = text[len(marker) : closing].strip()
        label = label_text.rstrip(":").strip().casefold()
        if label not in CALLOUT_TYPES:
            continue
        tail = text[closing + len(marker) :]
        if tail and not (tail[0].isspace() or tail.startswith(":")):
            continue
        if tail.startswith(":"):
            tail = tail[1:].lstrip()
        else:
            tail = tail.lstrip()
        return CalloutLead(indent, CALLOUT_TYPES[label], tail)

    match = _LABEL_RE.match(text)
    if not match:
        return None
    label = match.group("label").casefold()
    if not match.group("colon") and match.group("body"):
        # Bare 'Note that ...' is ordinary prose, not an editorial label.
        return None
    return CalloutLead(indent, CALLOUT_TYPES[label], match.group("body").lstrip())


def is_structural_block(line: str) -> bool:
    """Return whether a line starts a block that a callout should not absorb."""
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("```", "~~~", "![[", "![", ">", "|")):
        return True
    if _HEADING_RE.match(stripped) or _LIST_RE.match(stripped):
        return True
    if _SOURCE_RE.match(stripped) or _FIGURE_RE.match(stripped):
        return True
    if stripped.startswith(("<", "---")):
        return True
    return False


def _nested_callout_candidate(line: str) -> bool:
    """Detect a label in a list/table/blockquote without rewriting it."""
    stripped = line.strip()
    list_match = re.match(r"^(?:[-+*]\s+|\d+[.)]\s+)(?P<body>.+)$", stripped)
    if list_match and parse_callout_lead(list_match.group("body")) is not None:
        return True
    if stripped.startswith("|"):
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if any(parse_callout_lead(cell) is not None for cell in cells):
            return True
    if stripped.startswith(">") and not re.match(r"^>\s*\[!", stripped):
        return parse_callout_lead(stripped[1:].lstrip()) is not None
    return False


def _line_contents(text: str) -> tuple[list[str], str, bool]:
    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    has_final_newline = bool(lines and lines[-1].endswith(("\n", "\r")))
    return [line.rstrip("\r\n") for line in lines], newline, has_final_newline


def _render_callout(callout_type: str, body: list[str]) -> list[str]:
    rendered = [f"> [!{callout_type}]", "> "]
    rendered.extend(f"> {line}" if line else "> " for line in body)
    return rendered


def convert_callouts_text(
    text: str,
    *,
    style: str = "obsidian-callout",
    line_offset: int = 0,
) -> tuple[str, list[dict[str, object]], list[dict[str, object]]]:
    """Convert explicit top-level editorial labels to Obsidian callouts.

    The returned change/uncertain records are generic dictionaries so the
    Markdown repair module can attach its own Change dataclass without a
    circular import.
    """
    if style not in CALLOUT_STYLES:
        raise ValueError("callout style must be obsidian-callout, plain, or none")
    if style != "obsidian-callout":
        return text, [], []

    lines, newline, has_final_newline = _line_contents(text)
    output: list[str] = []
    changes: list[dict[str, object]] = []
    uncertain: list[dict[str, object]] = []
    in_fence = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            output.append(line)
            in_fence = not in_fence
            index += 1
            continue

        lead = None if in_fence else parse_callout_lead(line)
        if lead is None:
            if not in_fence and _nested_callout_candidate(line):
                uncertain.append({
                    "kind": "callout",
                    "line": index + 1 + line_offset,
                    "reason": "a possible nested or indented callout label was left unchanged",
                })
            output.append(line)
            index += 1
            continue

        if lead.indent:
            uncertain.append({
                "kind": "callout",
                "line": index + 1 + line_offset,
                "reason": "callout label is nested or indented; list/table structure was preserved",
            })
            output.append(line)
            index += 1
            continue

        body: list[str] = []
        end = index + 1
        if lead.body:
            body.append(lead.body)
            # Physical PDF wrapping without a blank line is still part of the
            # same paragraph. Do not absorb the next Markdown block.
            while (
                end < len(lines)
                and lines[end]
                and not is_structural_block(lines[end])
                and parse_callout_lead(lines[end]) is None
            ):
                body.append(lines[end])
                end += 1
        else:
            body_start = end
            while body_start < len(lines) and not lines[body_start]:
                body_start += 1
            end = body_start
            while end < len(lines):
                current = lines[end]
                if current:
                    if is_structural_block(current) or parse_callout_lead(current):
                        break
                    body.append(current)
                    end += 1
                    continue
                lookahead = end + 1
                while lookahead < len(lines) and not lines[lookahead]:
                    lookahead += 1
                if lookahead >= len(lines) or is_structural_block(lines[lookahead]) or parse_callout_lead(lines[lookahead]):
                    break
                body.append("")
                end += 1
            while body and not body[-1]:
                body.pop()

        output.extend(_render_callout(lead.callout_type, body))
        changes.append({
            "kind": "callout",
            "line": index + 1 + line_offset,
            "before": line,
            "after": f"> [!{lead.callout_type}]",
            "callout_type": lead.callout_type,
        })
        index = end

    result = newline.join(output)
    if has_final_newline:
        result += newline
    return result, changes, uncertain


def _encoded_path(path: str | Path) -> str:
    return quote(Path(path).as_posix(), safe="/:@-._~!$&'()*+,;=[]")


def render_note_link(
    path: str | Path,
    label: str | None,
    config: dict[str, object] | None,
    *,
    fragment: str | None = None,
) -> str:
    """Render a note link using Obsidian Wiki syntax or portable Markdown."""
    path_text = Path(path).as_posix()
    if markdown_baseline(config) == "obsidian":
        if path_text.lower().endswith(".md"):
            path_text = path_text[:-3]
        target = path_text + (f"#{fragment}" if fragment else "")
        return f"[[{target}|{label}]]" if label else f"[[{target}]]"
    target = _encoded_path(path_text)
    if fragment:
        target += "#" + quote(fragment, safe="-._~")
    return f"[{label or path_text}]({target})"


def render_file_embed(
    vault_relative_path: str | Path,
    config: dict[str, object] | None,
    *,
    markdown_target: str | Path | None = None,
) -> str:
    """Render a local asset embed for the selected syntax baseline."""
    path_text = Path(vault_relative_path).as_posix()
    if markdown_baseline(config) == "obsidian":
        return f"![[{path_text}]]"
    target = _encoded_path(str(markdown_target or path_text))
    alt = Path(path_text).stem
    return f"![{alt}]({target})"
