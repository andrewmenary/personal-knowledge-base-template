import subprocess
import tempfile
import unittest
import os
import hashlib
import sys
from pathlib import Path
from unittest.mock import patch

from tools import second_brain

from tools.second_brain import (
    ROOT,
    collection_source_candidates,
    clean_ocr,
    extract_collections,
    lint_links,
    lint_orphans,
    lint_source_drift,
    migrate_task,
    parse_bullet,
    route_bullet,
    save_query_output,
)


class SecondBrainTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.raw = self.root / "raw"
        self.wiki = self.root / "wiki"
        self.raw.mkdir()
        (self.wiki / "collections").mkdir(parents=True)
        (self.wiki / "concepts.md").write_text("# Concepts\n", encoding="utf-8")
        (self.root / "index.md").write_text("# Knowledge Index\n", encoding="utf-8")
        (self.root / "log.md").write_text("# Operations Log\n", encoding="utf-8")
        patcher = patch.multiple(
            second_brain, ROOT=self.root, RAW=self.raw, WIKI=self.wiki,
            LOG=self.root / "log.md", INDEX=self.root / "index.md",
            ASSETS=self.raw / "assets", INBOX=self.root / "inbox",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_bullet_routes(self):
        self.assertEqual(route_bullet("+ Ship release"), "wiki/collections/tasks.md")
        self.assertEqual(route_bullet("O Team event"), "wiki/collections/timeline.md")
        self.assertEqual(route_bullet("- Architecture fact"), "wiki/concepts.md")
        self.assertTrue((ROOT / "wiki" / "concepts.md").exists())
        self.assertEqual(route_bullet("^O Appointment"), "wiki/collections/future.md")
        self.assertEqual(route_bullet("! - Idea"), "wiki/collections/ideas.md")
        self.assertEqual(parse_bullet("[>] Migrated")["bullet"], ">")

    def test_ocr_cleanup(self):
        cleaned = clean_ocr("Pick up a -\nbook for mtg.", {"mtg": "meeting"})
        self.assertIn("a book", cleaned)
        self.assertIn("meeting", cleaned)

    def test_migration_updates_in_place(self):
        path = self.raw / "migration-test.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("+ Migrate this task\n", encoding="utf-8")
        try:
            changed = migrate_task("Migrate this task", "migrated", "September")
            self.assertIn("raw/migration-test.md", changed)
            self.assertIn("> Migrate this task -> September", path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

        scheduled = self.raw / "scheduled-test.md"
        scheduled.write_text("+ Schedule this task\n", encoding="utf-8")
        try:
            migrate_task("Schedule this task", "scheduled", date="2026-12-01")
            self.assertIn("< 2026-12-01 Schedule this task", scheduled.read_text(encoding="utf-8"))
        finally:
            scheduled.unlink(missing_ok=True)

    def test_migration_ignores_plain_prose(self):
        path = self.raw / "plain-test.md"
        path.write_text("# Release\n\nWe need to release soon.\n", encoding="utf-8")
        try:
            changed = migrate_task("release", "completed")
            self.assertEqual(changed, [])
            self.assertIn("We need to release soon.", path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

    def test_ingest_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            for folder in ("inbox", "raw/assets", "wiki/collections", "wiki/output"):
                (repo / folder).mkdir(parents=True, exist_ok=True)
            (repo / "index.md").write_text("# Knowledge Index\n", encoding="utf-8")
            (repo / "log.md").write_text("# Operations Log\n", encoding="utf-8")
            source = Path(directory) / "Fresh Source.md"
            source.write_text("# Fresh Source\n\n- A fact\n", encoding="utf-8")
            env = os.environ.copy()
            env["SECOND_BRAIN_ROOT"] = str(repo)
            result = subprocess.run(
                ["python", "tools/second_brain.py", "ingest", str(source), "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("raw/", result.stdout)

    def test_collection_has_source_and_index_entry(self):
        source = self.raw / "reading-test.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# Reading List\n\n- A useful book\n", encoding="utf-8")
        destination = self.wiki / "collections" / "reading-list.md"
        try:
            results = extract_collections(source)
            self.assertTrue(results)
            collection_text = destination.read_text(encoding="utf-8")
            self.assertIn("[source](../../raw/reading-test.md)", collection_text)
            self.assertIn("(wiki/collections/reading-list.md)", (self.root / "index.md").read_text(encoding="utf-8"))
        finally:
            source.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)

    def test_saved_query_links_are_relative(self):
        output = save_query_output("tasks", [{"path": "wiki/collections/tasks.md", "line": "+ Ship"}])
        try:
            text = output.read_text(encoding="utf-8")
            self.assertIn("](../../wiki/collections/tasks.md)", text)
        finally:
            output.unlink(missing_ok=True)

    def test_external_collection_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "note.md"
            source.write_text("# Reading List\n\n- External book\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                extract_collections(source)

    def test_automatic_collection_candidates_exclude_wiki(self):
        candidates = collection_source_candidates()
        self.assertFalse(any(path.is_relative_to(self.wiki) for path in candidates))

    def test_lint_helpers(self):
        self.assertIsInstance(lint_links(), list)
        self.assertIsInstance(lint_source_drift(), list)
        self.assertIsInstance(lint_orphans(), list)


class ReviewRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.raw = self.root / "raw"
        self.raw.mkdir()
        self.wiki = self.root / "wiki"
        self.wiki.mkdir()
        patcher = patch.multiple(
            second_brain, ROOT=self.root, RAW=self.raw, WIKI=self.wiki,
            LOG=self.root / "log.md", INDEX=self.root / "index.md",
            ASSETS=self.raw / "assets",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_migration_preserves_indent_and_signifiers(self):
        for original, expected in (
            ("* + priority task\n", "* X priority task\n"),
            ("! [ ] idea task\n", "! [X] idea task\n"),
            ("  \t*  =  + indented task\n", "  \t*  =  X indented task\n"),
            ("  + indented task\n", "  X indented task\n"),
        ):
            with self.subTest(original=original):
                source = self.raw / "journal.md"
                source.write_text(original, encoding="utf-8")
                migrate_task("task", "completed")
                self.assertEqual(source.read_text(encoding="utf-8"), expected)

    def test_scheduled_date_validation_before_any_write(self):
        source = self.raw / "journal.md"
        original = "  * [ ] schedule task\n"
        source.write_text(original, encoding="utf-8")
        for invalid in (None, "", "2026-2-03", "2026-02-29", "tomorrow", "2026-02-30"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "valid date"):
                    migrate_task("schedule task", "scheduled", date=invalid)
                self.assertEqual(source.read_text(encoding="utf-8"), original)
                self.assertFalse((self.root / "log.md").exists())
        migrate_task("schedule task", "scheduled", date="2028-02-29")
        self.assertEqual(source.read_text(encoding="utf-8"), "  * [<] 2028-02-29 schedule task\n")

    def test_scheduled_cli_rejects_missing_and_invalid_date(self):
        source = self.raw / "journal.md"
        original = "+ schedule task\n"
        source.write_text(original, encoding="utf-8")
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        for date_args in ([], ["--date", "2026-02-30"]):
            with self.subTest(date_args=date_args):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "second_brain.py"),
                     "migrate", "schedule task", "scheduled", *date_args],
                    env=env, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("valid date", result.stderr)
                self.assertEqual(source.read_text(encoding="utf-8"), original)
                self.assertFalse((self.root / "log.md").exists())

    def test_lint_reports_missing_or_malformed_source_metadata(self):
        digest = hashlib.sha256(b"original").hexdigest()
        source = self.root / "source.txt"
        source.write_bytes(b"original")
        cases = {
            "missing.md": "# No front matter\n",
            "unclosed.md": "---\nsource: example\n",
            "malformed.md": '---\nsource: "unterminated\n---\n',
            "nonmapping.md": "---\n- entry\n---\n",
            "empty-source.md": f"---\nsource: null\nsource_sha256: '{digest}'\n---\n",
            "missing-hash.md": f"---\nsource: '{source.as_posix()}'\n---\n",
            "bad-hash.md": f"---\nsource: '{source.as_posix()}'\nsource_sha256: bad\n---\n",
            "valid.md": second_brain.front_matter("Source", source.as_posix(), "file", digest) + "\n",
        }
        for name, text in cases.items():
            (self.raw / name).write_text(text, encoding="utf-8")
        issues = lint_source_drift()
        self.assertEqual({issue["path"] for issue in issues}, {f"raw/{name}" for name in cases if name != "valid.md"})
        self.assertTrue(all(issue["issue"] for issue in issues))

    def test_lint_validates_required_metadata_fields(self):
        source = self.root / "source.txt"
        source.write_bytes(b"source")
        digest = hashlib.sha256(b"source").hexdigest()
        base = {
            "title": "Source", "source": str(source), "source_type": "file",
            "ingested_at": "2026-01-01T10:00:00Z", "source_sha256": digest,
            "tags": [], "status": "active", "immutable": True,
        }
        import yaml
        path = self.raw / "source.md"
        for field in base:
            with self.subTest(missing=field):
                metadata = dict(base)
                del metadata[field]
                path.write_text("---\n" + yaml.safe_dump(metadata) + "---\n", encoding="utf-8")
                self.assertTrue(lint_source_drift(), field)
        for field, invalid in (("title", ""), ("source_type", "other"), ("source_type", []),
                               ("ingested_at", "2026-02-30"), ("tags", "tag"),
                               ("status", ""), ("immutable", False)):
            with self.subTest(field=field):
                metadata = dict(base, **{field: invalid})
                path.write_text("---\n" + yaml.safe_dump(metadata) + "---\n", encoding="utf-8")
                self.assertTrue(lint_source_drift(), field)
        for field, invalid in (("source_type", "url"), ("source", "https://example.com/note")):
            with self.subTest(mismatch=field):
                metadata = dict(base, **{field: invalid})
                path.write_text("---\n" + yaml.safe_dump(metadata) + "---\n", encoding="utf-8")
                self.assertTrue(lint_source_drift())
        path.write_text("---\n" + yaml.safe_dump(base) + "---\n", encoding="utf-8")
        self.assertEqual(lint_source_drift(), [])

    def test_queries_are_logged_once_with_and_without_saved_output(self):
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        (self.root / "index.md").write_text("# Test topic\n", encoding="utf-8")
        for options in ([], ["--json"], ["--save", "--json"]):
            with self.subTest(options=options):
                log = self.root / "log.md"
                log.write_text("# Operations Log\n", encoding="utf-8")
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "second_brain.py"), "query", "topic", *options],
                    env=env, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(log.read_text(encoding="utf-8").count("] query | topic"), 1)

    def test_image_extensions_follow_content_not_url_name(self):
        png = b"\x89PNG\r\n\x1a\n" + b"image"
        jpeg = b"\xff\xd8\xff" + b"image"
        cases = [
            ("https://example.com/image", png, "image/png", ".png"),
            ("https://example.com/image.jpg", png, "image/png", ".png"),
            ("https://example.com/image.png", jpeg, "image/jpeg", ".jpg"),
        ]
        for url, data, content_type, suffix in cases:
            with self.subTest(url=url):
                with patch.object(second_brain, "fetch_url", return_value=(data, content_type)):
                    result = second_brain.ingest(url)
                text = (self.root / result["raw"]).read_text(encoding="utf-8")
                self.assertIn(suffix + ")", text)
                self.assertTrue(any(path.suffix == suffix and path.read_bytes() == data
                                    for path in (self.raw / "assets").rglob("*") if path.is_file()))
        with patch.object(second_brain, "fetch_url", return_value=(b"not an image", "image/png")):
            with self.assertRaisesRegex(ValueError, "image format"):
                second_brain.ingest("https://example.com/broken")

    def test_svg_roots_with_and_without_namespace(self):
        for data in (b"<svg><path/></svg>",
                     b'<svg xmlns="http://www.w3.org/2000/svg"><path/></svg>'):
            with self.subTest(data=data):
                with patch.object(second_brain, "fetch_url", return_value=(data, "image/svg+xml")):
                    result = second_brain.ingest("https://example.com/image")
                raw = (self.root / result["raw"]).read_text(encoding="utf-8")
                self.assertIn(".svg)", raw)
                self.assertTrue(any(path.suffix == ".svg" and path.read_bytes() == data
                                    for path in (self.raw / "assets").rglob("*") if path.is_file()))
        with self.assertRaises(ValueError):
            second_brain.image_extension(b"<html/>")

    def test_markdown_links_references_and_orphan_detection(self):
        (self.root / "some file.md").write_text("# File\n", encoding="utf-8")
        (self.root / "balanced (name).md").write_text("# File\n", encoding="utf-8")
        (self.wiki / "linked.md").write_text("# Linked\n", encoding="utf-8")
        (self.root / "picture.png").write_bytes(b"image")
        (self.root / "index.md").write_text(
            '[angle](<some file.md> "title")\n'
            '[nested](balanced%20(name).md)\n'
            '[reference][PAGE] ![image][pic]\n'
            '[bad inline](missing.md) [bad ref][absent]\n'
            '[external](https://example.com) [anchor](#section)\n'
            '`[code](missing-code.md)`\n'
            r'\[escaped][no-reference]' + '\n'
            '\n[page]: wiki/linked.md\n[pic]: picture.png\n',
            encoding="utf-8",
        )
        issues = lint_links()
        self.assertEqual({issue["target"] for issue in issues}, {"missing.md", "absent"})
        self.assertIn("undefined reference", {issue.get("issue") for issue in issues})
        self.assertEqual(lint_orphans(), [])

    def test_broken_reference_destinations_and_collapsed_references(self):
        (self.root / "index.md").write_text(
            '[broken][label] ![icon][] [missing label][] ![other][unknown]\n'
            '\n[label]: <missing file.md>\n[icon]: missing.png\n',
            encoding="utf-8",
        )
        issues = lint_links()
        self.assertEqual(
            {issue["target"] for issue in issues},
            {"missing%20file.md", "missing.png", "missing label", "unknown"},
        )

    def test_binary_local_fallback_requires_conversion(self):
        samples = {
            "document.pdf": b"%PDF-1.0\nplain text",
            "data.bin": b"valid utf-8",
            "document.txt": b"hello\x00world",
            "disguised.md": b"%PDF-1.0\nplain text",
        }
        with patch.object(second_brain, "convert_markitdown", return_value=None):
            for name, data in samples.items():
                with self.subTest(name=name):
                    source = self.root / name
                    source.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, "requires MarkItDown"):
                        second_brain.ingest(str(source))
                    self.assertEqual(list(self.raw.rglob("*.md")), [])
            source = self.root / "notes.txt"
            source.write_text("A normal note\n", encoding="utf-8")
            result = second_brain.ingest(str(source))
            self.assertIn("A normal note", (self.root / result["raw"]).read_text(encoding="utf-8"))
        with patch.object(second_brain, "convert_markitdown", return_value="# Converted PDF"):
            result = second_brain.ingest(str(self.root / "document.pdf"))
            self.assertIn("Converted PDF", (self.root / result["raw"]).read_text(encoding="utf-8"))

    def test_ocr_alias_expansion_is_literal(self):
        self.assertEqual(clean_ocr("See loc and ref", {"loc": r"C:\temp\notes", "ref": r"\1\g<name>"}),
                         "See C:\\temp\\notes and \\1\\g<name>\n")
        self.assertEqual(clean_ocr("reference", {"reference": r"\g<name>\q"}), r"\g<name>\q" + "\n")

    def test_collection_deduplicates_and_preserves_each_source(self):
        first = self.raw / "first note.md"
        second = self.raw / "second.md"
        first.write_text("# Reading List\n\n- Shared book\n- First book\n", encoding="utf-8")
        second.write_text("# Reading List\n\n- Shared book\n- Second book\n", encoding="utf-8")
        extract_collections(first)
        extract_collections(second)
        destination = self.wiki / "collections" / "reading-list.md"
        before = destination.read_text(encoding="utf-8")
        extract_collections(first)
        extract_collections(second)
        self.assertEqual(destination.read_text(encoding="utf-8"), before)
        shared = [line for line in before.splitlines() if line.startswith("- Shared book")]
        self.assertEqual(len(shared), 1)
        self.assertIn("([source](../../raw/first%20note.md))", shared[0])
        self.assertIn("([source](../../raw/second.md))", shared[0])
        self.assertIn("- First book", before)
        self.assertIn("- Second book", before)
        self.assertEqual(lint_links(), [])

    def test_collection_merges_preexisting_duplicate_entries(self):
        source = self.raw / "third.md"
        source.write_text("# Reading List\n\n- Shared\n", encoding="utf-8")
        destination = self.wiki / "collections" / "reading-list.md"
        destination.parent.mkdir()
        destination.write_text("# Reading List\n\n- Shared ([source](../../raw/first.md))\n"
                               "- Shared ([source](../../raw/second.md))\n", encoding="utf-8")
        extract_collections(source)
        entries = [line for line in destination.read_text(encoding="utf-8").splitlines() if line.startswith("- Shared")]
        self.assertEqual(len(entries), 1)
        for name in ("first", "second", "third"):
            self.assertIn(f"../../raw/{name}.md", entries[0])


if __name__ == "__main__":
    unittest.main()
