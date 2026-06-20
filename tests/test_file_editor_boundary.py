from __future__ import annotations

import os
import tempfile
import unittest


from plugins.ai_assistant.ai_core.file_editor import FileEditor, PatchHunk


class FileEditorBoundaryTests(unittest.TestCase):
    def test_apply_patch_replaces_one_exact_hunk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "demo.py")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("alpha\nbeta\nbeta\n")
            editor = FileEditor(project_root=tmpdir)

            result = editor.apply_patch(
                "demo.py",
                [PatchHunk(old_string="beta", new_string="gamma")],
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.applied_hunks, 1)
            with open(target, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "alpha\ngamma\nbeta\n")

    def test_apply_patch_can_replace_all_occurrences(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "demo.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("one two one")
            editor = FileEditor(project_root=tmpdir)

            result = editor.apply_patch(
                "demo.txt",
                [{"old_string": "one", "new_string": "1", "replace_all": True}],
            )

            self.assertTrue(result.ok)
            self.assertEqual(result.applied_hunks, 2)
            with open(target, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "1 two 1")

    def test_apply_patch_creates_file_when_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            editor = FileEditor(project_root=tmpdir)
            target = os.path.join(tmpdir, "nested", "created.py")

            result = editor.apply_patch(
                "nested/created.py",
                [PatchHunk(old_string="", new_string="print('created')\n")],
                create_if_missing=True,
            )

            self.assertTrue(result.ok)
            self.assertTrue(result.created)
            self.assertTrue(os.path.exists(target))
            with open(target, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "print('created')\n")

    def test_apply_patch_rejects_missing_old_string_without_writing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "demo.py")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("safe = True\n")
            editor = FileEditor(project_root=tmpdir)

            result = editor.apply_patch(
                target,
                [PatchHunk(old_string="missing", new_string="unsafe")],
            )

            self.assertFalse(result.ok)
            self.assertIn("old_string not found", result.error)
            with open(target, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "safe = True\n")

    def test_apply_patch_rejects_path_outside_allowed_root(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outside_dir = tempfile.TemporaryDirectory()
            self.addCleanup(outside_dir.cleanup)
            outside_file = os.path.join(outside_dir.name, "outside.py")
            editor = FileEditor(project_root=tmpdir)

            result = editor.apply_patch(
                outside_file,
                [PatchHunk(old_string="", new_string="print('nope')\n")],
                create_if_missing=True,
            )

            self.assertFalse(result.ok)
            self.assertIn("outside allowed roots", result.error)
            self.assertFalse(os.path.exists(outside_file))

    def test_read_text_returns_content_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target = os.path.join(tmpdir, "demo.py")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("print('hello')\n")
            editor = FileEditor(project_root=tmpdir)

            result = editor.read_text("demo.py")

            self.assertTrue(result.ok)
            self.assertEqual(result.metadata["content"], "print('hello')\n")


if __name__ == "__main__":
    unittest.main()
