---
name: video-transcript-polisher
description: Conservatively polish Whisper or ASR video lecture transcripts into readable Markdown while preserving the original wording, order, and meaning; first assess whether single-agent or multi-agent handling is worthwhile and require explicit user confirmation before delegation or file writes; when explicitly requested, backfill an approved processed copy into a separate Markdown target while preserving its frontmatter; do not use for summarizing, translating, or rewriting the lecture.
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
- For an ordinary transcript without leading metadata, normalize the output to begin with exactly one empty physical line; begin the transcript on the second line. Do not add a generated opening title, introduction, summary, or processing note.
- If YAML frontmatter or other Markdown metadata must remain at the file start for tooling to recognize it, preserve that metadata first and insert exactly one empty line before the transcript body. Metadata takes priority over the blank-first-line rule.
- Keep the original language and use that language's normal punctuation, spacing, capitalization, and paragraph conventions.
- Preserve timestamps, speaker labels, existing headings, code spans/blocks, quotations, and other useful Markdown metadata as close to their original positions as possible. Reflow surrounding prose only when needed for readability. Apply the heading-level rules below to existing headings that are deeper than level two.

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

- Use headings as sparse navigational markers, not as a summary or outline of the lecture. Do not add a generated heading at the opening; the transcript must begin first after the required leading blank line.
- Add a generated heading for an independent concept, method phase, or complete case only when multiple signals support a real topic transition, such as changed terminology plus a sustained new subject or an explicit structural turn. A paragraph break alone, a short example, or a minor illustration is not enough.
- Use only two levels: `#` for a broad topic or classroom phase and `##` for a distinct subtopic under the current `#`. Do not use `##` as a child unless a clear parent `#` exists; if the hierarchy is unclear, omit the generated heading. Do not add `###` or deeper headings.
- Keep complete cases, demonstrations, and method stages eligible for headings when they are developed as independent sections; do not title one-sentence examples. Build heading text from short phrases already present in the nearby transcript, allowing only small deletions, combinations, or capitalization changes. Never introduce a new fact, conclusion, or interpretation.
- Preserve existing `#` and `##` headings where possible. Normalize existing `###` and deeper headings to `##` while retaining their wording and position.
- Convert speech into an ordered list only when the source explicitly presents ordered items, such as “first,” “second,” or “one, two.” Convert into an unordered list only when the source clearly presents separate parallel items. Keep each item faithful to the source and retain its order.
- Do not manufacture lists from ordinary consecutive sentences. Avoid decorative tables, callouts, bolding, italics, or elaborate Markdown unless they already exist in the source or are necessary to preserve its structure.

## Mode selection and execution gate

Use two independent decisions for every request: the task mode and the execution/authorization stage. Never infer permission to delegate or write from a request to process files.

### Select the task mode

At the beginning of the request, classify the work as one of the following:

- **Single-file processing:** one input transcript; process the complete file as one unit.
- **Batch processing:** two or more input transcripts; process each file independently and never merge content across files.
- **Approved-output backfill:** the user explicitly asks to replace, backfill, or synchronize an already processed copy into another Markdown target; use the backfill rules below and do not polish the body again.

File count is a routing signal, not an automatic subagent threshold. If the request mixes task modes, has unclear mappings, or leaves the destination or overwrite scope unclear, remain in discussion/planning and ask for the missing detail.

### Assess delegation before proposing or using subagents

Before any subagent call, the main agent must perform a read-only assessment. Consider all of the following together:

- number of files and approximate total text size;
- whether files are independent or require shared cross-file context;
- recurring terminology and the required consistency of corrections and formatting;
- ASR ambiguity and the amount of semantic judgment required;
- whether independent review would materially improve confidence;
- expected coordination, latency, token, and cost overhead;
- whether subagent/delegation capability is actually available in the current environment.

Do not decide from file count alone. As a default judgment, recommend **main-agent only** for a small number of short or strongly interdependent files, and recommend **multi-agent processing** only when independent files are large or numerous enough that parallel work and independent review are likely to outweigh coordination costs. If the available information is insufficient, report that and stay in planning.

Before asking for authorization, present a concise assessment in the user's language:

```text
任务评估：

- 文件数量/总规模：
- 文件独立性：
- 跨文件术语一致性要求：
- ASR 纠错与排版复杂度：
- 独立复核的预期收益：
- 协调、耗时和成本风险：
- 当前是否具备子代理能力：
- 推荐策略：主代理处理 / 启用多代理 / 信息不足
- 推荐理由：
- 写入范围：

请确认处理策略和写入范围后再开始执行。
```

The assessment and recommendation are read-only. Even when the user explicitly asks to use subagents, do not start them until the user confirms the assessed strategy. The user may override the recommendation after the main agent states the expected tradeoffs; an explicit choice such as “确认启用多代理” or “确认由主代理处理” is required. If the user does not confirm, do not delegate, polish, or write.

### Planning, discussion, and confirmation gate

Any operation that will process and save a file must first pass through either Codex Plan Mode or a sufficiently detailed discussion. The planning/discussion stage must settle, as applicable, the input set, task mode, exact mappings, output paths, frontmatter and blank-line handling, overwrite scope, delegation recommendation and user choice, review strategy, and whether Git operations are excluded.

