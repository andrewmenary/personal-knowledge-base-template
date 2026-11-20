#!/usr/bin/env python3
"""Second Brain command-line maintenance tools."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw"
ASSETS = RAW / "assets"
WIKI = ROOT / "wiki"
INBOX = ROOT / "inbox"
INDEX = ROOT / "index.md"
LOG = ROOT / "log.md"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
COLLECTION_HEADINGS = re.compile(
    r"^#{1,3}\s+(reading list|habit tracker|shopping list|meeting notes|"
    r"project spread|personal goals|goals|collection|book list|watch list)\b",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slugify(value: str) -> str:
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[-\s]+", "-", value) or "untitled"


def gfm(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip() + "\n"


def yaml_quote(value: object) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def front_matter(title: str, source: str, source_type: str, source_sha256: str) -> str:
    fields = [
        ("title", title),
        ("source", source),
        ("source_type", source_type),
        ("ingested_at", utc_now()),
        ("source_sha256", source_sha256),
        ("tags", "[]"),
        ("status", "active"),
        ("immutable", "true"),
    ]
    lines = ["---"]
    for key, value in fields:
        if key in {"tags", "immutable"}:
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {yaml_quote(value)}")
    lines.append("---")
    return "\n".join(lines)


def parse_front_matter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    result = {}
    for line in text[4:end].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def convert_markitdown(path: Path) -> str | None:
    try:
        from markitdown import MarkItDown
        result = MarkItDown().convert(str(path))
        return getattr(result, "text_content", None)
    except Exception:
        return None


def fetch_url(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "second-brain/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read(), response.headers.get_content_type() or "application/octet-stream"


def append_log(operation: str, title: str, detail: str = ""):
    if not LOG.exists():
        LOG.write_text("# Operations Log\n", encoding="utf-8")
    suffix = f" - {detail}" if detail else ""
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## [{utc_now()}] {operation} | {title}{suffix}\n")


def ingest(source: str) -> dict[str, str]:
    parsed = urlparse(source)
    is_url = parsed.scheme in {"http", "https"}
    year = datetime.now(timezone.utc).strftime("%Y")

    if is_url:
        data, content_type = fetch_url(source)
        name = Path(parsed.path).name or "web-source"
        suffix = Path(name).suffix.lower()
        title = re.sub(r"[-_]+", " ", Path(name).stem).strip().title() or "Web Source"
        sha = hashlib.sha256(data).hexdigest()
        slug = slugify(title)
        if suffix in IMAGE_SUFFIXES or "image/" in content_type:
            suffix = suffix or ".img"
            destination = ASSETS / year / slug
            destination.mkdir(parents=True, exist_ok=True)
            asset = destination / f"{slug}{suffix}"
            asset.write_bytes(data)
            body = f"# {title}\n\n![{title}](../assets/{year}/{slug}/{asset.name})\n"
        else:
            INBOX.mkdir(parents=True, exist_ok=True)
            temp = INBOX / f"_download{suffix or '.html'}"
            temp.write_bytes(data)
            converted = convert_markitdown(temp)
            temp.unlink(missing_ok=True)
            if converted is None:
                text = data.decode("utf-8", errors="replace")
                if "html" in content_type or suffix in {".htm", ".html"}:
                    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
                    text = re.sub(r"\s+", " ", text).strip()
                converted = text
            body = converted if converted.lstrip().startswith("#") else f"# {title}\n\n{converted}"
    else:
        path = Path(source).expanduser()
        if not path.is_absolute():
            path = (ROOT / path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"Source not found: {path}")
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        title = re.sub(r"[-_]+", " ", path.stem).strip().title() or "Untitled"
        slug = slugify(title)
        if path.suffix.lower() in IMAGE_SUFFIXES:
            destination = ASSETS / year / slug
            destination.mkdir(parents=True, exist_ok=True)
            asset = destination / path.name
            asset.write_bytes(data)
            body = f"# {title}\n\n![{title}](../assets/{year}/{slug}/{path.name})\n"
        else:
            converted = convert_markitdown(path)
            if converted is None:
                try:
                    converted = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    raise ValueError(f"Binary source requires MarkItDown: {path}")
            body = converted if converted.lstrip().startswith("#") else f"# {title}\n\n{converted}"

    RAW.mkdir(parents=True, exist_ok=True)
    destination_dir = RAW / year
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{slug}.md"
    sequence = 2
    while destination.exists():
        destination = destination_dir / f"{slug}-{sequence}.md"
        sequence += 1

    source_type = "url" if is_url else "file"
    destination.write_text(
        front_matter(title, source, source_type, sha) + "\n\n" + gfm(body),
        encoding="utf-8",
    )
    relative = destination.relative_to(ROOT).as_posix()
    append_log("ingest", title, f"[{relative}]")
    update_index(title, relative)
    return {"title": title, "raw": relative}


def update_index(title: str, relative_source: str):
    text = INDEX.read_text(encoding="utf-8") if INDEX.exists() else "# Knowledge Index\n"
    link = f"- [{title}]({relative_source})"
    section = "## Raw sources"
    if link not in text:
        if section in text:
            text = text.replace(section, section + "\n\n" + link)
        else:
            text = text.rstrip() + "\n\n" + section + "\n\n" + link
        INDEX.write_text(gfm(text), encoding="utf-8")


def parse_bullet(line: str) -> dict[str, object]:
    stripped = line.strip()
    signifiers = []
    while stripped and stripped[0] in "*=!^":
        signifiers.append(stripped[0])
        stripped = stripped[1:].strip()
    match = re.match(r"(?:\[([ Xx><])\]|([+\-XO>x<]))(?:\s+(.*))?$", stripped)
    if not match:
        return {"bullet": "", "text": stripped, "signifiers": signifiers}
    bracket, bullet, text = match.groups()
    return {"bullet": bracket if bracket is not None else bullet, "text": text or "", "signifiers": signifiers}


def route_bullet(line: str) -> str:
    parsed = parse_bullet(line)
    bullet = str(parsed["bullet"]).strip()
    signifiers = parsed["signifiers"]
    if "^" in signifiers or bullet == "<":
        return "wiki/collections/future.md"
    if "!" in signifiers:
        return "wiki/collections/ideas.md"
    if "=" in signifiers:
        return "wiki/collections/research.md"
    if bullet == "-":
        return "wiki/concepts.md"
    if bullet == "O":
        return "wiki/collections/timeline.md"
    if bullet in {"+", ">", "X", "x", "[ ]", "[>] ", "[<]", "[X]", "[x]"}:
        return "wiki/collections/tasks.md"
    return "wiki/collections/tasks.md"


def migrate_task(task: str, status: str, target: str | None = None, date: str | None = None) -> list[str]:
    symbols = {"open": "+", "completed": "X", "migrated": ">", "scheduled": "<"}
    symbol = symbols[status]
    needle = task.strip().lower()
    changed = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts or path.resolve() == LOG.resolve():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        output = []
        for line in lines:
            parsed = parse_bullet(line)
            if needle and needle in str(parsed["text"]).lower():
                prefix = re.match(r"^(\s*[*=!^]*)(?:\[.[^\]]*\]|[+\-XO>x<])", line)
                prefix_text = prefix.group(1) if prefix else ""
                replacement = f"{prefix_text}{symbol} {parsed['text']}"
                if status == "scheduled" and date:
                    replacement += f" ({date})"
                elif status == "migrated" and target:
                    replacement += f" -> {target}"
                output.append(replacement)
                changed.append(path.relative_to(ROOT).as_posix())
            else:
                output.append(line)
        new_text = "\n".join(output) + ("\n" if text.endswith("\n") else "")
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
    append_log("migration", task, f"status={status}; target={target or ''}")
    return sorted(set(changed))


def clean_ocr(text: str, aliases: dict[str, str] | None = None) -> str:
    text = html.unescape(text).replace("\u2010", "-").replace("\u2011", "-")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"-\s*\n\s*", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    for shorthand, expansion in sorted((aliases or {}).items(), key=lambda item: -len(item[0])):
        text = re.sub(rf"\b{re.escape(shorthand)}\b", expansion, text, flags=re.I)
    return gfm(text)


def extract_collections(source: Path) -> list[dict[str, str]]:
    text = source.read_text(encoding="utf-8")
    collections: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        heading = COLLECTION_HEADINGS.match(line)
        if heading:
            current = slugify(heading.group(1))
            collections.setdefault(current, [])
        elif current:
            if re.match(r"^#{1,6}\s+", line):
                current = None
            elif line.strip():
                collections[current].append(line)

    results = []
    for name, entries in collections.items():
        destination = WIKI / "collections" / f"{name}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        existing = destination.read_text(encoding="utf-8") if destination.exists() else f"# {name.replace('-', ' ').title()}\n"
        block = "\n".join(dict.fromkeys(entries)).strip()
        if block and block not in existing:
            destination.write_text(gfm(existing.rstrip() + "\n\n" + block), encoding="utf-8")
        results.append({"collection": name, "path": destination.relative_to(ROOT).as_posix()})
    if collections:
        append_log("collection", source.name, f"{len(collections)} collection(s)")
    return results


def query_terms(terms: str) -> list[dict[str, str]]:
    needles = [item.lower() for item in terms.split() if item]
    matches = []
    for base in (INDEX, WIKI, RAW):
        paths = [base] if base.is_file() else sorted(base.rglob("*.md"))
        for path in paths:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if any(needle not in text.lower() for needle in needles):
                continue
            for line in text.splitlines():
                if any(needle in line.lower() for needle in needles) and not line.startswith("---"):
                    matches.append({"path": path.relative_to(ROOT).as_posix(), "line": line.strip()[:300]})
                    if len(matches) >= 100:
                        return matches
    return matches


def lint_links() -> list[dict[str, str]]:
    issues = []
    pattern = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            for target in pattern.findall(line):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target = target.split("#", 1)[0]
                if target and not (path.parent / target).resolve().exists():
                    issues.append({"path": path.relative_to(ROOT).as_posix(), "line": str(line_number), "target": target})
    return issues


def lint_source_drift(check_urls: bool = False) -> list[dict[str, str]]:
    issues = []
    for path in sorted(RAW.rglob("*.md")):
        meta = parse_front_matter(path.read_text(encoding="utf-8", errors="replace"))
        source, expected = meta.get("source"), meta.get("source_sha256")
        if not source or not expected:
            continue
        parsed = urlparse(source)
        if parsed.scheme in {"http", "https"}:
            if check_urls:
                try:
                    data, _ = fetch_url(source)
                    if hashlib.sha256(data).hexdigest() != expected:
                        issues.append({"path": path.relative_to(ROOT).as_posix(), "source": source, "issue": "changed"})
                except Exception as exc:
                    issues.append({"path": path.relative_to(ROOT).as_posix(), "source": source, "issue": str(exc)})
        else:
            source_path = Path(source).expanduser()
            if not source_path.is_absolute():
                source_path = (ROOT / source).resolve()
            if not source_path.exists():
                issues.append({"path": path.relative_to(ROOT).as_posix(), "source": source, "issue": "missing"})
            elif hashlib.sha256(source_path.read_bytes()).hexdigest() != expected:
                issues.append({"path": path.relative_to(ROOT).as_posix(), "source": source, "issue": "changed"})
    return issues


def lint_orphans() -> list[dict[str, str]]:
    pages = {path.resolve() for path in WIKI.rglob("*.md")}
    linked = set()
    pattern = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)")
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        for target in pattern.findall(path.read_text(encoding="utf-8", errors="replace")):
            if target.startswith(("http://", "https://", "#")):
                continue
            linked.add((path.parent / target.split("#", 1)[0]).resolve())
    return [{"path": path.relative_to(ROOT).as_posix()} for path in sorted(pages) if path not in linked and path.name != "README.md"]


def save_query_output(terms: str, matches: list[dict[str, str]]) -> Path:
    output_dir = WIKI / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{slugify(terms)}-{utc_now()[:10]}.md"
    lines = [f"# Query: {terms}", "", "## Results", ""]
    lines.extend(f"- [`{item['path']}`]({item['path']}) - {item['line']}" for item in matches)
    if not matches:
        lines.append("_No matching results._")
    destination.write_text(gfm("\n".join(lines)), encoding="utf-8")
    append_log("query", terms, f"[{destination.relative_to(ROOT).as_posix()}]")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Second Brain tools")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest")
    ingest.add_argument("source")
    ingest.add_argument("--json", action="store_true")

    query = subcommands.add_parser("query")
    query.add_argument("terms", nargs="+")
    query.add_argument("--save", action="store_true")
    query.add_argument("--json", action="store_true")

    lint = subcommands.add_parser("lint")
    lint.add_argument("--check-urls", action="store_true")
    lint.add_argument("--json", action="store_true")

    migrate = subcommands.add_parser("migrate")
    migrate.add_argument("task")
    migrate.add_argument("status", choices=["open", "completed", "migrated", "scheduled"])
    migrate.add_argument("--target")
    migrate.add_argument("--date")
    migrate.add_argument("--json", action="store_true")

    collect = subcommands.add_parser("extract-collections")
    collect.add_argument("source", nargs="?")
    collect.add_argument("--json", action="store_true")

    ocr = subcommands.add_parser("ocr-clean")
    ocr.add_argument("--aliases", nargs="*", default=[], metavar="KEY=VALUE")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "ingest":
            result = ingest(args.source)
            print(json.dumps(result, indent=2) if args.json else f"Ingested: {result['raw']}")
            return 0

        if args.command == "query":
            terms = " ".join(args.terms)
            matches = query_terms(terms)
            if args.save:
                output = save_query_output(terms, matches)
                print(json.dumps({"output": output.relative_to(ROOT).as_posix(), "matches": matches}, indent=2) if args.json else f"Saved: {output.relative_to(ROOT).as_posix()}")
            elif args.json:
                print(json.dumps(matches, indent=2))
            else:
                if not matches:
                    print("No matches.")
                for match in matches:
                    print(f"{match['path']}: {match['line']}")
            return 0

        if args.command == "lint":
            issues = {
                "broken_links": lint_links(),
                "source_drift": lint_source_drift(args.check_urls),
                "orphan_pages": lint_orphans(),
            }
            if args.json:
                print(json.dumps(issues, indent=2))
            else:
                count = sum(len(items) for items in issues.values())
                print("Lint passed." if count == 0 else f"Lint found {count} issue(s).")
                for category, items in issues.items():
                    for item in items:
                        print(f"{category}: {item}")
            append_log("lint", "Knowledge base", f"{sum(len(items) for items in issues.values())} issue(s)")
            return 1 if sum(len(items) for items in issues.values()) else 0

        if args.command == "migrate":
            changed = migrate_task(args.task, args.status, args.target, args.date)
            result = {"task": args.task, "status": args.status, "changed": changed}
            print(json.dumps(result, indent=2) if args.json else f"Updated {len(changed)} file(s).")
            return 0

        if args.command == "extract-collections":
            candidates = [Path(args.source)] if args.source else [
                *RAW.rglob("*.md"),
                *INBOX.glob("*"),
                *WIKI.rglob("*.md"),
            ]
            results = []
            for candidate in candidates:
                if candidate.is_file() and candidate.suffix.lower() in {".md", ".txt"}:
                    results.extend(extract_collections(candidate))
            print(json.dumps(results, indent=2) if args.json else f"Extracted {len(results)} collection(s).")
            return 0

        if args.command == "ocr-clean":
            aliases = {}
            for item in args.aliases:
                if "=" in item:
                    key, value = item.split("=", 1)
                    aliases[key] = value
            sys.stdout.write(clean_ocr(sys.stdin.read(), aliases))
            return 0
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
