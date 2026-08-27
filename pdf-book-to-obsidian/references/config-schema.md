# Book configuration schema

The default configuration path is:

```text
<vault>/File/Config/<book>/book-config.yaml
```

The pipeline accepts ordinary YAML when PyYAML is available and a small built-in YAML subset for simple mappings and lists. JSON is also valid YAML and is useful for machine-generated configurations.

Example:

```yaml
source_pdf: File/PDF/My Book/My Book.pdf

modules:
  chapterize: true
  attachments: true
  tables: true
  lens: false
  moc: true

output:
  chapter_filename: "Chapter {number} - {title}.md"
  moc_filename: "MOC - {book}.md"
  page_links: chapter

chapters:
  - number: 1
    title: "The First Chapter"
    part: "01_Part I - Introduction"
    start_page: 12
    end_page: 30
  - number: 2
    title: "The Second Chapter"
    part: "01_Part I - Introduction"
    start_page: 31
    end_page: 49

table_transform:
  enabled: true
  min_rows: 2

lens:
  enabled: false
  heading_regex: '^#{2,6}\\s+Lens\\s+(?P<number>[0-9∞]+)\\s*[—:-]\\s*(?P<title>.+)$'

ocr:
  enabled: false
```

## Fields

- `source_pdf`: vault-relative or absolute PDF path. A relative path is resolved from the vault root.
- `modules`: booleans for `chapterize`, `attachments`, `tables`, `lens`, and `moc`. `chapterize` is always required by `apply`.
- `output.chapter_filename`: supports `{number}`, `{title}`, and `{book}`. The resulting filename is sanitized.
- `output.page_links`: `chapter` (default) keeps one stable source link per chapter, `every-page` adds a link for every PDF page, and `none` omits generated page links. Use `chapter` when tables may span pages.
- `chapters`: optional explicit chapter records. `start_page` and `end_page` are one-based physical PDF pages. Explicit records take precedence over inferred boundaries.
- `table_transform.enabled`: enables the conservative two-column table pass. It recognizes only top-level `- **Term**—Description` and `- **Term**: Description` runs.
- `lens`: optional heading-based extraction. It is disabled unless both the module and configuration enable it.
- `ocr.enabled`: must remain false for scans unless the user explicitly authorizes OCR. This skill detects scans but does not silently OCR them.

When `chapters` is omitted, the pipeline uses PDF bookmarks or conservative chapter-heading detection and exposes the result in `dry-run`. Do not apply inferred boundaries without user review.
