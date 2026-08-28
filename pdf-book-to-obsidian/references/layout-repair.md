# Markdown layout repair

Use this mode when a PDF-to-Markdown result already exists and the user asks
for conservative reading-view cleanup. It is a repair pass, not a second PDF
conversion.

When the destination is an Obsidian vault, use
[references/obsidian-markdown-baseline.md](obsidian-markdown-baseline.md) as
the syntax reference. The repair helper defaults to the Obsidian Callout
presentation but accepts an explicit compatibility style.

## Stable rules

- Preserve source wording, language, order, and meaning.
- Remove emphasis syntax from heading text while retaining its heading level.
- Repair only clear PDF span artifacts such as empty bold spans, duplicated
  opening markers, and a closing bold marker separated from the last word.
- Leave intentional adjacent emphasis, code, tables, and uncertain content
  unchanged.
- With the explicit `source_reference_style: plain-blockquote` choice, convert
  legacy linked references such as `> [Source PDF, p. 14](...)` to
  `> Source PDF, p. 14`. The helper may remove a repeated same-page reference
  only when the local block contains no meaningful prose, list, image, table,
  or code between the references. YAML provenance and the source PDF link are
  not changed.
- Move a standalone PDF source link to a Figure caption only when the image,
  caption, and source link are locally unambiguous. The target URL and page
  number must be preserved.
- Use `image -> Figure caption -> source link` when that order is locally
  unambiguous. Do not infer a caption across ordinary prose.
- Remove blank lines only between consecutive ordered-list items. Preserve
  spacing inside multi-block list items.
- Keep ordinary same-level unordered-list items together without blank lines.
  Treat `-`, `*`, and `+` as equivalent markers but preserve the original
  marker characters.
- Preserve blank lines around unordered-list items containing fenced code,
  images, tables, blockquotes, nested lists, or multiple paragraphs. If a
  line may be either a wrapped list continuation or a paragraph boundary,
  keep the blank and report the region instead of guessing.
- Keep the original PDF and attachments unchanged.

## Generation-time visual structures

Visual tables are reconstructed from the PDF drawing layer, not from the
appearance of the extracted prose alone. Auto discovery is accepted only when
the region has a closed, multi-column grid, stable column boundaries, and a
complete header row. Empty cells are retained. Code-like gray rectangles,
single-column boxes, diagrams, and grids without a reliable header remain
source-preserving candidates and are listed in the report for Agent review.

Clearly labelled rounded editorial boxes can be emitted as Obsidian Callouts,
including `Tips or important notes` as a titled `NOTE`. A rectangle without a
supported editorial label is not a Callout candidate. This distinction keeps
code examples and UML/diagram boxes out of the Callout conversion.

For an existing book, `markdown_structure_repair.py` may consume the PDF
structure preview and replace only a uniquely located visual-table region. It
never regenerates a whole note. A grid containing placed images is reported as
ambiguous because a text-only table cannot safely preserve images in their
original cells.

Repeated page-edge text is removed only when it behaves as PDF chrome: its
position is at the page edge, its text repeats as a running header/footer or
matches a page-number pattern, and it is not part of the body. In front matter,
an isolated Roman page-number token is eligible only when the next non-empty
line is an explicit `Source PDF, p. N` marker. Isolated Arabic numbers and
ambiguous tokens remain unchanged and are reported.

Adjacent inline-code URL fragments are joined only when the first fragment is
an `http://` or `https://` prefix ending at a URL boundary and the second
fragment contains only URL-safe characters. Ordinary neighbouring code spans
are never joined. If coordinate continuity is not clear, preserve both spans.

## Table-of-contents pages

TOC pages are cleaned more conservatively than ordinary prose. Clear emphasis
markers and PDF control characters may be removed, and an unambiguous trailing
printed page number may be rendered as `— p. N` in a heading. The helper does
not infer multi-column entry boundaries, nesting, reading order, or internal
links. If those boundaries are unclear, the original line is retained and the
region is reported for Agent review.

### Optional TOC table representation

Table conversion is a book-specific choice, not a default repair. Propose it
only when the PDF provides reliable chapter/section boundaries, printed page
numbers, and usable column geometry. A conservative layout is one table per
chapter grouped below Part headings:

```markdown
### Chapter 1 - [Chapter title](<path/to/chapter.md>) - p. 1

| Section | Print page |
| --- | ---: |
| [Section title](<path/to/chapter.md#Section title>) | 2 |
```

Use the PDF's visual reading order for double-column pages. Sort sections by
printed page, retaining the source order for equal page numbers. Standard
Markdown links are preferred inside tables when Wiki-link pipes could confuse
table parsing. Link only an existing chapter file or heading with one
reliable, conservative typography match. Leave ambiguous or missing targets
as plain text and add an `uncertain`/unmatched item to the preview report.
Preserve the source page range and verify the extracted entry counts before
apply. `scripts/toc_table_repair.py` separates manifest extraction, preview,
and guarded application; it is suitable for a scoped TOC change and does not
assume a particular vault, path, book title, or chapter count.

