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

from PySide6.QtWidgets import QApplication

from scripts.data.db_manager import DBManager
from scripts.data.dlis_exporter import _normalize_unit, export_well_to_dlis
from scripts.data.import_workers import ExportWorker
from scripts.ui.dialogs.export_dialogs import DLISExportDialog
from scripts.utils.well_metadata import get_well_export_snapshot


class _FakeFrame:
    def __init__(self, name):
        self.name = name
        self.channels = []
        self.index_curve = None

    def add_channel(self, name, values, unit=""):
        payload = {"name": name, "values": np.asarray(values), "unit": unit}
        self.channels.append(payload)
        return payload


class _FakeDLISFile:
    last_instance = None

    def __init__(self):
        self.frames = []
        self.well_name = None
        self.written_path = None
        _FakeDLISFile.last_instance = self

    def add_frame(self, frame_name):
        frame = _FakeFrame(frame_name)
        self.frames.append(frame)
        return frame

    def write(self, output_path):
        self.written_path = output_path


class _FakeDLISWriterModule:
    DLISFile = _FakeDLISFile
    class enums:
        class Unit:
            API_GRAVITY = type("EnumVal", (), {"value": "dAPI"})()
            OHM = type("EnumVal", (), {"value": "ohm"})()
            GRAM = type("EnumVal", (), {"value": "g"})()
            METER = type("EnumVal", (), {"value": "m"})()


class DLISExportRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "export_test.db")
        self.db = DBManager(self.db_path)
        self.well_id = self.db.save_well("DemoWell")
        self.frame0_id = self.db.create_folder(self.well_id, "FRAME0")
        self.frame1_id = self.db.create_folder(self.well_id, "FRAME1")

        self.db.save_curve(self.well_id, "DEPT", "m", np.array([1000.0, 1000.5], dtype=np.float32), folder_id=self.frame0_id)
        self.db.save_curve(self.well_id, "GR", "API", np.array([80.0, 81.0], dtype=np.float32), folder_id=self.frame0_id)
        self.db.save_curve(self.well_id, "GR", "API", np.array([90.0, 91.0], dtype=np.float32), folder_id=self.frame1_id)
        self.db.save_curve(self.well_id, "IMG", "", np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32), folder_id=self.frame1_id)
        self.db.save_curve(
            self.well_id,
            "CUBE",
            "",
            np.array([[[1.0, 2.0]], [[3.0, 4.0]]], dtype=np.float32),
            folder_id=self.frame1_id,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dialog_groups_curves_by_frame_and_defaults_file_name(self):
        snapshot = get_well_export_snapshot(self.db, self.db_path, self.well_id)
        dialog = DLISExportDialog([{"id": self.well_id, "name": "DemoWell", "db_path": self.db_path}])
        dialog.set_well_snapshot(self.db_path, self.well_id, snapshot)

        self.assertEqual(dialog.file_name_edit.text(), "DemoWell")
        self.assertEqual(dialog.curve_tree.topLevelItemCount(), 2)
        self.assertEqual(dialog.curve_tree.topLevelItem(0).text(0), "FRAME0")
        self.assertEqual(dialog.curve_tree.topLevelItem(1).text(0), "FRAME1")

    def test_dialog_uses_determinate_progress_for_curve_preparation(self):
        dialog = DLISExportDialog([{"id": self.well_id, "name": "DemoWell", "db_path": self.db_path}])
        dialog.begin_export()
        dialog.update_export_progress(
            {"phase": "preparing_curve", "current": 2, "total": 5, "curve": "FRAME0/GR"}
        )

        self.assertEqual(dialog.progress_bar.minimum(), 0)
        self.assertEqual(dialog.progress_bar.maximum(), 5)
        self.assertEqual(dialog.progress_bar.value(), 2)

    def test_export_preserves_frames_and_auto_adds_depth_curve(self):
        snapshot = get_well_export_snapshot(self.db, self.db_path, self.well_id)
        curves = snapshot["curves"]
        selected = [curve for curve in curves if curve["name"] == "GR" and curve["folder"] == "FRAME0"]
        progress_events = []

        output_path = os.path.join(self.temp_dir.name, "demo_export.dlis")
        result = export_well_to_dlis(
            {
                "db_path": self.db_path,
                "well_id": self.well_id,
                "well_name": "DemoWell",
                "snapshot": snapshot,
            },
            selected,
            output_path,
            dliswriter_module=_FakeDLISWriterModule,
            progress_callback=progress_events.append,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["exported_curve_count"], 2)
        self.assertEqual(len(result["auto_added_depth_ids"]), 1)
        writer = _FakeDLISFile.last_instance
        self.assertIsNotNone(writer)
        self.assertEqual(writer.written_path, output_path)
        self.assertEqual([frame.name for frame in writer.frames], ["FRAME0"])
        self.assertEqual([channel["name"] for channel in writer.frames[0].channels], ["DEPT", "GR"])
        self.assertEqual(result["exported_curves"], ["FRAME0/DEPT", "FRAME0/GR"])
        self.assertIn(progress_events[0]["phase"], {"preparing_curve"})
        self.assertEqual(progress_events[-1]["phase"], "writing_file")

    def test_export_supports_two_dimensional_curves(self):
        snapshot = get_well_export_snapshot(self.db, self.db_path, self.well_id)
        selected = [curve for curve in snapshot["curves"] if curve["name"] == "IMG"]
        output_path = os.path.join(self.temp_dir.name, "img_export.dlis")

        result = export_well_to_dlis(
            {
                "db_path": self.db_path,
                "well_id": self.well_id,
                "well_name": "DemoWell",
                "snapshot": snapshot,
            },
            selected,
            output_path,
            dliswriter_module=_FakeDLISWriterModule,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["exported_curve_count"], 2)
        self.assertNotIn("FRAME1/IMG", result["skipped_multidim"])
        writer = _FakeDLISFile.last_instance
        self.assertEqual([frame.name for frame in writer.frames], ["FRAME1"])
        self.assertEqual([channel["name"] for channel in writer.frames[0].channels], ["DEPT", "IMG"])
        self.assertEqual(writer.frames[0].channels[1]["values"].shape, (2, 2))

    def test_export_skips_three_dimensional_curves_with_warning(self):
        snapshot = get_well_export_snapshot(self.db, self.db_path, self.well_id)
        selected = [curve for curve in snapshot["curves"] if curve["name"] == "CUBE"]
        output_path = os.path.join(self.temp_dir.name, "cube_export.dlis")

        result = export_well_to_dlis(
            {
                "db_path": self.db_path,
                "well_id": self.well_id,
                "well_name": "DemoWell",
                "snapshot": snapshot,
            },
            selected,
            output_path,
            dliswriter_module=_FakeDLISWriterModule,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["exported_curve_count"], 0)
        self.assertIn("FRAME1/CUBE", result["skipped_multidim"])
        self.assertIn("warning", result)

    def test_export_reports_missing_dependency(self):
        snapshot = get_well_export_snapshot(self.db, self.db_path, self.well_id)
        selected = [curve for curve in snapshot["curves"] if curve["name"] == "GR"]

        with patch("scripts.data.dlis_exporter._load_dliswriter_module", return_value=None):
            result = export_well_to_dlis(
                {
                    "db_path": self.db_path,
                    "well_id": self.well_id,
                    "well_name": "DemoWell",
                    "snapshot": snapshot,
                },
                selected,
                os.path.join(self.temp_dir.name, "missing_dep.dlis"),
                dliswriter_module=None,
            )

        self.assertFalse(result["ok"])
        self.assertIn("dliswriter", result["error"])

    def test_unit_normalization_maps_common_log_units(self):
        warnings = []
        self.assertEqual(
            _normalize_unit("API", _FakeDLISWriterModule, warnings, {"name": "GR", "folder": "FRAME0"}),
            "dAPI",
        )
        self.assertEqual(
            _normalize_unit("ohm.m", _FakeDLISWriterModule, warnings, {"name": "RT", "folder": "FRAME1"}),
            "ohm",
        )
        self.assertEqual(
            _normalize_unit("g/cm3", _FakeDLISWriterModule, warnings, {"name": "RHOB", "folder": "FRAME0"}),
            "g",
        )
        self.assertGreaterEqual(len(warnings), 3)

    def test_export_worker_throttles_dense_record_progress(self):
        worker = ExportWorker({}, [], "dummy.dlis")

        self.assertTrue(worker._should_emit_progress({"phase": "writing_records", "current": 1, "total": 1000}))
        self.assertFalse(worker._should_emit_progress({"phase": "writing_records", "current": 2, "total": 1000}))
        self.assertFalse(worker._should_emit_progress({"phase": "writing_records", "current": 50, "total": 1000}))
        self.assertTrue(worker._should_emit_progress({"phase": "writing_records", "current": 101, "total": 1000}))
        self.assertTrue(worker._should_emit_progress({"phase": "writing_records", "current": 1000, "total": 1000}))


if __name__ == "__main__":
    unittest.main()
