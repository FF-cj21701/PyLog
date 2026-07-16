import os
import tempfile
from types import SimpleNamespace

import pytest

from scripts.data.db_manager import DBManager
from scripts.rendering.fracture_annotations import build_fracture_annotation
from scripts.rendering.plot_widget import LogWidget
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
