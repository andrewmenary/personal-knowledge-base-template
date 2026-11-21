# Second Brain Schema

This document is the Copilot-maintained contract for the repository.

## Content layers

- `raw/`: immutable source of truth. Markdown only. It may contain documents, emails, articles, transcripts, and journal entries.
- `raw/assets/`: image media referenced by raw Markdown.
- `wiki/`: agent-maintained derived knowledge.
- `wiki/collections/`: recurring groups merged from rapid logs.
- `wiki/output/`: disposable generated exports.
- `inbox/`: temporary staging; never the source of truth.
- `index.md`: read first; link pages with summaries and source counts.
- `log.md`: append-only timestamped operations.

## Ingested Markdown

Every raw source begins with YAML front matter:

```yaml
---
title: "Example"
source: "/original/location"
source_type: "file"
ingested_at: "2026-11-20T14:00:00Z"
source_sha256: "..."
tags: []
status: "active"
immutable: true
---
```

`title`, `source`, `source_type` (`file` or `url`), `ingested_at` (a timezone-aware ISO timestamp), `source_sha256` (64 hexadecimal digits), `tags` (a list of strings), `status` (a nonempty string), and `immutable` (`true`) are required.

Generated Markdown is GitHub-Flavored Markdown (GFM).

## Raw source immutability

Raw source prose must never be edited. The sole exception is status mutation in rapid-log journal entries:

- change `+` to `X`, `>`, or `<`
- change `[ ]` to `[X]`, `[>]`, or `[<]`
- use Markdown strikethrough for irrelevant tasks

Never duplicate a migrated task across days. Update or relocate its canonical status.
Only raw files explicitly marked with YAML `kind: journal` are eligible for CLI migration; missing or malformed front matter is never treated as a journal. Use `ingest <path> --journal` when ingesting a journal. Existing raw files without the marker remain immutable; an owner may explicitly classify a confirmed journal by adding this front-matter field before migration. Collections remain eligible for canonical task updates.

## Rapid logging

| Entry | Meaning | Route |
|---|---|---|
| `+` or `[ ]` | Task | active project page or `wiki/collections/tasks.md` |
| `X`, `x`, `[X]`, `[x]` | Completed task | update canonical task status |
| `>` or `[>]` | Migrated task | future or collection; no duplicate |
| `<` or `[<]` | Scheduled task | future/calendar collection |
| `-` | Note | concept/topic page |
| `O` | Event | timeline or person page |
| `*` | Priority signifier | left of bullet; increase visibility |
| `!` | Idea signifier | left of note; idea collection |
| `=` | Explore signifier | mark research gap |
| `^` | Appointment signifier | left of event; future/calendar |

Custom signifiers must be recorded under `Custom signifiers` below before use.

### Indentation and completion

Indented bullets are subtasks. A master task is complete only when all descendant tasks are complete or irrelevant. The migration CLI rejects completing a master with unfinished descendants or making a subtask unfinished beneath a completed or irrelevant ancestor. Completing a final subtask does not automatically complete its master; the owner explicitly completes each task.

### Signifier routing

- Tasks route to the named active project when identifiable; otherwise `wiki/collections/tasks.md`.
- Events route to `wiki/collections/timeline.md` and optionally named person pages.
- Notes route to concept/topic pages. Ideas route to `wiki/collections/ideas.md`.
- Explore signifiers route to `wiki/collections/research.md`.
- Appointment signifiers route to `wiki/collections/future.md`.

### Migration

1. Review unresolved tasks.
2. Mark completed tasks `X`.
3. Mark irrelevant tasks with `~~strikethrough~~`.
4. Change relevant tasks to `>` and point to a collection or future log.
5. Change date-bound tasks to `< YYYY-MM-DD`; scheduled migrations require a valid calendar date.
6. Preserve one canonical task record; historical dates may cite it.

The migration CLI matches complete task descriptions case-insensitively with normalized whitespace, excluding scheduling dates, migration destinations, and collection provenance, regardless of status. Leading `YYYY-MM-DD ` tokens and a trailing ` -> destination` are reserved task metadata, not literal description text; migrations replace or remove them as appropriate and preserve collection provenance. Migrated status requires a nonempty `--target`. The CLI rejects missing or ambiguous matches without changing tasks or recording a successful migration; it does not create or delete destination records.

Migration never rewrites headings, ordinary prose, fenced or indented code blocks, or HTML blocks. Text and Markdown ingest preserves UTF-8 Markdown text rather than reflowing or trimming it; line-ending normalization to LF is allowed.

