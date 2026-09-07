---
name: video-transcript-polisher
description: Conservatively polish Whisper or ASR lecture transcripts into readable Markdown while preserving the source wording, order, and meaning. Use for transcript cleanup, not summarizing, translating, or rewriting; read the batch or backfill reference only when that mode is actually needed.
---

# Video Transcript Polisher

Polish video-course and classroom transcripts into a readable, searchable record of what the lecturer said.

## Scope and invariants

- Preserve the source language, order of ideas, examples, claims, reasoning, numbers, dates, names, technical details, and meaningful repetition.
- Do not summarize, translate, condense, expand, explain, fact-check, or turn the lecture into a new article.
- Correct only high-confidence ASR wording errors. If the intended wording is still ambiguous, preserve the source.
- Keep the source file untouched. Use the requested destination, or a sibling `processed/` copy with the same filename when no destination is supplied. Never overwrite the source by default.

## Core workflow

1. Read the complete file before editing. Identify its language, existing Markdown, timestamps, speakers, and recurring terminology.
2. Make a conservative internal pass for likely ASR errors. Correct a word only when context, grammar, repeated terminology, or a uniquely identified reference makes the intended word clear.
3. Apply only necessary punctuation, sentence-boundary, capitalization, spacing, and paragraph changes.
4. Add sparse Markdown structure only when supported by the source.
5. Compare the result with the source before saving. Confirm that no claims, examples, numbers, names, meaningful spoken content, or idea order were lost or invented.
6. Save only the clean output at the requested destination or the default `processed/` destination.

## Conservative correction rules

- A recurring technical term, obvious homophone, malformed word, number, date, name, or acronym may be corrected when the surrounding transcript establishes the intended form.
- Use an authoritative external reference only when needed to verify the spelling or identity of a specialized term. Never use it to add facts or override what the speaker said.
- Keep awkward but grammatical wording, meaningful repetition, self-correction, hedging, transitions, modality, pronouns, tense, and voice.
- Treat proper names, products, tools, APIs, functions, labels, filenames, and code identifiers as high-risk tokens. Do not normalize their casing or separators without a uniquely supported correction.

## Sentence, paragraph, and Markdown cleanup

- Restore sentence boundaries and punctuation without creating or removing a proposition. Join fragments that belong to one sentence or thought.
- Remove only obvious non-semantic ASR noise such as pure hesitation sounds, duplicated partial fragments, or accidental repeated words. Do not delete ordinary spoken connectors by default.
- Make each paragraph one coherent unit of thought. Split at real boundaries between setup, explanation, example, method step, contrast, result, implication, or transition, while preserving every sentence and its order.
- Treat a long block of roughly 6–8 complete sentences or 800–1000 English characters as a review trigger, not a mechanical limit. Do not force one sentence per paragraph or split code, quotations, timestamps, or speaker turns destructively.
- Preserve timestamps, speaker labels, code spans/blocks, quotations, existing headings, and useful metadata near their original positions.
- Use only sparse `#` and `##` headings for sustained topic changes or independent method phases. Build generated headings from nearby source wording; never introduce a fact or conclusion. Preserve existing `#` and `##` headings, and normalize deeper headings to `##` only when needed.
- Create ordered or unordered lists only when the speaker clearly presents ordered or parallel items. Do not manufacture tables, callouts, bolding, italics, or decorative structure.

## Output wrapper

- Keep the original language's normal punctuation, spacing, capitalization, and paragraph conventions.
- For an ordinary transcript, begin with exactly one leading blank line and start the transcript on the second line.
- If YAML frontmatter or other required metadata is present, preserve it first and put exactly one blank line before the transcript body.

## Conditional modes

- For one file or a small, related set of files, handle the work with the main agent.
- For a large or independent multi-file batch, read [references/batch-review.md](references/batch-review.md) before delegating or coordinating independent review.
- When the user explicitly asks to replace or synchronize an already processed copy into another Markdown target, read [references/approved-output-backfill.md](references/approved-output-backfill.md) and do not polish the body again.
- Confirm the destination, overwrite scope, mappings, and any delegation choice when they are unclear or carry a material write risk. A clear request with a fixed non-destructive scope does not need an extra approval turn.
