---
name: query
description: Answer a question from the Second Brain using indexed wiki and raw sources. Use when asked to search or query the knowledge base.
---

# Query the knowledge base

The user can ask a natural question such as "What have I learned about caching?" Read `SCHEMA.md` and `index.md` first.

1. Select relevant search terms and run `python tools/second_brain.py query "<terms>" --json` from the repository root, passing terms safely as arguments. The command performs keyword search, not semantic answering; use other targeted searches if necessary. Check the exit status and surface errors.
2. Read relevant wiki pages and their raw sources. Synthesize an answer grounded in what they say, with Markdown links to the supporting files. Identify conflicting or missing evidence; do not invent claims when search returns no useful results.
3. Save an answer in `wiki/output/` only if the user requests it. `python tools/second_brain.py query "<terms>" --save --json` saves search results rather than a synthesized answer; if the user wants a synthesized answer, write one with valid relative source links instead.
4. Append one timestamped query entry to `log.md` for the operation, unless the `--save` command already logged it. Preserve all prior log entries.
