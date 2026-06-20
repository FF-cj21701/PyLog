from __future__ import annotations

import os
import sys
import tempfile
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from scripts.ui.script_tree import ScriptExplorerTree
from scripts.ui.ui_explorer import UnifiedExplorer


class ScriptExplorerRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_unified_explorer_lists_non_python_files(self):
        explorer = UnifiedExplorer()
        with tempfile.TemporaryDirectory() as temp_dir:
            py_path = os.path.join(temp_dir, "demo.py")
            txt_path = os.path.join(temp_dir, "notes.txt")
            hidden_path = os.path.join(temp_dir, ".secret")

            with open(py_path, "w", encoding="utf-8") as handle:
                handle.write("print('demo')\n")
            with open(txt_path, "w", encoding="utf-8") as handle:
                handle.write("hello\n")
            with open(hidden_path, "w", encoding="utf-8") as handle:
                handle.write("hidden\n")

            explorer._add_files_to_tree(temp_dir, explorer.script_tree)

        entries = {}
        for index in range(explorer.script_tree.topLevelItemCount()):
            item = explorer.script_tree.topLevelItem(index)
            entries[item.text(0)] = item.data(0, Qt.UserRole)

        self.assertEqual(entries["demo.py"]["type"], "script")
        self.assertEqual(entries["notes.txt"]["type"], "file")
        self.assertNotIn(".secret", entries)

    def test_rename_non_python_file_preserves_extension(self):
        tree = ScriptExplorerTree()
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = os.path.join(temp_dir, "notes.txt")
            with open(old_path, "w", encoding="utf-8") as handle:
                handle.write("hello\n")

            item = tree.invisibleRootItem()
            from PySide6.QtWidgets import QTreeWidgetItem

            file_item = QTreeWidgetItem(item)
            file_item.setText(0, "notes.txt")
            file_item.setData(0, Qt.UserRole, {"type": "file", "path": old_path})

            from unittest.mock import patch

            with patch("scripts.ui.script_tree.ThemeDialog.get_text", return_value=("renamed.txt", True)):
                tree.rename_script(file_item, old_path)

            self.assertTrue(os.path.exists(os.path.join(temp_dir, "renamed.txt")))
            self.assertFalse(os.path.exists(os.path.join(temp_dir, "renamed.txt.py")))


if __name__ == "__main__":
    unittest.main()
