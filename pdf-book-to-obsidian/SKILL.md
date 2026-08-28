---
name: pdf-book-to-obsidian
description: Convert PDF books into complete, structured Markdown knowledge bases with MOCs, indexes, assets, and Agent-assisted handling of book-specific layouts.
---

# PDF Book to Markdown Knowledge Base

Use this Skill when a user provides a PDF book and wants a complete, readable, navigable Markdown file system. Obsidian is an optional consumer of the output, not a required destination.

## Stable task contract

Remember these rules without asking the user to repeat them:

- Preserve the source language, wording, order, and meaning.
- Do not translate, summarize, correct, or silently invent missing content.
- Produce a usable Markdown system with a book MOC, structural navigation, and a topic/term index unless the user explicitly opts out.
- Use code for reproducible extraction and file operations; use Agent reasoning for structure, exceptions, and local transformation choices.
- Inspect the whole PDF before conversion.
- Show a conversion plan/preview before writing formal output.
- Preserve the original PDF and do not overwrite manual files.
- Low-risk layout cleanup may be automatic; structural or semantic uncertainty requires discussion.
- After generation, check order, missing content, links, assets, code fences, tables, and overall readability.
- Treat image placement, source-reference style, and Figure-caption style as book-specific choices. When coordinates are available, coordinate-ordered placement is a strong default for illustrated books, but the Agent must review ambiguous pages.
- Distinguish small images embedded in a text line from independent figures. In
  Obsidian mode, a clearly line-overlapping icon stays inline with the sentence;
  uncertain image roles are preserved and reported.

## Required Agent workflow

The Agent must enter a planning conversation before formal output is created. Do not assume a vault, repository, `File` directory, naming style, or output location.

1. Inspect the supplied PDF and nearby context only as needed to understand the book and possible destinations.
2. Report concise findings: text quality, book structure, likely reading order, sections, code, tables, images, and anomalies.
3. Discuss only the book-specific decisions that matter. At minimum, discuss the output location and the chapter-versus-section granularity. Also discuss scope, attachments, code, tables, complex layout, MOC/index depth, and OCR when the PDF makes them relevant.
4. Give a concrete recommendation with alternatives and examples from the PDF. The user may accept, reject, or revise each important choice.
5. Do not create formal Markdown until the user has confirmed the selected plan. Keep the technical configuration internal unless the user asks to see it.
6. Execute the selected plan with the deterministic helpers, then have the Agent review the result. Automatically repair only clearly low-risk local issues; return to discussion for structure, order, or source-content questions.

## Agent-assisted conversion

Treat the PDF extraction as evidence, not as the final interpretation. Code may expose text blocks, coordinates, fonts, images, page renders, and candidate tables. The Agent may choose different strategies for different regions:

- normal prose for ordinary paragraphs;
- column-aware ordering for multi-column pages;
- fenced code for confirmed code blocks;
- visual-table reconstruction only when geometry, stable columns, and explicit
  headers support it. A configured region is not required: when enabled, the
  helper may discover high-confidence closed grids across the PDF;
- conversion of clearly labelled rounded editorial boxes to Obsidian Callouts.
  Filled code rectangles, UML/diagram boxes, and unlabelled boxes remain
  source-preserving candidates in the report;
- maintenance-time visual tables are only patched when the PDF preview and
  current Markdown identify one unique source region. A grid containing
  images inside cells is kept for Agent review because text-only reconstruction
  cannot safely preserve those images;
- removal of repeated page-edge headers/footers only when their position,
  repetition, and page-number pattern make the PDF chrome unambiguous;
- joining only coordinate-confirmed adjacent inline-code URL fragments;
- conservative list-to-table conversion only when the structure is clear and the user accepts it;
- source-preserving fallback for uncertain regions.

The Agent must not rewrite the whole book. When a region is ambiguous, preserve the extracted source and page reference, explain the uncertainty, and ask for a decision.

## Output principles

- Default to Obsidian Flavored Markdown when the user has not requested a
  cross-platform Markdown result. Read [references/obsidian-markdown-baseline.md](references/obsidian-markdown-baseline.md)
  for the official syntax sources and the conversion checklist.
- The destination may be any user-selected directory or an Agent-recommended directory; it need not be an Obsidian vault.
- At least split the main text by chapter. If a chapter has many meaningful subsections, propose splitting that chapter further and let the user decide.
- Include front matter, appendices, indexes, and other back matter according to the book-specific plan after inspecting their value.
- Generate structural links and a topic/term index page. Prefer index links over creating many standalone topic notes unless the user chooses deeper decomposition.
- Keep images and other assets close enough to the Markdown system for reliable links. Discuss a different asset layout when the book or user's file system calls for it.
- Keep reports, plans, and rollback data outside the main reading structure or in a clearly separated auxiliary area.
- Use Obsidian Wiki links, file embeds, tables, code fences, footnotes, and
  Callouts when the selected baseline and the book-specific plan support them.
