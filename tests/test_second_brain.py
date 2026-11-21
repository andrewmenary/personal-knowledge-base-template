import subprocess
import tempfile
import unittest
import os
import hashlib
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
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

JOURNAL_HEADER = "---\nkind: journal\n---\n"


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
        path.write_text(JOURNAL_HEADER + "+ Migrate this task\n", encoding="utf-8")
        try:
            changed = migrate_task("Migrate this task", "migrated", "September")
            self.assertIn("raw/migration-test.md", changed)
            self.assertIn("> Migrate this task -> September", path.read_text(encoding="utf-8"))
        finally:
            path.unlink(missing_ok=True)

        scheduled = self.raw / "scheduled-test.md"
        scheduled.write_text(JOURNAL_HEADER + "+ Schedule this task\n", encoding="utf-8")
        try:
            migrate_task("Schedule this task", "scheduled", date="2026-12-01")
            self.assertIn("< 2026-12-01 Schedule this task", scheduled.read_text(encoding="utf-8"))
        finally:
            scheduled.unlink(missing_ok=True)

    def test_migration_ignores_plain_prose(self):
        path = self.raw / "plain-test.md"
        path.write_text("# Release\n\nWe need to release soon.\n", encoding="utf-8")
        try:
            with self.assertRaisesRegex(ValueError, "task not found"):
                migrate_task("release", "completed")
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
        source = self.wiki / "collections" / "tasks.md"
        source.write_text("+ Ship\n", encoding="utf-8")
        output = save_query_output("tasks", [{"path": "wiki/collections/tasks.md", "line": "+ Ship"}])
        try:
            text = output.read_text(encoding="utf-8")
            self.assertIn("](../collections/tasks.md)", text)
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
            ASSETS=self.raw / "assets", INBOX=self.root / "inbox",
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
                source.write_text(JOURNAL_HEADER + original, encoding="utf-8")
                migrate_task(str(parse_bullet(original)["text"]), "completed")
                self.assertEqual(source.read_text(encoding="utf-8"), JOURNAL_HEADER + expected)

    def test_scheduled_date_validation_before_any_write(self):
        source = self.raw / "journal.md"
        original = JOURNAL_HEADER + "  * [ ] schedule task\n"
        source.write_text(original, encoding="utf-8")
        for invalid in (None, "", "2026-2-03", "2026-02-29", "tomorrow", "2026-02-30"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "valid date"):
                    migrate_task("schedule task", "scheduled", date=invalid)
                self.assertEqual(source.read_text(encoding="utf-8"), original)
                self.assertFalse((self.root / "log.md").exists())
        migrate_task("schedule task", "scheduled", date="2028-02-29")
        self.assertEqual(source.read_text(encoding="utf-8"), JOURNAL_HEADER + "  * [<] 2028-02-29 schedule task\n")

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

    def test_rescheduling_replaces_previous_date(self):
        source = self.raw / "journal.md"
        for marker in ("<", "[<]"):
            with self.subTest(marker=marker):
                source.write_text(JOURNAL_HEADER + f"  * {marker} 2026-11-20 task\n", encoding="utf-8")
                migrate_task("task", "scheduled", date="2026-12-01")
                self.assertEqual(source.read_text(encoding="utf-8"),
                                 JOURNAL_HEADER + f"  * {marker} 2026-12-01 task\n")
                migrate_task("task", "scheduled", date="2026-12-01")
                self.assertEqual(source.read_text(encoding="utf-8"),
                                 JOURNAL_HEADER + f"  * {marker} 2026-12-01 task\n")

    def test_status_transitions_remove_previous_metadata(self):
        source = self.raw / "journal.md"
        source.write_text(JOURNAL_HEADER + "  * [ ]  Ship release\n", encoding="utf-8")
        for status, options, expected in (
            ("scheduled", {"date": "2026-12-01"}, "[<]  2026-12-01 Ship release"),
            ("completed", {}, "[X]  Ship release"),
            ("migrated", {"target": "First"}, "[>]  Ship release -> First"),
            ("migrated", {"target": "Second"}, "[>]  Ship release -> Second"),
            ("migrated", {"target": "Second"}, "[>]  Ship release -> Second"),
            ("scheduled", {"date": "2027-01-02"}, "[<]  2027-01-02 Ship release"),
            ("open", {}, "[ ]  Ship release"),
        ):
            with self.subTest(status=status, options=options):
                self.assertEqual(migrate_task("ship release", status, **options), ["raw/journal.md"])
                self.assertEqual(source.read_text(encoding="utf-8"), JOURNAL_HEADER + f"  * {expected}\n")

    def test_migration_normalizes_legacy_metadata_and_keeps_provenance(self):
        collection = self.wiki / "collections" / "tasks.md"
        collection.parent.mkdir()
        a = "([source](../../raw/a.md))"
        b = "([source](../../raw/b.md))"
        for original in (
            f"> 2026-12-01 Ship {a} -> Old\n",
            f"> Ship -> Old {a} -> Older {b}\n",
            f"X 2026-12-01 Ship -> Old {a} {b}\n",
        ):
            with self.subTest(original=original):
                collection.write_text(original, encoding="utf-8")
                migrate_task("Ship", "migrated", target="New")
                expected_sources = f" {a}" + (f" {b}" if b in original else "")
                self.assertEqual(collection.read_text(encoding="utf-8"), f"> Ship -> New{expected_sources}\n")
                migrate_task("Ship", "completed")
                self.assertEqual(collection.read_text(encoding="utf-8"), f"X Ship{expected_sources}\n")

    def test_normalized_duplicate_tasks_are_rejected_across_destinations(self):
        folder = self.wiki / "collections"
        folder.mkdir()
        first = folder / "first.md"
        second = folder / "second.md"
        first.write_text("> Ship -> Old ([source](../../raw/a.md))\n", encoding="utf-8")
        second.write_text("< 2026-12-01 ship ([source](../../raw/b.md))\n", encoding="utf-8")
        originals = [first.read_bytes(), second.read_bytes()]
        with self.assertRaisesRegex(ValueError, "ambiguous task"):
            migrate_task("Ship", "completed")
        self.assertEqual([first.read_bytes(), second.read_bytes()], originals)
        self.assertFalse((self.root / "log.md").exists())

    def test_invalid_migration_target_does_not_write(self):
        source = self.raw / "journal.md"
        original = JOURNAL_HEADER + "+ Ship\n"
        source.write_text(original, encoding="utf-8")
        for target in ("", " \t", "One\nTwo", "One -> Two", "One\t->\tTwo", "([source](a.md))"):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "single destination"):
                migrate_task("Ship", "migrated", target=target)
            self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_missing_target_preserves_migrated_destination(self):
        source = self.raw / "journal.md"
        original = JOURNAL_HEADER + "> Ship -> Existing\n"
        source.write_text(original, encoding="utf-8")
        for target in (None, "", "   "):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "target"):
                migrate_task("Ship", "migrated", target=target)
            self.assertEqual(source.read_text(encoding="utf-8"), original)
            self.assertFalse((self.root / "log.md").exists())

    def test_migration_cli_missing_target_and_task_fail_without_log(self):
        source = self.raw / "journal.md"
        original = JOURNAL_HEADER + "> Ship -> Existing\n"
        source.write_text(original, encoding="utf-8")
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        for arguments, error in ((["Ship", "migrated"], "target"),
                                 (["Missing", "completed"], "task not found")):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools" / "second_brain.py"), "migrate", *arguments],
                    env=env, text=True, capture_output=True,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn(error, result.stderr)
                self.assertEqual(source.read_text(encoding="utf-8"), original)
                self.assertFalse((self.root / "log.md").exists())

    def test_content_lock_serializes_collection_and_migration_processes(self):
        collection = self.wiki / "collections" / "tasks.md"
        collection.parent.mkdir()
        collection.write_text("+ Ship\n", encoding="utf-8")
        source = self.raw / "reading.md"
        source.write_text("# Reading List\n\n- Book\n", encoding="utf-8")
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        script = str(ROOT / "tools" / "second_brain.py")
        with second_brain.repository_lock("content"):
            processes = [
                subprocess.Popen([sys.executable, script, *args], env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                for args in (["migrate", "Ship", "completed"],
                             ["extract-collections", str(source)])
            ]
            self.addCleanup(lambda: [process.kill() for process in processes if process.poll() is None])
            import time
            time.sleep(2)
            for process in processes:
                self.assertIsNone(process.poll(), "process bypassed the content lock")
            self.assertEqual(collection.read_text(encoding="utf-8"), "+ Ship\n")
            self.assertFalse((collection.parent / "reading-list.md").exists())
        for process in processes:
            _, stderr = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(collection.read_text(encoding="utf-8"), "X Ship\n")
        self.assertIn("- Book", (collection.parent / "reading-list.md").read_text(encoding="utf-8"))

    def test_overlapping_collection_processes_preserve_entries(self):
        sources = []
        for i in range(5):
            source = self.raw / f"source-{i}.md"
            source.write_text(f"# Reading List\n\n- Book {i}\n", encoding="utf-8")
            sources.append(source)
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        script = str(ROOT / "tools" / "second_brain.py")
        processes = [subprocess.Popen([sys.executable, script, "extract-collections", str(source)],
                                      env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for source in sources]
        self.addCleanup(lambda: [process.kill() for process in processes if process.poll() is None])
        for process in processes:
            _, stderr = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, stderr)
        text = (self.wiki / "collections" / "reading-list.md").read_text(encoding="utf-8")
        for i in range(5):
            self.assertIn(f"- Book {i} ([source](../../raw/source-{i}.md))", text)

    def test_overlapping_migrations_preserve_both_tasks(self):
        source = self.raw / "journal.md"
        source.write_text(JOURNAL_HEADER + "+ Ship\n+ Review\n", encoding="utf-8")
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        script = str(ROOT / "tools" / "second_brain.py")
        processes = [subprocess.Popen([sys.executable, script, "migrate", task, "completed"],
                                      env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                     for task in ("Ship", "Review")]
        self.addCleanup(lambda: [process.kill() for process in processes if process.poll() is None])
        for process in processes:
            _, stderr = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(source.read_text(encoding="utf-8"), JOURNAL_HEADER + "X Ship\nX Review\n")

    def test_migration_requires_unique_exact_task(self):
        source = self.raw / "journal.md"
        original = JOURNAL_HEADER + "+ Ship fast\n+ Shipments\n+ Ship\n+ ship\n"
        source.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "ambiguous task"):
            migrate_task(" SHIP ", "completed")
        self.assertEqual(source.read_text(encoding="utf-8"), original)
        migrate_task("ship fast", "completed")
        self.assertEqual(source.read_text(encoding="utf-8"), original.replace("+ Ship fast", "X Ship fast"))
        with self.assertRaisesRegex(ValueError, "ambiguous task"):
            migrate_task("ship", "completed")

    def test_migration_ignores_fenced_code(self):
        source = self.raw / "journal.md"
        original = JOURNAL_HEADER + "```\n+ Ship\n```\n+ Ship fast\n"
        source.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "task not found"):
            migrate_task("Ship", "completed")
        self.assertEqual(source.read_text(encoding="utf-8"), original)

    def test_collection_task_matches_without_provenance(self):
        collection = self.wiki / "collections" / "tasks.md"
        collection.parent.mkdir()
        collection.write_text("+ Ship ([source](../../raw/a.md))\n", encoding="utf-8")
        self.assertEqual(migrate_task("ship", "completed"), ["wiki/collections/tasks.md"])
        self.assertEqual(collection.read_text(encoding="utf-8"), "X Ship ([source](../../raw/a.md))\n")

    def test_shortcut_reference_links_and_images(self):
        target = self.root / "page.md"
        target.write_text("# Page\n", encoding="utf-8")
        index = self.root / "index.md"
        index.write_text(
            "[  Page  ] ![Pic] [missing] ![lost]\n"
            "`[code]` \\[escaped] [ ] [X]\n\n"
            "[page]: page.md\n[pIC]: page.md\n", encoding="utf-8",
        )
        issues = lint_links()
        self.assertEqual({issue["target"] for issue in issues}, {"missing", "lost"})

    def test_collection_preserves_structured_blocks(self):
        source = self.raw / "blocks.md"
        source.write_text(
            "# Reading List\n\n"
            "```md\n# not a heading\n- [literal](not-a-link.md)  \n```\n\n"
            "| Name | Item |\n| --- | --- |\n| One | Two |\n\n"
            "> Quote\n> next line\n\n"
            "- Parent\n  - Child\n- Separate\n",
            encoding="utf-8",
        )
        extract_collections(source)
        collection = self.wiki / "collections" / "reading-list.md"
        result = collection.read_text(encoding="utf-8")
        for expected in ("```md\n# not a heading\n- [literal](not-a-link.md)  \n```",
                         "| Name | Item |\n| --- | --- |\n| One | Two |",
                         "> Quote\n> next line", "- Parent\n  - Child"):
            self.assertIn(expected, result)
        from markdown_it import MarkdownIt
        token_types = [token.type for token in MarkdownIt("commonmark").enable("table").parse(result)]
        for expected in ("fence", "table_open", "blockquote_open"):
            self.assertIn(expected, token_types)
        extract_collections(source)
        self.assertEqual(collection.read_text(encoding="utf-8"), result)
        another = self.raw / "another.md"
        another.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        extract_collections(another)
        merged = collection.read_text(encoding="utf-8")
        self.assertEqual(merged.count("```md"), 1)
        self.assertEqual(merged.count("| Name | Item |"), 1)
        self.assertIn("([source](../../raw/blocks.md)) ([source](../../raw/another.md))", merged)

    def test_migration_only_changes_explicit_journals(self):
        article = self.raw / "a-article.md"
        unmarked = self.raw / "b-unmarked.md"
        malformed = self.raw / "c-malformed.md"
        journal = self.raw / "d-journal.md"
        article.write_text("---\nkind: article\n---\n+ shared task\n", encoding="utf-8")
        unmarked.write_text("+ shared task\n", encoding="utf-8")
        malformed.write_text("---\nkind: [\n---\n+ shared task\n", encoding="utf-8")
        journal.write_bytes(b"---\r\nkind: journal\r\n---\r\n+ shared task\r\n")
        originals = {p: p.read_bytes() for p in (article, unmarked, malformed)}
        self.assertEqual(migrate_task("shared task", "completed"), ["raw/d-journal.md"])
        for path, original in originals.items():
            self.assertEqual(path.read_bytes(), original)
        self.assertEqual(journal.read_bytes(), b"---\r\nkind: journal\r\n---\r\nX shared task\r\n")

    def test_journal_ingest_sets_explicit_kind(self):
        source = self.root / "capture.md"
        source.write_text("+ task\n", encoding="utf-8")
        with patch.object(second_brain, "convert_markitdown", return_value=None):
            article = second_brain.ingest(str(source))
            journal = second_brain.ingest(str(source), journal=True)
        self.assertNotIn("kind", second_brain.parse_front_matter((self.root / article["raw"]).read_text()))
        self.assertEqual(second_brain.parse_front_matter((self.root / journal["raw"]).read_text())["kind"], "journal")
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "second_brain.py"), "ingest",
             str(source), "--journal", "--json"], env=env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        import json
        metadata = second_brain.parse_front_matter((self.root / json.loads(result.stdout)["raw"]).read_text())
        self.assertEqual(metadata["kind"], "journal")

    def test_collection_rebases_inline_and_reference_links(self):
        source = self.raw / "2026" / "reading.md"
        source.parent.mkdir()
        (source.parent / "a (book).md").write_text("# Book\n", encoding="utf-8")
        (source.parent / "cover image.png").write_bytes(b"image")
        source.write_text(
            "# Reading List\n\n"
            "- [Book](<a (book).md#intro> \"title\") ![Cover][cover] [site](https://example.com)\n"
            "- [reference][book] [section](#heading) and `[](missing.md)`\n\n"
            "[cover]: <cover image.png>\n[book]: <a (book).md> \"Book title\"\n", encoding="utf-8")
        extract_collections(source)
        collection = self.wiki / "collections" / "reading-list.md"
        result = collection.read_text(encoding="utf-8")
        self.assertIn("../../raw/2026/a%20%28book%29.md#intro", result)
        self.assertIn("![Cover](../../raw/2026/cover%20image.png)", result)
        self.assertIn('[reference](../../raw/2026/a%20%28book%29.md "Book title")', result)
        self.assertIn("[section](../../raw/2026/reading.md#heading)", result)
        self.assertIn("[site](https://example.com)", result)
        self.assertIn("`[](missing.md)`", result)
        self.assertNotIn("[cover]:", result)
        self.assertFalse([issue for issue in lint_links() if issue["path"] == "wiki/collections/reading-list.md"])
        extract_collections(source)
        self.assertEqual(collection.read_text(encoding="utf-8"), result)

    def test_saved_query_escapes_paths_and_rebases_snippets(self):
        source = self.wiki / "note (#one).md"
        target = self.wiki / "linked file.md"
        target.write_text("# Linked\n", encoding="utf-8")
        source.write_text("[link][ref] ![img](<linked file.md#part>)\n\n[ref]: <linked file.md>\n", encoding="utf-8")
        output = save_query_output("example", [{"path": "wiki/note (#one).md", "line": "[link][ref] ![img](<linked file.md#part>)"}])
        text = output.read_text(encoding="utf-8")
        self.assertIn("../note%20%28%23one%29.md", text)
        self.assertIn("[link](../linked%20file.md)", text)
        self.assertIn("![img](../linked%20file.md#part)", text)
        self.assertFalse([issue for issue in lint_links() if issue["path"] == output.relative_to(self.root).as_posix()])

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

    def test_url_staging_is_unique_and_preserves_inbox(self):
        inbox = self.root / "inbox"
        inbox.mkdir()
        existing = inbox / "_download.html"
        existing.write_text("Keep this capture", encoding="utf-8")
        barrier = threading.Barrier(2)
        paths = []

        def convert(path):
            paths.append(path)
            before = path.read_bytes()
            barrier.wait(timeout=10)
            self.assertEqual(path.read_bytes(), before)
            return before.decode()

        def fetch(url):
            return url.encode(), "text/html"

        urls = ["https://example.com/first.html", "https://example.com/second.html"]
        with patch.object(second_brain, "fetch_url", side_effect=fetch), \
             patch.object(second_brain, "convert_markitdown", side_effect=convert):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(second_brain.ingest, urls))
        self.assertEqual(len(set(paths)), 2)
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertEqual(existing.read_text(encoding="utf-8"), "Keep this capture")
        for result, url in zip(results, urls):
            self.assertIn(url, (self.root / result["raw"]).read_text(encoding="utf-8"))

    def test_url_staging_cleans_up_when_conversion_raises(self):
        paths = []

        def convert(path):
            paths.append(path)
            raise RuntimeError("conversion failed")

        with patch.object(second_brain, "fetch_url", return_value=(b"text", "text/html")), \
             patch.object(second_brain, "convert_markitdown", side_effect=convert):
            with self.assertRaisesRegex(RuntimeError, "conversion failed"):
                second_brain.ingest("https://example.com/test.html")
        self.assertEqual(len(paths), 1)
        self.assertFalse(paths[0].exists())

    def test_concurrent_ingests_preserve_raw_captures_index_and_log(self):
        source_dirs = [self.root / f"source-{i}" for i in range(8)]
        for i, directory in enumerate(source_dirs):
            directory.mkdir()
            (directory / "same.txt").write_text(f"Unique content {i}", encoding="utf-8")
        env = os.environ.copy()
        env["SECOND_BRAIN_ROOT"] = str(self.root)
        processes = [
            subprocess.Popen(
                [sys.executable, str(ROOT / "tools" / "second_brain.py"),
                 "ingest", str(directory / "same.txt"), "--json"],
                env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            ) for directory in source_dirs
        ]
        import json
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=60)
            self.assertEqual(process.returncode, 0, stderr)
            results.append(json.loads(stdout))
        paths = [result["raw"] for result in results]
        self.assertEqual(len(set(paths)), len(source_dirs))
        index = (self.root / "index.md").read_text(encoding="utf-8")
        for i, path in enumerate(paths):
            self.assertIn(f"Unique content {i}", (self.root / path).read_text(encoding="utf-8"))
            self.assertIn(f"]({path})", index)
        self.assertEqual((self.root / "log.md").read_text(encoding="utf-8").count("] ingest | Same"), len(paths))

    def test_existing_raw_slug_collision_is_never_overwritten(self):
        source = self.root / "same.txt"
        source.write_text("New content", encoding="utf-8")
        year = second_brain.datetime.now(second_brain.timezone.utc).strftime("%Y")
        destination = self.raw / year
        destination.mkdir()
        existing = destination / "same.md"
        existing.write_text("Previous capture", encoding="utf-8")
        with patch.object(second_brain, "convert_markitdown", return_value=None):
            result = second_brain.ingest(str(source))
        self.assertEqual(existing.read_text(encoding="utf-8"), "Previous capture")
        self.assertEqual(Path(result["raw"]).name, "same-2.md")
        self.assertIn("New content", (self.root / result["raw"]).read_text(encoding="utf-8"))

    def test_raw_and_collection_index_updates_share_lock(self):
        started = threading.Barrier(3)

        def update_raw():
            started.wait(timeout=10)
            second_brain.update_index("Raw", "raw/example.md")

        def update_collection():
            started.wait(timeout=10)
            second_brain.update_collection_index("reading-list", self.wiki / "reading-list.md")

        with ThreadPoolExecutor(max_workers=2) as pool:
            with second_brain.repository_lock("index"):
                futures = [pool.submit(update_raw), pool.submit(update_collection)]
                started.wait(timeout=10)
                for future in futures:
                    with self.assertRaises(TimeoutError):
                        future.result(timeout=0.2)
                (self.root / "index.md").write_text("# Preserved edit\n", encoding="utf-8")
            for future in futures:
                future.result(timeout=10)
        index = (self.root / "index.md").read_text(encoding="utf-8")
        for expected in ("# Preserved edit", "raw/example.md", "wiki/reading-list.md"):
            self.assertIn(expected, index)

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
