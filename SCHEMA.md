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

Indented bullets are subtasks. A master task is complete only when all subtasks are complete or irrelevant.

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

### Collections

Recognize reading lists, habits, shopping lists, goals, meeting notes, project spreads, and other recurring headings. Merge entries by stable identity into `wiki/collections/<slug>.md`. Preserve source links and do not treat collection entries as daily reflections.

For automatic extraction, identity is the exact entry text with leading and trailing whitespace removed, including its Markdown bullet or task marker. Matching entries retain one line with a link for each source.

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

The CLI reads text directly or uses MarkItDown when available. URLs are fetched and converted. Non-image binaries are converted to Markdown and the original is not stored under `raw/`. Images are stored under `raw/assets/`.

Image file extensions are derived from supported image content, not a URL suffix. Unsupported or unrecognized image formats are rejected.

Without a successful conversion, local text fallback accepts extensionless files and `.txt`, `.md`, `.markdown`, `.csv`, `.tsv`, `.json`, `.xml`, `.yaml`, `.yml`, `.html`, or `.htm` files, provided their UTF-8 content has no binary control characters.

### Query

Read `index.md`, search relevant wiki pages, and synthesize answers with source links. Optional output goes to `wiki/output/`. The CLI appends one query operation to `log.md` whether or not output is saved.

### Lint

Lint broken GFM links, orphan wiki pages, missing raw sources, source hash drift, and stale front matter. URL drift is opt-in with `--check-urls`.

## Implementation decisions

- Python and PyYAML are required for tooling and YAML validation.
- MarkItDown is optional.
- Entry point: `python tools/second_brain.py`.
- Compatibility entry point: `python second_brain.py`.
- Log format: `## [2026-11-20T14:00:00Z] operation | title`.
