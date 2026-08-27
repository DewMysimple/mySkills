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
