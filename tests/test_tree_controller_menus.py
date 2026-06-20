from __future__ import annotations

import os
import sys
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtWidgets import QApplication, QMainWindow, QMenu

from scripts.ui.tree_controller import TreeController


def _action_texts(menu: QMenu) -> list[str]:
    texts: list[str] = []
    for action in menu.actions():
        texts.append("---separator---" if action.isSeparator() else action.text())
    return texts


class _MainWindowStub(QMainWindow):
    def __init__(self):
        super().__init__()
        self.explorer_clipboard = None

    def handle_quick_plot(self, _items):
        return None

    def handle_open_data_viewer(self, _items):
        return None


class TreeControllerMenuRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.main_window = _MainWindowStub()
        self.controller = TreeController(self.main_window)

    def test_folder_menu_keeps_rename_action(self):
        menu = QMenu()
        data = {"type": "folder", "id": 10, "well_id": 3, "db_path": "data/demo.db", "name": "Custom_Curves"}

        self.controller._build_folder_menu(menu, data, [data])

        self.assertEqual(
            _action_texts(menu),
            [
                "New Sub-Folder",
                "New Custom Curve...",
                "---separator---",
                "Cut",
                "Copy",
                "Rename",
                "---separator---",
                "Delete Folder",
            ],
        )

    def test_folder_menu_shows_paste_when_clipboard_matches_db(self):
        menu = QMenu()
        data = {"type": "folder", "id": 10, "well_id": 3, "db_path": "data/demo.db", "name": "Custom_Curves"}
        self.main_window.explorer_clipboard = {"db_path": "data/demo.db", "items": [], "op": "copy"}

        self.controller._build_folder_menu(menu, data, [data])

        self.assertIn("Paste", _action_texts(menu))

    def test_well_menu_keeps_expected_actions(self):
        menu = QMenu()
        data = {"type": "well", "id": 1, "db_path": "data/demo.db", "name": "DemoWell"}

        self.controller._build_well_menu(menu, data)

        self.assertEqual(
            _action_texts(menu),
            [
                "New Folder",
                "Rename",
                "Delete",
                "---separator---",
                "New Custom Curve...",
            ],
        )

    def test_curve_menu_keeps_expected_actions(self):
        menu = QMenu()
        data = {"type": "curve", "id": 7, "db_path": "data/demo.db", "name": "GR"}

        self.controller._build_curve_menu(menu, data, [data])

        self.assertEqual(
            _action_texts(menu),
            [
                "Quick Plot",
                "Data Viewer",
                "---separator---",
                "Cut",
                "Copy",
                "Rename",
                "---separator---",
                "Delete Curve",
            ],
        )

    def test_multi_selection_menu_for_curves_exposes_bulk_actions(self):
        menu = QMenu()
        items = [
            {"type": "curve", "id": 7, "db_path": "data/demo.db", "name": "GR"},
            {"type": "curve", "id": 8, "db_path": "data/demo.db", "name": "RT"},
        ]

        self.controller._build_multi_selection_menu(
            menu,
            selected_items=items,
            valid_items_data=items,
            db_paths={"data/demo.db"},
            types={"curve"},
        )

        self.assertEqual(
            _action_texts(menu),
            [
                "Quick Plot (2 curves)",
                "Data Viewer (2 curves)",
                "---separator---",
                "Cut (2 items)",
                "Copy (2 items)",
                "---separator---",
                "Delete (2 Curves)",
            ],
        )


if __name__ == "__main__":
    unittest.main()
