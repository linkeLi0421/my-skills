import os
import tempfile
import unittest

from skills.summarize_to_notes import skill


class SummarizeToNotesTests(unittest.TestCase):
    def test_slugify_rules(self):
        slug = skill.slugify("My Project: Topic! With Spaces")
        self.assertRegex(slug, r"^[a-z0-9-]+$")
        self.assertLessEqual(len(slug), 40)
        self.assertFalse(slug.startswith("-"))
        self.assertFalse(slug.endswith("-"))

    def test_process_creates_note(self):
        with tempfile.TemporaryDirectory() as repo:
            data = {
                "text": "error: something broke at src/main.c:42\nMore details...",
                "notes_repo_path": repo,
                "meta": {"project": "demo", "topic": "build"},
                "date": "2026-02-24",
            }
            result = skill.process(data)
            self.assertTrue(result["ok"])
            self.assertTrue(os.path.isfile(result["note_path"]))
            self.assertTrue(result["note_path"].endswith("2026-02-24-build.md"))
            with open(result["note_path"], "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("title:", content)
            self.assertIn("date: 2026-02-24", content)
            self.assertIn("project: demo", content)
            self.assertIn("topic: build", content)
            self.assertIn("id:", content)
            self.assertIn("#", content)
            self.assertIn("## TL;DR", content)

    def test_excerpt_trimming(self):
        long_line = "x" * (skill.MAX_LINE_LEN + 50)
        evidence = skill.select_evidence([long_line], 5)
        self.assertEqual(len(evidence), 1)
        self.assertLessEqual(len(evidence[0]), skill.MAX_LINE_LEN)

    def test_auto_mode_defaults_to_summary(self):
        with tempfile.TemporaryDirectory() as repo:
            text = "# Title\n\nSome content.\n"
            data = {
                "text": text,
                "notes_repo_path": repo,
                "meta": {"project": "demo"},
                "date": "2026-02-24",
            }
            result = skill.process(data)
            self.assertTrue(result["ok"])
            with open(result["note_path"], "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("## TL;DR", content)

    def test_document_mode_explicit(self):
        with tempfile.TemporaryDirectory() as repo:
            text = "# Title\n\nSome content.\n"
            data = {
                "text": text,
                "mode": "document",
                "notes_repo_path": repo,
                "meta": {"project": "demo", "topic": "doc"},
                "date": "2026-02-24",
            }
            result = skill.process(data)
            self.assertTrue(result["ok"])
            with open(result["note_path"], "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("# Title", content)
            self.assertIn("Some content.", content)
            self.assertNotIn("## TL;DR", content)

    def test_mojibake_is_rejected(self):
        with tempfile.TemporaryDirectory() as repo:
            bad = "鈥鈥鈥锛锛锛銆銆銆馃馃馃锟锟锟"
            data = {
                "text": bad,
                "notes_repo_path": repo,
                "meta": {"project": "demo", "topic": "encoding"},
                "date": "2026-02-24",
            }
            with self.assertRaises(ValueError):
                skill.process(data)


if __name__ == "__main__":
    unittest.main()
