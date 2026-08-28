#!/usr/bin/env python3
"""Repair PDF-backed figure placement without replacing whole Markdown files.

The PDF pipeline remains the source of image coordinates and figure order, while
this maintenance helper patches only existing standalone image/caption blocks.
It deliberately leaves prose, code, tables, callouts, and inline icons alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import pdf_book_pipeline as pipeline  # noqa: E402


GENERATOR = "pdf-book-to-obsidian"
VERSION = "0.1.0"
IMAGE_RE = re.compile(r"^\s*!\[\[([^\]]+)\]\]\s*$")
CAPTION_RE = re.compile(r"^\s*>\s*Figure\s+([0-9]+\.[0-9]+)\s+[–-]\s*(.+?)\s*$")
SOURCE_RE = re.compile(r"^>\s*Source PDF,\s*p\.\s*(\d+)\s*$")
IMAGE_PAGE_RE = re.compile(r"Figure-p(\d{4})-")


class RepairError(RuntimeError):
    """Raised when a safe image-only repair cannot be completed."""


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def normalize_path(value: str) -> str:
    return value.replace("\\", "/").strip()


def normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def fence_mask(lines: list[str]) -> list[bool]:
    mask: list[bool] = []
    inside = False
    for line in lines:
        mask.append(inside)
        if re.match(r"^\s*(```+|~~~+)", line):
            inside = not inside
    return mask


def standalone_images(lines: list[str]) -> list[tuple[int, str]]:
    mask = fence_mask(lines)
    found: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if mask[index]:
            continue
        match = IMAGE_RE.match(line)
        if match:
            found.append((index, normalize_path(match.group(1))))
    return found


def figure_captions(lines: list[str]) -> list[tuple[int, str, str]]:
    mask = fence_mask(lines)
    found: list[tuple[int, str, str]] = []
    for index, line in enumerate(lines):
        if mask[index]:
            continue
        match = CAPTION_RE.match(line)
        if match:
            found.append((index, match.group(1), match.group(2).strip()))
    return found


def source_page(line: str) -> int | None:
    match = SOURCE_RE.match(line.strip())
    return int(match.group(1)) if match else None


def image_page(path: str) -> int | None:
    match = IMAGE_PAGE_RE.search(Path(path).name)
    return int(match.group(1)) if match else None


def generated_figure_pairs(lines: list[str]) -> list[dict[str, Any]]:
    """Return coordinate-ordered image/caption pairs from generated output."""
    images = standalone_images(lines)
    captions = figure_captions(lines)
    pairs: list[dict[str, Any]] = []
    for image_index, path in images:
        candidate: tuple[int, str, str] | None = None
        for caption in captions:
            caption_index = caption[0]
            if caption_index <= image_index or caption_index > image_index + 6:
                continue
            meaningful = [
                item.strip()
                for item in lines[image_index + 1 : caption_index]
                if item.strip()
            ]
            if meaningful:
                continue
            candidate = caption
            break
        if candidate is None:
            continue
        pairs.append({
            "image_path": path,
            "generated_image_index": image_index,
            "caption_index": candidate[0],
            "figure": candidate[1],
            "caption": candidate[2],
            "page": image_page(path),
        })
    return pairs


def find_unique_indices(values: list[tuple[int, str]], wanted: str) -> list[int]:
    return [index for index, value in values if normalize_path(value) == normalize_path(wanted)]


def find_source_for_image(
    lines: list[str], image_index: int, caption_index: int, page: int | None,
) -> tuple[int | None, str | None, str | None]:
    if page is None:
        return None, None, "image filename has no PDF page token"
    mask = fence_mask(lines)
    low = max(0, min(image_index, caption_index) - 8)
    high = min(len(lines), max(image_index, caption_index) + 8)
    candidates: list[tuple[int, int, int]] = []
    for index in range(low, high):
        if mask[index]:
            continue
        if source_page(lines[index]) != page:
            continue
        before_image = 0 if index <= image_index else 1
        candidates.append((before_image, abs(index - image_index), index))
    if not candidates:
        return None, None, "no nearby matching Source PDF reference"
    candidates.sort()
    best = candidates[0]
    if len(candidates) > 1 and candidates[1][:2] == best[:2]:
        return None, None, "multiple equally-near Source PDF references"
    return best[2], lines[best[2]].strip(), None


def is_correct_block(lines: list[str], source_index: int | None, image_index: int, caption_index: int, page: int | None) -> bool:
    if source_index is None or page is None:
        return False
    if not (source_index < image_index < caption_index):
        return False
    between_source_image = [line.strip() for line in lines[source_index + 1 : image_index] if line.strip()]
    between_image_caption = [line.strip() for line in lines[image_index + 1 : caption_index] if line.strip()]
    return (
        not between_source_image
        and not between_image_caption
        and source_page(lines[source_index]) == page
    )


def apply_pairs(old_text: str, generated_text: str) -> tuple[str, dict[str, Any]]:
    old_lines = old_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    generated_lines = generated_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    generated_pairs = generated_figure_pairs(generated_lines)
    old_images = standalone_images(old_lines)
    old_captions = figure_captions(old_lines)
    removals: set[int] = set()
    replacements: dict[int, list[str]] = {}
    used_images: set[int] = set()
    used_captions: set[int] = set()
    records: list[dict[str, Any]] = []
    uncertain: list[dict[str, Any]] = []

    for pair in generated_pairs:
        path = str(pair["image_path"])
        image_matches = [index for index, value in old_images if index not in used_images and normalize_path(value) == path]
        caption_matches = [
            index for index, figure, caption in old_captions
            if index not in used_captions
            and figure == pair["figure"]
            and normalize_line(caption) == normalize_line(str(pair["caption"]))
        ]
        if len(image_matches) != 1 or len(caption_matches) != 1:
            uncertain.append({
                "figure": pair["figure"],
                "image_path": path,
                "reason": "image or caption is missing/ambiguous in current Markdown",
                "image_matches": image_matches,
                "caption_matches": caption_matches,
            })
            continue
        image_index = image_matches[0]
        caption_index = caption_matches[0]
        source_index, source_line, source_reason = find_source_for_image(
            old_lines, image_index, caption_index, pair.get("page"),
        )
        if source_reason:
            uncertain.append({
                "figure": pair["figure"],
                "image_path": path,
                "reason": source_reason,
                "image_line": image_index + 1,
                "caption_line": caption_index + 1,
            })
            continue
        if is_correct_block(old_lines, source_index, image_index, caption_index, pair.get("page")):
            used_images.add(image_index)
            used_captions.add(caption_index)
            records.append({
                "figure": pair["figure"],
                "image_path": path,
                "action": "unchanged",
                "current_image_line": image_index + 1,
                "current_caption_line": caption_index + 1,
            })
            continue

        used_images.add(image_index)
        used_captions.add(caption_index)
        removals.add(image_index)
        if source_index is not None:
            removals.add(source_index)
        caption_line = old_lines[caption_index].strip()
        if not caption_line.startswith(">"):
            caption_line = f"> Figure {pair['figure']} – {pair['caption']}"
        replacements[caption_index] = [
            source_line or f"> Source PDF, p. {pair['page']}",
            "",
            old_lines[image_index].strip(),
            "",
            caption_line,
        ]
        # Remove orphaned blank separators directly attached to moved source/image lines.
        for removed in (source_index, image_index):
            if removed is None:
                continue
            for neighbor in (removed - 1, removed + 1):
                if 0 <= neighbor < len(old_lines) and not old_lines[neighbor].strip():
                    removals.add(neighbor)
        records.append({
            "figure": pair["figure"],
            "image_path": path,
            "action": "moved-before-caption",
            "old_image_line": image_index + 1,
            "old_caption_line": caption_index + 1,
            "old_source_line": source_index + 1 if source_index is not None else None,
            "new_block": replacements[caption_index],
        })

    output_lines: list[str] = []
    for index, line in enumerate(old_lines):
        if index in replacements:
            output_lines.extend(replacements[index])
        elif index not in removals:
            output_lines.append(line)
    new_text = "\n".join(output_lines)
    if old_text.endswith(("\n", "\r")) and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, {
        "generated_figure_pairs": len(generated_pairs),
        "records": records,
        "uncertain": uncertain,
        "changed": new_text != old_text,
    }


def make_args(args: argparse.Namespace, command: str) -> argparse.Namespace:
    chapters = args.chapters
    return argparse.Namespace(
        vault=str(args.vault),
        book=args.book,
        config=getattr(args, "config", None),
        source=getattr(args, "source", None),
        output_root=None,
        command=command,
        stages=None,
        only_chapters=chapters,
        only_sections=None,
        copy_source=False,
        report_out=None,
    )


def build_preview(args: argparse.Namespace) -> dict[str, Any]:
    context = pipeline.prepare_context(make_args(args, "dry-run"))
    if context["source_info"]["likely_scanned"]:
        raise RepairError("The source PDF appears to be scanned; image-only repair refuses to continue.")
    stages = pipeline.stages_from_config(context["config"], None)
    outputs, _details = pipeline.build_outputs(
        context["vault"], context["book"], context["config"], context["source"],
        context["source"], context["source_info"]["sha256"], stages,
        args.chapters, None,
    )
    chapter_outputs = [item for item in outputs if item.kind == "chapter"]
    if not chapter_outputs:
        raise RepairError("No selected chapter outputs were generated.")
    file_reports: list[dict[str, Any]] = []
    total_pairs = 0
    total_moved = 0
    total_unchanged = 0
    all_uncertain: list[dict[str, Any]] = []
    for output in chapter_outputs:
        target = context["vault"] / output.relative_path
        if not target.exists():
            raise RepairError(f"Target chapter does not exist: {target}")
        old_bytes = target.read_bytes()
        old_text = old_bytes.decode("utf-8")
        new_text, detail = apply_pairs(old_text, output.content.decode("utf-8"))
        if b"\r\n" in old_bytes:
            new_bytes = new_text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        else:
            new_bytes = new_text.encode("utf-8")
        moved = [record for record in detail["records"] if record["action"] == "moved-before-caption"]
        unchanged = [record for record in detail["records"] if record["action"] == "unchanged"]
        file_report = {
            "relative_path": output.relative_path,
            "current_sha256": pipeline.sha256_bytes(old_bytes),
            "desired_sha256": pipeline.sha256_bytes(new_bytes),
            "changed": old_bytes != new_bytes,
            "current_standalone_images": len(standalone_images(old_text.splitlines())),
            "generated_figure_pairs": detail["generated_figure_pairs"],
            "moved_figures": len(moved),
            "unchanged_figures": len(unchanged),
            "uncertain": detail["uncertain"],
            "examples": moved[:3],
        }
        file_reports.append(file_report)
        total_pairs += detail["generated_figure_pairs"]
        total_moved += len(moved)
        total_unchanged += len(unchanged)
        all_uncertain.extend({"path": output.relative_path, **item} for item in detail["uncertain"])
    return {
        "mode": "preview",
        "timestamp": utc_stamp(),
        "generator": GENERATOR,
        "helper_version": VERSION,
        "vault": str(context["vault"]),
        "book": context["book"],
        "config_path": str(context["config_path"]),
        "config_sha256": pipeline.sha256_file(context["config_path"]),
        "source": context["source_info"],
        "scope": {"only_chapters": args.chapters.split(",")},
        "files": file_reports,
        "totals": {
            "chapters": len(file_reports),
            "generated_figure_pairs": total_pairs,
            "moved_figures": total_moved,
            "unchanged_figures": total_unchanged,
            "uncertain": len(all_uncertain),
            "changed_files": sum(1 for item in file_reports if item["changed"]),
        },
        "uncertain": all_uncertain,
        "safety": {
            "only_standalone_images_and_figure_blocks": True,
            "inline_images_touched": False,
            "source_pdf_written": False,
            "attachments_written": False,
            "manual_text_rewritten": False,
        },
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    pipeline.atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def default_report_path(preview: dict[str, Any], kind: str) -> Path:
    reports = pipeline.resource_root(
        Path(preview["vault"]), "Reports", preview["book"],
        pipeline.load_config(Path(preview["config_path"])),
    )
    reports.mkdir(parents=True, exist_ok=True)
    return reports / f"full-image-coordinate-{kind}-{preview['timestamp']}.json"


def backup_targets(preview: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    vault = Path(preview["vault"])
    config = Path(preview["config_path"])
    config_data = pipeline.load_config(config)
    backup_root = pipeline.resource_root(vault, "Backups", preview["book"], config_data)
    backup_root.mkdir(parents=True, exist_ok=True)
    timestamp = utc_stamp()
    backup_path = backup_root / f"pre-image-coordinate-{timestamp}.zip"
    files: list[dict[str, Any]] = []
    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in [item["relative_path"] for item in preview["files"]] + [pipeline.vault_relative(vault, config)]:
            target = pipeline.vault_path(vault, relative)
            data = target.read_bytes()
            archive.writestr(relative, data)
            files.append({"relative_path": relative, "sha256": pipeline.sha256_bytes(data)})
        archive.writestr(
            "backup-manifest.json",
            (json.dumps({"created_at": timestamp, "book": preview["book"], "files": files}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    return backup_path, {"path": str(backup_path), "files": files, "testzip": zip_test(backup_path)}


def zip_test(path: Path) -> str | None:
    with zipfile.ZipFile(path, "r") as archive:
        return archive.testzip()


def apply_preview(args: argparse.Namespace) -> dict[str, Any]:
    if not args.preview:
        raise RepairError("apply requires --preview pointing to a reviewed preview JSON")
    preview_path = Path(args.preview).resolve()
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    if preview.get("mode") != "preview":
        raise RepairError("The supplied report is not an image-coordinate preview.")
    fresh = build_preview(args)
    if fresh["source"]["sha256"] != preview["source"]["sha256"]:
        raise RepairError("Source PDF hash changed since preview.")
    if fresh["config_sha256"] != preview["config_sha256"]:
        raise RepairError("Configuration hash changed since preview.")
    old_by_path = {item["relative_path"]: item for item in preview["files"]}
    fresh_by_path = {item["relative_path"]: item for item in fresh["files"]}
    if old_by_path.keys() != fresh_by_path.keys():
        raise RepairError("Selected chapter set changed since preview.")
    for relative, old_item in old_by_path.items():
        if old_item["current_sha256"] != fresh_by_path[relative]["current_sha256"]:
            raise RepairError(f"Target changed since preview: {relative}")
        if old_item["desired_sha256"] != fresh_by_path[relative]["desired_sha256"]:
            raise RepairError(f"Repair result changed since preview: {relative}")
    if fresh["totals"]["uncertain"]:
        raise RepairError("Uncertain image/caption relationships remain; review the preview before apply.")
    backup_path, backup = backup_targets(preview)
    context = pipeline.prepare_context(make_args(args, "dry-run"))
    stages = pipeline.stages_from_config(context["config"], None)
    outputs, _details = pipeline.build_outputs(
        context["vault"], context["book"], context["config"], context["source"],
        context["source"], context["source_info"]["sha256"], stages, args.chapters, None,
    )
    output_by_path = {output.relative_path: output for output in outputs}
    written: list[str] = []
    post_write_hashes: dict[str, str] = {}
    for relative, item in fresh_by_path.items():
        if not item["changed"]:
            continue
        target = pipeline.vault_path(Path(preview["vault"]), relative)
        # Rebuild the exact candidate once more, then preserve existing line endings.
        generated = output_by_path[relative]
        old_bytes = target.read_bytes()
        new_text, _detail = apply_pairs(old_bytes.decode("utf-8"), generated.content.decode("utf-8"))
        if b"\r\n" in old_bytes:
            new_bytes = new_text.replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8")
        else:
            new_bytes = new_text.encode("utf-8")
        if pipeline.sha256_bytes(new_bytes) != item["desired_sha256"]:
            raise RepairError(f"Candidate hash changed before write: {relative}")
        pipeline.atomic_write(target, new_bytes)
        actual_hash = pipeline.sha256_file(target)
        if actual_hash != item["desired_sha256"]:
            raise RepairError(f"Post-write hash verification failed: {relative}")
        post_write_hashes[relative] = actual_hash
        written.append(relative)
    reports = pipeline.resource_root(Path(preview["vault"]), "Reports", preview["book"], pipeline.load_config(Path(preview["config_path"])))
    report = {
        "mode": "apply",
        "timestamp": utc_stamp(),
        "generator": GENERATOR,
        "helper_version": VERSION,
        "preview": str(preview_path),
        "book": preview["book"],
        "source_sha256": fresh["source"]["sha256"],
        "scope": fresh["scope"],
        "written_files": written,
        "post_write_hashes": post_write_hashes,
        "backup": backup,
        "verification": {
            "source_pdf_unchanged": True,
            "all_written_hashes_match_preview": True,
            "uncertain_count": 0,
            "inline_images_touched": False,
        },
    }
    report_path = reports / f"full-image-coordinate-apply-{report['timestamp']}.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("preview", "apply"):
        child = sub.add_parser(name)
        child.add_argument("vault", type=Path)
        child.add_argument("--book", required=True)
        child.add_argument("--chapters", required=True, help="Comma-separated chapter numbers")
        child.add_argument("--config")
        child.add_argument("--source")
        if name == "preview":
            child.add_argument("--report-out")
        else:
            child.add_argument("--preview", required=True)
            child.add_argument("--confirm-apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        if args.command == "preview":
            report = build_preview(args)
            path = Path(args.report_out).resolve() if args.report_out else default_report_path(report, "preview")
            write_json(path, report)
            print(json.dumps({"mode": "preview", "report": str(path), "totals": report["totals"]}, ensure_ascii=False, indent=2))
            return 0 if report["totals"]["uncertain"] == 0 else 3
        if not args.confirm_apply:
            raise RepairError("apply requires --confirm-apply")
        report = apply_preview(args)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (RepairError, pipeline.PipelineError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
