#!/usr/bin/env python3
"""Second Brain command-line maintenance tools."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import os
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import date as calendar_date, datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlparse, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import yaml
from filelock import FileLock
from markdown_it import MarkdownIt
from markdown_it.rules_inline import image as image_rule, link as link_rule


ROOT = Path(os.environ.get("SECOND_BRAIN_ROOT", Path(__file__).resolve().parents[1])).resolve()
RAW = ROOT / "raw"
ASSETS = RAW / "assets"
WIKI = ROOT / "wiki"
INBOX = ROOT / "inbox"
INDEX = ROOT / "index.md"
LOG = ROOT / "log.md"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}
TEXT_TYPES = {"text/", "application/json", "application/xml", "application/yaml", "application/javascript"}
TEXT_SUFFIXES = {"", ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".html", ".htm"}
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


def front_matter(title: str, source: str, source_type: str, source_sha256: str, journal: bool = False) -> str:
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
    if journal:
        fields.append(("kind", "journal"))
    lines = ["---"]
    for key, value in fields:
        if key in {"tags", "immutable"}:
            lines.append(f"{key}: {value}")
        else:
            lines.append(f"{key}: {yaml_quote(value)}")
    lines.append("---")
    return "\n".join(lines)


def parse_front_matter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise ValueError("missing YAML front matter")
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise ValueError("unterminated YAML front matter") from None
    try:
        result = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError as exc:
        raise ValueError(f"malformed YAML front matter: {exc}") from exc
    if not isinstance(result, dict):
        raise ValueError("YAML front matter must be a mapping")
    return result


def convert_markitdown(path: Path) -> str | None:
    try:
        from markitdown import MarkItDown
        result = MarkItDown().convert(str(path))
        return getattr(result, "text_content", None)
    except Exception:
        return None


def convert_markitdown_available() -> bool:
    try:
        __import__("markitdown")
        return True
    except Exception:
        return False


def fetch_url(url: str) -> tuple[bytes, str]:
    request = Request(url, headers={"User-Agent": "second-brain/1.0"})
    with urlopen(request, timeout=30) as response:
        return response.read(), response.headers.get_content_type() or "application/octet-stream"


def image_extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if data.startswith(b"BM"):
        return ".bmp"
    if data.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    try:
        if ET.fromstring(data).tag in {"svg", "{http://www.w3.org/2000/svg}svg"}:
            return ".svg"
    except ET.ParseError:
        pass
    raise ValueError("Unrecognized or unsupported image format")


def append_log(operation: str, title: str, detail: str = ""):
    with repository_lock("log"):
        if not LOG.exists():
            LOG.write_text("# Operations Log\n", encoding="utf-8")
        suffix = f" - {detail}" if detail else ""
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## [{utc_now()}] {operation} | {title}{suffix}\n")


def repository_lock(name: str) -> FileLock:
    directory = ROOT / ".second-brain-locks"
    directory.mkdir(parents=True, exist_ok=True)
    return FileLock(str(directory / f"{name}.lock"))


def ingest(source: str, journal: bool = False) -> dict[str, str]:
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
            suffix = image_extension(data)
            destination = ASSETS / year / slug
            destination.mkdir(parents=True, exist_ok=True)
            asset = destination / f"{slug}-{sha[:12]}{suffix}"
            asset.write_bytes(data)
            body = f"# {title}\n\n![{title}](../assets/{year}/{slug}/{asset.name})\n"
        else:
            if content_type and not any(content_type.startswith(prefix) for prefix in TEXT_TYPES):
                if not convert_markitdown_available():
                    raise ValueError(f"Binary URL content requires MarkItDown: {source}")
            with tempfile.TemporaryDirectory(prefix="second-brain-") as directory:
                temp = Path(directory) / f"{uuid.uuid4().hex}{suffix or '.html'}"
                temp.write_bytes(data)
                converted = convert_markitdown(temp)
            if converted is None:
                if content_type and not any(content_type.startswith(prefix) for prefix in TEXT_TYPES):
                    raise ValueError(f"Binary URL content could not be converted: {source}")
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
            suffix = image_extension(data)
            destination = ASSETS / year / slug
            destination.mkdir(parents=True, exist_ok=True)
            asset = destination / f"{slug}-{sha[:12]}{suffix}"
            asset.write_bytes(data)
            body = f"# {title}\n\n![{title}](../assets/{year}/{slug}/{asset.name})\n"
        else:
            converted = convert_markitdown(path)
            if converted is None:
                if path.suffix.lower() not in TEXT_SUFFIXES or data.startswith((b"%PDF-", b"PK\x03\x04")):
                    raise ValueError(f"Binary source requires MarkItDown: {path}")
                try:
                    converted = data.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ValueError(f"Binary source requires MarkItDown: {path}") from exc
                if any(ord(char) < 32 and char not in "\t\r\n" for char in converted) or "\x7f" in converted:
                    raise ValueError(f"Binary source requires MarkItDown: {path}")
            body = converted if converted.lstrip().startswith("#") else f"# {title}\n\n{converted}"

    RAW.mkdir(parents=True, exist_ok=True)
    destination_dir = RAW / year
    destination_dir.mkdir(parents=True, exist_ok=True)
    source_type = "url" if is_url else "file"
    content = front_matter(title, source, source_type, sha, journal) + "\n\n" + gfm(body)
    sequence = 1
    while True:
        filename = f"{slug}.md" if sequence == 1 else f"{slug}-{sequence}.md"
        destination = destination_dir / filename
        try:
            handle = destination.open("x", encoding="utf-8")
        except FileExistsError:
            sequence += 1
            continue
        try:
            with handle:
                handle.write(content)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        break
    relative = destination.relative_to(ROOT).as_posix()
    append_log("ingest", title, f"[{relative}]")
    update_index(title, relative)
    return {"title": title, "raw": relative}


def update_index(title: str, relative_source: str):
    with repository_lock("index"):
        _update_index(title, relative_source, "## Raw sources")


def _update_index(title: str, relative_source: str, section: str):
    text = INDEX.read_text(encoding="utf-8") if INDEX.exists() else "# Knowledge Index\n"
    link = f"- [{title}]({relative_source})"
    if link not in text:
        if section in text:
            text = text.replace(section, section + "\n\n" + link)
        else:
            text = text.rstrip() + "\n\n" + section + "\n\n" + link
        INDEX.write_text(gfm(text), encoding="utf-8")


def update_collection_index(name: str, destination: Path):
    relative = destination.relative_to(ROOT).as_posix()
    with repository_lock("index"):
        _update_index(name.replace("-", " ").title(), relative, "## Collections")


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


def task_parts(text: str, *, collection: bool) -> tuple[str, str]:
    """Separate reserved status metadata from a task description and provenance."""
    text = text.strip()
    sources = []
    arrow = re.search(r"\s+->\s+", text)
    if collection and arrow:
        before, metadata = text[:arrow.start()], text[arrow.start():]
        sources.extend(re.findall(r"\(\[source\]\([^)]+\)\)", metadata))
        text = before + re.sub(r"\s*\(\[source\]\([^)]+\)\)", "", metadata)
    while True:
        if collection:
            source = re.search(r"\s+(\(\[source\]\([^)]+\)\))$", text)
            if source:
                sources.insert(0, source.group(1))
                text = text[:source.start()]
                continue
        destination = re.search(r"\s+->\s+.*$", text)
        if destination:
            text = text[:destination.start()]
            continue
        break
    text = re.sub(r"^(?:\d{4}-\d{2}-\d{2}[ \t]+)+", "", text)
    return text.rstrip(), "".join(f" {source}" for source in sources)


def task_identity(text: str) -> str:
    return " ".join(text.split()).casefold()


def migrate_task(task: str, status: str, target: str | None = None, date: str | None = None) -> list[str]:
    symbols = {"open": "+", "completed": "X", "migrated": ">", "scheduled": "<"}
    symbol = symbols[status]
    if status == "scheduled":
        if not date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError("scheduled tasks require a valid date in YYYY-MM-DD format")
        try:
            calendar_date.fromisoformat(date)
        except ValueError:
            raise ValueError("scheduled tasks require a valid date in YYYY-MM-DD format") from None
    if target is not None and (
        not target.strip() or "\n" in target or "\r" in target
        or re.search(r"\s+->\s+|\(\[source\]\([^)]+\)\)", target)
    ):
        raise ValueError("migration target must be a nonempty single destination")
    needle = task_identity(task_parts(task, collection=True)[0])
    if not needle:
        raise ValueError("task must not be empty")
    candidates = []
    candidates.extend(RAW.rglob("*.md"))
    candidates.extend((WIKI / "collections").rglob("*.md"))
    matches = []
    for path in sorted(set(candidates)):
        if path.resolve() == LOG.resolve():
            continue
        if not (path.resolve().is_relative_to(RAW.resolve()) or
                path.resolve().is_relative_to((WIKI / "collections").resolve())):
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            text = handle.read()
        body_start = 0
        if path.is_relative_to(RAW):
            try:
                metadata = parse_front_matter(text)
            except ValueError:
                continue
            if metadata.get("kind") != "journal":
                continue
            body_start = text.splitlines().index("---", 1) + 1
        lines = text.splitlines(keepends=True)
        protected = set()
        for token in MarkdownIt("commonmark").parse(text):
            if token.type in {"fence", "html_block"} and token.map:
                protected.update(range(*token.map))
        for line_number, original_line in enumerate(lines):
            if line_number < body_start or line_number in protected:
                continue
            line = original_line.rstrip("\r\n")
            ending = original_line[len(line):]
            parsed = parse_bullet(line)
            description, sources = task_parts(str(parsed["text"]), collection=not path.is_relative_to(RAW))
            if parsed["bullet"] in {" ", "+", ">", "<", "X", "x"} and needle == task_identity(description):
                match = re.match(r"^([ \t]*(?:[*=!^][ \t]*)*)(\[[ Xx><]\]|[+Xx><])", line)
                if match is None:
                    continue
                marker = f"[{symbol if symbol != '+' else ' '}]" if match.group(2).startswith("[") else symbol
                whitespace = re.match(r"[ \t]*", line[match.end():]).group()
                replacement = match.group(1) + marker + (whitespace or " ")
                if status == "scheduled":
                    replacement += f"{date} "
                replacement += description
                if status == "migrated" and target:
                    replacement += f" -> {target.strip()}"
                replacement += sources
                replacement += re.search(r"[ \t]*$", line).group()
                matches.append((path, lines, line_number, replacement + ending))
    if len(matches) > 1:
        locations = ", ".join(f"{path.relative_to(ROOT).as_posix()}:{number + 1}" for path, _, number, _ in matches)
        raise ValueError(f"ambiguous task; multiple exact matches: {locations}")
    changed = []
    if matches:
        path, lines, line_number, replacement = matches[0]
        lines[line_number] = replacement
        with path.open("w", encoding="utf-8", newline="") as handle:
            handle.write("".join(lines))
        changed.append(path.relative_to(ROOT).as_posix())
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
        text = re.sub(rf"\b{re.escape(shorthand)}\b", lambda _match: expansion, text, flags=re.I)
    return gfm(text)


def rebase_link(target: str, source: Path, destination: Path) -> str:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("/"):
        return target
    target_path = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source.resolve()
    relative = Path(os.path.relpath(target_path, destination.parent.resolve())).as_posix()
    return urlunsplit(("", "", quote(relative, safe="/-._~"), parsed.query, parsed.fragment))


def rebase_markdown(text: str, source: Path, destination: Path, source_text: str) -> str:
    """Rebase Markdown links using the source document's reference definitions."""
    parser = MarkdownIt("commonmark")
    environment = {}
    parser.parse(source_text, environment)
    edits = []
    for name, rule in (("link", link_rule), ("image", image_rule)):
        def rebase_rule(state, silent, rule=rule, name=name):
            start = state.pos
            label_end = state.md.helpers.parseLinkLabel(state, start + (name == "image"), name == "link")
            token_start = len(state.tokens)
            success = rule(state, silent)
            if not success or silent or state.src != text or label_end < 0:
                return success
            token = next((token for token in state.tokens[token_start:]
                          if token.type == ("image" if name == "image" else "link_open")), None)
            if token is None:
                return success
            target = token.attrGet("src" if name == "image" else "href")
            rebased = rebase_link(target, source, destination)
            if rebased == target:
                return success
            suffix_start = label_end + 1
            if suffix_start < len(text) and text[suffix_start] == "(":
                pos = suffix_start + 1
                while pos < len(text) and text[pos] in " \t\n":
                    pos += 1
                parsed = state.md.helpers.parseLinkDestination(text, pos, len(text))
                if parsed.ok:
                    edits.append((pos, parsed.pos, rebased))
            else:
                title = token.attrGet("title")
                title_part = f' "{title.replace(chr(34), "&quot;")}"' if title else ""
                edits.append((suffix_start, state.pos, f"({rebased}{title_part})"))
            return success

        parser.inline.ruler.at(name, rebase_rule)
    parser.inline.parse(text, parser, environment, [])
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    return text