- Do not generate CSS, multi-column layouts, third-party plugin syntax, HTML,
  or web embeds by default. Treat them as explicit book-specific choices.

## Safety and maintenance

- A preview is a non-writing simulation of the proposed outputs and changes; the internal command may still be named `dry-run` for compatibility.
- Never silently choose a missing output location, OCR policy, chapter boundary, or high-impact transformation.
- Do not move or delete existing files as part of ordinary conversion.
- If a generated file was manually edited or its recorded content changed, stop and report the conflict instead of overwriting it.
- For scans or unreliable text layers, pause and ask whether to use an OCR-processed source. Do not silently OCR.
- Keep source and generated hashes, configuration/plan identity, and a recoverable backup for maintenance, but do not burden the normal conversation with implementation fields.
- A full-book backup includes the current Markdown system, source, attachments,
  reports, and configuration, but excludes the existing backup directory itself
  to avoid recursively copying historical ZIP backups and exhausting disk space.

## Existing Markdown layout repair

When the user asks to clean an already generated book, treat it as a separate
repair pass rather than silently re-converting the PDF. Inspect the actual
Markdown first, show a preview with representative before/after snippets, and
then apply only the confirmed conservative rules. Preserve intentional inline
emphasis and all source content. For headings, PDF span artifacts, Figure
captions, source-page links, and ordered-list spacing, read
[references/layout-repair.md](references/layout-repair.md) and use the helper
script there. Keep ambiguous image/caption/source relationships unchanged and
report them for later Agent review. If an earlier generator manifest is
available, pass it as a baseline so possible manual drift is detected before
any backup or write; a detected conflict blocks the repair until the user has
reviewed it.

For ordinary unordered lists, keep consecutive same-level items together
without blank lines. Treat `-`, `*`, and `+` as equivalent list markers while
preserving each original marker. Keep necessary blank lines for code, images,
tables, blockquotes, nested lists, multi-paragraph items, or ambiguous
list/paragraph boundaries.

When repairing an existing book, the Agent may select
`--source-reference-style plain-blockquote` to migrate legacy linked source
references to `> Source PDF, p. N`. The repair helper removes only repeated
same-page references in a local metadata/header block; references separated by
meaningful content remain. This is a presentation choice for the selected
repair pass and does not change YAML provenance or the source PDF.

Table-of-contents pages receive a conservative cleanup: clear emphasis and
PDF control-character fragments may be removed, but uncertain multi-column
entry boundaries, nesting, page order, and internal links are not inferred.
Such regions remain unchanged or are recorded for Agent review.

When a book's TOC has reliable chapter/section boundaries, printed page
numbers, and usable column geometry, the Agent may propose a navigable
chapter-table representation. This is conditional, not a universal output
requirement: preserve the original TOC when its structure is ambiguous, and
let the user choose between preservation and a table layout. A useful option
is one `Section / Print page` table per chapter, grouped under Part headings.
Reconstruct double-column TOCs in visual reading order, sort entries by
printed page while preserving same-page order, and use standard Markdown
links in table cells when linking avoids Wiki-link pipe ambiguity. Link a
chapter or subsection only when one existing file or heading matches after
conservative typography normalization; leave unmatched entries as plain text
and record them as uncertain. Keep the source-page provenance and compare
entry counts before applying. The reusable helper is
`scripts/toc_table_repair.py`; its preview must be reviewed before a scoped
TOC replacement.

For clear block-leading editorial labels such as `Note`, `Tip`, `Warning`, or
`Example`, and for visibly boxed labels such as `Tips or important notes`, use
Obsidian Callouts in the default baseline. Do not convert words such as “note”
inside ordinary prose. Labels inside lists, tables, or code are ambiguous and
must remain unchanged for Agent review.

For programming and technical books, the Agent may recommend formatting
clearly identified keyboard-shortcut entries as complete inline-code spans,
for example ``- `Ctrl + C`: Copies the selected text``. Apply this only when
the surrounding section and the extracted key tokens make the interpretation
clear; preserve ordinary emphasis and non-technical lists. Standalone
emphasis-only labels that clearly introduce a shortcut subsection may become
the next appropriate Markdown heading level. This is a book-specific
presentation choice, not a universal rule for every Markdown conversion.

## Helper scripts

