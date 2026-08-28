# Maintenance protocol

Maintenance starts from the generated Markdown system and its auxiliary records, wherever the user chose to keep them.

1. Identify the source PDF, output root, current plan/configuration, latest manifest, and latest report.
2. Check the source PDF hash and inspect the current output before proposing changes.
3. Ask the Agent to compare the new PDF structure or requested change with the previous plan. Do not assume that a previous book's layout applies to another book.
4. Present only the affected book-specific decisions: changed chapter boundaries, new sections, layout anomalies, table/code/image choices, and output paths.
5. Run a conversion preview and show the affected files and representative content.
   When only a configured front-matter, appendix, or other section needs
   regeneration, use the section's stable id with `--only-sections` so
   unrelated chapters and generated outputs are not selected.
6. Create a backup before changing generated files.
   A full-book ZIP should exclude the existing backup directory itself; prior
   historical backups remain untouched and are not recursively copied.
7. Update only files still matching the previous generated hash and marker. Preserve manual edits and report conflicts for discussion.
8. Let the Agent review the updated regions and perform only clearly low-risk local repairs automatically.
9. Audit source fidelity, order, links, attachments, code fences, tables, provenance, and generated-file hashes.

Do not move, delete, or duplicate existing notes as part of routine maintenance. Migration is a separate user-approved task.
