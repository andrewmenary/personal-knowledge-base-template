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
    RAW,
    WIKI,
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
        self.index_before = (ROOT / "index.md").read_text(encoding="utf-8")
        self.log_before = (ROOT / "log.md").read_text(encoding="utf-8")

    def tearDown(self):
        (ROOT / "index.md").write_text(self.index_before, encoding="utf-8")
        (ROOT / "log.md").write_text(self.log_before, encoding="utf-8")

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
        path = RAW / "migration-test.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("+ Migrate this task\n", encoding="utf-8")
        try:
            changed = migrate_task("Migrate this task", "migrated", "September")
            self.assertIn("raw/migration-test.md", changed)
            self.assertIn("> Migrate this task -> September", path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

        scheduled = RAW / "scheduled-test.md"
        scheduled.write_text("+ Schedule this task\n", encoding="utf-8")
        try:
            migrate_task("Schedule this task", "scheduled", date="2026-12-01")
            self.assertIn("< 2026-12-01 Schedule this task", scheduled.read_text(encoding="utf-8"))
        finally:
            scheduled.unlink(missing_ok=True)

    def test_migration_ignores_plain_prose(self):
        path = RAW / "plain-test.md"
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
        source = RAW / "reading-test.md"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("# Reading List\n\n- A useful book\n", encoding="utf-8")
        destination = WIKI / "collections" / "reading-list.md"
        index_before = (ROOT / "index.md").read_text(encoding="utf-8")
        try:
            results = extract_collections(source)
            self.assertTrue(results)
            collection_text = destination.read_text(encoding="utf-8")
            self.assertIn("[source](../../raw/reading-test.md)", collection_text)
            self.assertIn("(wiki/collections/reading-list.md)", (ROOT / "index.md").read_text(encoding="utf-8"))
        finally:
            source.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            (ROOT / "index.md").write_text(index_before, encoding="utf-8")

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
        self.assertFalse(any(path.is_relative_to(WIKI) for path in candidates))

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
            "valid.md": f"---\nsource: '{source.as_posix()}'\nsource_sha256: '{digest}'\n---\n",
        }
        for name, text in cases.items():
            (self.raw / name).write_text(text, encoding="utf-8")
        issues = lint_source_drift()
        self.assertEqual({issue["path"] for issue in issues}, {f"raw/{name}" for name in cases if name != "valid.md"})
        self.assertTrue(all(issue["issue"] for issue in issues))

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