## Technical shortcut lists

For a programming or technical book, `shortcut_style: inline-code` may be
selected after review when a list is clearly a keyboard-shortcut section. The
repair then converts the complete shortcut label, including combinations such
as `Ctrl + Shift + F`, to one inline-code span and separates comma-delimited
alternatives into separate spans. It can also convert a standalone
emphasis-only label such as `***Copy and paste***` to the next appropriate
heading level when the surrounding heading hierarchy confirms that role.

The default is `shortcut_style: preserve`. Do not apply the technical rule to
ordinary lists, prose emphasis, code blocks, tables, or labels whose role is
unclear. A malformed star sequence without a clear shortcut interpretation
remains unchanged and is reported for Agent review.

## Editorial Callouts

Clear block-leading labels are formatted as Obsidian Callouts in the default
mode:

```markdown
> [!NOTE]
>
> Original note text.
```

The recognized mappings are Note/Notes, Tip/Hint, Warning/Caution, Important,
Danger/Error, Example, and the visibly boxed `Tips or important notes` label.
A label must be at the start of a top-level block;
ordinary prose such as “note that ...” is not a candidate. A standalone label
may absorb consecutive prose paragraphs until a heading, list, table, code,
image, source-page reference, or another structural block. The marker itself
is removed as presentation syntax, while the body remains unchanged.

Labels inside lists, tables, code fences, or other nested structures remain
unchanged and are recorded as uncertain for Agent review. Existing Callouts
are left unchanged. For existing Markdown, the shared Callout helper applies
the same supported-label rule; PDF geometry is still required to discover a
new boxed region during generation.

## Preview and apply

The reusable helper is `scripts/markdown_layout_repair.py`:

```text
preview --book-root <markdown-root> --report <preview.json> \
  [--source-reference-style plain-blockquote]
apply --book-root <markdown-root> --report <report.json> --backup <backup.zip> --confirm-apply
```

For a partial repair, repeat `--include <relative-file.md>` for each selected
content file. The paths are relative to `--book-root`; the helper rejects
absolute paths, paths outside the root, and non-content Markdown files.

The helper defaults clear Figure captions to blockquotes, matching the
Obsidian-oriented presentation. Use `--figure-caption-style plain` when the
book-specific plan calls for plain captions. Use `--callout-style plain` or
`--callout-style none` when the current book does not use Obsidian Callouts.

When an earlier generator manifest exists, pass it to both commands with
`--baseline-manifest <latest-manifest.json>`. The helper compares current
Markdown hashes with the manifest's recorded generated hashes. If a possible
manual change is found, `apply` stops before creating a new backup or writing
files; the current file can then be reviewed as a new baseline.

The helper scans Markdown content outside technical/resource directories. The
Agent must review representative preview changes before apply, especially
Figure associations and headings containing extracted page-number debris.
Ambiguous regions remain unchanged and are listed in `uncertain` in the
report.

The backup destination is selected for the current book. It is not a global
`File/...` requirement and should not be hard-coded into new books.

## Generation-time image and reference layout

For a new or explicitly regenerated chapter, image objects should be treated
as positioned page events when the PDF exposes usable rectangles. Insert the
page reference immediately before each image, then emit the image and its
locally confirmed Figure caption:

```markdown
> Source PDF, p. 49

![[Assets/Figure-p0049-833.png]]

> Figure 2.7 – VS Build and the Output window
```

This is controlled by the internal output choices `image_placement`,
`source_reference_style`, and `figure_caption_style`. Multiple images on one
page are ordered by `y0`, `x0`, then PDF object identity. If a PDF object has
no usable rectangle, retain it and place it using the configured fallback,
while recording the fallback in the report. Never infer a caption solely from
an image filename or move a Figure mention embedded in ordinary prose.

When `inline_image_policy` is `auto`, an image is treated as a line-level icon
only when its display rectangle overlaps one text line by a meaningful amount
and its width and height are close to that line's height. The icon is inserted
at its horizontal position using `inline_image_syntax` (Obsidian Wiki syntax by
default), without an independent source-page reference or Figure caption.
Images that overlap multiple lines, code, tables, or an unclear structural
region remain block-level and are recorded as ambiguous. Use
`inline_image_policy: block` to disable this classification for a book whose
small images should all remain independent blocks.

The coordinate strategy is deliberately local: a page with ambiguous columns,
overlapping objects, or an uncertain caption may use a conservative fallback
and must be reported for Agent review rather than forced through a global
ordering rule.
