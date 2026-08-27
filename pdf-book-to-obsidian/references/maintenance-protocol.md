# Maintenance protocol

1. Locate the managed PDF, configuration, latest manifest, and latest report for the book.
2. Verify the source PDF hash before planning changes. If it changed, show the new hash and require a new dry-run.
3. Use `audit` to classify generated files, manually edited files, missing attachments, and broken links.
4. Modify the configuration or source only after the user has chosen the intended change. Re-run `dry-run` and show the diff summary.
5. Apply only when there are no unapproved conflicts. Create a ZIP backup before overwriting generated files.
6. If a generated file has been manually edited, do not merge or overwrite it automatically. Preserve it and report the conflict for human resolution.
7. Use `rollback` only with the matching book and backup archive. Refuse rollback when a target file changed after the apply unless the user resolves that conflict explicitly.

Do not remove old reports, backups, source PDFs, or manual notes as part of routine maintenance. Historical `File/Conversion` folders from older projects are not used by the new pipeline; migrate them separately and retain the old copy until verified.
