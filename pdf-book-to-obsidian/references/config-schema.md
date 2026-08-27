# Internal conversion plan

This file describes the internal configuration consumed by the helper scripts. It is not a form the user must fill in. The Agent creates it after discussing the book-specific plan.

## Minimal shape

```yaml
book_title: "Book Title"
source_pdf: "C:/path/to/source.pdf"

output:
  root: "C:/path/to/markdown-system"
  mode: chapterized
  chapter_filename: "Chapter {number:02d} - {title}.md"
  section_filename: "{title}.md"
  moc_filename: "00_MOC.md"
  markdown_baseline: obsidian
  page_links: headings-and-code
  source_reference_style: linked-blockquote
  figure_caption_style: plain
  image_placement: pdf-coordinate
  callout_style: obsidian-callout

modules:
  chapterize: true
  sections: true
  attachments: true
  code_blocks: true
  tables: true
  visual_tables: true
  moc: true

book_specific_decisions:
  - area: visual-table
    pages: [71, 72]
    action: convert
    reason: "Stable grid and explicit headers"
```

The actual structure may be richer when a book needs it. Do not add fields merely to expose implementation detail. Paths, file names, chapter ranges, section ranges, page-link style, attachment choices, OCR, and local conversion decisions are selected for the current book.

## Presentation choices

These output fields are optional and are selected per book after inspecting the
PDF:

- `markdown_baseline`: `obsidian` (default) or `commonmark`. The Obsidian mode
  permits Wiki links, file embeds, Callouts, and other documented extensions;
  the CommonMark mode prefers portable Markdown links and images.
- `source_reference_style`: `linked-blockquote`, `plain-blockquote`, or
  `none`. The plain form renders as `> Source PDF, p. N`.
- `figure_caption_style`: `plain` or `blockquote`. Only lines that match a
  real `Figure N.N – ...` caption are affected; prose mentions are not.
- `image_placement`: `pdf-coordinate` or `append`. The coordinate mode
  interleaves image events with text blocks using page coordinates and sorts
  multiple images by vertical then horizontal position. The append mode is a
  compatibility fallback for older conversions.
- `callout_style`: `obsidian-callout` (the default when the baseline is
  `obsidian`), `plain`, or `none`. Explicit block-leading Note/Tip/Warning and
  related labels are converted only in the Callout mode.

Use `--only-chapters 1,2` for a confirmed partial generation. It limits writes
to the selected chapter outputs and preserves the other file records in the
maintenance manifest. The Agent should use `--allow-generated-drift` only for
a user-authorized replacement of selected files that still carry the generator
marker; it is intentionally unavailable as a general overwrite switch.

## Path rules

- `source_pdf` may be absolute or relative to the plan/config location.
- `output.root` is the Markdown system root and may be any user-selected directory.
- The output root does not need `.obsidian` or any particular directory names.
- Auxiliary reports and backups are kept outside the main reading tree or in a clearly separated auxiliary area chosen for that book.
- Existing `vault`, `book`, `File/PDF`, `File/Reports`, `File/Backups`, and `File/Attachment` fields remain supported for legacy conversions only.

## Content decisions

- `output.mode` is normally `chapterized`; the Agent may propose section-level splitting when a chapter contains many meaningful sections.
- Full-PDF scope is inspected first. Front matter, appendices, indexes, and other back matter are included or separated according to the confirmed plan.
- Table and visual-table decisions are local where possible. A clear region may be converted while an ambiguous region remains source-preserving.
- The plan records decisions and examples, not rewritten source text.
- OCR remains disabled unless the user explicitly chooses it after the text-quality inspection.
