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
  sections: true
  attachments: true
  code_blocks: true
  tables: true
  visual_tables: true
  lens: false
  moc: true

output:
  chapter_filename: "Chapter {number:02d} - {title}.md"
  section_filename: "{title}.md"
  moc_filename: "MOC - {book}.md"
  page_links: headings-and-code

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

sections:
  - id: preface
    type: paratext
    title: "Preface"
    folder: "00_Paratext"
    filename: "06_Preface.md"
    start_page: 14
    end_page: 21
  - id: part-1-overview
    type: part-overview
    title: "Part 1 - Introduction"
    folder: "01_Part I - Introduction"
    filename: "00_Part Overview.md"
    start_page: 10
    end_page: 11
  - id: index
    type: back-matter
    title: "Index"
    folder: "04_Back Matter"
    filename: "01_Index.md"
    start_page: 100
    end_page: 110

book_metadata:
  technology: "Unreal Engine 5"
  language: "C++"

frontmatter:
  type_field: type
  tags:
    - book/example

code_blocks:
  enabled: true
  inline: true
  min_lines: 2
  min_chars: 60
  languages:
    cpp: cpp
    shell: bash
    powershell: powershell
    ini: ini
    default: text

visual_tables:
  enabled: true
  regions:
    - id: data-types
      start_page: 71
      end_page: 72
      columns: [65, 125, 185, 470]
      headers: ["Data type", "Size (bytes)", "Description"]
      page_y_ranges:
        "71": [120, 575]
        "72": [60, 270]

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
- `book_title`: optional display title used in frontmatter and MOC when the resource folder key contains additional naming characters such as `《》`.
- `modules`: booleans for `chapterize`, `sections`, `attachments`, `code_blocks`, `tables`, `visual_tables`, `lens`, and `moc`. `chapterize` is always required by `apply`.
- `output.chapter_filename` and `output.section_filename`: support `{number}`, `{number:02d}`, `{title}`, and `{book}`. The resulting filename is sanitized.
- `output.page_links`: `chapter` (default) keeps one stable source link per chapter, `every-page` adds a link for every PDF page, `headings-and-code` links detected headings, code blocks, visual tables, and images, and `none` omits generated page links.
- `attachments.include_section_kinds`: optional section types whose images should be attached in addition to chapter images. By default, front-matter images are excluded as publisher/decorative material; set this explicitly when they are part of the book content.
- `chapters`: optional explicit chapter records. `start_page` and `end_page` are one-based physical PDF pages; `print_pages` is descriptive metadata. Explicit records take precedence over inferred boundaries.
- `parts`: optional ranges used when chapter records do not already contain their output folder/part. A part may provide `start_chapter`, `end_chapter`, and `folder`.
- `sections`: optional non-chapter records for title pages, front matter, Part overviews, indexes, and other back matter. Each record has an `id`, `type`, `title`, output folder/filename, and physical page range.
- `table_transform.enabled`: enables the conservative two-column table pass. It recognizes only top-level `- **Term**—Description` and `- **Term**: Description` runs.
- `visual_tables.enabled`: enables only explicitly configured visual table regions. Each region requires `columns`, `headers`, and page-specific `page_y_ranges`; the PDF drawing layer must confirm stable grid lines. `|` in cells is escaped.
- `code_blocks.enabled`: enables monospace/Courier detection. Blocks below `min_lines` and `min_chars` remain inline code when `inline` is true. `languages` maps inferred C++, shell, PowerShell, and INI blocks; uncertain blocks use `text`.
- `frontmatter.type_field`: chooses the primary frontmatter field name (`type` for new books, `kind` for legacy compatibility). `frontmatter.tags` and `book_metadata` are copied into generated notes according to the output contract.
- `lens`: optional heading-based extraction. It is disabled unless both the module and configuration enable it.
- `ocr.enabled`: must remain false for scans unless the user explicitly authorizes OCR. This skill detects scans but does not silently OCR them.

When `chapters` is omitted, the pipeline uses PDF bookmarks or conservative chapter-heading detection and exposes the result in `dry-run`. Do not apply inferred boundaries without user review.
