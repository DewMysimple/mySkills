# Long-transcript workflow

Use this workflow if reading, drafting, or reviewing the full transcript in one pass would risk omission or truncation. Use one source map and coverage ledger for the file.

## Map the full source

1. Identify the exact file and metadata boundary. Record a source fingerprint or equivalent identity check for use before assembly or when resuming. Record a stable position for the first and last body line.
2. Read the source in ordered windows through the actual end of the file, verifying that each read returned its intended range. Keep a compact topic map, confirmed spellings with evidence, unresolved terms, speaker and timestamp conventions, and the requested layout. Keep these notes outside the transcript.
3. Divide the entire body into consecutive, non-overlapping ranges identified by line numbers or equivalent stable positions. Prefer semantic, topic, or speaker boundaries. Keep code blocks, quotations, and meaningful corrections or qualifications together. If a read window cuts a unit, carry the open unit across the window and put the edit boundary at a safe position.

## Draft and verify

1. Track each source range, candidate location, and draft/review state in the ledger. Use the whole-file map for each range. Read neighboring source for context when needed and emit only the current range. Treat range boundaries as processing boundaries and carry headings or paragraphs across them when the source warrants it.
2. Compare each candidate range with its source using both review passes from [SKILL.md](../SKILL.md). If later evidence resolves a term or changes an earlier edit, revisit the affected range and its neighbors. Retry incomplete ranges in scratch space and keep exactly one reviewed candidate per range.
3. Verify the source identity, then assemble the reviewed ranges in source order with the original metadata prefix and valid separator once. Verify coverage from the first to the last source position with no gaps, overlaps, duplicate output, or unreviewed ranges. Re-read joins against both adjacent source ranges for missing or repeated speech, shifted qualifiers, and broken Markdown or speaker turns. Check the assembled outline, terminology, and start and end of the body against the full-source map.
4. Save the assembled file once its coverage, joins, source identity, and both reviews pass, using the verified destination. If a check fails, leave that target untouched and report the affected range and reason outside the transcript.
