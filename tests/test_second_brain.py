import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.second_brain import (
    ROOT,
    clean_ocr,
    lint_links,
    lint_orphans,
    lint_source_drift,
    migrate_task,
    parse_bullet,
    route_bullet,
)


class SecondBrainTests(unittest.TestCase):
    def test_bullet_routes(self):
        self.assertEqual(route_bullet("+ Ship release"), "wiki/collections/tasks.md")
        self.assertEqual(route_bullet("O Team event"), "wiki/collections/timeline.md")
        self.assertEqual(route_bullet("- Architecture fact"), "wiki/concepts.md")
        self.assertEqual(route_bullet("^O Appointment"), "wiki/collections/future.md")
        self.assertEqual(route_bullet("! - Idea"), "wiki/collections/ideas.md")
        self.assertEqual(parse_bullet("[>] Migrated")["bullet"], ">")

    def test_ocr_cleanup(self):
        cleaned = clean_ocr("Pick up a -\nbook for mtg.", {"mtg": "meeting"})
        self.assertIn("a book", cleaned)
        self.assertIn("meeting", cleaned)

    def test_migration_updates_in_place(self):
        path = ROOT / "daily_test.md"
        path.write_text("+ Migrate this task\n", encoding="utf-8")
        try:
            changed = migrate_task("Migrate this task", "migrated", "September")
            self.assertIn("daily_test.md", changed)
            self.assertIn("> Migrate this task -> September", path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

    def test_ingest_cli(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "Fresh Source.md"
            source.write_text("# Fresh Source\n\n- A fact\n", encoding="utf-8")
            result = subprocess.run(
                ["python", "tools/second_brain.py", "ingest", str(source), "--json"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("raw/", result.stdout)

    def test_lint_helpers(self):
        self.assertIsInstance(lint_links(), list)
        self.assertIsInstance(lint_source_drift(), list)
        self.assertIsInstance(lint_orphans(), list)


if __name__ == "__main__":
    unittest.main()
