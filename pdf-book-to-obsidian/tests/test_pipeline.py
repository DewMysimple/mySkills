#!/usr/bin/env python3
"""Isolated smoke tests for the PDF-to-Obsidian Skill."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from reportlab.pdfgen import canvas

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from markdown_tables import transform_definition_lists  # noqa: E402
import markdown_layout_repair as layout_repair  # noqa: E402
import toc_table_repair as toc_repair  # noqa: E402
from markdown_layout_repair import repair_text  # noqa: E402
from markdown_obsidian import (  # noqa: E402
    convert_callouts_text,
    inline_image_syntax,
    render_file_embed,
    render_note_link,
)
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

    def test_layout_repair_keeps_intentional_emphasis_and_cleans_split_spans(self) -> None:
        source = (
            "### **What is the difference between C++ programming and C++ ** **scripting?**\n"
            "The **Operator** **Operation** labels remain separate.\n"
            "The **Desktop ** **development with C++ **group is one phrase.\n"
            "- ** ****C++ profiling tools**\n"
            "1. First step\n\n2. Second step\n\n3. Third step\n"
        )
        transformed, changes, uncertain = repair_text(source, "Chapter.md")
        self.assertIn("### What is the difference between C++ programming and C++ scripting?", transformed)
        self.assertIn("The **Operator** **Operation** labels remain separate.", transformed)
        self.assertIn("The **Desktop development with C++** group is one phrase.", transformed)
        self.assertIn("- **C++ profiling tools**", transformed)
        self.assertIn("1. First step\n2. Second step\n3. Third step", transformed)
        self.assertFalse(uncertain)
        self.assertGreaterEqual(sum(change.kind == "broken-emphasis" for change in changes), 2)

    def test_layout_repair_formats_keyboard_shortcuts_and_subheadings(self) -> None:
        source = (
            "### Useful editing hotkeys\n\n"
            "***Copy and paste***\n\n"
            "Use the following keys:\n\n"
            "The **C++** label remains normal emphasis.\n\n"
            "- * **Ctrl* + *C*: Copies the selected text\n"
            "- * **Ctrl* + *Shift* + *F*: Searches for a keyword\n\n"
            "***Go to operations***\n\n"
            "- * **F12*, *Ctrl* + *F12*: Goes to the definition\n"
        )
        transformed, changes, uncertain = repair_text(
            source,
            "Chapter.md",
            shortcut_style="inline-code",
        )
        self.assertIn("#### Copy and paste", transformed)
        self.assertIn("#### Go to operations", transformed)
        self.assertIn("- `Ctrl + C`: Copies the selected text", transformed)
        self.assertIn("- `Ctrl + Shift + F`: Searches for a keyword", transformed)
        self.assertIn("- `F12`, `Ctrl + F12`: Goes to the definition", transformed)
        self.assertIn("The **C++** label remains normal emphasis.", transformed)
        self.assertNotIn("- * **", transformed)
        self.assertFalse(any(item["kind"].startswith("shortcut") for item in uncertain))
        self.assertEqual(
            sum(change.kind == "shortcut-inline-code" for change in changes),
            3,
        )
        self.assertEqual(
            sum(change.kind == "shortcut-subheading" for change in changes),
            2,
        )
        repeated, repeated_changes, repeated_uncertain = repair_text(
            transformed,
            "Chapter.md",
            shortcut_style="inline-code",
        )
        self.assertEqual(repeated, transformed)
        self.assertFalse(repeated_changes)
        self.assertEqual(repeated_uncertain, uncertain)

    def test_layout_repair_preserves_shortcuts_when_style_is_not_selected(self) -> None:
        source = (
            "### Useful editing hotkeys\n\n"
            "***Copy and paste***\n\n"
            "- * **Ctrl* + *C*: Copies the selected text\n"
        )
        transformed, changes, uncertain = repair_text(source, "Chapter.md")
        self.assertEqual(transformed, source)
        self.assertFalse(changes)
        self.assertFalse(uncertain)

    def test_layout_repair_normalizes_source_refs_and_deduplicates_header_metadata(self) -> None:
        source = (
            "> [Source PDF, p. 14](book.pdf#page=14)\n\n"
            "# Preface\n\n"
            "> [Source PDF, p. 14](book.pdf#page=14)\n\n"
            "A paragraph.\n\n"
            "> [Source PDF, p. 15](book.pdf#page=15)\n"
        )
        transformed, changes, uncertain = repair_text(
            source,
            "06_Preface.md",
            source_reference_style="plain-blockquote",
        )
        self.assertEqual(transformed.count("> Source PDF, p. 14"), 1)
        self.assertEqual(transformed.count("> Source PDF, p. 15"), 1)
        self.assertNotIn("[Source PDF, p. 14](", transformed)
        self.assertTrue(any(change.kind == "source-reference-style" for change in changes))
        self.assertTrue(any(change.kind == "duplicate-source-reference" for change in changes))
        self.assertFalse(uncertain)

    def test_layout_repair_cleans_toc_fragments_without_rebuilding_entries(self) -> None:
        source = (
            "# Table of Contents\n\n"
            "> [Source PDF, p. 8](book.pdf#page=8)\n\n"
            "### **Part 1 – Getting Started with Unreal C++ ** **Scripting**\n\n"
            "### **1**\n\n"
            "## **Creating Your First Unreal C++ Game\x08** **3**\n\n"
            "**Technical requirements\x08** **3** **Understanding C++ scripting in Unreal\x08**** ****4**\n"
        )
        transformed, changes, uncertain = repair_text(
            source,
            "00_Paratext/05_Table of Contents.md",
            source_reference_style="plain-blockquote",
        )
        self.assertIn("### Part 1 – Getting Started with Unreal C++ Scripting", transformed)
        self.assertIn("### 1", transformed)
        self.assertIn("## Creating Your First Unreal C++ Game — p. 3", transformed)
        self.assertIn("Technical requirements 3 Understanding C++ scripting in Unreal 4", transformed)
        self.assertNotIn("**", transformed)
        self.assertNotIn("\x08", transformed)
        self.assertTrue(any(change.kind == "toc-format" for change in changes))
        self.assertFalse(uncertain)
        repeated, repeated_changes, repeated_uncertain = repair_text(
            transformed,
            "00_Paratext/05_Table of Contents.md",
            source_reference_style="plain-blockquote",
        )
        self.assertEqual(repeated, transformed)
        self.assertFalse(repeated_changes)
        self.assertEqual(repeated_uncertain, uncertain)

    def test_layout_repair_removes_only_redundant_leading_heading(self) -> None:
        source = (
            "> [Source PDF, p. 22](book.pdf#page=22)\n\n"
            "# Part 1 - Getting Started with Unreal C++ Scripting\n\n"
            "> [Source PDF, p. 22](book.pdf#page=22)\n\n"
            "# Part 1 – Getting Started with Unreal C++ Scripting\n\n"
            "Introductory text.\n"
        )
        transformed, changes, uncertain = repair_text(
            source,
            "01_Part 1 - Getting Started with Unreal C++ Scripting/00_Part Overview.md",
            source_reference_style="plain-blockquote",
        )
        self.assertEqual(
            transformed.count("# Part 1 - Getting Started with Unreal C++ Scripting"),
            1,
        )
        self.assertTrue(any(change.kind == "duplicate-heading" for change in changes))
        self.assertFalse(uncertain)

    def test_layout_repair_closes_clear_italic_list_fragment(self) -> None:
        source = "- * Chapter 1*, *Creating Your First Unreal C++ Game*\n*Figure 1.1* remains italic.\n"
        transformed, changes, uncertain = repair_text(source, "00_Part Overview.md")
        self.assertIn("- *Chapter 1*, *Creating Your First Unreal C++ Game*", transformed)
        self.assertIn("*Figure 1.1* remains italic.", transformed)
        self.assertTrue(any(change.kind == "broken-emphasis" for change in changes))
        self.assertFalse(uncertain)
        repeated, repeated_changes, repeated_uncertain = repair_text(
            transformed,
            "00_Part Overview.md",
        )
        self.assertEqual(repeated, transformed)
        self.assertFalse(repeated_changes)
        self.assertEqual(repeated_uncertain, uncertain)

    def test_layout_repair_moves_figure_source_to_caption(self) -> None:
        source = (
            "A paragraph.\n\n"
            "> [Source PDF, p. 37](book.pdf#page=37)\n\n"
            "![[Figure-p0037-777.jpeg]]\n\n"
            "> Figure 1.14 – Adding a new C++ class from the Character class\n"
        )
        transformed, changes, uncertain = repair_text(source, "Chapter.md")
        self.assertNotIn("> [Source PDF, p. 37]", transformed)
        self.assertIn("![[Figure-p0037-777.jpeg]]\n\n> Figure 1.14 – Adding a new C++ class from the Character class ([Source PDF, p. 37](book.pdf#page=37))", transformed)
        self.assertTrue(any(change.kind == "figure-source-to-caption" for change in changes))
        self.assertFalse(any(change.kind == "figure-caption" for change in changes))
        self.assertFalse(uncertain)

    def test_layout_repair_inserts_figure_caption_separator(self) -> None:
        source = (
            "![[Figure-p0037-777.jpeg]]\n"
            "Figure 1.14 – Adding a new C++ class from the Character class\n"
        )
        transformed, changes, uncertain = repair_text(source, "Chapter.md")
        self.assertIn(
            "![[Figure-p0037-777.jpeg]]\n\n> Figure 1.14 – Adding a new C++ class from the Character class",
            transformed,
        )
        self.assertTrue(any(change.kind == "figure-spacing" for change in changes))
        self.assertFalse(uncertain)

    def test_layout_repair_apply_creates_recoverable_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            book = root / "Book"
            book.mkdir()
            note = book / "Chapter 01.md"
            original = "### **A heading**\n\n1. First\n\n2. Second\n"
            note.write_text(original, encoding="utf-8")
            original_bytes = note.read_bytes()
            report = layout_repair.preview(book)
            backup = root / "pre-layout-repair.zip"
            result = layout_repair.apply_repairs(book, report, backup)
            self.assertEqual(result["files_changed"], 1)
            self.assertIn("### A heading\n\n1. First\n2. Second", note.read_text(encoding="utf-8"))
            with zipfile.ZipFile(backup) as archive:
                self.assertEqual(archive.read("Chapter 01.md"), original_bytes)

    def test_layout_repair_include_limits_preview_to_selected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            book = Path(temporary) / "Book"
            book.mkdir()
            selected = book / "Chapter 01.md"
            other = book / "Chapter 02.md"
            selected.write_text("**Note** Selected text.\n", encoding="utf-8")
            other.write_text("**Note** Other text.\n", encoding="utf-8")

            report = layout_repair.preview(book, include=["Chapter 01.md"])

            self.assertEqual(report["scope"], "selected files")
            self.assertEqual(report["files_scanned"], 1)
            self.assertEqual(report["files"][0]["relative_path"], "Chapter 01.md")
            with self.assertRaises(ValueError):
                layout_repair.preview(book, include=["../outside.md"])

    def test_layout_repair_collapses_only_outside_code_fence(self) -> None:
        source = "Before\n\n\n```cpp\n\n\nint main() {}\n```\n\n\nAfter\n"
        transformed, _, _ = repair_text(source, "Chapter.md")
        self.assertIn("Before\n\n```cpp\n\n\nint main() {}\n```\n\nAfter", transformed)

    def test_layout_repair_removes_isolated_roman_footer_before_source_marker(self) -> None:
        source = (
            "---\n"
            "title: Preface\n"
            "---\n"
            "Body text.\n\n"
            "xviii\n\n"
            "> Source PDF, p. 19\n"
        )
        transformed, changes, uncertain = repair_text(source, "00_Paratext/06_Preface.md")
        self.assertNotIn("xviii", transformed)
        self.assertTrue(any(change.kind == "page-chrome" for change in changes))
        self.assertFalse(uncertain)

    def test_unordered_lists_compact_wrapped_items_and_preserve_markers(self) -> None:
        source = (
            "- Non-engineer game developers, such as game designers and artists\n"
            "  who aspire to learn C++.\n\n"
            "* Software engineers who wish to acquire the necessary skills.\n\n"
            "+ Students interested in Unreal C++.\n"
        )
        transformed, changes, uncertain = repair_text(source, "Preface.md")
        self.assertIn(
            "- Non-engineer game developers, such as game designers and artists\n"
            "  who aspire to learn C++.\n"
            "* Software engineers who wish to acquire the necessary skills.\n"
            "+ Students interested in Unreal C++.",
            transformed,
        )
        self.assertEqual(sum(change.kind == "unordered-list-spacing" for change in changes), 2)
        self.assertFalse(uncertain)
        repeated, repeated_changes, repeated_uncertain = repair_text(transformed, "Preface.md")
        self.assertEqual(repeated, transformed)
        self.assertFalse(repeated_changes)
        self.assertEqual(repeated_uncertain, uncertain)

    def test_unordered_lists_keep_spacing_for_structural_items(self) -> None:
        source = (
            "- Plain item one\n\n"
            "- Plain item two\n\n"
            "- Code item\n\n"
            "  ```cpp\n"
            "  int value = 1;\n"
            "  ```\n\n"
            "- Image item\n\n"
            "  ![[image.png]]\n\n"
            "- Parent item\n\n"
            "  - Nested item\n\n"
            "- Multi paragraph item\n\n"
            "  A second paragraph.\n\n"
            "- Final item\n\n"
            "Paragraph after the list.\n"
        )
        transformed, changes, uncertain = repair_text(source, "Chapter.md")
        self.assertIn("- Plain item one\n- Plain item two", transformed)
        self.assertIn("  ```cpp\n  int value = 1;\n  ```\n\n- Image item", transformed)
        self.assertIn("  ![[image.png]]\n\n- Parent item", transformed)
        self.assertIn("  - Nested item\n\n- Multi paragraph item", transformed)
        self.assertIn("  A second paragraph.\n\n- Final item", transformed)
        self.assertNotIn("Final item\nParagraph after", transformed)
        self.assertGreaterEqual(sum(change.kind == "unordered-list-spacing" for change in changes), 1)
        self.assertFalse(uncertain)

    def test_unordered_list_ambiguous_boundary_is_reported_and_preserved(self) -> None:
        source = "- First item\n\nPossible paragraph boundary.\n\n- Second item\n"
        transformed, changes, uncertain = repair_text(source, "Chapter.md")
        self.assertEqual(transformed, source)
        self.assertFalse(any(change.kind == "unordered-list-spacing" for change in changes))
        self.assertEqual(uncertain[0]["kind"], "unordered-list-spacing")
        self.assertIn("ambiguous", str(uncertain[0]["reason"]))

    def test_obsidian_callouts_convert_labels_without_touching_prose_or_urls(self) -> None:
        source = (
            "**Note** Keep `https://` `example.com/path` unchanged.\n\n"
            "Note that ordinary prose is not a callout.\n\n"
            "**Tip** Use the shortcut.\n\n"
            "**Warning** Save your work first.\n"
        )
        transformed, changes, uncertain = convert_callouts_text(source)
        self.assertIn("> [!NOTE]\n> \n> Keep `https://` `example.com/path` unchanged.", transformed)
        self.assertIn("Note that ordinary prose is not a callout.", transformed)
        self.assertIn("> [!TIP]\n> \n> Use the shortcut.", transformed)
        self.assertIn("> [!WARNING]\n> \n> Save your work first.", transformed)
        self.assertEqual(len(changes), 3)
        self.assertFalse(uncertain)
        repeated, repeated_changes, repeated_uncertain = convert_callouts_text(transformed)
        self.assertEqual(repeated, transformed)
        self.assertFalse(repeated_changes)
        self.assertFalse(repeated_uncertain)

    def test_tips_or_important_notes_becomes_titled_note_callout(self) -> None:
        source = "**Tips or important notes**\n\nAppear like this.\n"
        transformed, changes, uncertain = convert_callouts_text(source)
        self.assertIn("> [!NOTE] Tips or important notes", transformed)
        self.assertIn("> Appear like this.", transformed)
        self.assertEqual(len(changes), 1)
        self.assertFalse(uncertain)

    def test_obsidian_callout_absorbs_continuous_prose_but_stops_at_blocks(self) -> None:
        source = (
            "**Note**\n\n"
            "First paragraph.\n\n"
            "Second paragraph.\n\n"
            "## Next section\n\n"
            "- A list item\n"
        )
        transformed, changes, uncertain = convert_callouts_text(source)
        self.assertIn(
            "> [!NOTE]\n> \n> First paragraph.\n> \n> Second paragraph.\n\n## Next section",
            transformed,
        )
        self.assertIn("- A list item", transformed)
        self.assertEqual(len(changes), 1)
        self.assertFalse(uncertain)

    def test_obsidian_callout_preserves_nested_structures_and_reports_them(self) -> None:
        source = (
            "- **Note** A list item note.\n\n"
            "| **Warning** | Text |\n"
            "| --- | --- |\n\n"
            "```text\n"
            "**Example** stays code\n"
            "```\n"
        )
        transformed, changes, uncertain = convert_callouts_text(source)
        self.assertEqual(transformed, source)
        self.assertFalse(changes)
        self.assertGreaterEqual(len(uncertain), 2)

    def test_repair_and_generation_use_the_same_callout_shape(self) -> None:
        source = "**Important** Read this first.\n"
        repaired, changes, uncertain = repair_text(source, "Chapter.md")
        generated, _, _ = convert_callouts_text(source)
        self.assertEqual(repaired, generated)
        self.assertIn("> [!IMPORTANT]", repaired)
        self.assertTrue(any(change.kind == "callout" for change in changes))
        self.assertFalse(uncertain)

    def test_pdf_generation_applies_callouts_to_extracted_page_text(self) -> None:
        class Rect:
            height = 800.0

        class Page:
            rect = Rect()

            def get_text(self, mode: str, sort: bool = True) -> dict[str, object]:
                return {
                    "blocks": [{
                        "bbox": (60.0, 100.0, 500.0, 114.0),
                        "lines": [{
                            "bbox": (60.0, 100.0, 500.0, 114.0),
                            "spans": [{
                                "text": "**Note** Generated page note.",
                                "bbox": (60.0, 100.0, 500.0, 114.0),
                                "size": 10,
                                "font": "Helvetica",
                            }],
                        }],
                    }],
                }

        markdown = pipeline.render_page_content(
            Page(),
            "Chapter 1",
            {"output": {"page_links": "none", "markdown_baseline": "obsidian"}},
        )
        self.assertEqual(markdown, "> [!NOTE]\n> \n> Generated page note.")

    def test_obsidian_and_commonmark_link_baselines(self) -> None:
        obsidian = {"output": {"markdown_baseline": "obsidian"}}
        commonmark = {"output": {"markdown_baseline": "commonmark"}}
        self.assertEqual(
            render_note_link("Chapters/Chapter 01.md", "Chapter 1", obsidian),
            "[[Chapters/Chapter 01|Chapter 1]]",
        )
        self.assertEqual(
            render_note_link("Chapters/Chapter 01.md", "Chapter 1", commonmark),
            "[Chapter 1](Chapters/Chapter%2001.md)",
        )
        self.assertEqual(
            render_file_embed("Assets/Figure 1.png", commonmark, markdown_target="../Assets/Figure 1.png"),
            "![Figure 1](../Assets/Figure%201.png)",
        )

    def test_pdf_generation_uses_compact_unordered_list_spacing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "list.pdf"
            pdf = canvas.Canvas(str(pdf_path))
            pdf.setFont("Helvetica", 10)
            pdf.drawString(60, 750, "- First generated item")
            pdf.drawString(60, 730, "- Second generated item")
            pdf.showPage()
            pdf.save()
            document = pipeline.require_pdf_runtime().open(str(pdf_path))
            try:
                markdown = pipeline.render_page_content(
                    document[0],
                    "",
                    {"output": {"page_links": "chapter"}},
                )
            finally:
                document.close()
        self.assertIn("- First generated item\n- Second generated item", markdown)

    def test_coordinate_image_events_keep_page_order_and_styles(self) -> None:
        class Rect:
            height = 800.0

        class Page:
            rect = Rect()

            def get_text(self, mode: str, sort: bool = True) -> dict[str, object]:
                def block(text: str, y: float) -> dict[str, object]:
                    return {
                        "bbox": (60.0, y, 500.0, y + 14.0),
                        "lines": [{
                            "bbox": (60.0, y, 500.0, y + 14.0),
                            "spans": [{"text": text, "bbox": (60.0, y, 500.0, y + 14.0), "size": 10, "font": "Helvetica"}],
                        }],
                    }

                return {"blocks": [
                    block("Top paragraph", 100),
                    block("Figure 2.7 – VS Build and the Output window", 420),
                    block("Bottom paragraph", 600),
                ]}

        class Document:
            page_count = 1

            def __getitem__(self, index: int) -> Page:
                return Page()

            def get_toc(self, simple: bool = True) -> list[list[object]]:
                return []

        config = {
            "output": {
                "page_links": "none",
                "source_reference_style": "plain-blockquote",
                "figure_caption_style": "blockquote",
                "image_placement": "pdf-coordinate",
            }
        }
        markdown = pipeline.render_pages(
            Document(),
            "Chapter 2",
            1,
            1,
            Path("C:/book/source.pdf"),
            Path("C:/book"),
            Path("C:/book/Chapter.md"),
            config,
            {1: [{"relative_path": "Assets/Figure-p0001-7.png", "y0": 300, "x0": 20, "xref": 7}]},
        )
        self.assertLess(markdown.index("Top paragraph"), markdown.index("![[Assets/Figure-p0001-7.png]]"))
        self.assertLess(markdown.index("![[Assets/Figure-p0001-7.png]]"), markdown.index("> Figure 2.7"))
        self.assertLess(markdown.index("> Figure 2.7"), markdown.index("Bottom paragraph"))
        self.assertEqual(markdown.count("> Source PDF, p. 1"), 1)

    def test_small_image_overlapping_one_text_line_is_classified_inline(self) -> None:
        class Page:
            def get_text(self, mode: str, sort: bool = True) -> dict[str, object]:
                return {"blocks": [{
                    "type": 0,
                    "lines": [{
                        "bbox": (60.0, 100.0, 500.0, 114.0),
                        "spans": [{"text": "Click the Play button.", "bbox": (60.0, 100.0, 500.0, 114.0)}],
                    }],
                }]}

        inline = pipeline.classify_inline_image(
            Page(),
            {"x0": 180.0, "y0": 101.0, "x1": 190.0, "y1": 113.0},
        )
        self.assertEqual(inline["image_role"], "inline-icon")
        self.assertEqual(inline["image_classification"], "clear-inline")
        self.assertEqual(inline["inline_line_y0"], 100.0)

        large = pipeline.classify_inline_image(
            Page(),
            {"x0": 180.0, "y0": 100.0, "x1": 260.0, "y1": 180.0},
        )
        self.assertEqual(large["image_role"], "figure-image")
        self.assertEqual(large["image_classification"], "clear-block")

    def test_inline_image_is_embedded_inside_text_without_source_reference(self) -> None:
        class Rect:
            height = 800.0

        class Page:
            rect = Rect()

            def get_text(self, mode: str, sort: bool = True) -> dict[str, object]:
                return {"blocks": [{
                    "type": 0,
                    "bbox": (60.0, 100.0, 260.0, 114.0),
                    "lines": [{
                        "bbox": (60.0, 100.0, 260.0, 114.0),
                        "spans": [
                            {"text": "Click the Play (", "bbox": (60.0, 100.0, 180.0, 114.0), "size": 10, "font": "Helvetica"},
                            {"text": ") button.", "bbox": (192.0, 100.0, 260.0, 114.0), "size": 10, "font": "Helvetica"},
                        ],
                    }],
                }]}

        markdown = pipeline.render_page_content(
            Page(),
            "Chapter 1",
            {"output": {"page_links": "none", "markdown_baseline": "obsidian"}},
            inline_images=[{
                "x0": 180.0,
                "x1": 190.0,
                "inline_line_y0": 100.0,
                "inline_line_y1": 114.0,
                "inline_markdown": "![[Assets/play.png]]",
            }],
        )
        self.assertIn("Click the Play ( ![[Assets/play.png]] ) button.", markdown)
        self.assertNotIn("\n\n![[Assets/play.png]]", markdown)
        self.assertNotIn("Source PDF", markdown)

    def test_inline_images_join_text_blocks_and_wrapped_lines(self) -> None:
        class Rect:
            height = 800.0

        def line(text: str, bbox: tuple[float, float, float, float]) -> dict[str, object]:
            return {"bbox": bbox, "spans": [{"text": text, "bbox": bbox, "size": 10, "font": "Helvetica"}]}

        class Page:
            rect = Rect()

            def get_text(self, mode: str, sort: bool = True) -> dict[str, object]:
                return {"blocks": [
                    {"type": 0, "lines": [line("Build the solution and play the program by clicking either the Start (", (63.0, 100.0, 342.6, 114.0))]},
                    {"type": 0, "lines": [
                        line(") or Start without Debug ", (353.3, 100.0, 461.3, 114.0)),
                        line("( ", (63.0, 113.1, 68.7, 126.5)),
                    ]},
                    {"type": 0, "lines": [line(") button.", (80.4, 113.1, 117.2, 126.5))]},
                ]}

        markdown = pipeline.render_page_content(
            Page(),
            "Chapter 2",
            {"output": {"page_links": "none", "markdown_baseline": "obsidian"}},
            inline_images=[
                {
                    "x0": 342.7, "y0": 101.1, "x1": 353.3, "y1": 113.0,
                    "inline_line_y0": 100.0, "inline_line_y1": 114.0,
                    "inline_markdown": "![[Assets/start.png]]",
                },
                {
                    "x0": 68.7, "y0": 113.2, "x1": 80.4, "y1": 126.4,
                    "inline_line_y0": 113.1, "inline_line_y1": 126.5,
                    "inline_markdown": "![[Assets/start-without-debug.png]]",
                },
            ],
        )
        self.assertIn(
            "Build the solution and play the program by clicking either the Start ( ![[Assets/start.png]] ) or Start without Debug ( ![[Assets/start-without-debug.png]] ) button.",
            markdown,
        )
        self.assertNotIn("\n\n![[Assets/start.png]]", markdown)
        self.assertNotIn("\n\n![[Assets/start-without-debug.png]]", markdown)

    def test_inline_image_syntax_defaults_to_obsidian_and_supports_markdown_override(self) -> None:
        self.assertEqual(inline_image_syntax({"output": {"markdown_baseline": "obsidian"}}), "obsidian-wiki")
        self.assertEqual(
            inline_image_syntax({"output": {"markdown_baseline": "obsidian", "inline_image_syntax": "markdown"}}),
            "markdown",
        )

    def test_only_chapters_selection_preserves_source_order(self) -> None:
        chapters = [
            pipeline.Chapter("1", "One", "Part", 1, 2),
            pipeline.Chapter("2", "Two", "Part", 3, 4),
            pipeline.Chapter("3", "Three", "Part", 5, 6),
        ]
        selected, requested = pipeline.select_chapters(chapters, "3,1")
        self.assertEqual([chapter.number for chapter in selected], ["1", "3"])
        self.assertEqual(requested, ["3", "1"])

    def test_only_sections_selection_uses_stable_ids_and_preserves_source_order(self) -> None:
        sections = [
            pipeline.Section("title-page", "Title Page", "paratext", "00_Paratext", "01_Title Page.md", 2, 2),
            pipeline.Section("foreword", "Foreword", "paratext", "00_Paratext", "03_Foreword.md", 4, 5),
            pipeline.Section("contributors", "Contributors", "paratext", "00_Paratext", "04_Contributors.md", 6, 7),
        ]
        selected, requested = pipeline.select_sections(sections, "contributors,foreword")
        self.assertEqual([section.section_id for section in selected], ["foreword", "contributors"])
        self.assertEqual(requested, ["contributors", "foreword"])

    def test_only_sections_and_only_chapters_are_mutually_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pdf_path = root / "book.pdf"
            self.make_pdf(pdf_path, ["Plain text"])
            with self.assertRaises(pipeline.PipelineError):
                pipeline.build_outputs(
                    root,
                    "Book",
                    {"output": {"page_links": "none"}, "sections": []},
                    pdf_path,
                    pdf_path,
                    "hash",
                    ["chapterize", "sections"],
                    "1",
                    "foreword",
                )

    def test_section_only_manifest_merge_does_not_expand_legacy_manifest(self) -> None:
        previous = {"files": [{"relative_path": "Chapter.md", "after_sha256": "old"}]}
        current = [{"relative_path": "00_Paratext/03_Foreword.md", "after_sha256": "new"}]
        merged = pipeline.merge_manifest_files(previous, current, True, include_new=False)
        self.assertEqual(merged, previous["files"])

    def test_full_backup_excludes_existing_backup_trees(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary)
            backup_dir = vault / "File" / "Backups" / "Book"
            backup_dir.mkdir(parents=True)
            (backup_dir / "historical.zip").write_bytes(b"historical backup")
            (vault / "note.md").write_text("content\n", encoding="utf-8")
            backup, _ = pipeline.make_backup(vault, "Book", [], "20260828-000000", {}, full=True)
            self.assertIsNotNone(backup)
            with zipfile.ZipFile(backup) as archive:
                names = archive.namelist()
            self.assertIn("files/note.md", names)
            self.assertNotIn("files/File/Backups/Book/historical.zip", names)

    def test_layout_repair_baseline_manifest_detects_manual_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            note = root / "Chapter.md"
            note.write_text("# Current text\n", encoding="utf-8")
            manifest = root / "latest-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "files": [{
                            "relative_path": "Chapter.md",
                            "after_sha256": "not-the-current-hash",
                        }]
                    }
                ),
                encoding="utf-8",
            )
            report = layout_repair.preview(root)
            layout_repair.add_baseline_check(report, manifest)
            self.assertEqual(len(report["baseline_manifest"]["conflicts"]), 1)

    def test_table_transform_accepts_repeated_pdf_bold_spans(self) -> None:
        source = (
            "## Technical requirements\n\n"
            "- ** ****Operating system**: Windows 10\n\n"
            "- ** ****Processor**: Intel 7th generation or equivalent\n\n"
            "- ** ****Memory**: 16 GB of RAM\n"
        )
        transformed, audit = transform_definition_lists(source)
        self.assertIn("| **Operating system** | Windows 10 |", transformed)
        self.assertEqual(audit["tables_count"], 1)
        self.assertEqual(audit["rows_transformed"], 3)

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

    def test_pdf_and_arbitrary_output_root_work_without_obsidian_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.pdf"
            output = root / "Markdown Book"
            output.mkdir()
            self.make_pdf(
                source,
                [
                    "Chapter 1: A Portable Book\n"
                    "## Concepts\n"
                    "The first paragraph.\n"
                    "## Examples\n"
                    "The second paragraph.",
                ],
            )
            missing_destination_args = pipeline.build_parser().parse_args([
                "dry-run",
                "--source",
                str(source),
                "--book",
                "Portable Book",
            ])
            with self.assertRaises(pipeline.PipelineError):
                pipeline.build_dry_run(missing_destination_args)

            dry_args = pipeline.build_parser().parse_args([
                "dry-run",
                "--source",
                str(source),
                "--output-root",
                str(output),
                "--book",
                "Portable Book",
            ])
            summary = pipeline.build_dry_run(dry_args)
            self.assertFalse(summary["conflicts"])
            self.assertIn("topic_index", summary["stages"])
            self.assertIn("moc", summary["stages"])
            self.assertTrue(any(item["relative_path"] == "01_Topic Index.md" for item in summary["outputs"]))
            self.assertTrue(all("File" not in item["relative_path"] for item in summary["outputs"]))

            apply_args = pipeline.build_parser().parse_args([
                "apply",
                "--source",
                str(source),
                "--output-root",
                str(output),
                "--book",
                "Portable Book",
                "--confirm-apply",
            ])
            self.assertEqual(pipeline.command_apply(apply_args), 0)
            self.assertTrue((output / "01_Topic Index.md").exists())
            self.assertTrue((output / "00_MOC.md").exists())
            self.assertIn("A Portable Book", (output / "01_Topic Index.md").read_text(encoding="utf-8"))
            self.assertTrue((output / ".conversion" / "reports" / "latest-manifest.json").exists())
            self.assertTrue(source.exists())

            audit_args = pipeline.build_parser().parse_args([
                "audit",
                "--source",
                str(source),
                "--output-root",
                str(output),
                "--book",
                "Portable Book",
            ])
            self.assertEqual(pipeline.command_audit(audit_args), 0)

            backup = next((output / ".conversion" / "backups").glob("pre-*.zip"))
            rollback_args = pipeline.build_parser().parse_args([
                "rollback",
                "--output-root",
                str(output),
                "--book",
                "Portable Book",
                "--backup",
                str(backup),
                "--confirm-rollback",
            ])
            self.assertEqual(pipeline.command_rollback(rollback_args), 0)
            self.assertFalse((output / "01_Topic Index.md").exists())
            self.assertFalse((output / "00_MOC.md").exists())

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

    def test_visual_table_auto_discovery_preserves_empty_cells(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            pdf_path = Path(temporary) / "auto-visual-table.pdf"
            pdf = canvas.Canvas(str(pdf_path), pagesize=(400, 400))
            x = [50, 200, 350]
            y = [300, 260, 220, 180]
            for xpos in x:
                pdf.line(xpos, 180, xpos, 300)
            for ypos in y:
                pdf.line(50, ypos, 350, ypos)
            rows = [
                ("Name", "Value"),
                ("Engine", "Unreal"),
                ("Compiler", ""),
            ]
            for row_index, row in enumerate(rows):
                for col_index, value in enumerate(row):
                    if value:
                        pdf.setFont("Helvetica", 9)
                        pdf.drawString(x[col_index] + 5, [282, 242, 202][row_index], value)
            pdf.showPage()
            pdf.save()
            document = pipeline.require_pdf_runtime().open(str(pdf_path))
            try:
                tables = pipeline.discover_visual_tables(
                    document,
                    {"visual_tables": {"enabled": True, "discovery": "auto", "regions": []}},
                )
            finally:
                document.close()
            converted = [item for item in tables if item["status"] == "converted"]
            self.assertEqual(len(converted), 1)
            self.assertEqual(converted[0]["headers"], ["Name", "Value"])
            self.assertEqual(converted[0]["rows"][-1], ["Compiler", ""])

    def test_split_inline_code_urls_join_only_url_fragments(self) -> None:
        self.assertEqual(
            pipeline.merge_split_inline_code_urls("`https://` `example.com/path`"),
            "`https://example.com/path`",
        )
        self.assertEqual(
            pipeline.merge_split_inline_code_urls("`left/` `right`"),
            "`left/` `right`",
        )
        self.assertEqual(
            pipeline.merge_split_plain_urls("See https://\nexample.com/path."),
            "See https://example.com/path.",
        )
        self.assertEqual(
            pipeline.merge_split_plain_urls("See https://example.com\nnext."),
            "See https://example.com\nnext.",
        )

    def test_roman_page_numbers_are_page_chrome_candidates(self) -> None:
        self.assertTrue(pipeline.is_pdf_page_number("xvii"))
        self.assertTrue(pipeline.is_pdf_page_number("17"))
        self.assertFalse(pipeline.is_pdf_page_number("Chapter"))

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

    def test_toc_title_normalization_keeps_identifiers_and_removes_delimiters(self) -> None:
        self.assertEqual(
            toc_repair.normalize_title("TP_ PickUpComponent.cpp"),
            toc_repair.normalize_title("TP_PickUpComponent.cpp"),
        )
        self.assertEqual(
            toc_repair.normalize_title("_Copy and paste_"),
            "copy and paste",
        )

    def test_toc_renderer_builds_chapter_tables_and_reports_unmatched_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toc = root / "00_Paratext" / "05_Table of Contents.md"
            chapter_dir = root / "01_Part 1"
            back_dir = root / "04_Back Matter"
            toc.parent.mkdir(parents=True)
            chapter_dir.mkdir()
            back_dir.mkdir()
            toc.write_text("---\ntype: paratext\n---\n", encoding="utf-8")
            chapter = chapter_dir / "Chapter 01 - A Book.md"
            chapter.write_text("# A Book\n## First section\n", encoding="utf-8")
            (back_dir / "01_Index.md").write_text("# Index\n", encoding="utf-8")
            (back_dir / "02_Recommended.md").write_text(
                "# Other Books You May Enjoy\n", encoding="utf-8"
            )
            entries = {
                "toc_pdf_pages": [8, 13],
                "parts": [{"number": 1, "title": "Part 1 - Getting Started"}],
                "chapters": [{
                    "number": 1,
                    "title": "A Book",
                    "print_page": 1,
                    "part_number": 1,
                    "sections": [
                        {"title": "First section", "print_page": 2, "sequence": 1},
                        {"title": "Unknown | section", "print_page": 3, "sequence": 2},
                    ],
                }],
                "back_matter": [
                    {"title": "Index", "print_page": 10},
                    {"title": "Other Books You May Enjoy", "print_page": 11},
                ],
            }
            rendered, audit = toc_repair.render_toc(entries, toc, root)
            self.assertIn("> Source PDF, pp. 8-13", rendered)
            self.assertIn("| Section | Print page |", rendered)
            self.assertIn("[First section](<../01_Part 1/Chapter 01 - A Book.md#First section>)", rendered)
            self.assertIn("| Unknown \\| section | 3 |", rendered)
            self.assertIn("[Index](<../04_Back Matter/01_Index.md>)", rendered)
            self.assertEqual(audit["counts"]["linked_sections"], 1)
            self.assertEqual(audit["counts"]["linked_back_matter"], 2)
            self.assertEqual(len(audit["unmatched_sections"]), 1)

    def test_toc_renderer_does_not_link_replacement_character_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toc = root / "TOC.md"
            toc.write_text("---\ntype: paratext\n---\n", encoding="utf-8")
            chapter = root / "Chapter 02 - A Book.md"
            chapter.write_text("# A Book\n## Walking through the VS IDE��s UI\n", encoding="utf-8")
            entries = {
                "toc_pdf_pages": [1, 1],
                "parts": [{"number": 1, "title": "Part 1"}],
                "chapters": [{
                    "number": 2, "title": "A Book", "print_page": 1,
                    "part_number": 1,
                    "sections": [{
                        "title": "Walking through the VS IDE��s UI",
                        "print_page": 2,
                        "sequence": 1,
                    }],
                }],
                "back_matter": [],
            }
            rendered, audit = toc_repair.render_toc(entries, toc, root)
            self.assertIn("| Walking through the VS IDE��s UI | 2 |", rendered)
            self.assertEqual(audit["counts"]["unmatched_sections"], 1)

    def test_toc_apply_rejects_stale_preview_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toc = root / "TOC.md"
            chapter = root / "Chapter 01 - A Book.md"
            entries = root / "entries.json"
            preview = root / "preview.json"
            backup = root / "backup.zip"
            report = root / "apply.json"
            toc.write_text("---\ntype: paratext\n---\n", encoding="utf-8")
            chapter.write_text("# A Book\n## First section\n", encoding="utf-8")
            entries.write_text(json.dumps({
                "toc_pdf_pages": [1, 1],
                "parts": [{"number": 1, "title": "Part 1"}],
                "chapters": [{
                    "number": 1, "title": "A Book", "print_page": 1,
                    "part_number": 1,
                    "sections": [{"title": "First section", "print_page": 2, "sequence": 1}],
                }],
                "back_matter": [],
            }), encoding="utf-8")
            preview_report = toc_repair.preview(toc, entries, root)
            toc_repair.write_json(preview, preview_report)
            toc.write_text(toc.read_text(encoding="utf-8") + "manual drift\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                toc_repair.apply_change(toc, entries, root, preview, backup, None)
            toc.write_text("---\ntype: paratext\n---\n", encoding="utf-8")
            toc_repair.apply_change(toc, entries, root, preview, backup, None)
            second_preview = toc_repair.preview(toc, entries, root)
            self.assertFalse(second_preview["changed"])
            self.assertTrue(backup.exists())


if __name__ == "__main__":
    unittest.main()
