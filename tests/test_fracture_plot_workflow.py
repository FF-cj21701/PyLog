import os
import tempfile
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from scripts.data.db_manager import DBManager
from scripts.rendering.fracture_annotations import build_fracture_annotation
from scripts.rendering.plot_widget import LogWidget
from scripts.ui.data_tree import CustomTreeWidget
from scripts.ui.ui_components import FracturePickingPanel


def test_panel_host_reads_expanded_and_collapsed_sizes_from_qml_root():
    values = {
        "expandedWidth": 440,
        "collapsedWidth": 106,
        "panelHeight": 504,
    }
    root = SimpleNamespace(property=lambda name: values[name])
    panel = SimpleNamespace(rootObject=lambda: root)

    assert FracturePickingPanel._qml_panel_size(panel, collapsed=False) == (440, 504)
    assert FracturePickingPanel._qml_panel_size(panel, collapsed=True) == (106, 504)


def test_fracture_panel_qml_exposes_ai_pick_action_and_status():
    qml_path = os.path.join("scripts", "ui", "qml", "FracturePickingPanel.qml")
    qml = open(qml_path, encoding="utf-8").read()

    assert "bridge.autoDetectionButtonText" in qml
    assert "bridge.toggleAutoDetection()" in qml
    assert "bridge.autoDetectionStatus" in qml
    assert 'label: "AI Test"' not in qml
    assert "bridge.runDirectAiTest()" not in qml


def test_borehole_diameter_converts_from_inches_to_depth_unit():
    widget = SimpleNamespace(fracture_borehole_diameter_in=8.0)

    assert LogWidget._fracture_borehole_diameter_for_depth_unit(widget, "m") == pytest.approx(0.2032)
    assert LogWidget._fracture_borehole_diameter_for_depth_unit(widget, "ft") == pytest.approx(2.0 / 3.0)
    assert LogWidget._fracture_borehole_diameter_for_depth_unit(widget, "in") == pytest.approx(8.0)
    assert LogWidget._fracture_borehole_diameter_for_depth_unit(widget, "") is None


def test_saving_empty_plot_results_clears_persisted_results_and_refreshes_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "fractures.db")
        db = DBManager(db_path)
        well_id = db.save_well("DemoWell")
        annotation = build_fracture_annotation(
            [[0, 1000.0], [90, 1000.1], [180, 1000.2]],
        )
        db.save_fracture_interpretations(well_id, [annotation])

        events = []
        widget = SimpleNamespace(
            _fracture_results_dirty=True,
            collect_fracture_annotations=lambda: [],
            _infer_fracture_well_id=lambda annotations=None: well_id,
            _infer_fracture_db_path=lambda annotations=None: db_path,
            set_db_source=lambda path: events.append(("db", path)),
            _show_fracture_status=lambda message: events.append(("status", message)),
            _refresh_fracture_tables=lambda path, selected_well_id: events.append(
                ("refresh", path, selected_well_id)
            ),
        )

        inserted = LogWidget.save_fracture_results(widget)

        assert inserted == []
        assert db.get_fracture_interpretations(well_id) == []
        assert ("refresh", db_path, well_id) in events
        assert any(
            event[0] == "status" and "Cleared saved fracture results" in event[1]
            for event in events
        )


def test_saving_untouched_empty_plot_does_not_clear_persisted_results():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "fractures.db")
        db = DBManager(db_path)
        well_id = db.save_well("DemoWell")
        annotation = build_fracture_annotation(
            [[0, 1000.0], [90, 1000.1], [180, 1000.2]],
        )
        db.save_fracture_interpretations(well_id, [annotation])

        events = []
        widget = SimpleNamespace(
            _fracture_results_dirty=False,
            collect_fracture_annotations=lambda: [],
            _infer_fracture_well_id=lambda annotations=None: well_id,
            _infer_fracture_db_path=lambda annotations=None: db_path,
            _show_fracture_status=lambda message: events.append(message),
        )

        inserted = LogWidget.save_fracture_results(widget)

        assert inserted == []
        assert len(db.get_fracture_interpretations(well_id)) == 1
        assert events == ["No fracture results to save."]


def test_fracture_table_tree_item_exports_drag_mime():
    QApplication.instance() or QApplication([])
    tree = CustomTreeWidget()
    item = QTreeWidgetItem()
    item.setData(0, Qt.UserRole, {
        "type": "fracture_table",
        "name": "Fracture Picks",
        "well_id": 7,
        "db_path": "demo.db",
    })

    mime = tree.mimeData([item])

    assert mime.hasFormat("application/x-pylog-fracture-table")
    payload = bytes(mime.data("application/x-pylog-fracture-table")).decode("utf-8")
    assert '"type": "fracture_table"' in payload
    assert '"well_id": 7' in payload


def test_apply_fracture_table_results_draws_sinusoids_and_tadpoles():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "fractures.db")
        db = DBManager(db_path)
        well_id = db.save_well("DemoWell")
        annotation = build_fracture_annotation(
            [[0, 1000.0], [90, 1000.15], [180, 1000.0]],
            fracture_type="Resistive",
        )
        db.save_fracture_interpretations(well_id, [annotation])

        events = []

        class FakeImageTrack:
            def __init__(self):
                self.track_name = "Image Track"
                self.plot_widget = SimpleNamespace(curves=[{
                    "is_image": True,
                    "info": {"name": "FMI"},
                }])
                self.fracture_annotations = [{"type": "sinusoidal_fracture", "name": "Old"}]

            def clear_fracture_annotations(self):
                self.fracture_annotations.clear()
                events.append("clear")

            def add_fracture_annotation(self, item):
                self.fracture_annotations.append(item)
                events.append(("add", item.get("fracture_type"), item.get("color")))

        track = FakeImageTrack()
        widget = SimpleNamespace(
            track_containers=[track],
            fracture_target_track=None,
            _image_tracks_for_fracture_display=lambda: [track],
            get_fracture_display_track=lambda: track,
            refresh_fracture_target_tracks=lambda: None,
            _show_fracture_status=lambda message: events.append(("status", message)),
            show_tadpole_track=lambda: events.append("tadpole"),
            refresh_tadpole_tracks=lambda: events.append("refresh_tadpole"),
            _fracture_track_label=lambda item: "Image Track / FMI",
        )

        applied = LogWidget.apply_fracture_table_results(widget, db_path, well_id)

        assert len(applied) == 1
        assert track.fracture_annotations == applied
        assert ("add", "Resistive", "#FF2D2D") in events
        assert "tadpole" in events
        assert widget._fracture_results_dirty is False
