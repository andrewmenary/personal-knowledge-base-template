---
name: lint
description: Check the Second Brain for broken links, source drift, metadata problems, and orphan wiki pages. Use when asked to lint or health-check the knowledge base.
---

# Lint the knowledge base

The user can say "Check my knowledge base for broken links and stale sources." Read `SCHEMA.md` first.

1. From the repository root, run `python tools/second_brain.py lint --json`. Add `--check-urls` only if the user explicitly requests online URL checks; this fetches external sources. Check the exit status: 0 means no reported issues, 1 means issues were found, and other failures must be reported.
2. Explain findings with file paths and actionable next steps. The CLI checks links, source metadata and drift, and orphan pages; it does not automatically detect every contradiction, missing concept, or stale claim. For a broader health check, inspect relevant wiki pages and sources and identify uncertainties without claiming exhaustive coverage.
3. Do not silently rewrite immutable raw sources or delete anything. Propose repairs, or make appropriate wiki changes only when authorized by the user's request. The command appends its own lint entry to `log.md`; do not append a duplicate.
