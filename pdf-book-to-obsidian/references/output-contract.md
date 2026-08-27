# Markdown knowledge-base output contract

The output is a general Markdown file system. The default syntax baseline is
Obsidian Flavored Markdown because it provides reliable note navigation and
asset embeds for the primary use case. A book may explicitly select the
portable `commonmark` baseline when the output must be consumed by other
Markdown applications. See [obsidian-markdown-baseline.md](obsidian-markdown-baseline.md)
for the official sources and presentation rules.

## Required results

- Main content is split at least by chapter.
- A book-level MOC or equivalent home page links to the generated structure.
- Structural navigation links connect Parts, chapters, and selected sections.
- A topic/term index page links clear concepts to the relevant notes.
- The source order and source language are preserved.
- Images, code, tables, captions, footnotes, and page references are retained when present and selected by the plan.

## Source fidelity

Generated notes may normalize layout artifacts such as ordinary line wrapping, repeated running headers, and confirmed reading order. They must not translate, summarize, spell-check, silently correct, or invent text.

Complex regions should retain a source-page reference and a reason whenever they are left unconverted.

## Provenance and maintenance

Generated Markdown may contain a small provenance marker with the source path, source hash, page range, generator name, and generator version. Technical reports and rollback metadata are separate from the reading structure.

The manifest is an internal maintenance aid. It records generated files, prior and resulting hashes, selected plan identity, and any local decisions. It must not be treated as permission to overwrite a changed or manual file.

## Preview and reports

The internal `dry-run` command is presented to users as a conversion preview. A preview should summarize:

- detected book structure;
- proposed output location and file granularity;
- detected assets, code, tables, and anomalies;
- planned transformations with representative examples;
- files to be created or updated;
- unresolved decisions and conflicts.

The preview does not write formal Markdown. Reports may be saved in a separate auxiliary location for later maintenance.
