#!/usr/bin/env python3
"""Apply high-confidence visual-structure repairs to existing Markdown.

This maintenance helper consumes a PDF pipeline preview.  It never replaces
an entire generated note: it only replaces a clearly located, PDF-backed
visual-table text region.  Existing Callouts are detected and left intact;
ambiguous regions are reported for Agent review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


FIGURE_RE = re.compile(r"^\s*>?\s*Figure\s+\d+(?:\.\d+)?\s*[–-]\s*.+$")
SOURCE_RE = re.compile(r"^\s*>\s*(?:\[Source PDF, p\.\s*\d+\]|Source PDF, p\.\s*\d+)\s*$")


@dataclass
class RepairChange:
    kind: str
    page: int
    relative_path: str
    start_line: int | None
    end_line: int | None
    before: str
    after: str
    confidence: str = "high"


@dataclass
class FileResult:
    relative_path: str
    original_sha256: str
    repaired_sha256: str
    changed: bool
    changes: list[RepairChange] = field(default_factory=list)
    uncertain: list[dict[str, Any]] = field(default_factory=list)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def content_markdown(root: Path) -> list[Path]:
    result: list[Path] = []
    for path in root.rglob("*.md"):
        relative_parts = {part.casefold() for part in path.relative_to(root).parts}
        if relative_parts.intersection({"file", ".obsidian", ".trash"}):
            continue
        result.append(path)
    return sorted(result)


def source_pages(text: str) -> tuple[int, int] | None:
    match = re.search(r"^source_pages:\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]\s*$", text, re.MULTILINE)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def normalise_match(value: str) -> str:
    value = re.sub(r"!\[\[[^\]]+\]\]", " ", value)
    value = re.sub(r"[*_`~]", "", value)
    value = value.replace("\ufeff", "").replace("\u00ad", "")
    return re.sub(r"\s+", " ", value).strip().casefold()


def contains_match(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    if needle[0].isalnum() and needle[-1].isalnum():
        return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None
    return needle in haystack


def table_is_present(text: str, markdown: str) -> bool:
    return normalise_match(markdown) in normalise_match(text)


def candidate_owner(files: list[Path], root: Path, page: int) -> Path | None:
    owners: list[Path] = []
    for path in files:
        try:
            pages = source_pages(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError):
            continue
        if pages and pages[0] <= page <= pages[1]:
            owners.append(path)
    return owners[0] if len(owners) == 1 else None


def first_cell_tokens(table: dict[str, Any]) -> list[str]:
    tokens: list[str] = []
    rows = table.get("rows", [])
    if not isinstance(rows, list):
        rows = parse_table_rows(str(table.get("markdown") or ""))
    for row in rows or []:
        if not isinstance(row, list) or not row:
            continue
        token = normalise_match(str(row[0]))
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def parse_table_rows(markdown: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in markdown.splitlines():
        if not line.strip().startswith("|"):
            continue
        inner = line.strip()[1:-1] if line.strip().endswith("|") else line.strip()[1:]
        cells = [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", inner)]
        if cells and not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            rows.append(cells)
    return rows[1:] if rows else []


def locate_table(
    lines: list[str],
    table: dict[str, Any],
    cursor: int,
) -> tuple[int, int] | None:
    headers = [normalise_match(str(item)) for item in table.get("headers", []) or [] if str(item).strip()]
    if not headers:
        return None
    header_keys = ["example(s)" if header.startswith("example(s)") else header for header in headers]
    row_tokens = first_cell_tokens(table)
    first_header = headers[0]
    for anchor in range(cursor, len(lines)):
        anchor_text = normalise_match(lines[anchor])
        header_like = (
            anchor_text == first_header
            or bool(re.search(r"\|", lines[anchor]))
            or bool(re.search(r"\*{1,3}\s*" + re.escape(first_header) + r"\s*\*{1,3}", lines[anchor], re.IGNORECASE))
        )
        if not header_like or not contains_match(anchor_text, first_header):
            continue
        start = anchor
        # PDF extraction often emits an Example(s) header before the other
        # cells. Include that nearby line, but never cross a real paragraph,
        # list, heading, or source-page boundary.
        for previous in range(max(cursor, anchor - 3), anchor):
            if normalise_match(lines[previous]) == "example(s)":
                start = previous
        for window_end in range(anchor, min(len(lines), anchor + 14)):
            window = normalise_match(" ".join(lines[start : window_end + 1]))
            if not all(contains_match(window, header) for header in header_keys):
                continue
            figure_end = next(
                (index for index in range(window_end + 1, len(lines)) if FIGURE_RE.match(lines[index])),
                None,
            )
            limit = figure_end if figure_end is not None else len(lines)
            region_text = normalise_match(" ".join(lines[start:limit]))
            found_tokens = [token for token in row_tokens if contains_match(region_text, token)]
            if row_tokens and len(found_tokens) < min(2, len(row_tokens)):
                continue
            if figure_end is not None:
                return start, figure_end
            hits = [
                index
                for index in range(window_end + 1, limit)
                if any(token and contains_match(normalise_match(lines[index]), token) for token in row_tokens)
            ]
            if hits:
                return start, max(hits) + 1
            return start, window_end + 1
    return None


def existing_callout(text: str, markdown: str) -> bool:
    body = [
        line[2:].strip()
        for line in markdown.splitlines()
        if line.startswith("> ") and "[!" not in line
    ]
    if not body:
        return False
    probe = normalise_match(" ".join(body))
    if not probe:
        return False
    for match in re.finditer(r"(?m)^>\s*\[![^\]]+\].*$", text):
        end = text.find("\n\n", match.end())
        block = text[match.start() : len(text) if end < 0 else end]
        if probe[:80] in normalise_match(block):
            return True
    return False


def build_preview(book_root: Path, source_report: Path) -> dict[str, Any]:
    root = book_root.resolve()
    pipeline = read_json(source_report)
    files = content_markdown(root)
    text_by_path = {path: path.read_text(encoding="utf-8-sig") for path in files}
    cursors: dict[Path, int] = {}
    changes: list[RepairChange] = []
    uncertain: list[dict[str, Any]] = []
    replacements: dict[Path, list[tuple[int, int, str, dict[str, Any]]]] = {}

    tables = [
        item for item in ((pipeline.get("structure_preview") or {}).get("visual_tables") or [])
        if isinstance(item, dict) and item.get("markdown")
    ]
    audits = {
        str(item.get("id")): item
        for item in pipeline.get("visual_table_audits", []) or []
        if isinstance(item, dict)
    }
    for raw_table in sorted(tables, key=lambda item: (int(item.get("start_page", item.get("page", 0))), str(item.get("id")))):
        table_id = str(raw_table.get("id") or "")
        audit = audits.get(table_id, {})
        if audit.get("status") == "skipped":
            continue
        table = {**audit, **raw_table}
        table["rows"] = parse_table_rows(str(raw_table.get("markdown") or ""))
        page = int(table.get("start_page", table.get("page", 0)))
        path = candidate_owner(files, root, page)
        if path is None:
            uncertain.append({"kind": "visual-table", "id": table_id, "page": page, "reason": "no-unique-markdown-owner"})
            continue
        text = text_by_path[path]
        markdown = str(table["markdown"]).strip()
        if table_is_present(text, markdown):
            continue
        lines = text.splitlines()
        start_at = cursors.get(path, 0)
        location = locate_table(lines, table, start_at)
        if location is None:
            uncertain.append({"kind": "visual-table", "id": table_id, "page": page, "relative_path": str(path.relative_to(root)).replace("\\", "/"), "reason": "no-safe-source-region"})
            continue
        start, end = location
        replacements.setdefault(path, []).append((start, end, markdown, table))
        cursors[path] = end

    callout_preview = (pipeline.get("structure_preview") or {}).get("boxed_callouts") or []
    callouts_existing = 0
    for item in callout_preview:
        if not isinstance(item, dict) or not item.get("markdown"):
            continue
        page = int(item.get("page", 0))
        path = candidate_owner(files, root, page)
        if path is None:
            uncertain.append({"kind": "boxed-callout", "id": item.get("id"), "page": page, "reason": "no-unique-markdown-owner"})
            continue
        if existing_callout(text_by_path[path], str(item["markdown"])):
            callouts_existing += 1
        else:
            uncertain.append({"kind": "boxed-callout", "id": item.get("id"), "page": page, "relative_path": str(path.relative_to(root)).replace("\\", "/"), "reason": "plain-body-needs-local-context-review"})

    result_files: list[FileResult] = []
    for path in files:
        raw = path.read_bytes()
        text = text_by_path[path]
        edits = sorted(replacements.get(path, []), key=lambda item: item[0], reverse=True)
        repaired_lines = text.splitlines()
        file_changes: list[RepairChange] = []
        for start, end, markdown, table in edits:
            before = "\n".join(repaired_lines[start:end])
            repaired_lines[start:end] = markdown.splitlines()
            change = RepairChange(
                kind="visual-table",
                page=int(table.get("start_page", 0)),
                relative_path=str(path.relative_to(root)).replace("\\", "/"),
                start_line=start + 1,
                end_line=end,
                before=before,
                after=markdown,
            )
            file_changes.append(change)
            changes.append(change)
        repaired = "\n".join(repaired_lines)
        if text.endswith("\n") and not repaired.endswith("\n"):
            repaired += "\n"
        if text.endswith("\r\n"):
            repaired = repaired.replace("\n", "\r\n")
        repaired_raw = repaired.encode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
        result_files.append(FileResult(
            relative_path=str(path.relative_to(root)).replace("\\", "/"),
            original_sha256=sha256_bytes(raw),
            repaired_sha256=sha256_bytes(repaired_raw),
            changed=raw != repaired_raw,
            changes=file_changes,
        ))

    for item in uncertain:
        matching = [result for result in result_files if result.relative_path == item.get("relative_path")]
        if matching:
            matching[0].uncertain.append(item)

    return {
        "mode": "visual-structure-preview",
        "book_root": str(root),
        "source_report": str(source_report.resolve()),
        "files": [
            {
                "relative_path": item.relative_path,
                "original_sha256": item.original_sha256,
                "repaired_sha256": item.repaired_sha256,
                "changed": item.changed,
                "changes": [change.__dict__ for change in item.changes],
                "uncertain": item.uncertain,
            }
            for item in result_files
        ],
        "changes": [change.__dict__ for change in changes],
        "uncertain": uncertain,
        "tables_to_apply": len(changes),
        "callouts_already_present": callouts_existing,
        "callouts_review_required": len([item for item in uncertain if item.get("kind") == "boxed-callout"]),
    }


def backup_is_readable(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as archive:
            return bool(archive.namelist())
    except (OSError, zipfile.BadZipFile):
        return False


def apply_preview(book_root: Path, preview_path: Path, backup: Path) -> dict[str, Any]:
    report = read_json(preview_path)
    if not backup_is_readable(backup):
        raise RuntimeError(f"Backup is missing or unreadable: {backup}")
    changed_files: list[str] = []
    for item in report.get("files", []) or []:
        if not item.get("changed"):
            continue
        path = book_root / Path(str(item["relative_path"]))
        raw = path.read_bytes()
        if sha256_bytes(raw) != item.get("original_sha256"):
            raise RuntimeError(f"Source changed after preview: {path}")
        text = raw.decode("utf-8-sig")
        lines = text.splitlines()
        for change in sorted(item.get("changes", []), key=lambda value: int(value["start_line"]), reverse=True):
            start = int(change["start_line"]) - 1
            end = int(change["end_line"])
            lines[start:end] = str(change["after"]).splitlines()
        repaired = "\n".join(lines)
        if text.endswith("\n") and not repaired.endswith("\n"):
            repaired += "\n"
        if text.endswith("\r\n"):
            repaired = repaired.replace("\n", "\r\n")
        encoded = repaired.encode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
        path.write_bytes(encoded)
        if sha256_bytes(encoded) != item.get("repaired_sha256"):
            raise RuntimeError(f"Post-write hash verification failed: {path}")
        changed_files.append(str(item["relative_path"]))
    return {"backup": str(backup.resolve()), "changed_files": changed_files, "files_changed": len(changed_files)}


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("preview", "apply"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--book-root", required=True, type=Path)
        sub.add_argument("--source-report", required=True, type=Path)
        sub.add_argument("--report", required=True, type=Path)
        if command == "apply":
            sub.add_argument("--backup", required=True, type=Path)
            sub.add_argument("--confirm-apply", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.command == "preview":
        report = build_preview(args.book_root, args.source_report)
        write_report(report, args.report)
        print(json.dumps({"report": str(args.report.resolve()), "tables_to_apply": report["tables_to_apply"], "uncertain": len(report["uncertain"])}, ensure_ascii=False, indent=2))
        return 0
    if not args.confirm_apply:
        raise RuntimeError("apply requires --confirm-apply")
    result = apply_preview(args.book_root.resolve(), args.report.resolve(), args.backup.resolve())
    report = read_json(args.report)
    report["mode"] = "visual-structure-apply"
    report["apply"] = result
    write_report(report, args.report)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(2)
