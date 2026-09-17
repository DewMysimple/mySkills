---
name: video-transcript-polisher
description: Faithfully polish Whisper or ASR lecture transcripts into readable Markdown while preserving the source wording, order, and meaning. Use for transcript cleanup and restrained structure when useful, not summarizing, translating, or rewriting; read the batch or backfill reference only when that mode is actually needed.
---

# Video Transcript Polisher

Polish video-course and classroom transcripts into a readable, searchable record of what the lecturer said.

## Scope and invariants

- Preserve the source language, order of ideas, examples, claims, reasoning, numbers, dates, names, technical details, and meaningful repetition.
- Do not summarize, translate, condense, expand, explain, fact-check, or turn the lecture into a new article.
- Follow explicit user constraints on punctuation-only cleanup, headings, lists, or layout. Do not add structure the user has declined.
- Correct only high-confidence ASR wording errors. If the intended wording is still ambiguous, preserve the source.
- Keep the source file untouched. Use the requested destination, or a sibling `processed/` copy with the same filename when no destination is supplied. Never overwrite the source by default.

## Core workflow

1. Read the complete file before editing. Identify its language, existing Markdown, timestamps, speakers, and recurring terminology.
2. Make a conservative internal pass for likely ASR errors. Correct a word only when source repetition, uniquely identifying context, a user-provided reference, or an authoritative reference makes the intended word clear. Grammar or familiarity alone is not enough.
3. Apply only necessary punctuation, sentence-boundary, capitalization, spacing, and paragraph changes.
4. Map the source's topic phases before formatting. Follow the user's requested format, and add Markdown structure only when it materially improves navigation: use headings for clear sustained topic changes or independent method phases, and lists for explicit parallel or ordered items.
5. Compare the result with the source before saving. Confirm that no claims, examples, numbers, names, meaningful spoken content, or idea order were lost or invented.
6. Save only the clean output at the requested destination or the default `processed/` destination.

## Conservative correction rules

- A recurring technical term, obvious homophone, malformed word, number, date, name, or acronym may be corrected when the surrounding transcript strongly establishes the intended form.
- Prefer evidence in this order: user-provided terminology or source repetition, uniquely identifying local context, then an authoritative external reference when needed. Treat grammar and general plausibility only as supporting evidence.
- Use an authoritative external reference only when needed to verify the spelling or identity of a specialized term. Never use it to add facts or override what the speaker said.
- Keep awkward but grammatical wording, meaningful repetition, self-correction, hedging, transitions, modality, pronouns, tense, and voice.
- Treat numbers, dates, proper names, products, tools, APIs, functions, labels, filenames, and code identifiers as high-risk tokens. Change them only when source repetition, uniquely identifying context, or a user-provided reference supports the correction; never normalize them merely because another form looks more familiar.

## Sentence, paragraph, and Markdown cleanup

- Restore sentence boundaries and punctuation without creating or removing a proposition. Join fragments that belong to one sentence or thought.
- Remove only obvious non-semantic ASR noise such as pure hesitation sounds, duplicated partial fragments, or accidental repeated words. Do not delete ordinary spoken connectors by default.
- Make each paragraph one coherent unit of thought. Split at real boundaries between setup, explanation, example, method step, contrast, result, implication, or transition, while preserving every sentence and its order.
- Review any paragraph whose length or internal shifts make its topic boundary hard to follow. Sentence and character counts are signals only, never output targets. Do not force one sentence per paragraph or split code, quotations, timestamps, or speaker turns destructively.
- Preserve timestamps, speaker labels, code spans/blocks, quotations, existing headings, and useful metadata near their original positions.
- Use headings only when clear sustained topic changes or independent method phases make navigation materially easier; do not target a heading count or create a heading for every paragraph or isolated example. Use `#` only for a source-provided or user-requested document title and `##` for useful section boundaries.
- Build generated headings from nearby source wording; normalize them for readability but never introduce a fact, conclusion, or topic absent from the transcript. Preserve existing `#` and `##` headings, and normalize deeper headings to `##` only when needed.
- Create ordered or unordered lists when the speaker clearly presents ordered or parallel items, such as named design patterns or explicit workflow steps. Do not manufacture tables, callouts, bolding, italics, or decorative structure.
- Before saving, check heading coverage: if the transcript contains multiple sustained topics but the output has no headings, revisit the topic map and add the smallest useful set only when consistent with the user's request and the source format.

## Output wrapper

- Keep the original language's normal punctuation, spacing, capitalization, and paragraph conventions.
- For an ordinary transcript, start the body on the first line unless the user or destination format requires a leading wrapper. Do not add a leading blank line merely as a house style.
- Preserve YAML frontmatter and other required metadata verbatim. Retain the existing metadata/body separator when valid; when creating a separator for a new target, use one blank line. Do not repair malformed metadata as part of transcript polishing, and stop before writing if the body boundary is unsafe to determine.

## Conditional modes

- For one file or a small, related set of files, handle the work with the main agent.
- For a large or independent multi-file batch, read [references/batch-review.md](references/batch-review.md) before delegating or coordinating independent review.
- When the user explicitly asks to replace or synchronize an already processed copy into another Markdown target, read [references/approved-output-backfill.md](references/approved-output-backfill.md) and do not polish the body again.
- Confirm the destination, overwrite scope, mappings, and any delegation choice when they are unclear or carry a material write risk. A clear request with a fixed non-destructive scope does not need an extra approval turn.
