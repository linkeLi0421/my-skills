import os
import tempfile
import unittest

from skills.git_sync_notes import skill


class GitSyncNotesValidationTests(unittest.TestCase):
    def test_validate_note_file_ok(self):
        with tempfile.TemporaryDirectory() as root:
            rel = "notes/2026/2026-03/2026-03-02-topic-slug.md"
            path = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            content = """---
title: Topic Slug
date: 2026-03-02
project: demo
topic: topic-slug
---
# Topic Slug

Body
"""
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            issues = skill.validate_note_file(path, rel)
            self.assertEqual(issues, [])

    def test_validate_note_file_bad_filename_and_h1(self):
        with tempfile.TemporaryDirectory() as root:
            rel = "notes/2026/2026-03/2026-03-02-topic-slug-deadbeef.md"
            path = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            content = """---
title: Topic Slug
date: 2026-03-02
project: demo
topic: topic-slug
---
# Different Title
"""
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(content)
            issues = skill.validate_note_file(path, rel)
            self.assertTrue(
                any("invalid filename/path" in issue for issue in issues)
                or any("legacy shortid suffix" in issue for issue in issues)
            )
            self.assertTrue(any("first H1 must exactly match" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