Use `scripts/pdf_book_pipeline.py` for deterministic inspection, preview, generation, auditing, and rollback. The compatibility commands remain available:

```text
inspect <vault> --book <book> [--source <pdf>]
dry-run <vault> --book <book> [--stages ...]
apply <vault> --book <book> --confirm-apply [--copy-source]
dry-run <vault> --book <book> --only-chapters 1,2
apply <vault> --book <book> --only-chapters 1,2 --allow-generated-drift --confirm-apply
dry-run <vault> --book <book> --only-sections foreword,contributors
apply <vault> --book <book> --only-sections foreword,contributors --allow-generated-drift --confirm-apply
audit <vault> --book <book>
rollback <vault> --book <book> --backup <zip> --confirm-rollback
```

For a partial Markdown repair, repeat `--include <relative-file.md>` on the
layout-repair helper for each selected content file. The paths are relative to
the selected book root; this is a scope control, not a book-specific path
convention.

For PDF-backed visual structure repairs, first run
`scripts/markdown_structure_repair.py preview` with the pipeline structure
preview, then apply only after reviewing its exact table-region replacements.
The helper preserves existing Callouts and reports boxed regions whose body
cannot be uniquely located. It never replaces a whole Markdown file.

For an existing illustrated book whose chapter files have been manually
formatted after generation, use `scripts/markdown_image_repair.py` for a
coordinate-backed image-only maintenance pass. It compares the current
standalone image and Figure-caption blocks with a fresh PDF coordinate render,
then moves only the matching source-reference/image/caption block into the
correct local position. It preserves prose, code, tables, Callouts, inline
icons, attachments, and manual formatting. The helper requires a reviewed
preview, refuses unresolved image/caption relationships, checks source/config
and target hashes before writing, and creates a lightweight ZIP containing the
selected Markdown files and configuration. It is appropriate when a full
chapter regeneration would overwrite known manual drift.

For new work, the helper also accepts an explicit PDF and arbitrary output root through `--source` and `--output-root`; the Agent should use that only after the user has selected the destination. Read [references/config-schema.md](references/config-schema.md) for the small internal plan/config contract, [references/obsidian-markdown-baseline.md](references/obsidian-markdown-baseline.md) for Obsidian syntax, [references/output-contract.md](references/output-contract.md) for generated-file expectations, and [references/maintenance-protocol.md](references/maintenance-protocol.md) when updating an existing conversion.

For a partial regeneration, use `--only-chapters` or `--only-sections` only
after the user has confirmed the scope. Section selection uses the stable ids
declared in the book configuration. A scoped run skips unrelated chapter,
attachment, Lens, topic-index, and MOC outputs, records the selected scope,
and merges chapter-scope records into the existing manifest. Section-only
maintenance keeps its changed-file records in the dedicated apply report so a
legacy chapter manifest is not expanded implicitly. A drifted
generated chapter or section may be replaced only with the explicit
`--allow-generated-drift` flag; this flag cannot authorize a full regeneration
or a non-generated/manual file. The two scope selectors are mutually
exclusive.

The generator supports these optional output choices:

- `markdown_baseline`: `obsidian` (default) or `commonmark` for an explicitly
  cross-platform result;
- `source_reference_style`: `linked-blockquote` (legacy default),
  `plain-blockquote`, or `none`;
- `figure_caption_style`: `plain` or `blockquote`;
- `image_placement`: `pdf-coordinate` (coordinate-interleaved default) or
  `append` (legacy compatibility).
- `callout_style`: `obsidian-callout` (default in Obsidian mode), `plain`, or
  `none`.
- `inline_image_policy`: `auto` (classify only clear text-overlapping icons) or
  `block` (force all images to remain block-level).
- `inline_image_syntax`: `obsidian-wiki` (default for Obsidian) or `markdown`.
- `visual_tables.discovery`: `auto` (default when visual tables are enabled)
  or `off`. Auto discovery converts only high-confidence closed grids with
  stable column boundaries and a complete header row; rejected candidates are
  recorded rather than forced into tables.
- `boxed_callout_policy`: `auto` (default) or `off`. Auto recognizes labelled
  rounded editorial boxes and emits Obsidian Callouts; it does not treat every
  rectangle or diagram as a Callout.
- `shortcut_style` (layout repair): `preserve` by default, or `inline-code`
  when the Agent and user select complete inline-code formatting for clearly
  identified keyboard-shortcut lists in a technical book.
- `source_reference_style` (layout repair): `preserve` by default, or
  `plain-blockquote` for a confirmed migration of legacy linked PDF references.

These choices affect presentation only; they do not authorize the Agent or
the code to invent, translate, summarize, or reorder source content.
