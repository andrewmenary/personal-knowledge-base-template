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

4. Install the dependencies described in **Start** below. Review and customize `SCHEMA.md` and `index.md` for your own workflow.
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

## Start

```sh
python tools/second_brain.py ingest <file-or-url>
python tools/second_brain.py query "term"
python tools/second_brain.py lint
```

Install the required YAML parser and optional MarkItDown conversion support:

```sh
pip install -r requirements.txt
```
