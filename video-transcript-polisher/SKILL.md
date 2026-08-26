---
name: video-transcript-polisher
description: Conservatively polish Whisper or ASR video lecture transcripts into readable Markdown while preserving the original wording, order, and meaning; do not use for summarizing, translating, or rewriting the lecture.
---

# Video Transcript Polisher

Polish video-course and classroom transcripts produced by Whisper or another speech-to-text system. The result should be easier to read while remaining a faithful, searchable record of what the lecturer said.

## Non-negotiable boundary

- Preserve the source language, order of ideas, examples, claims, reasoning, numbers, dates, names, technical details, and meaningful repetition.
- Do not summarize, translate, condense, expand, explain, fact-check the lecturer, write a new article, or add a conclusion.
- Do not correct a statement merely because it may be factually wrong. Correct only likely transcription errors in the words themselves.
- If a possible correction is not supported with high confidence by the surrounding context, grammar, repeated terminology, common knowledge, or a clearly authoritative term reference, leave the original wording unchanged.
- Do not expose uncertainty markers, edit annotations, a change log, or a processing preface in the clean output unless the user explicitly asks for them.

## Input and output

- Accept one or more transcript text files, especially Markdown files, and process each file independently.
- Keep the source file untouched. When the user has not supplied another destination for a local file, write a Markdown copy to a `processed/` directory beside the input, keeping the original filename.
- Start the output with the transcript itself. Do not add a title, introduction, summary, or processing note that is not already present in the source.
- Keep the original language and use that language's normal punctuation, spacing, capitalization, and paragraph conventions.
- Preserve timestamps, speaker labels, existing headings, code spans/blocks, quotations, and other useful Markdown metadata as close to their original positions as possible. Reflow surrounding prose only when needed for readability.

## Conservative transcription correction

Read the complete file before deciding on corrections so that terminology and references later in the lecture are available. Correct a word only when the intended word is clear from the transcript and the correction preserves the speaker's meaning. Typical high-confidence corrections include:

- a recurring technical acronym rendered inconsistently by ASR, such as `LOM`, `OMS`, or `alum` where the surrounding lecture clearly means `LLM`;
- an obvious homophone or malformed word that breaks the sentence, such as `drop` where the context clearly requires `draft`;
- a number, date, name, or technical term whose correct form is established by nearby repeated context.

Use authoritative external references only when needed to verify the spelling or identity of a specialized term or proper name. External material may support a word-level correction, but it must never be used to add information, rewrite the lecture's claims, or override what the speaker actually said. When context and external sources do not make the intended wording clear, preserve the source wording.

Apply only the minimum grammatical or capitalization change needed after a high-confidence ASR correction. Do not make stylistic improvements merely because a sentence could sound more elegant in written prose.

Do not swap synonyms, change tense or voice, or smooth an awkward-but-plausible phrase. Treat a fluent but unusual sentence as part of the source unless there is clear evidence that ASR changed its wording.

## Sentence, paragraph, and speech cleanup

- Restore missing sentence boundaries and punctuation from syntax, cadence, and meaning. Do not create or remove a proposition.
- Join lines or fragments that belong to the same sentence or thought, including fragments caused by ASR segmentation.
- Split the transcript into coherent paragraphs when the topic, purpose, example, or reasoning changes. Avoid both one-sentence-per-paragraph formatting and very large unbroken blocks.
- Remove only obvious non-semantic ASR noise: pure hesitation sounds, duplicated partial fragments, or accidental repeated words that do not convey emphasis. Keep meaningful repetition, emphasis, self-correction, hedging, transitions, and natural spoken logic.
- Do not turn ordinary spoken connectors such as “so,” “now,” or “let's take a look” into deletions by default; remove them only when they are clearly empty noise in context.

## Light Markdown structure

- Add a short `##` heading only at a clear major topic transition. A heading may concisely describe the passage, but it must not introduce a new fact, argument, conclusion, or interpretation. Do not add one heading for every paragraph.
- Convert speech into an ordered list only when the source explicitly presents ordered items, such as “first,” “second,” or “one, two.” Convert into an unordered list only when the source clearly presents separate parallel items. Keep each item faithful to the source and retain its order.
- Do not manufacture lists from ordinary consecutive sentences. Avoid decorative tables, callouts, bolding, italics, or elaborate Markdown unless they already exist in the source or are necessary to preserve its structure.

## Required workflow

1. Read the entire input and identify its language, existing Markdown structure, timestamps, speakers, and recurring terminology.
2. Make a conservative internal pass for likely ASR errors. Resolve only high-confidence word-level corrections; preserve ambiguous wording.
3. Apply minimal punctuation, sentence-boundary, capitalization, and spacing fixes.
4. Group the unchanged sequence of ideas into topic-coherent paragraphs, then add only justified headings or explicit lists.
5. Compare the result against the source before saving: confirm that no claims, examples, numbers, dates, names, or meaningful spoken content were omitted, reordered, invented, or turned into a summary.
6. Save only the clean Markdown output at the requested destination or the default `processed/` destination. Never overwrite the source by default.

For multiple files, repeat this workflow independently for each file. Do not merge content across files or use a later file to invent content missing from an earlier one.
