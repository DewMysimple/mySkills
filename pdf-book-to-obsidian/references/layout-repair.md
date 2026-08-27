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

## Editorial Callouts

Clear block-leading labels are formatted as Obsidian Callouts in the default
mode:

```markdown
> [!NOTE]
>
> Original note text.
```

The recognized mappings are Note/Notes, Tip/Hint, Warning/Caution, Important,
Danger/Error, and Example. A label must be at the start of a top-level block;
ordinary prose such as “note that ...” is not a candidate. A standalone label
may absorb consecutive prose paragraphs until a heading, list, table, code,
image, source-page reference, or another structural block. The marker itself
is removed as presentation syntax, while the body remains unchanged.

Labels inside lists, tables, code fences, or other nested structures remain
unchanged and are recorded as uncertain for Agent review. Existing Callouts
are left unchanged. URL fragments are not merged as part of this operation.

## Preview and apply

The reusable helper is `scripts/markdown_layout_repair.py`:

```text
preview --book-root <markdown-root> --report <preview.json>
apply --book-root <markdown-root> --report <report.json> --backup <backup.zip> --confirm-apply
```

Use `--callout-style plain` or `--callout-style none` when the current book
does not use Obsidian Callouts.

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

The coordinate strategy is deliberately local: a page with ambiguous columns,
overlapping objects, or an uncertain caption may use a conservative fallback
and must be reported for Agent review rather than forced through a global
ordering rule.