def extract_collections(source: Path) -> list[dict[str, str]]:
    text = source.read_text(encoding="utf-8")
    resolved_source = source.resolve()
    if not resolved_source.is_relative_to(ROOT.resolve()):
        raise ValueError(f"Collection source must be inside the knowledge base: {source}")
    parser = MarkdownIt("commonmark", {"inline_definitions": True}).enable("table")
    tokens = parser.parse(text)
    source_lines = text.splitlines()
    protected = set()
    for token in tokens:
        if token.type in {"fence", "code_block", "html_block"} and token.map:
            protected.update(range(*token.map))
    collections: dict[str, list[str]] = {}
    current = None
    for token in tokens:
        if token.type == "heading_open" and token.level == 0:
            heading = COLLECTION_HEADINGS.match(source_lines[token.map[0]])
            current = slugify(heading.group(1)) if heading else None
            if current:
                collections.setdefault(current, [])
            continue
        if not current or not token.map:
            continue
        is_item = token.type == "list_item_open" and token.level == 1
        is_block = token.level == 0 and token.type in {
            "paragraph_open", "fence", "code_block", "blockquote_open", "table_open", "html_block"
        }
        if is_item or is_block:
            start, end = token.map
            collections[current].append((start, end))

    results = []
    for name, entries in collections.items():
        destination = WIKI / "collections" / f"{name}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        existing = destination.read_text(encoding="utf-8") if destination.exists() else f"# {name.replace('-', ' ').title()}\n"
        source_relative = resolved_source.relative_to(ROOT.resolve()).as_posix()
        source_annotation = f"([source](../../{quote(source_relative, safe='/')}))"
        block_pattern = re.compile(
            r"(?ms)^<!-- collection-entry:([0-9a-f]{64}) -->\n(.*?)\n"
            r"((?:\(\[source\]\([^)]+\)\)(?: |\n|$))+)\n<!-- /collection-entry -->"
        )
        blocks = {}
        def remember_block(match):
            blocks[match.group(1)] = [match.group(2).rstrip("\n"), match.group(3).strip()]
            return ""
        existing_without_blocks = block_pattern.sub(remember_block, existing)
        lines = []
        provenance = re.compile(r"(?:\s+\(\[source\]\([^)]+\)\))+$")
        annotation = re.compile(r"\(\[source\]\([^)]+\)\)")
        identities = {}
        for line in existing_without_blocks.splitlines():
            identity = provenance.sub("", line).strip()
            if identity and not identity.startswith("#"):
                if identity in identities:
                    index = identities[identity]
                    for link in annotation.findall(line):
                        if link not in lines[index]:
                            lines[index] += f" {link}"
                    continue
                identities[identity] = len(lines)
            lines.append(line)
        for start, end in entries:
            entry = "\n".join(
                source_lines[line] if line in protected else
                rebase_markdown(source_lines[line], resolved_source, destination, text)
                for line in range(start, end)
            ).strip("\n")
            identity = entry.strip()
            if not identity:
                continue
            if "\n" in identity:
                digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
                if digest not in blocks:
                    blocks[digest] = [entry, source_annotation]
                elif source_annotation not in blocks[digest][1]:
                    blocks[digest][1] += " " + source_annotation
                continue
            if identity in identities:
                index = identities[identity]
                if source_annotation not in lines[index]:
                    lines[index] += f" {source_annotation}"
            else:
                identities[identity] = len(lines)
                lines.append(f"{entry} {source_annotation}")
        updated = "\n".join(lines).strip()
        for digest, (entry, sources) in blocks.items():
            updated += f"\n\n<!-- collection-entry:{digest} -->\n{entry}\n\n{sources}\n<!-- /collection-entry -->"
        updated += "\n"
        if updated != existing:
            destination.write_text(updated, encoding="utf-8")
        update_collection_index(name, destination)
        results.append({"collection": name, "path": destination.relative_to(ROOT).as_posix()})
    if collections:
        append_log("collection", source.name, f"{len(collections)} collection(s)")
    return results


