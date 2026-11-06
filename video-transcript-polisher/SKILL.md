---
name: video-transcript-polisher
description: Faithfully edit Whisper or ASR lecture transcripts into readable, searchable Markdown while preserving the speaker's meaning, voice, and order. Use for transcript cleanup, restrained structure, or approved-output backfill. Excludes summarization, translation, and knowledge rewriting.
---

# Video Transcript Polisher

**Edit the transcript, not the knowledge.** Produce a readable record of the lecture. Every substantive statement and relationship must be traceable to what the speaker expressed.

## Editing boundaries

- **L1 · Text repair.** Restore punctuation and sentence boundaries first, then clear mechanical noise and fix unambiguous local grammar, such as doubled function words or a broken verb form. Actively repair these defects when the intended reading is clear. Restore casing and spacing. Join fragments that belong together. Keep meaningful connectors and questions.
- **L2 · Structure and local fluency.** Use the smallest repair within a phrase, sentence, or adjacent sentences. Adjust word order only as needed to clarify an existing thought. Preserve the language, voice, order of ideas, claims, reasoning, examples, and technical details. Keep meaningful repetition, polarity, uncertainty, degree, conditions, scope, and exceptions. If the speaker later corrects or clarifies their own wording, keep the referenced wording apart from punctuation or supported ASR repair. Preserve uncertain wording and screen references when the source cannot resolve them.
- **L3 · Knowledge rewriting.** Exclude summaries, key takeaways, review questions, new definitions, explanations, examples, abstractions, causal links, and conclusions. Do not translate, fact-check the speaker's claims, or rearrange the lecture into a new argument.

For uncertain word identities, prefer user-supplied terminology or clear source repetition, then uniquely identifying context. Consult an authoritative reference only to resolve a specialized term's identity or spelling. Numbers, dates, names, tools, APIs, functions, filenames, and code identifiers require support from the user or transcript. Apparent inconsistencies in the speaker's facts or arithmetic do not establish an ASR error.

Remove an abandoned starter when it states no distinct information, the speaker never resumes it, and the following complete thought stands on its own. Keep a supported time or setup phrase with that thought. For example, repair “By the end of the day, we might need. Not every station will still be open” to “By the end of the day, not every station will still be open.” Preserve the complete thought and never use it to supply the missing object. Mark the interruption if the fragment may carry meaning.

When the intended wording or grouping inside a garbled phrase is unclear, copy that whole span verbatim. Fix obvious restarts around it without deleting or reordering words inside it. For example, edit “I did, in the demo, I did sort of section other section pass” to “In the demo, I did sort of section other section pass.”

## Workflow

1. Inspect the input and destination read-only. Keep the source unchanged by default. Use the requested destination or `processed/<same filename>` alongside the input file. Resolve unclear paths, mappings, or replacement scope before writing.
2. Read the entire source before editing. Identify its language, topic order, recurring terminology, Markdown, timestamps, speaker labels, and metadata. If input, candidate output, or comparison cannot fit reliably in one pass, use [the long-transcript workflow](references/long-transcripts.md).
3. Locate source sentences with clear repairable faults and mark the start and source wording of sustained topic or demo phases. Use those locations to guide the edit. Honor user constraints on punctuation, headings, lists, and layout.
4. Review the complete candidate for fidelity and readability as separate passes. Repair issues and recheck affected passages before saving.
5. Save only the reviewed transcript. Keep diagnostic notes, review findings, and any unfinished work outside the transcript and formal target.

## Markdown

- Keep each paragraph a coherent unit of thought. Split at real changes such as setup to explanation or principle to example. Join fragments of one thought. Review walls of text and excessive one-sentence paragraphs without enforcing length or count targets.
- Preserve existing headings. When a named tool, method, project example, or demonstration phase gets its own explanation or steps, put a short source-derived `##` before it if the format allows and it helps readers locate the phase. Keep the spoken transition and its explanation in the body. A brief example or passing mention stays in prose. Use no new headings when there is no useful phase boundary. Reserve a new `#` for a source-provided or user-requested title. A `##` can stand on its own.
- Format explicit steps or parallel items as a list when it improves scanning and the format allows it. Preserve their order, detail, and qualifiers. Keep continuous reasoning in prose. Avoid decorative formatting, automatic emphasis, and labels that introduce an editorial conclusion.
- Retain existing Markdown formatting unless the requested edit calls for a change. Keep timestamps, speaker labels, code, quotations, and metadata in place relative to the related speech. Preserve YAML frontmatter verbatim and keep a valid existing separator. Use one blank line if a new separator is needed. Stop before writing if a metadata boundary is unsafe. An unwrapped transcript begins on the first line.

## Candidate review

- **Fidelity.** Walk source and candidate in order by sentence or thought. Account for each substantive source passage and trace each edited statement, heading, and list item back to its source. Check gaps, high-risk tokens, emphasis, corrections, and scope. For interrupted or ambiguous speech, revert any edit that supplies missing meaning or picks one unresolved reading.
- **Spoken repairs.** For “I just said X”, “by X I mean Y”, or “no, I meant Y”, locate the original X and the later repair in the candidate. Keep both in source order. For example, preserve “the right side is waiting” at its first occurrence and “by waiting I mean the write hasn't arrived” at the later clarification.
- **Readability opportunities.** Revisit the source locations marked for repair or navigation. Fix any still-unambiguous grammar or sentence fault. For a clearly named, sustained transition, verify the heading and paragraph break, or retain prose if the format or scope warrants it. Read through for noise, abrupt joins, walls of text, and fragments. Recheck fidelity for any new change.
- When checking file-based candidates with dense technical details or transcript markers, optionally run `python -X utf8 scripts/check_fidelity.py SOURCE CANDIDATE` from the Skill directory. Review flagged literal differences in context. An empty scan still requires both review passes.

## Other workflows

- Use the main agent for one file or a small, related set. For large or independent batches, delegation, or independent batch review, read [batch review](references/batch-review.md). Confirm materially unclear delegation, mapping, or overwrite choices. A clear, non-destructive request needs no extra approval turn.
- For explicit backfill or synchronization of an approved copy, use [approved-output backfill](references/approved-output-backfill.md) instead of editing the body again.
