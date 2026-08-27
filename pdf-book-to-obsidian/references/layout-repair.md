# Markdown layout repair

Use this mode when a PDF-to-Markdown result already exists and the user asks
for conservative reading-view cleanup. It is a repair pass, not a second PDF
conversion.

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

## Preview and apply

The reusable helper is `scripts/markdown_layout_repair.py`:

```text
preview --book-root <markdown-root> --report <preview.json>
apply --book-root <markdown-root> --report <report.json> --backup <backup.zip> --confirm-apply
```

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
