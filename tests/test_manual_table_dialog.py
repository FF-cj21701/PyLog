from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from scripts.data.db_manager import DBManager
from scripts.ui.dialogs.manual_table_dialog import ManualTableDialog


class ManualTableDialogRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "manual_table_test.db")
        self.db = DBManager(self.db_path)
        self.well_id = self.db.save_well("DemoWell")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dialog_uses_true_index_first_layout(self):
        dialog = ManualTableDialog("DemoWell", self.well_id, self.db_path)

        self.assertFalse(dialog.table.verticalHeader().isVisible())
        self.assertEqual(dialog.table.horizontalHeaderItem(0).text(), "")
        self.assertEqual(dialog.table.horizontalHeaderItem(1).text(), "Depth")
        self.assertEqual(dialog.table.item(0, 0).text(), "1")
        self.assertFalse(dialog.table.item(0, 0).flags() & Qt.ItemIsEditable)

    def _flush_dialog_timers(self, dialog, max_cycles=50):
        for _ in range(max_cycles):
            self.app.processEvents()
            if not getattr(dialog, "_depth_fill_timer", None) or not dialog._depth_fill_timer.isActive():
                if dialog.table.item(0, 1) is not None:
                    break

    def test_paste_and_save_preserve_depth_and_data_column_offsets(self):
        dialog = ManualTableDialog(
            "DemoWell",
            self.well_id,
            self.db_path,
            initial_depth=np.array([1000.0, 1000.5], dtype=float),
        )
        dialog.set_loading_depth_state(True)
        self._flush_dialog_timers(dialog)
        dialog.folder_edit.setText("Custom_Curves")
        dialog.table.setCurrentCell(0, dialog._first_data_column())

        with patch("scripts.ui.dialogs.manual_table_dialog.QApplication.clipboard") as mock_clipboard:
            mock_clipboard.return_value.text.return_value = "GR [API]\tRHOB [g/cc]\n80\t2.35\n81\t2.36"
            dialog.paste_from_clipboard()

        self.assertEqual(dialog.table.horizontalHeaderItem(2).text(), "GR [API]")
        self.assertEqual(dialog.table.horizontalHeaderItem(3).text(), "RHOB [g/cc]")
        self.assertEqual(dialog.table.item(0, 1).text(), "1000.0000")
        self.assertEqual(dialog.table.item(0, 2).text(), "80")
        self.assertEqual(dialog.table.item(1, 3).text(), "2.36")

        with patch("scripts.ui.dialogs.manual_table_dialog.ThemeDialog.message") as mock_info:
            dialog.handle_save()

        curves = self.db.get_curves(self.well_id)
        names = {row[1] for row in curves}
        self.assertEqual(names, {"Depth", "GR", "RHOB"})
        mock_info.assert_called_once()

        curve_by_name = {row[1]: row[0] for row in curves}
        gr = np.asarray(self.db.get_curve_data(curve_by_name["GR"]))
        rhob = np.asarray(self.db.get_curve_data(curve_by_name["RHOB"]))
        depth = np.asarray(self.db.get_curve_data(curve_by_name["Depth"]))

        np.testing.assert_allclose(depth, np.array([1000.0, 1000.5], dtype=np.float32))
        np.testing.assert_allclose(gr, np.array([80.0, 81.0], dtype=np.float32))
        np.testing.assert_allclose(rhob, np.array([2.35, 2.36], dtype=np.float32))
