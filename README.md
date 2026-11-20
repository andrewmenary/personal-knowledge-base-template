# Second Brain

A private, markdown-first knowledge system for raw sources and generated wiki knowledge.

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

Optional MarkItDown support:

```sh
pip install -r requirements.txt
```
