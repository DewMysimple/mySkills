---
name: pdf-book-to-obsidian
description: Convert and maintain text-based PDF books as chapterized Obsidian Markdown libraries with configurable tables, attachments, reports, and rollback-safe writes.
---

# PDF Book to Obsidian

Use this skill when a user wants a PDF book inspected, converted into an Obsidian vault, or safely maintained after conversion. It is PDF-first and preserves the source language and wording.

## Operating contract

1. Treat `File/PDF/<book>/` as the managed source location. If the PDF is elsewhere, inspect it first and only copy it into that location after explicit authorization; never delete the original.
2. Resolve the book configuration from `File/Config/<book>/book-config.yaml`. If it is missing, create a proposed configuration in the conversation or a dry-run output; do not silently guess chapter boundaries for an apply operation.
3. Run `inspect` and then `dry-run` before any write. Present the predicted files, chapter boundaries, table changes, skipped/ambiguous blocks, source hash, and scan quality. Run `apply` only after the user explicitly authorizes the displayed plan.
4. Use the bundled PDF runtime when available. The helper supports both `pymupdf` and the bundled legacy `fitz` import; do not install global packages as part of an ordinary conversion.
5. Keep original wording. Do not translate, summarize, or add interpretations to generated source notes. Table conversion is conservative and must leave ambiguous lists unchanged.
6. Never overwrite a file that has no generator marker or whose hash differs from the last applied manifest. Stop with a conflict report and ask for a targeted decision instead.
7. Store resources by type and book: `File/PDF/<book>/`, `File/Config/<book>/`, `File/Reports/<book>/`, `File/Backups/<book>/`, and `File/Attachment/<book>/`. Chapter Markdown remains in the vault's configured output folders.

## Content-preserving structure

- Prefer explicit `chapters`, `parts`, and `sections` page ranges for a known book. Physical PDF pages are one-based; `print_pages` is optional metadata and is never used as an extraction boundary.
- Normalize only layout artifacts such as wrapped bookmark titles and confirmed missing word spaces. Do not translate, spell-check, summarize, or correct source wording.
- When `code_blocks.enabled` is true, detect Courier/monospace spans, preserve indentation and blank lines, fence only sufficiently long code blocks, and keep short code inline when configured. Use configured language mappings (`cpp`, `bash`, `powershell`, `ini`, or `text`); uncertain code uses `text`.
- When `visual_tables.enabled` is true, convert only configured regions whose PDF drawing layer confirms stable horizontal and vertical grid geometry plus an explicit header. Cross-page rows and repeated headers are merged conservatively. Uncertain tables remain in the source extraction and are reported.
- `table_transform` is a separate conservative pass for clear top-level definition lists and always uses `| Term / Item | Original description |`.
- `output.page_links: headings-and-code` adds physical PDF page links before detected headings, code blocks, visual tables, and extracted images. `chapter`, `every-page`, and `none` remain available.
- Attachment extraction covers chapter pages by default; configure `attachments.include_section_kinds` when images from Part overviews or selected back-matter sections should also be included. This keeps decorative front-matter assets out unless requested.

Generated chapter/section frontmatter uses the configurable `frontmatter.type_field` (use `type` for new books; `kind` remains supported for legacy vaults), records `source_pages`, `source_pdf`, `source_sha256`, and generator metadata, and may include book-specific metadata such as technology and language.

## Script entry point

Use `scripts/pdf_book_pipeline.py` for deterministic operations:

```text
inspect <vault> --book <book> [--source <pdf>]
dry-run <vault> --book <book> [--stages ...]
apply <vault> --book <book> --confirm-apply [--copy-source]
audit <vault> --book <book>
rollback <vault> --book <book> --backup <zip> --confirm-rollback
```

Read [references/config-schema.md](references/config-schema.md) before creating or changing a book configuration. Read [references/output-contract.md](references/output-contract.md) when auditing generated files or interpreting a report. Read [references/maintenance-protocol.md](references/maintenance-protocol.md) before applying changes to an existing book.
