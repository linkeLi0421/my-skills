import json
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
                "date": "2026-02-24"
            }
            result = skill.process(data)
            self.assertTrue(result["ok"])
            self.assertTrue(os.path.isfile(result["note_path"]))
            with open(result["note_path"], "r", encoding="utf-8") as handle:
                content = handle.read()
            self.assertIn("id:", content)
            self.assertIn("#", content)
            self.assertIn("## TL;DR", content)

    def test_excerpt_trimming(self):
        long_line = "x" * (skill.MAX_LINE_LEN + 50)
        evidence = skill.select_evidence([long_line], 5)
        self.assertEqual(len(evidence), 1)
        self.assertLessEqual(len(evidence[0]), skill.MAX_LINE_LEN)


if __name__ == "__main__":
    unittest.main()