- If the user requests execution without a preceding plan or complete discussion, automatically produce the read-only plan and pause.
- Plan Mode itself never authorizes mutation. A detailed discussion can satisfy the planning stage only when the relevant scope and safety details are explicit.
- Treat only an unambiguous authorization such as “确认执行”, “同意写入”, “开始处理”, or an equivalent explicit statement as permission to proceed. Do not treat a bare “好的” as authorization when the scope or strategy is not explicit.
- One confirmation covers the complete, fixed file set, selected strategy, and stated write scope. If any of those change, invalidate the confirmation and plan again.
- Do not create polished intermediate content, invoke subagents, or write formal outputs before confirmation.

### Confirmed batch execution

When the user confirms a multi-agent batch:

- Give every processing agent the same immutable task brief, including the Skill rules, source language, shared terminology guidance, heading rules, output mapping, and prohibited transformations.
- Have one processing agent read and process one complete input file. Do not split one file across agents.
- Store candidate outputs in an isolated task-specific temporary directory; do not let subagents write the final `processed` or Analysis targets.
- After each processing wave, use an independent review pass to compare each candidate with its source for omissions, reordering, unsupported corrections, summaries, and formatting violations. Review agents report findings and do not rewrite final files.
- Choose concurrency dynamically from the assessment. When parallel processing is worthwhile, use bounded waves such as 4–8 files; this range is an execution limit, not the trigger for enabling multi-agent work.
- The main agent resolves reviewer disagreements and performs the final consistency check before any formal write.
- If a key file, review, mapping, or validation fails, stop the entire batch and do not perform partial formal writes.
- If delegation is unavailable after confirmation, report the limitation and fall back to the main agent without silently changing the content rules or write scope.

## Approved-output backfill mode

Use this mode only when the user explicitly asks to replace, backfill, or synchronize an already processed file into a separate Markdown target. This is a controlled file-placement operation, not another transcript-polishing pass.

- Treat the supplied processed file as authoritative. Do not re-run ASR correction, paragraph editing, heading generation, translation, summarization, or any other content transformation during backfill.
- Establish mappings by exact course identifier, such as `M2-01.md` → `Analysis-M2-01.md`. Do not match by list order or infer mappings from content. Verify that every mapping is one-to-one and that no requested input or target is missing.
- Before writing anything, run a read-only preflight for the whole batch. In the user's language, report the mappings, file existence, frontmatter presence and boundary, whether each target has an existing body, the old/new body size or hash summary, the replacement scope, and how leading blank lines will be normalized.
- Require an explicit confirmation after the preflight, even when the user initially said “replace.” Treat an existing target body as an expected replacement case, show it in the preview, and do not overwrite it until confirmation is received. Do not include a full content diff by default; provide one if requested.
- If any file is missing, duplicated, ambiguously mapped, or has an unclear frontmatter boundary, pause the entire batch and report the issue. Do not perform a partial write.
- For each target, preserve every byte from the start of the file through the end of its frontmatter closing-delimiter line. Replace only the bytes after that boundary. If frontmatter is absent or malformed, stop rather than reconstructing it.
- Produce exactly one blank line between the preserved frontmatter and the processed body. Remove only the processed file's leading blank-line wrapper when needed to avoid duplicating that separator; do not alter the body content itself.
- Do not create `.bak` files by default. After writing, provide a concise audit report listing successful mappings, whether each frontmatter prefix remained unchanged, body write status, exceptions, and final paths.
- Do not run `git add`, `commit`, `push`, or other repository operations unless the user explicitly requests them.

Use a concise preflight message in the user's language, for example:

```text
准备回填以下文件：

M2-01.md → Analysis-M2-01.md
M2-02.md → Analysis-M2-02.md

检查结果：
- 文件映射：通过
- frontmatter：完整，将保持不变
- 旧正文：为空/存在，将在确认后替换
- 写入范围：仅替换 frontmatter 后的正文
- 空行处理：frontmatter 后保留一个空行
- Git 操作：不执行

请确认后开始写入。
```

## Required workflow

1. Read the entire input and identify its language, existing Markdown structure, timestamps, speakers, and recurring terminology.
2. Make a conservative internal pass for likely ASR errors. Resolve only high-confidence word-level corrections; preserve ambiguous wording.
3. Apply minimal punctuation, sentence-boundary, capitalization, and spacing fixes.
4. Group the unchanged sequence of ideas into topic-coherent paragraphs, then add only justified two-level headings or explicit lists. Keep the opening free of generated headings.
5. Apply the output wrapper: use exactly one leading blank line for ordinary transcripts, or preserve required leading metadata and place exactly one blank line before the transcript body.
6. Compare the result against the source before saving: confirm that no claims, examples, numbers, dates, names, or meaningful spoken content were omitted, reordered, invented, or turned into a summary.
7. Save only the clean Markdown output at the requested destination or the default `processed/` destination. Never overwrite the source by default.

For multiple files, repeat this workflow independently for each file. Do not merge content across files or use a later file to invent content missing from an earlier one.

When the user explicitly requests an approved-output backfill, follow the backfill mode above instead of the ordinary processed-output destination behavior.
