# Batch processing and independent review

Read this file only when the request contains multiple transcripts, asks for delegation, or needs an independent review pass.

## Decide whether delegation is worthwhile

- First inspect the number of files, approximate total size, file independence, shared terminology, ASR ambiguity, review value, coordination cost, and whether delegation is available.
- Use the main agent for a small batch, short files, or files that need shared cross-file context.
- Consider multiple agents only when files are sufficiently independent and large or numerous enough for parallel work and independent review to outweigh coordination overhead.
- File count alone is not a delegation threshold.

## Before delegation

Give the user a concise assessment in their language covering file count/size, independence, terminology consistency, correction complexity, review value, coordination risk, available capability, recommended strategy, and write scope. Ask for explicit confirmation only when delegation, mappings, output scope, or overwrite behavior is not already unambiguous.

## Safe batch execution

- Process each input file as a complete unit. Never split one transcript across agents or merge content across files.
- Assign every input exactly once to a worker, candidate path, and reviewer. Keep candidates in an isolated task directory; workers must not write formal output targets.
- Give workers the same immutable content rules and output mapping. Workers must not broaden the file set, delegate further, or reopen planning.
- Compare each candidate with its source for omissions, reordering, unsupported corrections, summaries, and Markdown violations. Review paragraph structure separately from transcription fidelity.
- A long-block warning or paragraph with multiple independent moves requires an explicit review finding: confirm one coherent argument or request targeted reflow.
- If a spawn result is missing, contradictory, or reports capacity failure, stop the wave and reconcile assignments before launching replacements. Do not reuse an unresolved assignment.
- If a reviewer times out, retry once; if it still does not report, the main agent may perform the equivalent review. A failed review requires a targeted correction and another review.
- Write formal outputs only after every file has passed review or the main agent has completed the equivalent takeover review. Do not perform partial formal writes when a required mapping, candidate, review, or validation has failed.
