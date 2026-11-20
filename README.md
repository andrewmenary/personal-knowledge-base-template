# Second Brain

A private, markdown-first knowledge system for raw sources and generated wiki knowledge.

## Create your Second Brain from this template

> **Template setup only:** After initialization, remove this entire section from your new repository's README. Keep the sections below as documentation for your instance.

1. On this repository's GitHub page, select **Use this template**, then **Create a new repository**.
2. Choose an owner and repository name. Select **Private** if your knowledge base will contain personal information, then create the repository.
3. Clone your new repository and open its directory:

   ```sh
   git clone https://github.com/<owner>/<repository>.git
   cd <repository>
   ```

4. Install the dependencies described in **Manual CLI** below. Review and customize `SCHEMA.md` and `index.md` for your own workflow.
5. Remove this **Create your Second Brain from this template** section from the new instance's README, then commit your changes.

## Layout

- `inbox/` - temporary captures
- `raw/` - immutable Markdown sources
- `raw/assets/` - image assets
- `wiki/` - generated and maintained knowledge
- `wiki/collections/` - reading lists, habits, projects, and other collections
- `wiki/output/` - reports and exports
- `index.md` - content-oriented wiki catalog
- `log.md` - chronological operation log
- `SCHEMA.md` - maintained agent/user operating contract

## Using Copilot

Open this repository in a Copilot agent session and ask naturally. Copilot can select the repository's skills when relevant:

- "Ingest the article at this URL and add its key ideas to my wiki."
- "What have I learned about caching? Cite my sources."
- "Check my knowledge base for broken links and stale sources."
- "Log a task to review the design" or "Process today's journal."

You can also request `/ingest`, `/query`, `/lint`, or `/log` by name in your prompt. Skills guide Copilot through the work; they do not hide tool activity or automatically perform OCR. If the skills are not available in a current Copilot CLI session, restart it or use `/skills reload`. For a new journal capture, the `/log` skill keeps its original in the Git-ignored `inbox/`; removing that original can produce a source-drift warning.

## Manual CLI

Install the required YAML parser and optional MarkItDown conversion support:

```sh
pip install -r requirements.txt
```

For direct use without Copilot:

```sh
python tools/second_brain.py ingest <file-or-url>
python tools/second_brain.py query "term"
python tools/second_brain.py lint
```
