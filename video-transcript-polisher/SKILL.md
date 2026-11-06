---
name: video-transcript-polisher
description: Faithfully edit Whisper or ASR lecture transcripts into readable, searchable Markdown while preserving the speaker's meaning, voice, and order. Use for transcript cleanup, restrained structure, or approved-output backfill. Excludes summarization, translation, and knowledge rewriting.
---

# Video Transcript Polisher

**Edit the transcript, not the knowledge.** Produce a readable record of the lecture. Every substantive statement and relationship must be traceable to what the speaker expressed.

## Editing boundaries

- **L1 · Text repair.** Correct supported ASR errors and restore punctuation, sentence boundaries, casing, and spacing in the source language. Join fragments and remove only clearly non-semantic fillers, stutter fragments, and accidental repeats. Keep meaningful connectors and questions.
- **L2 · Structure and local fluency.** Use the smallest local wording or word-order change that resolves a reading difficulty. Use sentence and paragraph boundaries to clarify transitions the speaker already made. Preserve the language, voice, order of ideas, claims, reasoning, examples, and technical details. Keep meaningful repetition, polarity, uncertainty, degree, conditions, scope, and exceptions. If the speaker later refers back to their own wording to correct or clarify it, keep the referenced wording as spoken, apart from punctuation or supported ASR repair. Leave difficult wording intact when smoothing it would require guessing.
- **L3 · Knowledge rewriting.** Exclude summaries, key takeaways, review questions, new definitions, explanations, examples, abstractions, causal links, and conclusions. Do not translate, fact-check the speaker's claims, or rearrange the lecture into a new argument.

For ASR substitutions, prefer user-supplied terminology or clear source repetition, then uniquely identifying context. Consult an authoritative reference only to resolve a specialized term's identity or spelling. For high-risk tokens such as numbers, dates, names, tools, APIs, functions, filenames, and code identifiers, require support from the user or the transcript itself. Familiarity and grammar alone are insufficient. Keep ambiguous readings and distinguish spoken self-corrections from transcription errors.

## Workflow

1. Inspect the input and destination read-only. Keep the source unchanged by default. Use the requested destination or `processed/<same filename>` alongside the input file. Resolve unclear paths, mappings, or replacement scope before writing.
2. Read the entire source before editing. Identify its language, topic order, recurring terminology, Markdown, timestamps, speaker labels, and metadata. If input, candidate output, or comparison cannot fit reliably in one pass, use [the long-transcript workflow](references/long-transcripts.md).
3. Repair the text and apply only source-supported structure. Honor user constraints on punctuation, headings, lists, and layout.
4. Review the complete candidate for fidelity and readability as separate passes. Repair issues and recheck affected passages before saving.
5. Save only the reviewed transcript. Keep diagnostic notes, review findings, and any unfinished work outside the transcript and formal target.

## Markdown

- Keep each paragraph a coherent unit of thought. Split at real changes such as setup to explanation or principle to example. Join fragments of one thought. Review walls of text and excessive one-sentence paragraphs without enforcing length or count targets.
- Preserve existing headings. When the speaker moves to another topic or method phase and gives it its own explanation or steps, use a short source-derived `##` where it helps navigation and the requested format allows it. A single example or transition needs no heading. Reserve a new `#` for a source-provided or user-requested title.
- When the speaker announces and enumerates several steps or parallel items, use a list if the requested format allows it. Preserve their order, detail, and qualifiers. Keep continuous reasoning in prose. Avoid decorative formatting, automatic emphasis, and labels that introduce an editorial conclusion.
- Retain existing Markdown formatting unless the requested edit calls for a change. Keep timestamps, speaker labels, code, quotations, and metadata in place relative to the related speech. Preserve YAML frontmatter verbatim and keep a valid existing separator. Use one blank line if a new separator is needed. Stop before writing if a metadata boundary is unsafe. An unwrapped transcript begins on the first line.

## Candidate review

- **Fidelity.** Walk source and candidate in order by sentence or thought. Account for each substantive source passage and trace each edited statement, heading, and list item back to its source. Inspect gaps, changes in high-risk tokens, and any change to emphasis, correction, or logical scope. Require evidence for ASR substitutions. Revert or repair an edit if its meaning or provenance is unclear.
- **Spoken repairs.** For “I just said X”, “by X I mean Y”, or “no, I meant Y”, locate the original X and the later repair in the candidate. Keep both in source order. For example, preserve “the right side is waiting” at its first occurrence and “by waiting I mean the write hasn't arrived” at the later clarification.
- **Readability.** Read the candidate continuously, then compare suspect passages with the source. Check for residual ASR fragments or noise, abrupt joins, walls of text, fragmented paragraphs, and whether headings and lists make the source's actual topics and enumerations easier to find. Reflow only where it improves the reading path.
- When checking file-based candidates with dense technical details or transcript markers, optionally run `python -X utf8 scripts/check_fidelity.py SOURCE CANDIDATE` from the Skill directory. Review flagged literal differences in context. An empty scan still requires both review passes.

## Other workflows

- Use the main agent for one file or a small, related set. For large or independent batches, delegation, or independent batch review, read [batch review](references/batch-review.md). Confirm materially unclear delegation, mapping, or overwrite choices. A clear, non-destructive request needs no extra approval turn.
- For explicit backfill or synchronization of an approved copy, use [approved-output backfill](references/approved-output-backfill.md) instead of editing the body again.
