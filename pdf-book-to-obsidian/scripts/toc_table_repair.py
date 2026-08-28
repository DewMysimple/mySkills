#!/usr/bin/env python3
"""Build a navigable, chapter-grouped Markdown table of contents.

The PDF extraction step is deliberately separate from rendering.  An Agent
may review or amend the extracted entry manifest before preview/apply.  The
renderer only links to existing chapter files and headings that match after
conservative typography normalization.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterable


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def clean_pdf_text(value: str) -> str:
    """Remove extraction controls without rewriting ordinary wording."""
    text = str(value or "").replace("\x08", "").replace("\u200b", "")
    text = text.replace("�C", "-")
    text = re.sub(r"�+([A-Za-z])", r"’\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_title(value: str) -> str:
    """Normalize only matching typography, not semantic content."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("‑", "-")
    text = text.replace("\ufeff", "")
    text = re.sub(r"[`*~]", "", text)
    # PDF line wrapping can insert spaces inside identifiers such as
    # ``TP_ PickUpComponent`` or ``BP_ PlayerAvatar``.  Removing whitespace
    # only around identifier punctuation is a typography normalization, not
    # a semantic fuzzy match.
    text = re.sub(r"\s*([_.])\s*", r"\1", text)
    # Remove only delimiter-like underscores.  Keep underscores inside
    # identifiers such as ``TP_PickUpComponent``.
    text = re.sub(r"(?<!\w)_+|_+(?!\w)", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def table_cell(value: str) -> str:
    return str(value).replace("|", r"\|").replace("\n", " ").strip()


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---"):
        return "", text
    match = re.match(r"\A---\r?\n.*?\r?\n---\r?\n?", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(0), text[match.end() :]


def iter_pdf_lines(page: Any) -> Iterable[list[dict[str, Any]]]:
    """Yield visual lines in the PDF content-stream order, grouped by block."""
    words = page.get_text("words", sort=False)
    blocks: dict[int, dict[int, list[dict[str, Any]]]] = {}
    for word in words:
        if len(word) < 8:
            continue
        x0, y0, x1, y1, value, block_no, line_no, word_no = word[:8]
        blocks.setdefault(int(block_no), {}).setdefault(int(line_no), []).append(
            {
                "x0": float(x0),
                "y0": float(y0),
                "x1": float(x1),
                "y1": float(y1),
                "text": clean_pdf_text(str(value)),
                "word_no": int(word_no),
            }
        )
    for block in blocks.values():
        yield [sorted(line, key=lambda item: item["word_no"]) for line in block.values()]


def page_marker(line: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]] | None:
    if not line:
        return None
    last = line[-1]
    token = str(last["text"])
    if not re.fullmatch(r"\d{1,3}", token):
        return None
    first_x = float(line[0]["x0"])
    # A TOC page number is in the right margin of its column.  This avoids
    # treating title text such as "Visual Studio 2022" as a page number.
    if len(line) == 1:
        # Wrapped chapter titles commonly place the page number on its own
        # line inside the same PDF text block.
        if first_x < 150.0:
            return None
        return int(token), []
    if float(last["x0"]) < first_x + 100.0:
        return None
    return int(token), line[:-1]


def extract_toc_manifest(source_pdf: Path, start_page: int, end_page: int) -> dict[str, Any]:
    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:  # pragma: no cover - older bundled runtimes
        import fitz  # type: ignore

    if start_page < 1 or end_page < start_page:
        raise ValueError("Invalid 1-based TOC page range")
    document = fitz.open(str(source_pdf))
    if end_page > len(document):
        raise ValueError(f"TOC end page {end_page} exceeds PDF page count {len(document)}")

    parts: list[dict[str, Any]] = []
    chapters: list[dict[str, Any]] = []
    back_matter: list[dict[str, Any]] = []
    current_part: dict[str, Any] | None = None
    current_chapter: dict[str, Any] | None = None
    pending_chapter_number: int | None = None
    pending_title_words: list[str] = []
    unresolved_fragments: list[dict[str, Any]] = []
    sequence = 0

    for pdf_page in range(start_page, end_page + 1):
        page = document[pdf_page - 1]
        for lines in iter_pdf_lines(page):
            if not lines:
                continue
            flattened = clean_pdf_text(" ".join(word["text"] for line in lines for word in line))
            if not flattened or flattened.casefold().startswith("table of contents"):
                if flattened.casefold().startswith("table of contents"):
                    pending_title_words = []
                continue
            part_match = re.match(r"^Part\s+(\d+)\b", flattened, re.IGNORECASE)
            if part_match:
                current_part = {
                    "number": int(part_match.group(1)),
                    "title": flattened,
                }
                parts.append(current_part)
                current_chapter = None
                pending_chapter_number = None
                pending_title_words = []
                continue
            for line in lines:
                raw_line = clean_pdf_text(" ".join(word["text"] for word in line))
                if not raw_line:
                    continue
                if re.fullmatch(r"(?:v|x|i|l|c|d|m)+", raw_line.casefold()):
                    continue
                if re.fullmatch(r"\d{1,2}", raw_line) and float(line[0]["x0"]) < 150:
                    pending_chapter_number = int(raw_line)
                    current_chapter = None
                    pending_title_words = []
                    continue

                marker = page_marker(line)
                if marker is None:
                    pending_title_words.extend(word["text"] for word in line)
                    continue

                print_page, title_words = marker
                title_parts = [*pending_title_words, *(word["text"] for word in title_words)]
                title = clean_pdf_text(" ".join(title_parts))
                pending_title_words = []
                if not title:
                    continue
                sequence += 1

                if pending_chapter_number is not None:
                    current_chapter = {
                        "number": pending_chapter_number,
                        "title": title,
                        "print_page": print_page,
                        "part_number": current_part["number"] if current_part else None,
                        "sections": [],
                    }
                    chapters.append(current_chapter)
                    pending_chapter_number = None
                    continue

                if normalize_title(title) in {"index", "other books you may enjoy"}:
                    current_chapter = None
                    back_matter.append(
                        {
                            "title": title,
                            "print_page": print_page,
                            "source_pdf_page": pdf_page,
                            "sequence": sequence,
                        }
                    )
                    continue

                if current_chapter is None:
                    continue
                current_chapter["sections"].append(
                    {
                        "title": title,
                        "print_page": print_page,
                        "source_pdf_page": pdf_page,
                        "sequence": sequence,
                    }
                )

    if pending_title_words:
        unresolved_fragments.append({"text": clean_pdf_text(" ".join(pending_title_words))})

    for chapter in chapters:
        chapter["sections"].sort(key=lambda item: (int(item["print_page"]), int(item["sequence"])))
    document.close()
    return {
        "source_pdf": str(source_pdf.resolve()),
        "source_sha256": sha256_file(source_pdf),
        "toc_pdf_pages": [start_page, end_page],
        "parts": parts,
        "chapters": chapters,
        "back_matter": back_matter,
        "unresolved_fragments": unresolved_fragments,
        "counts": {
            "parts": len(parts),
            "chapters": len(chapters),
            "sections": sum(len(item["sections"]) for item in chapters),
            "back_matter": len(back_matter),
        },
    }


def load_heading_index(chapters_root: Path) -> tuple[dict[int, Path], dict[str, list[tuple[Path, str, int]]]]:
    chapter_files: dict[int, Path] = {}
    headings: dict[str, list[tuple[Path, str, int]]] = {}
    for path in sorted(chapters_root.rglob("Chapter *.md")):
        number_match = re.match(r"^Chapter\s+(\d+)\b", path.name, re.IGNORECASE)
        if number_match:
            chapter_files[int(number_match.group(1))] = path
        for line in path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if not match:
                continue
            title = match.group(2).rstrip("#").strip()
            headings.setdefault(normalize_title(title), []).append(
                (path, title, len(match.group(1)))
            )
    return chapter_files, headings


def relative_target(path: Path, base: Path, fragment: str | None = None) -> str:
    relative = os.path.relpath(path, base).replace(os.sep, "/")
    if fragment:
        return f"<{relative}#{fragment}>"
    return f"<{relative}>"


def markdown_link(label: str, target: str) -> str:
    return f"[{table_cell(label)}]({target})"


def is_reliable_match(source: str, target: str) -> bool:
    """Reject visible replacement-character artifacts as link evidence."""
    return "\ufffd" not in str(source) and "\ufffd" not in str(target)


def find_back_matter_file(chapters_root: Path, title: str) -> Path | None:
    """Find a back-matter note without assuming a book's filename prefix."""
    wanted = normalize_title(title)
    candidates: list[Path] = []
    for path in sorted(chapters_root.rglob("*.md")):
        stem = re.sub(r"^\d+[_ .-]*", "", path.stem)
        if normalize_title(stem) == wanted:
            candidates.append(path)
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.match(r"^#\s+(.+?)\s*$", line)
                if match and normalize_title(match.group(1).rstrip("#").strip()) == wanted:
                    candidates.append(path)
                    break
        except OSError:
            continue
    return candidates[0] if len(candidates) == 1 else None


def render_toc(
    entries: dict[str, Any],
    toc_path: Path,
    chapters_root: Path,
) -> tuple[str, dict[str, Any]]:
    frontmatter, _ = split_frontmatter(toc_path.read_text(encoding="utf-8"))
    chapter_files, headings = load_heading_index(chapters_root)
    link_audit: dict[str, Any] = {
        "chapter_links": [],
        "section_links": [],
        "unmatched_sections": [],
        "missing_chapter_files": [],
        "back_matter_links": [],
        "unmatched_back_matter": [],
    }
    toc_pages = entries.get("toc_pdf_pages") or []
    if len(toc_pages) == 2:
        source_reference = f"> Source PDF, pp. {int(toc_pages[0])}-{int(toc_pages[1])}"
    elif len(toc_pages) == 1:
        source_reference = f"> Source PDF, p. {int(toc_pages[0])}"
    else:
        source_reference = "> Source PDF"
    lines: list[str] = [frontmatter.rstrip("\n"), "# Table of Contents", "", source_reference, ""]

    parts = {int(item["number"]): item for item in entries.get("parts", [])}
    chapters_by_part: dict[int | None, list[dict[str, Any]]] = {}
    for chapter in entries.get("chapters", []):
        chapters_by_part.setdefault(chapter.get("part_number"), []).append(chapter)

    for part_number, part_chapters in chapters_by_part.items():
        part = parts.get(part_number)
        part_title = str(part.get("title") if part else f"Part {part_number}")
        part_title = part_title.replace("–", "-").replace("—", "-").replace("‑", "-")
        lines.extend([f"## {table_cell(part_title)}", ""])
        for chapter in sorted(part_chapters, key=lambda item: int(item["number"])):
            number = int(chapter["number"])
            title = str(chapter["title"])
            chapter_path = chapter_files.get(number)
            if chapter_path is None:
                link_audit["missing_chapter_files"].append(number)
                chapter_label = table_cell(title)
            else:
                chapter_label = markdown_link(
                    title,
                    relative_target(chapter_path, toc_path.parent),
                )
                link_audit["chapter_links"].append(
                    {"chapter": number, "path": str(chapter_path), "status": "ok"}
                )
            lines.extend(
                [
                    f"### Chapter {number} - {chapter_label} - p. {int(chapter['print_page'])}",
                    "",
                    "| Section | Print page |",
                    "| --- | ---: |",
                ]
            )
            for section in chapter.get("sections", []):
                section_title = str(section["title"])
                matches = headings.get(normalize_title(section_title), [])
                forced_plain = section.get("link") is False
                same_file = [] if forced_plain else [
                    item for item in matches
                    if item[0] == chapter_path and is_reliable_match(section_title, item[1])
                ]
                if len(same_file) == 1 and chapter_path is not None:
                    heading_path, heading_title, _ = same_file[0]
                    section_cell = markdown_link(
                        section_title,
                        relative_target(heading_path, toc_path.parent, heading_title),
                    )
                    link_audit["section_links"].append(
                        {
                            "chapter": number,
                            "title": section_title,
                            "target_heading": heading_title,
                            "status": "ok",
                        }
                    )
                else:
                    section_cell = table_cell(section_title)
                    reason = section.get("link_reason") if forced_plain else (
                        "missing-heading" if not same_file else "ambiguous-heading"
                    )
                    link_audit["unmatched_sections"].append(
                        {
                            "chapter": number,
                            "title": section_title,
                            "print_page": int(section["print_page"]),
                            "reason": reason,
                        }
                    )
                lines.append(f"| {section_cell} | {int(section['print_page'])} |")
            lines.append("")

    if entries.get("back_matter"):
        lines.extend(["## Back Matter", "", "| Item | Print page |", "| --- | ---: |"])
        for item in entries["back_matter"]:
            item_title = str(item["title"])
            path = find_back_matter_file(chapters_root, item_title)
            if path is not None and is_reliable_match(item_title, path.stem):
                cell = markdown_link(item_title, relative_target(path, toc_path.parent))
                link_audit["back_matter_links"].append(
                    {"title": item_title, "path": str(path), "status": "ok"}
                )
            else:
                cell = table_cell(item_title)
                link_audit["unmatched_back_matter"].append(
                    {
                        "title": item_title,
                        "print_page": int(item["print_page"]),
                        "reason": "missing-file",
                    }
                )
            lines.append(f"| {cell} | {int(item['print_page'])} |")
        lines.append("")

    body = "\n".join(lines).rstrip() + "\n"
    audit = {
        **link_audit,
        "counts": {
            "chapters": len(entries.get("chapters", [])),
            "sections": sum(len(item.get("sections", [])) for item in entries.get("chapters", [])),
            "linked_sections": len(link_audit["section_links"]),
            "unmatched_sections": len(link_audit["unmatched_sections"]),
            "back_matter": len(entries.get("back_matter", [])),
            "linked_back_matter": len(link_audit["back_matter_links"]),
            "unmatched_back_matter": len(link_audit["unmatched_back_matter"]),
        },
    }
    return body, audit


def preview(toc_path: Path, entries_path: Path, chapters_root: Path) -> dict[str, Any]:
    current = toc_path.read_text(encoding="utf-8")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    desired, link_audit = render_toc(entries, toc_path, chapters_root)
    diff = list(
        difflib.unified_diff(
            current.splitlines(), desired.splitlines(),
            fromfile=str(toc_path), tofile=f"{toc_path} (proposed)", lineterm="",
        )
    )
    return {
        "mode": "preview",
        "toc": str(toc_path.resolve()),
        "entries_manifest": str(entries_path.resolve()),
        "chapters_root": str(chapters_root.resolve()),
        "current_sha256": sha256_bytes(current.encode("utf-8")),
        "desired_sha256": sha256_bytes(desired.encode("utf-8")),
        "changed": current != desired,
        "diff": diff[:500],
        "source": {
            "pdf": entries.get("source_pdf"),
            "sha256": entries.get("source_sha256"),
            "toc_pdf_pages": entries.get("toc_pdf_pages"),
        },
        "entry_counts": entries.get("counts", {}),
        "link_audit": link_audit,
    }


def create_backup(backup_path: Path, files: list[Path]) -> None:
    if backup_path.exists():
        raise FileExistsError(f"Backup already exists: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(backup_path, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            if path.exists():
                archive.write(path, arcname=path.name)


def apply_change(
    toc_path: Path,
    entries_path: Path,
    chapters_root: Path,
    preview_path: Path,
    backup_path: Path,
    config_path: Path | None,
) -> dict[str, Any]:
    preview_report = json.loads(preview_path.read_text(encoding="utf-8"))
    before = toc_path.read_text(encoding="utf-8")
    before_sha256 = sha256_bytes(before.encode("utf-8"))
    if before_sha256 != preview_report.get("current_sha256"):
        raise RuntimeError("TOC changed after preview; refusing to apply stale changes")
    entries = json.loads(entries_path.read_text(encoding="utf-8"))
    desired, link_audit = render_toc(entries, toc_path, chapters_root)
    desired_sha256 = sha256_bytes(desired.encode("utf-8"))
    if desired_sha256 != preview_report.get("desired_sha256"):
        raise RuntimeError("Entries or chapter headings changed after preview; rerun preview")
    if before == desired:
        return {
            "mode": "apply",
            "changed": False,
            "toc": str(toc_path.resolve()),
            "before_sha256": before_sha256,
            "after_sha256": before_sha256,
            "backup": None,
            "link_audit": link_audit,
        }

    backup_files = [toc_path]
    if config_path is not None:
        backup_files.append(config_path)
    create_backup(backup_path, backup_files)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", dir=toc_path.parent, delete=False,
        prefix=f".{toc_path.stem}.", suffix=".tmp",
    ) as stream:
        temporary = Path(stream.name)
        stream.write(desired)
    os.replace(temporary, toc_path)
    return {
        "mode": "apply",
        "changed": True,
        "toc": str(toc_path.resolve()),
        "before_sha256": before_sha256,
        "after_sha256": sha256_file(toc_path),
        "backup": str(backup_path.resolve()),
        "config": str(config_path.resolve()) if config_path else None,
        "entry_counts": entries.get("counts", {}),
        "link_audit": link_audit,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    extract = commands.add_parser("extract", help="Extract a reviewed TOC entry manifest from PDF pages")
    extract.add_argument("--source-pdf", required=True, type=Path)
    extract.add_argument("--start-page", required=True, type=int)
    extract.add_argument("--end-page", required=True, type=int)
    extract.add_argument("--output", required=True, type=Path)

    for name in ("preview", "apply"):
        command = commands.add_parser(name)
        command.add_argument("--toc", required=True, type=Path)
        command.add_argument("--entries", required=True, type=Path)
        command.add_argument("--chapters-root", required=True, type=Path)
        if name == "preview":
            command.add_argument("--report-out", required=True, type=Path)
        else:
            command.add_argument("--preview", required=True, type=Path)
            command.add_argument("--backup", required=True, type=Path)
            command.add_argument("--config", type=Path)
            command.add_argument("--report-out", required=True, type=Path)
            command.add_argument("--confirm-apply", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        write_json(args.output, extract_toc_manifest(args.source_pdf.resolve(), args.start_page, args.end_page))
        print(json.dumps({"manifest": str(args.output.resolve()), "mode": "extract"}, ensure_ascii=False))
        return 0
    toc = args.toc.resolve()
    entries = args.entries.resolve()
    chapters_root = args.chapters_root.resolve()
    if not toc.exists() or not entries.exists() or not chapters_root.is_dir():
        raise SystemExit("TOC, entries manifest, or chapters root does not exist")
    if args.command == "preview":
        report = preview(toc, entries, chapters_root)
        write_json(args.report_out.resolve(), report)
        print(json.dumps({"report": str(args.report_out.resolve()), "mode": "preview", "changed": report["changed"]}, ensure_ascii=False))
        return 0
    if not args.confirm_apply:
        raise SystemExit("apply requires --confirm-apply")
    report = apply_change(
        toc, entries, chapters_root, args.preview.resolve(), args.backup.resolve(),
        args.config.resolve() if args.config else None,
    )
    write_json(args.report_out.resolve(), report)
    print(json.dumps({"report": str(args.report_out.resolve()), "mode": "apply", "changed": report["changed"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
