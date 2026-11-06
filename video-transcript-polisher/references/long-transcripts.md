# Long-transcript workflow

Use this workflow if reading, drafting, or reviewing the full transcript in one pass would risk omission or truncation. Keep one editor responsible for the whole file. In a batch, keep the same file assignment and candidate review gates.

## Map the full source

1. Identify the exact file and metadata boundary. Record a source fingerprint or equivalent identity check for use before assembly or when resuming. Record a stable position for the first and last body line.
2. Read the source in ordered windows through the actual end of the file, verifying that each read returned its intended range. Keep a compact topic map, confirmed spellings with evidence, unresolved terms, speaker and timestamp conventions, and the requested layout. Keep these notes outside the transcript.
3. Assign the entire body to consecutive, non-overlapping ranges identified by line numbers or equivalent stable positions. Prefer semantic, topic, or speaker boundaries. Keep code blocks, quotations, and meaningful corrections or qualifications together. If a read window cuts a unit, carry the open unit across the window and put the edit boundary at a safe position.

## Draft and verify

1. Maintain a private ledger with each source range, candidate location, and draft/review state. Edit one range at a time using the whole-file map. Read neighboring source for context when needed and emit only the owned range. Treat range boundaries as processing boundaries and carry headings or paragraphs across them when the source warrants it.
2. Compare each candidate range with its source using both review passes from [SKILL.md](../SKILL.md). If later evidence resolves a term or changes an earlier edit, revisit the affected range and its neighbors. Retry incomplete ranges in scratch space and keep exactly one reviewed candidate per range.
3. Verify the source identity, then assemble the reviewed ranges in source order with the original metadata prefix and valid separator once. Verify coverage from the first to the last source position with no gaps, overlaps, duplicate output, or unreviewed ranges. Re-read joins against both adjacent source ranges for missing or repeated speech, shifted qualifiers, and broken Markdown or speaker turns. Check the assembled outline, terminology, and start and end of the body against the full-source map.
4. In a batch, return the assembled candidate and coverage record to the assigned reviewer and follow the formal write gate in [batch review](batch-review.md). For a standalone file, write the formal output only after the assembled candidate passes review. If any range, join, or source identity cannot be verified, report the affected range and reason outside the transcript and leave the formal target untouched.
