import subprocess
import tempfile
import unittest
import os
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