def collection_source_candidates() -> list[Path]:
    candidates = [*RAW.rglob("*.md"), *INBOX.glob("*")]
    return [path for path in candidates if path.is_file() and path.suffix.lower() in {".md", ".txt"}]


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


def markdown_links(text: str):
    """Yield parsed links and suspected unresolved references with their block line."""
    parser = MarkdownIt("commonmark")
    environment = {}
    tokens = parser.parse(text, environment)
    missing = []
    for name, rule in (("link", link_rule), ("image", image_rule)):
        def find_missing(state, silent, rule=rule, name=name):
            start = state.pos
            result = rule(state, silent)
            if result or silent or state.linkLevel:
                return result
            if start >= state.posMax or state.src[start] != ("!" if name == "image" else "["):
                return result
            if name == "link" and start and state.src[start - 1] == "]":
                return result
            label_start = start + (2 if name == "image" else 1)
            label_end = state.md.helpers.parseLinkLabel(state, start + (name == "image"), name == "link")
            if label_end < 0:
                return result
            label = state.src[label_start:label_end]
            following = label_end + 1
            if following < state.posMax and state.src[following] == "(":
                return result
            end = following
            if following < state.posMax and state.src[following] == "[":
                ref_end = state.md.helpers.parseLinkLabel(state, following)
                if ref_end >= 0:
                    label = state.src[following + 1:ref_end] or label
                    end = ref_end + 1
            if (label.strip() and label not in {" ", "X", "x", ">", "<"}
                    and not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", label)):
                if not any(start < prior_end for _, prior_end in missing):
                    missing.append((label, end))
            return result

        parser.inline.ruler.at(name, find_missing)
    for token in tokens:
        if token.type != "inline" or not token.children:
            continue
        line = (token.map[0] + 1) if token.map else 1
        missing.clear()
        parser.inline.parse(token.content, parser, environment, [])
        for label, _ in missing:
            yield line, label, True
        for child in token.children:
            if child.type == "link_open":
                yield line, child.attrGet("href"), False
            elif child.type == "image":
                yield line, child.attrGet("src"), False


def local_link_target(path: Path, target: str) -> Path | None:
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    return (path.parent / unquote(parsed.path)).resolve()


def lint_links() -> list[dict[str, str]]:
    issues = []
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        for line, target, undefined in markdown_links(path.read_text(encoding="utf-8", errors="replace")):
            if undefined:
                issues.append({"path": path.relative_to(ROOT).as_posix(), "line": str(line),
                               "target": target, "issue": "undefined reference"})
            else:
                resolved = local_link_target(path, target)
                if resolved is not None and not resolved.exists():
                    issues.append({"path": path.relative_to(ROOT).as_posix(), "line": str(line), "target": target})
    return issues


def lint_source_drift(check_urls: bool = False) -> list[dict[str, str]]:
    issues = []
    for path in sorted(RAW.rglob("*.md")):
        relative = path.relative_to(ROOT).as_posix()
        try:
            meta = parse_front_matter(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            issues.append({"path": relative, "issue": str(exc)})
            continue
        for field in ("title", "source", "source_type", "status"):
            value = meta.get(field)
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                issues.append({"path": relative, "issue": f"missing or invalid {field} metadata"})
        if not isinstance(meta.get("source_type"), str) or meta["source_type"] not in {"file", "url"}:
            issues.append({"path": relative, "issue": "source_type must be file or url"})
        if not isinstance(meta.get("tags"), list) or not all(isinstance(tag, str) for tag in meta["tags"]):
            issues.append({"path": relative, "issue": "tags must be a list of strings"})
        if meta.get("immutable") is not True:
            issues.append({"path": relative, "issue": "immutable must be true"})
        timestamp = meta.get("ingested_at")
        try:
            parsed_time = timestamp if isinstance(timestamp, datetime) else datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
                raise ValueError("timestamp requires timezone")
        except (ValueError, TypeError, AttributeError):
            issues.append({"path": relative, "issue": "missing or invalid ingested_at timestamp"})
        source, expected = meta.get("source"), meta.get("source_sha256")
        if not isinstance(source, str) or not source.strip() or "\0" in source:
            continue
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
            issues.append({"path": relative, "issue": "missing or invalid source_sha256 metadata"})
            continue
        expected = expected.lower()
        try:
            parsed = urlparse(source)
        except ValueError:
            issues.append({"path": relative, "issue": "invalid source location"})
            continue
        is_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        if meta.get("source_type") == "url" and not is_url:
            issues.append({"path": relative, "issue": "URL source must be an absolute HTTP(S) URL"})
            continue
        if meta.get("source_type") == "file" and is_url:
            issues.append({"path": relative, "issue": "file source must not be an HTTP(S) URL"})
            continue
        if is_url:
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
    output_dir = (WIKI / "output").resolve()
    pages = {
        path.resolve()
        for path in WIKI.rglob("*.md")
        if output_dir not in path.resolve().parents
    }
    linked = set()
    for path in sorted(ROOT.rglob("*.md")):
        if ".git" in path.parts:
            continue
        for _, target, undefined in markdown_links(path.read_text(encoding="utf-8", errors="replace")):
            if not undefined:
                resolved = local_link_target(path, target)
                if resolved is not None:
                    linked.add(resolved)
    return [{"path": path.relative_to(ROOT).as_posix()} for path in sorted(pages) if path not in linked and path.name != "README.md"]


def save_query_output(terms: str, matches: list[dict[str, str]]) -> Path:
    output_dir = WIKI / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / f"{slugify(terms)}-{utc_now()[:10]}.md"
    lines = [f"# Query: {terms}", "", "## Results", ""]
    for item in matches:
        source = ROOT / item["path"]
        target = quote(Path(os.path.relpath(source, destination.parent)).as_posix(), safe="/-._~")
        label = "source"
        snippet = rebase_markdown(item["line"], source, destination, source.read_text(encoding="utf-8"))
        lines.append(f"- [{label}]({target}) - {snippet}")
    if not matches:
        lines.append("_No matching results._")
    destination.write_text(gfm("\n".join(lines)), encoding="utf-8")
    return destination


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Personal Second Brain tools")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest")
    ingest.add_argument("source")
    ingest.add_argument("--journal", action="store_true", help="Mark this source as a rapid-log journal")
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
            result = ingest(args.source, journal=args.journal)
            print(json.dumps(result, indent=2) if args.json else f"Ingested: {result['raw']}")
            return 0

        if args.command == "query":
            terms = " ".join(args.terms)
            matches = query_terms(terms)
            if args.save:
                output = save_query_output(terms, matches)
                append_log("query", terms, f"[{output.relative_to(ROOT).as_posix()}]")
                print(json.dumps({"output": output.relative_to(ROOT).as_posix(), "matches": matches}, indent=2) if args.json else f"Saved: {output.relative_to(ROOT).as_posix()}")
            elif args.json:
                append_log("query", terms)
                print(json.dumps(matches, indent=2))
            else:
                append_log("query", terms)
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
            candidates = [Path(args.source)] if args.source else collection_source_candidates()
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
