# Approved-output backfill

Read this file only when the user explicitly asks to replace, backfill, or synchronize an already processed transcript into a separate Markdown target.

Treat the supplied approved copy as authoritative. Transfer its body without ASR correction, paragraph editing, heading generation, translation, summarization, or other content changes.

## Preflight

- Establish exact one-to-one mappings by course or file identifier, such as `M2-01.md` → `Analysis-M2-01.md`. Verify that each source and target exists and that every replacement is in the authorized scope. Match by identifier or explicit path.
- Use [batch processing](batch-review.md) to check collisions for multiple mappings. Keep preflight results internal. Proceed with clear authorized replacements and skip and report any ambiguous or unsafe mapping.

## Replacement and verification

- Preserve every byte from the target start through the frontmatter closing-delimiter line, including any BOM and line endings. Replace only the bytes after that boundary. Skip and report a target with absent or malformed frontmatter or an unreadable metadata boundary.
- Produce exactly one blank line between preserved frontmatter and the processed body. Remove only the processed copy's leading wrapper when needed to avoid duplicating that separator.
- For each target, record the approved source hash, target identity and prefix hash, and expected body bytes. Inspect the assembled output and recheck source and target identity before replacing the target safely. Save each verified replacement independently unless the user requests all-or-nothing behavior.
- After each write, verify the approved source hash, frontmatter prefix, and body bytes. Report saved paths and any skipped or failed mappings.
