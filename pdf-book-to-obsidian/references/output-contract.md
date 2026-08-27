# Output and report contract

## Managed resource folders

```text
File/PDF/<book>/           source PDFs
File/Config/<book>/        book-config.yaml
File/Reports/<book>/       JSON reports and latest manifests
File/Backups/<book>/       ZIP rollback archives
File/Attachment/<book>/    extracted images
```

Chapter notes remain in the configured vault output folders, normally one folder per Part. Generated notes contain a YAML frontmatter marker:

```yaml
type: chapter
generated_by: pdf-book-to-obsidian
generator_version: 0.1.0
source_sha256: <sha256>
source_pages: [12, 30]
source_pdf: File/PDF/<book>/<source>.pdf
```

Chapter records may also include `part`, `chapter`, `title`, `print_pages`, `pdf_pages`, `technology`, `language`, and configured tags. Section records use the same provenance fields with their configured `type`. The primary type key is controlled by `frontmatter.type_field`; `kind` is retained for legacy configurations.

For a book with explicit physical ranges, `pdf_pages` and `source_pages` are one-based PDF page numbers. `print_pages` is the book's printed-page range and is metadata only.

## Applied report

An apply creates a timestamped JSON report and updates `latest-report.json` and `latest-manifest.json`. The report records:

- source path, SHA-256, page count, text-page count, and scan quality;
- configuration path and SHA-256;
- requested and effective modules;
- chapter boundaries and generated outputs;
- before/after hashes for changed files;
- table and row counts, skipped blocks, and conflicts;
- visual-table audits, including configured page regions, explicit headers, row counts, grid status, and skip reasons;
- backup path and rollback metadata.

The manifest's `files` records are the authority for detecting later manual edits. A file may be updated only when its current hash equals the previous applied `after_sha256` and it still carries the generator marker.

## Dry-run and audit

`inspect` and `dry-run` print JSON and do not write the vault by default. They may write only when the user explicitly supplies `--report-out`. `audit` is read-only and returns a non-zero exit code for missing generated files, hash drift, malformed frontmatter, broken local links, or invalid tables.
