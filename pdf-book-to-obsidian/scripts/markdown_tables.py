#!/usr/bin/env python3
"""Conservative conversion of definition-like Markdown lists to tables."""

from __future__ import annotations

import re
from typing import Any


def parse_table_candidate(line: str) -> dict[str, str] | None:
    """Parse only a top-level bold-label definition bullet."""
    if not line.startswith("- **"):
        return None
    # PDF styling can emit an empty/repeated bold span before the actual
    # label, e.g. ``- ** ****Operating system**: Windows 10``. Treat that as
    # the same structural list while leaving all non-matching prose alone.
    match = re.match(r"^- (?P<opening>\*\*(?:\s*\*\*)*)(?P<label>.+?)\*\*(?P<separator>—|:)(?P<description>.*)$", line)
    if not match:
        return None
    label = match.group("label").strip()
    if not label or "*" in label:
        return None
    return {"label": label, "description": match.group("description").lstrip()}


def wrapped_continuation_text(line: str, previous_description: str) -> str | None:
    """Return only a conservative lower-case PDF wrap continuation."""
    stripped = line.strip()
    if not stripped or previous_description.rstrip().endswith((".", "!", "?", ":", ";", ")")):
        return None
    if stripped.startswith(("- ", "#", "![", "![[", "|")):
        return None
    if stripped.startswith("> "):
        stripped = stripped[2:].lstrip()
    probe = stripped
    while probe.startswith(("*", "_", "`")):
        probe = probe[1:]
    return stripped if probe and probe[0].islower() else None


def escape_table_cell(value: str) -> str:
    return re.sub(r"(?<!\\)\|", r"\\|", value)


def transform_definition_lists(markdown: str, min_rows: int = 2) -> tuple[str, dict[str, Any]]:
    """Replace safe definition-list runs while preserving all other lines.

    A run must contain at least ``min_rows`` unambiguous rows. Ambiguous or
    interrupted runs remain as lists and are reported for human review.
    """
    if min_rows < 2:
        raise ValueError("min_rows must be at least 2")

    lines = markdown.splitlines()
    final_newline = markdown.endswith("\n")
    output: list[str] = []
    tables: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    current_heading = ""
    index = 0

    while index < len(lines):
        line = lines[index]
        if line.startswith("## "):
            current_heading = line[3:].strip()

        item = parse_table_candidate(line)
        if item is None:
            if line.startswith("- **"):
                skipped.append({
                    "heading": current_heading,
                    "start_line": index + 1,
                    "end_line": index + 1,
                    "items": [],
                    "reason": "not-an-unambiguous-dash-or-colon-definition",
                })
            output.append(line)
            index += 1
            continue

        start = index
        rows: list[dict[str, str]] = []
        end = index
        cursor = index
        while True:
            current = parse_table_candidate(lines[cursor])
            if current is None:
                break
            row = dict(current)
            row_end = cursor
            probe = cursor + 1
            while probe < len(lines) and not lines[probe].strip():
                probe += 1
            continuation = (
                wrapped_continuation_text(lines[probe], row["description"])
                if probe < len(lines)
                else None
            )
            while continuation is not None:
                row["description"] = f'{row["description"]} {continuation}'.strip()
                row_end = probe
                probe += 1
                while probe < len(lines) and not lines[probe].strip():
                    probe += 1
                continuation = (
                    wrapped_continuation_text(lines[probe], row["description"])
                    if probe < len(lines)
                    else None
                )
            rows.append(row)
            end = row_end
            if probe < len(lines) and parse_table_candidate(lines[probe]) is not None:
                cursor = probe
                continue
            break

        if len(rows) < min_rows:
            skipped.append({
                "heading": current_heading,
                "start_line": start + 1,
                "end_line": end + 1,
                "items": [row["label"] for row in rows],
                "reason": "fewer-than-minimum-rows-or-interrupted-by-other-content",
            })
            output.extend(lines[start : end + 1])
            index = end + 1
            continue

        output.extend([
            "| Term / Item | Original description |",
            "| --- | --- |",
        ])
        for row in rows:
            label = escape_table_cell(row["label"])
            description = escape_table_cell(row["description"])
            output.append(f"| **{label}** | {description} |")
        tables.append({
            "heading": current_heading,
            "start_line": start + 1,
            "end_line": end + 1,
            "rows": len(rows),
            "items": [row["label"] for row in rows],
        })
        index = end + 1

    transformed = "\n".join(output)
    if final_newline:
        transformed += "\n"
    return transformed, {
        "tables": tables,
        "tables_count": len(tables),
        "rows_transformed": sum(int(table["rows"]) for table in tables),
        "skipped": skipped,
    }
