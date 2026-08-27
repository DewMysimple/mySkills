#!/usr/bin/env python3
"""Isolated smoke tests for the PDF-to-Obsidian Skill."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from reportlab.pdfgen import canvas

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from markdown_tables import transform_definition_lists  # noqa: E402
import pdf_book_pipeline as pipeline  # noqa: E402


class PipelineTests(unittest.TestCase):
    def make_pdf(self, path: Path, pages: list[str], image_only: bool = False) -> None:
        pdf = canvas.Canvas(str(path))
        for text in pages:
            if image_only:
                pdf.rect(100, 500, 200, 100, fill=1)
            else:
                y = 750
                for line in text.splitlines():
                    pdf.drawString(60, y, line)
                    y -= 18
            pdf.showPage()
        pdf.save()

    def test_table_transform_preserves_interrupted_text_and_merges_wrap(self) -> None:
        source = (
            "## Skills\n\n"
            "- **Animation**—Modern games are full of characters that need to seem alive\n"
            "  and responsive.\n\n"
            "- **Anthropology**: You study your audience.\n\n"
            "A paragraph remains here.\n\n"
            "- **Only one**—This must remain a list.\n"
        )
        transformed, audit = transform_definition_lists(source)
        self.assertIn("| Term / Item | Original description |", transformed)
        self.assertIn("alive and responsive", transformed)
        self.assertIn("A paragraph remains here.", transformed)
        self.assertIn("- **Only one**—This must remain a list.", transformed)
        self.assertEqual(audit["tables_count"], 1)
        self.assertEqual(audit["rows_transformed"], 2)

    def test_wrapped_pdf_outline_titles_are_recognized_as_chapters(self) -> None:
        class OutlineOnlyDocument:
            page_count = 100

            def get_toc(self, simple: bool = True) -> list[list[object]]:
                return [
                    [1, "Chapter 1: Creating Your First Unreal\nC++ Game", 24],
                    [1, "Chapter 2: Editing C++ Code in\nVisual Studio", 42],
                    [1, "Chapter 3: Learning C++ and Object-Oriented Programming", 64],
                ]

        chapters = pipeline.infer_chapters(OutlineOnlyDocument(), {})
        self.assertEqual([(item.number, item.start_page, item.end_page) for item in chapters], [
            ("1", 24, 41),
            ("2", 42, 63),
            ("3", 64, 100),
        ])
        self.assertEqual(chapters[0].title, "Creating Your First Unreal C++ Game")

    def test_text_pdf_dry_run_and_apply_with_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "Vault"
            source_dir = vault / "File" / "PDF" / "Demo Book"
            config_dir = vault / "File" / "Config" / "Demo Book"
            source_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            pdf_path = source_dir / "Demo Book.pdf"
            self.make_pdf(
                pdf_path,
                ["Chapter 1: The Beginning\n- **Animation**—Give life\n- **Games**—Create play"],
            )
            (config_dir / "book-config.yaml").write_text(
                "modules:\n  chapterize: true\n  tables: true\n  attachments: false\n  lens: false\n  moc: true\n",
                encoding="utf-8",
            )
            args = pipeline.build_parser().parse_args([
                "dry-run", str(vault), "--book", "Demo Book",
            ])
            summary = pipeline.build_dry_run(args)
            self.assertEqual(summary["tables_count"], 1)
            self.assertEqual(summary["rows_transformed"], 2)
            self.assertFalse(summary["conflicts"])

            apply_args = pipeline.build_parser().parse_args([
                "apply", str(vault), "--book", "Demo Book", "--confirm-apply",
            ])
            self.assertEqual(pipeline.command_apply(apply_args), 0)
            reports = vault / "File" / "Reports" / "Demo Book"
            backups = vault / "File" / "Backups" / "Demo Book"
            self.assertTrue((reports / "latest-manifest.json").exists())
            backup = next(backups.glob("pre-*.zip"))
            audit_args = pipeline.build_parser().parse_args([
                "audit", str(vault), "--book", "Demo Book",
            ])
            self.assertEqual(pipeline.command_audit(audit_args), 0)

            rollback_args = pipeline.build_parser().parse_args([
                "rollback", str(vault), "--book", "Demo Book", "--backup", str(backup), "--confirm-rollback",
            ])
            self.assertEqual(pipeline.command_rollback(rollback_args), 0)
            self.assertFalse(any(vault.glob("00_Book/*.md")))

    def test_manual_file_conflict_is_reported_before_apply(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "Vault"
            source_dir = vault / "File" / "PDF" / "Demo Book"
            config_dir = vault / "File" / "Config" / "Demo Book"
            output_dir = vault / "00_Book"
            source_dir.mkdir(parents=True)
            config_dir.mkdir(parents=True)
            output_dir.mkdir()
            self.make_pdf(source_dir / "Demo Book.pdf", ["Chapter 1: Start\nOriginal text"])
            (output_dir / "Chapter 1 - Start.md").write_text("# A manual note\n", encoding="utf-8")
            args = pipeline.build_parser().parse_args([
                "dry-run", str(vault), "--book", "Demo Book",
            ])
            summary = pipeline.build_dry_run(args)
            self.assertEqual(len(summary["conflicts"]), 1)
            self.assertEqual(summary["conflicts"][0]["action"], "update")

    def test_scan_pdf_is_stopped_without_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "Vault"
            source_dir = vault / "File" / "PDF" / "Scan Book"
            source_dir.mkdir(parents=True)
            self.make_pdf(source_dir / "Scan Book.pdf", ["", ""], image_only=True)
            args = pipeline.build_parser().parse_args([
                "dry-run", str(vault), "--book", "Scan Book",
            ])
            with self.assertRaises(pipeline.PipelineError):
                pipeline.build_dry_run(args)

    def test_external_source_is_copied_only_with_apply_and_can_be_rolled_back(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vault = root / "Vault"
            external = root / "outside.pdf"
            config_dir = vault / "File" / "Config" / "External Book"
            config_dir.mkdir(parents=True)
            self.make_pdf(external, ["Chapter 1: External\nSource text"])
            blocked_args = pipeline.build_parser().parse_args([
                "dry-run", str(vault), "--book", "External Book", "--source", str(external),
            ])
            blocked = pipeline.build_dry_run(blocked_args)
            self.assertEqual(blocked["conflicts"][0]["type"], "external-source-not-managed")
            dry_args = pipeline.build_parser().parse_args([
                "dry-run", str(vault), "--book", "External Book", "--source", str(external), "--copy-source",
            ])
            summary = pipeline.build_dry_run(dry_args)
            self.assertTrue(summary["copy_source_target"].endswith("External Book\\outside.pdf"))
            self.assertFalse((vault / "File" / "PDF" / "External Book" / "outside.pdf").exists())

            apply_args = pipeline.build_parser().parse_args([
                "apply", str(vault), "--book", "External Book", "--source", str(external), "--copy-source", "--confirm-apply",
            ])
            self.assertEqual(pipeline.command_apply(apply_args), 0)
            managed_source = vault / "File" / "PDF" / "External Book" / "outside.pdf"
            self.assertTrue(managed_source.exists())
            self.assertTrue(external.exists())
            backup = next((vault / "File" / "Backups" / "External Book").glob("pre-*.zip"))
            rollback_args = pipeline.build_parser().parse_args([
                "rollback", str(vault), "--book", "External Book", "--backup", str(backup), "--confirm-rollback",
            ])
            self.assertEqual(pipeline.command_rollback(rollback_args), 0)
            self.assertFalse(managed_source.exists())
            self.assertTrue(external.exists())

    def test_courier_code_is_fenced_as_cpp(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "code.pdf"
            pdf = canvas.Canvas(str(pdf_path), pagesize=(500, 500))
            pdf.setFont("Courier", 10)
            for index, line in enumerate(["#include <iostream>", "int main() {", "  return 0;", "}"]):
                pdf.drawString(60, 420 - index * 16, line)
            pdf.showPage()
            pdf.save()
            document = pipeline.require_pdf_runtime().open(str(pdf_path))
            try:
                config = {"code_blocks": {"enabled": True, "languages": {"cpp": "cpp", "default": "text"}}}
                markdown = pipeline.page_markdown_from_spans(document[0], config=config)
            finally:
                document.close()
            self.assertIn("```cpp", markdown)
            self.assertIn("int main()", markdown)
            self.assertIn("  return 0;", markdown)

    def test_visual_table_uses_drawn_grid_and_merges_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "visual-table.pdf"
            pdf = canvas.Canvas(str(pdf_path), pagesize=(400, 400))
            for page_index, rows in enumerate([
                [("Data type", "Size (bytes)", "Description"), ("int", "4", "Signed integer"), ("float", "4", "Floating point")],
                [("Data type", "Size (bytes)", "Description"), ("string", "varied", "Text with | pipe"), ("bool", "1", "Boolean")],
            ]):
                x = [50, 120, 180, 350]
                y = [300, 270, 220, 170, 100]
                for xpos in x:
                    pdf.line(xpos, 100, xpos, 300)
                for ypos in y:
                    pdf.line(50, ypos, 350, ypos)
                baselines = [282, 250, 200]
                for row_index, row in enumerate(rows):
                    for col_index, value in enumerate(row):
                        pdf.setFont("Helvetica", 9)
                        pdf.drawString(x[col_index] + 5, baselines[row_index], value)
                pdf.showPage()
            pdf.save()
            document = pipeline.require_pdf_runtime().open(str(pdf_path))
            try:
                config = {
                    "visual_tables": {
                        "enabled": True,
                        "regions": [{
                            "id": "demo-grid",
                            "start_page": 1,
                            "end_page": 2,
                            "columns": [45, 120, 180, 355],
                            "headers": ["Data type", "Size (bytes)", "Description"],
                            "page_y_ranges": {"1": [95, 305], "2": [95, 305]},
                        }],
                    }
                }
                tables, skip_regions = pipeline.extract_visual_tables(document, config)
            finally:
                document.close()
            self.assertEqual(len(tables), 1)
            self.assertEqual(tables[0]["status"], "converted")
            self.assertEqual([row[0] for row in tables[0]["rows"]], ["int", "float", "string", "bool"])
            self.assertIn("Text with \\| pipe", tables[0]["markdown"])
            self.assertEqual(sorted(skip_regions), [1, 2])

    def test_cross_page_code_fences_are_merged_conservatively(self) -> None:
        source = (
            "> [Source PDF, p. 1](book.pdf#page=1)\n\n"
            "```cpp\nint first = 1;\n```\n\n"
            "> [Source PDF, p. 2](book.pdf#page=2)\n\n"
            "```cpp\nint second = 2;\n```\n"
        )
        merged = pipeline.merge_adjacent_code_fences(source)
        self.assertEqual(merged.count("```cpp"), 1)
        self.assertEqual(merged.count("```"), 2)
        self.assertIn("int first = 1;\nint second = 2;", merged)

    def test_markdown_link_audit_allows_parentheses_in_pdf_filename(self) -> None:
        targets = list(pipeline.markdown_link_targets("[PDF](../Book (Author).pdf#page=2)"))
        self.assertEqual(targets, ["../Book (Author).pdf#page=2"])


if __name__ == "__main__":
    unittest.main()
