# Approved-output backfill

Read this file only when the user explicitly asks to replace, backfill, or synchronize an already processed transcript into a separate Markdown target.

This is a controlled placement operation, not a second polishing pass. Treat the supplied processed copy as authoritative and do not rerun ASR correction, paragraph editing, heading generation, translation, summarization, or other content transformation.

## Preflight

- Establish exact one-to-one mappings by course or file identifier, such as `M2-01.md` → `Analysis-M2-01.md`. Never match by list order or inferred content.
- Check the whole batch before writing: every source and target exists, mappings are unique, and each target's frontmatter boundary is clear.
- Report the mappings, frontmatter status, whether each target has an existing body, old/new body size or hash summaries, replacement scope, and blank-line normalization. Require explicit confirmation when replacement or overwrite scope is not already unambiguous.

## Replacement and verification

- Preserve every byte from the target start through the frontmatter closing-delimiter line. Replace only the bytes after that boundary. Stop if frontmatter is absent or malformed.
- Produce exactly one blank line between preserved frontmatter and the processed body. Remove only the processed copy's leading wrapper when needed to avoid duplicating that separator.
- Before writing, record source hashes, target frontmatter-prefix hashes, and expected candidate-body bytes. Construct and inspect every expected output before writing any target.
- After writing, verify every source hash, frontmatter-prefix hash, and candidate-body byte sequence. Report successful mappings, prefix preservation, body write status, exceptions, and final paths.
