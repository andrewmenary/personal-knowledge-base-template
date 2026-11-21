---
name: log
description: Capture or process daily rapid-log entries in the Second Brain. Use when asked to log a task, note, event, or process a daily journal.
---

# Process a daily rapid log

The user can say "Log a task to review the design" or "Process today's journal." Read `SCHEMA.md` and `index.md`; use the user's date if supplied, otherwise the local current date.

1. For an existing journal file, use its exact path. For entries supplied in conversation, create a new uniquely named UTF-8 Markdown capture under `inbox/` with the date and the user's entries. Never overwrite an existing capture. Retain the capture: it is the CLI's recorded original source, and deleting it will cause a source-drift warning. Tell the user that `inbox/` is Git-ignored and the capture will not be committed.
2. If the journal is already in `raw/`, use that source directly; do not ingest it again. Otherwise run `python tools/second_brain.py ingest "<capture-path>" --journal --json` from the repository root, passing the path safely as one argument. Check the exit status; on failure leave the capture intact and report the error. The command files raw Markdown with `kind: journal`, updates the index, and logs ingestion.
3. Read the resulting raw journal. Recognize `+`, `X`/`x`, `>`, `<`, `-`, `O`, and the `*`, `!`, `=`, `^`, and documented custom signifiers. Preserve indentation and subtask relationships. Route tasks, events, notes, and collections to appropriate wiki pages per `SCHEMA.md`, citing the raw journal; do not invent a project, date, person, or shorthand expansion.
4. For a status update or migration, identify the exact canonical task first. If it is ambiguous, ask the user rather than guessing. Raw journals permit status-only edits; other raw sources are immutable. The `migrate` CLI searches explicitly marked raw journals and collection Markdown for an exact, case-insensitive, whitespace-normalized task description, excluding the reserved date and destination syntax described in `SCHEMA.md`; it rejects multiple matches. Verify the intended entry before using `python tools/second_brain.py migrate "<task>" <status>`. Scheduled tasks require `--date YYYY-MM-DD`. Otherwise, make the targeted permitted status edit and append a migration entry to `log.md`. Never create duplicate canonical tasks.
5. Update `index.md` for new wiki pages. If processing an existing raw journal without ingestion, append a timestamped log entry for that processing; otherwise do not duplicate the ingest entry. Report what was captured and any questions. Do not claim OCR succeeded for images without a transcription.