### Collections

Recognize reading lists, habits, shopping lists, goals, meeting notes, project spreads, and other recurring headings. Merge entries by stable identity into `wiki/collections/<slug>.md`. Preserve source links and do not treat collection entries as daily reflections.

For automatic extraction, identity is the entry or complete block after rebasing Markdown destinations to the collection location and removing leading and trailing whitespace, including its Markdown bullet or task marker. Matching entries retain links for each source. Multiline links are rebased as a unit; code and HTML blocks are not rewritten. Structured blocks retain their structure with provenance outside the block. New entries are appended in source order; unrelated existing content is preserved. Collection index links use encoded local targets and are added to an actual Collections heading, not examples in code.

### OCR cleanup

For photos or scans:

1. Preserve objective intent.
2. Silently correct obvious OCR typos and joined/split words.
3. Expand only declared aliases.
4. Mark uncertain text `[unclear: ...]`.
5. Keep binaries only in `raw/assets/<year>/<slug>/`.
6. Update `index.md` only after cleanup.

## Custom signifiers

```yaml
signifiers:
  "*": priority
  "!": idea
  "=": explore
  "^": appointment
aliases: {}
```

## Operations

### Ingest

`python tools/second_brain.py ingest <file-or-url>`

The CLI reads text directly or uses MarkItDown when available. Add `--journal` only for a rapid-log journal. URLs are fetched and converted. Non-image binaries are converted to Markdown and the original is not stored under `raw/`. Images are stored under `raw/assets/`.

Image file extensions are derived from supported image content, not a URL suffix. Unsupported or unrecognized image formats are rejected.

Local text input and URL text fallback after unsuccessful conversion accept only extensionless files and `.txt`, `.md`, `.markdown`, `.csv`, `.tsv`, `.json`, `.xml`, `.yaml`, `.yml`, `.html`, or `.htm` files. They require valid UTF-8 without binary control characters or recognized binary signatures, regardless of URL Content-Type. These checks are heuristic: arbitrary binary data that looks like printable UTF-8 cannot always be distinguished from text. Unsupported URL extensions require successful conversion; supported images use the image handling above.

Local UTF-8 text and Markdown, and valid non-HTML URL text, are captured without trimming, reformatting, or rebasing links; only line endings are normalized. Relative source links may therefore resolve differently or break in the raw capture; consult its original `source` for the original context. Generated or converted content may be normalized. URL conversion uses operation-private temporary files, never fixed inbox filenames. Ingest, collection extraction, and task migration share the `content` lock across their complete operations. Ingest also holds the index and log locks and rolls back its newly created capture, newly created image asset, and index/log writes on failure; a rollback error is reported explicitly. Concurrent CLI ingests reserve distinct raw filenames. Locks are stored in the Git-ignored `.second-brain-locks/` directory; other tools editing those files must use the same locks to coordinate, and lock files must not be removed while operations are running.

### Query

Read `index.md`, search relevant wiki pages, and synthesize answers with source links. Optional output goes to `wiki/output/`. The CLI appends one query operation to `log.md` whether or not output is saved.

### Weekend reminders

The `weekend-reminders` skill provides a Friday preview and a first-workday check-in, using configured workdays and known holidays without assuming calendar completeness. Scheduling and delivery are host responsibilities; prompts do not guarantee notifications or automatic snoozes. Preserve raw sources and canonical task statuses when preparing or deferring a reminder.

### Daily and periodic routines

The routine skills follow `.github/routine-guidance.md` for concise, optional check-ins. Scheduling stays with the host. Reviews and reminders do not silently change journal entries, task statuses, or events; explicitly requested captures and migrations follow the existing rapid-log rules.

### Lint

Lint broken GFM links, orphan wiki pages, missing raw sources, source hash drift, and stale front matter. URL drift is opt-in with `--check-urls`.

Link lint checks inline links, images, and defined reference links; it reports undefined full and collapsed references and possible undefined shortcut references. Undefined shortcuts are indistinguishable from ordinary bracketed prose in Markdown, so those reports may require human review. Escape literal brackets to avoid such warnings.

## Implementation decisions

- Python, PyYAML, markdown-it-py, and filelock are required for tooling, YAML validation, Markdown link parsing, and concurrent writes.
- MarkItDown is optional.
- Entry point: `python tools/second_brain.py`.
- Compatibility entry point: `python second_brain.py`.
- Log format: `## [2026-11-20T14:00:00Z] operation | title`.
