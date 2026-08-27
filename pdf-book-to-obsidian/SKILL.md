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
- visual-table reconstruction only when geometry and headers support it;
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

For clear block-leading editorial labels such as `Note`, `Tip`, `Warning`, or
`Example`, use Obsidian Callouts in the default baseline. Do not convert words
such as “note” inside ordinary prose. Labels inside lists, tables, or code are
ambiguous and must remain unchanged for Agent review.

## Helper scripts

Use `scripts/pdf_book_pipeline.py` for deterministic inspection, preview, generation, auditing, and rollback. The compatibility commands remain available:

```text
inspect <vault> --book <book> [--source <pdf>]
dry-run <vault> --book <book> [--stages ...]
apply <vault> --book <book> --confirm-apply [--copy-source]
dry-run <vault> --book <book> --only-chapters 1,2
apply <vault> --book <book> --only-chapters 1,2 --allow-generated-drift --confirm-apply
audit <vault> --book <book>
rollback <vault> --book <book> --backup <zip> --confirm-rollback
```

For new work, the helper also accepts an explicit PDF and arbitrary output root through `--source` and `--output-root`; the Agent should use that only after the user has selected the destination. Read [references/config-schema.md](references/config-schema.md) for the small internal plan/config contract, [references/obsidian-markdown-baseline.md](references/obsidian-markdown-baseline.md) for Obsidian syntax, [references/output-contract.md](references/output-contract.md) for generated-file expectations, and [references/maintenance-protocol.md](references/maintenance-protocol.md) when updating an existing conversion.

For a partial regeneration, use `--only-chapters` only after the user has
confirmed the scope. The helper skips non-chapter outputs, records the scope,
and merges the selected file records into the existing manifest. A drifted
generated chapter may be replaced only with the explicit
`--allow-generated-drift` flag; this flag cannot authorize a full regeneration
or a non-generated/manual file.

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

These choices affect presentation only; they do not authorize the Agent or
the code to invent, translate, summarize, or reorder source content.
