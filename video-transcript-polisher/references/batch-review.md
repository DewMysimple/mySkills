# Batch processing

Use these rules for requests covering multiple files, including [approved-output backfill](approved-output-backfill.md).

## Map the files

- Identify each input and its one distinct destination before writing. Check for collisions between targets and with inputs, accounting for the filesystem's path and case rules. Treat paths or links whose identity or scope is uncertain as unsafe. Keep each source's content in its own output.
- Set aside all entries involved in a duplicate mapping. Classify each remaining mapping as create, explicitly authorized replacement, or conflict before editing. For example, “polish the originals into `Test/` using the same filenames” creates new outputs. An existing `Test/lesson.md` is a conflict even if it contains the same text as the source. In that case, use a distinct safe path if the request allows it, or skip the target and record the conflict.

## Verify and save each result

- For each transcript edit, complete both review passes in [SKILL.md](../SKILL.md). For a [long transcript](long-transcripts.md), verify coverage and joins before saving. Apply the byte checks in the backfill workflow to approved copies.
- Keep unfinished candidates outside formal targets. Check that the source still matches the reviewed input. Save each verified file as it is ready, using the mapped write mode from [SKILL.md](../SKILL.md). Coordinate writes so each target has a single publisher. Verify each saved result.
- Isolate mapping, reading, review, and write failures to the affected files. Report saved paths, skipped or failed files, and the reasons after completing the safe work.

When the user requests all-or-nothing behavior, validate every file and use a write plan that can honor the requested guarantee. If any check fails or the environment cannot support that guarantee, report the limitation before publishing any result.
