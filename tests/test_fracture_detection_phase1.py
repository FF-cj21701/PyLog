import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialogButtonBox

from plugins.ai_assistant.ai_core.config import AIConfig
from plugins.ai_assistant.services.fracture_detection_service import (
    FractureDetectionManager,
    FractureDetectionRequest,
)
from plugins.ai_assistant.tools.fracture_detection_tool import (
    CancelFractureDetectionTool,
    ExportFractureDetectionDebugTool,
    GetBoreholeImageMetadataTool,
    GetFractureDetectionStatusTool,
    StartFractureDetectionTool,
)
from scripts.rendering.plot_widget import LogWidget
from scripts.data.export_manager import PlotAnalysisRenderer
from scripts.rendering.plot_components import PainterDepthTrack


class MemorySettings:
    def __init__(self):
        self.values = {}

    def value(self, key, default=None):
        return self.values.get(key, default)

    def setValue(self, key, value):
        self.values[key] = value


def wait_for_terminal(manager, run_id, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.get_status(run_id)
        if status["status"] in {"completed", "cancelled", "failed"}:
            return status
        time.sleep(0.01)
    raise AssertionError("fracture detection run did not finish")


def make_request():
    return FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["Track 1", "Track 2"],
        target_image_track="Track 1",
        depth_start=1000,
        depth_end=1002,
        fracture_types=["Conductive", "Bedding", "Conductive"],
    )


def test_detection_request_normalizes_types_and_validates_range():
    request = make_request()

    assert request.fracture_types == ("Conductive", "Bedding")
    assert request.tracks == ("Track 1", "Track 2")
    assert request.target_image_track == "Track 1"
    assert request.min_confidence == pytest.approx(0.60)
    assert request.sliding_window_m == pytest.approx(2.0)
    assert request.pick_entry_level is None
    assert request.fast_mode is False
    with pytest.raises(ValueError, match="depth_start"):
        FractureDetectionRequest.build("Plot", "Track", 2, 1, ["Conductive"])
    with pytest.raises(ValueError, match="unsupported"):
        FractureDetectionRequest.build("Plot", "Track", 1, 2, ["Unknown"])
    with pytest.raises(ValueError, match="target_image_track"):
        FractureDetectionRequest.build(
            window_id="Plot",
            tracks=["Image", "GR"],
            target_image_track="Other",
            depth_start=1,
            depth_end=2,
            fracture_types=["Conductive"],
        )
    with pytest.raises(ValueError, match="sliding_window_m"):
        FractureDetectionRequest.build("Plot", "Track", 1, 2, ["Conductive"], sliding_window_m=0)
    with pytest.raises(ValueError, match="pick_entry_level"):
        FractureDetectionRequest.build("Plot", "Track", 1, 2, ["Conductive"], pick_entry_level="maybe")


def test_ai_pick_setup_dialog_defaults_to_visible_range_and_three_metre_window():
    QApplication.instance() or QApplication([])
    from scripts.ui.dialogs.ai_pick_setup_dialog import AIPickSetupDialog

    dialog = AIPickSetupDialog(1002.25, 1008.75, 1000.0, 1015.0)
    values = dialog.values()

    assert values["depth_start"] == pytest.approx(1002.25)
    assert values["depth_end"] == pytest.approx(1008.75)
    assert values["sliding_window_m"] == pytest.approx(3.0)
    assert values["pick_entry_level"] == "confirmed"
    assert values["fast_mode"] is True
    assert dialog.minimumWidth() == 390
    assert dialog.maximumWidth() == 390
    assert dialog.maximumHeight() > dialog.minimumHeight()
    dialog.entry_level_combo.setCurrentIndex(1)
    assert dialog.values()["pick_entry_level"] == "suspected"
    dialog.fast_mode_check.setChecked(False)
    assert dialog.values()["fast_mode"] is False


def test_ai_pick_setup_depth_can_be_replaced_by_typing():
    QApplication.instance() or QApplication([])
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from scripts.ui.dialogs.ai_pick_setup_dialog import AIPickSetupDialog

    dialog = AIPickSetupDialog(8077.129, 8081.267, 8070.0, 8090.0)
    dialog.depth_end_spin.lineEdit().selectAll()
    QTest.keyClicks(dialog.depth_end_spin.lineEdit(), "8082.5")
    QTest.keyClick(dialog.depth_end_spin.lineEdit(), Qt.Key_Return)

    assert dialog.depth_end_spin.value() == pytest.approx(8082.5)

    dialog.depth_end_spin.lineEdit().selectAll()
    QTest.keyClicks(dialog.depth_end_spin.lineEdit(), "8095")
    QTest.keyClick(dialog.depth_end_spin.lineEdit(), Qt.Key_Return)

    assert dialog.depth_end_spin.value() == pytest.approx(8095.0)
    assert not dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert "between 8070.000 m and 8090.000 m" in dialog.validation_label.text()


def test_detection_request_keeps_legacy_single_track_compatibility():
    request = FractureDetectionRequest.build("Plot", "Image", 1, 2, ["Conductive"])

    assert request.tracks == ("Image",)
    assert request.target_image_track == "Image"


def test_manager_runs_in_background_and_reports_completion():
    manager = FractureDetectionManager()

    def worker(_request, context, _input_payload):
        context.update("detecting", 0.5, "Detecting")
        return [{"id": 1}, {"id": 2}]

    manager.set_worker(worker)
    started = manager.start(make_request())
    finished = wait_for_terminal(manager, started["run_id"])

    assert finished["status"] == "completed"
    assert finished["progress"] == 1.0
    assert finished["result_count"] == 2


def test_manager_failure_exposes_concise_error_in_monitor_event():
    manager = FractureDetectionManager()

    def worker(_request, _context, _input_payload):
        raise RuntimeError("Only the default (1) value is supported for temperature")

    started = manager.start(make_request(), worker=worker)
    finished = wait_for_terminal(manager, started["run_id"])

    assert finished["status"] == "failed"
    assert "default (1)" in finished["message"]
    assert "default (1)" in finished["error"]
    events = manager.get_monitor_snapshot(started["run_id"])["events"]
    assert events[-1]["status"] == "failed"
    assert "default (1)" in events[-1]["reason"]


def test_manager_can_defer_completion_until_gui_playback_finishes():
    manager = FractureDetectionManager()
    handed_off = threading.Event()

    def worker(_request, context, _input_payload):
        context.defer_completion()
        context.update("playback", 0.8, "Playing points")
        handed_off.set()
        return [{"id": 1}]

    started = manager.start(make_request(), worker=worker)
    assert handed_off.wait(0.5)
    time.sleep(0.02)
    running = manager.get_status(started["run_id"])
    assert running["status"] == "running"
    assert running["stage"] == "playback"

    manager.update_playback(
        started["run_id"],
        current_fracture_index=1,
        total_fractures=2,
        current_point_index=3,
        total_points=6,
        correction_round=1,
        review_action_count=3,
        review_view_count=2,
        review_view_id="review-F1-r1-v2",
        applied_count=0,
        needs_review_count=0,
        staged_count=1,
        discarded_count=1,
        audit_stage="auditing",
        audit_action_count=4,
        audit_view_count=2,
        audit_view_id="audit-v2",
    )
    manager.complete(started["run_id"], 1)
    finished = manager.get_status(started["run_id"])

    assert finished["status"] == "completed"
    assert finished["current_fracture_index"] == 1
    assert finished["current_point_index"] == 3
    assert finished["correction_round"] == 1
    assert finished["review_action_count"] == 3
    assert finished["review_view_count"] == 2
    assert finished["review_view_id"] == "review-F1-r1-v2"
    assert finished["staged_count"] == 1
    assert finished["discarded_count"] == 1
    assert finished["audit_stage"] == "auditing"
    assert finished["audit_action_count"] == 4
    assert finished["audit_view_count"] == 2
    assert finished["audit_view_id"] == "audit-v2"


def test_manager_cancels_running_worker_cooperatively():
    manager = FractureDetectionManager()
    entered = threading.Event()

    def worker(_request, context, _input_payload):
        entered.set()
        while not context.cancelled:
            time.sleep(0.005)
        return []

    manager.set_worker(worker)
    started = manager.start(make_request())
    assert entered.wait(0.5)
    manager.cancel(started["run_id"])
    finished = wait_for_terminal(manager, started["run_id"])

    assert finished["status"] == "cancelled"
    assert finished["cancel_requested"] is True


def test_manager_refuses_start_before_pipeline_is_installed():
    manager = FractureDetectionManager()

    with pytest.raises(RuntimeError, match="pipeline is not available"):
        manager.start(make_request())


def test_manager_exports_exact_analysis_input_and_coordinate_diagnostics(tmp_path):
    manager = FractureDetectionManager()

    def worker(_request, context, _input_payload):
        context.set_diagnostics({"raw_candidates": [{"points": [{"x_norm": 0.5, "y_norm": 0.25}]}]})
        context.set_view_payload("view-001", {
            "data_url": "data:image/png;base64,iVBORw0KGgo=",
            "overlay_data_url": "data:image/png;base64,iVBORw0KGgo=",
            "metadata": {"depth_start": 1000.0, "depth_end": 1001.0},
        })
        context.update_exploration(action_count=2, view_count=2, candidate_count=1)
        context.set_candidate_payload("F1", {
            "data_url": "data:image/png;base64,iVBORw0KGgo=",
            "overlay_data_url": "data:image/png;base64,iVBORw0KGgo=",
            "metadata": {"depth_start": 1000.25, "depth_end": 1001.25},
        })
        context.set_monitor_media("final_overlay", {
            "data_url": "data:image/png;base64,iVBORw0KGgo=",
            "metadata": {"depth_start": 1000.0, "depth_end": 1002.0},
        })
        return [{"id": 1}]

    started = manager.start(
        make_request(),
        input_payload={
            "data_url": "data:image/png;base64,iVBORw0KGgo=",
            "metadata": {"plot_top": 100, "plot_bottom": 1200, "depth_start": 1000, "depth_end": 1002},
        },
        worker=worker,
    )
    wait_for_terminal(manager, started["run_id"])

    bundle = manager.export_debug_bundle(started["run_id"], root_directory=tmp_path)
    report = json.loads(Path(bundle["report_path"]).read_text(encoding="utf-8"))

    assert Path(bundle["image_path"]).read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert report["diagnostics"]["raw_candidates"][0]["points"][0]["y_norm"] == pytest.approx(0.25)
    assert report["render_metadata"]["depth_end"] == 1002
    assert len(bundle["candidate_image_paths"]) == 1
    assert len(bundle["candidate_overlay_image_paths"]) == 1
    assert len(bundle["view_image_paths"]) == 1
    assert len(bundle["view_overlay_image_paths"]) == 1
    assert len(bundle["monitor_image_paths"]) >= 1
    assert Path(bundle["candidate_image_paths"][0]).read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert Path(bundle["candidate_overlay_image_paths"][0]).read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert Path(bundle["view_image_paths"][0]).read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert Path(bundle["view_overlay_image_paths"][0]).read_bytes() == b"\x89PNG\r\n\x1a\n"
    assert report["candidate_inputs"][0]["metadata"]["depth_start"] == pytest.approx(1000.25)
    assert Path(report["candidate_inputs"][0]["overlay_image_path"]).exists()
    assert report["exploration_views"][0]["metadata"]["depth_end"] == pytest.approx(1001.0)
    assert Path(report["exploration_views"][0]["overlay_image_path"]).exists()
    final_overlay = next(item for item in report["monitor_media"] if item["slot"] == "final_overlay")
    assert Path(final_overlay["image_path"]).exists()
    assert final_overlay["metadata"]["depth_end"] == pytest.approx(1002.0)
    assert report["exploration_action_count"] == 2


def test_vision_config_is_independent_and_clamped():
    config = object.__new__(AIConfig)
    config.settings = MemorySettings()

    defaults = config.get_vision_config()
    assert defaults["provider"] == "OpenAI"
    assert defaults["use_current_profile"] is True
    assert defaults["model"] == ""
    assert defaults["concurrency"] == 2

    config.set_vision_config({
        "use_current_profile": False,
        "provider": "Custom / Other",
        "api_key": " vision-key ",
        "base_url": "https://vision.example/v1",
        "model": "vision-model",
        "timeout_seconds": 999,
        "concurrency": 20,
    })
    saved = config.get_vision_config()

    assert saved["api_key"] == "vision-key"
    assert saved["timeout_seconds"] == 600
    assert saved["concurrency"] == 8
    assert config.is_vision_configured() is True


def test_vision_config_inherits_current_profile_with_optional_model_override():
    config = object.__new__(AIConfig)
    config.settings = MemorySettings()
    config.set_profiles([{
        "name": "Current",
        "provider": "OpenAI",
        "api_key": "chat-key",
        "base_url": "https://api.openai.com/v1",
        "model": "profile-model",
    }])
    config.set_current_profile_name("Current")

    inherited = config.get_resolved_vision_config()
    assert inherited["api_key"] == "chat-key"
    assert inherited["model"] == "profile-model"

    config.set_vision_config({"use_current_profile": True, "model": "vision-override"})
    overridden = config.get_resolved_vision_config()
    assert overridden["api_key"] == "chat-key"
    assert overridden["model"] == "vision-override"


def test_incomplete_independent_vision_config_falls_back_to_current_chat_profile():
    config = object.__new__(AIConfig)
    config.settings = MemorySettings()
    config.set_profiles([{
        "name": "Current",
        "provider": "OpenAI",
        "api_key": "chat-key",
        "base_url": "https://chat.example/v1",
        "model": "vision-capable-chat-model",
    }])
    config.set_current_profile_name("Current")
    config.set_vision_config({
        "use_current_profile": False,
        "api_key": "",
        "model": "",
    })

    resolved = config.get_resolved_vision_config()

    assert resolved["api_key"] == "chat-key"
    assert resolved["base_url"] == "https://chat.example/v1"
    assert resolved["model"] == "vision-capable-chat-model"
    assert config.is_vision_configured() is True


def test_plot_details_exposes_image_metadata_without_raw_data():
    image_curve = {
        "is_image": True,
        "data": SimpleNamespace(shape=(4, 8)),
        "depth": [1000.0, 1000.5, 1001.0, 1001.5],
        "info": {"name": "QGEO_RES_DYN", "unit": "ohm.m", "min": 0, "max": 260},
    }
    track = SimpleNamespace(
        track_name="Track 1",
        plot_widget=SimpleNamespace(curves=[image_curve]),
    )
    widget = SimpleNamespace(
        windowTitle=lambda: "Log Plot 1",
        fracture_borehole_diameter_in=8.0,
        collect_fracture_annotations=lambda: [{"id": "f1"}],
        get_master_viewbox=lambda: SimpleNamespace(viewRange=lambda: [[0, 360], [1000.2, 1001.2]]),
        track_containers=[track],
    )

    details = LogWidget.get_plot_details(widget)
    curve = details["tracks"][0]["curves"][0]

    assert details["visible_depth_range"] == [1000.2, 1001.2]
    assert details["existing_fracture_count"] == 1
    assert curve["is_image"] is True
    assert curve["shape"] == [4, 8]
    assert "data" not in curve


def test_phase1_tools_publish_stable_interfaces():
    assert GetBoreholeImageMetadataTool().spec.get_required_args() == ["window_id"]
    assert StartFractureDetectionTool().spec.get_required_args() == [
        "window_id", "tracks", "depth_start", "depth_end", "fracture_types"
    ]
    assert GetFractureDetectionStatusTool().spec.get_required_args() == ["run_id"]
    assert ExportFractureDetectionDebugTool().spec.get_required_args() == ["run_id"]
    assert CancelFractureDetectionTool().spec.get_required_args() == ["run_id"]


def test_fracture_panel_ai_pick_uses_all_types_and_visible_depth(monkeypatch):
    import plugins.ai_assistant.services.fracture_detection_service as detection_service
    import plugins.ai_assistant.services.fracture_vision_service as vision_service

    captured = {}

    class Manager:
        def start(self, request, input_payload=None, worker=None):
            captured["request"] = request
            captured["input_payload"] = input_payload
            captured["worker"] = worker
            return {"run_id": "panel-run"}

    class Timer:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    manager = Manager()
    monkeypatch.setattr(detection_service, "get_fracture_detection_manager", lambda: manager)
    monkeypatch.setattr(vision_service, "FractureVisionPipeline", lambda: SimpleNamespace(detect=lambda *_args: []))

    target = object()
    timer = Timer()
    panel_states = []
    render_calls = []
    widget = SimpleNamespace(
        _fracture_detection_run_id=None,
        _fracture_detection_timer=timer,
        fracture_target_track=target,
        fracture_pick_type="Bedding",
        fracture_borehole_diameter_in=8.5,
        aiFractureResultsReady=SimpleNamespace(emit=lambda *_args: None),
        _image_tracks_for_fracture_display=lambda: [target],
        get_fracture_display_track=lambda: target,
        get_master_viewbox=lambda: SimpleNamespace(viewRange=lambda: [[0, 360], [1001.25, 1004.75]]),
        _fracture_track_label=lambda _track: "Track 1 / IMAGE",
        windowTitle=lambda: "Log Plot 1",
        _set_ai_fracture_panel_state=lambda running, status="": panel_states.append((running, status)),
        _show_fracture_status=lambda _message: None,
        render_analysis_tracks=lambda *args, **kwargs: (
            render_calls.append((args, kwargs))
            or {"png_bytes": b"png", "metadata": {"depth_start": 1001.25, "depth_end": 1004.75}}
        ),
    )

    run = LogWidget.start_ai_fracture_detection(widget)

    assert run["run_id"] == "panel-run"
    assert widget._fracture_detection_run_id == "panel-run"
    assert timer.started is True
    assert captured["request"].tracks == ("Track 1 / IMAGE",)
    assert captured["request"].target_image_track == "Track 1 / IMAGE"
    assert captured["request"].fracture_types == ("Conductive", "Resistive")
    assert captured["request"].depth_start == pytest.approx(1001.25)
    assert captured["request"].depth_end == pytest.approx(1004.75)
    assert captured["request"].pick_entry_level == "confirmed"
    assert captured["request"].fast_mode is True
    assert captured["request"].borehole_diameter_in == pytest.approx(8.5)
    assert render_calls[0][1]["respect_current_vertical_scale"] is True
    assert panel_states[-1] == (True, "AI: queued")


def test_fracture_panel_ai_playback_uses_detected_type_colors(monkeypatch):
    import plugins.ai_assistant.services.fracture_detection_service as detection_service

    captured = {}
    target = SimpleNamespace(track_name="Track 1")
    scheduler = SimpleNamespace(
        active=False,
        start=lambda *args, **kwargs: captured.update(
            candidates=args[2],
            scheduler_kwargs=kwargs,
        ),
    )
    manager = SimpleNamespace(
        get_status=lambda _run_id: {"diagnostics": {}},
        update_playback=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(detection_service, "get_fracture_detection_manager", lambda: manager)
    widget = SimpleNamespace(
        _fracture_playback_scheduler=scheduler,
        _fracture_detection_run_id=None,
        track_containers=[target],
        _image_tracks_for_fracture_display=lambda: [target],
        _fracture_track_label=lambda _track: "Track 1 / IMAGE",
        set_active_fracture_track=lambda _track: None,
        _set_ai_fracture_panel_state=lambda *_args: None,
    )

    result = LogWidget.start_ai_fracture_playback(
        widget,
        "run-type-colors",
        "Track 1 / IMAGE",
        [
            {"type": "sinusoidal_fracture", "fracture_type": "Conductive", "color": "#FF2D2D"},
            {"type": "sinusoidal_fracture", "fracture_type": "Resistive", "color": "#0099CC"},
        ],
    )

    assert result == {"ok": True, "queued_count": 2}
    assert captured["candidates"][0]["fracture_type"] == "Conductive"
    assert captured["candidates"][0]["color"] == "#0099CC"
    assert captured["candidates"][1]["fracture_type"] == "Resistive"
    assert captured["candidates"][1]["color"] == "#FF2D2D"


def test_settings_page_contains_independent_vision_fields():
    template = open("plugins/ai_assistant/ui/resources/settings_template.html", encoding="utf-8").read()
    script = open("plugins/ai_assistant/ui/resources/settings_page.js", encoding="utf-8").read()

    assert 'id="vision-api-key-input"' in template
    assert 'id="vision-model-input"' in template
    assert 'id="vision-use-current-input"' in template
    assert "syncVisionFromInputs" in script
    assert "effectiveVisionProfile" in script
    assert "vision: state.vision" in script


def test_analysis_renderer_preserves_plot_order_and_pixel_mapping():
    QApplication.instance() or QApplication([])

    class Header:
        items = []

        def adjust_height(self):
            pass

        def height(self):
            return 80

    class Track:
        def __init__(self, name, width, color, is_image=False):
            self.track_name = name
            self._width = width
            self.color = QColor(color)
            self.header = Header()
            self.calls = []
            self.plot_widget = SimpleNamespace(curves=[{
                "is_image": is_image,
                "info": {"name": f"{name} Curve", "unit": "unit", "min": 0, "max": 100},
            }])

        def width(self):
            return self._width

        def render_to(self, painter, rect, min_y, max_y, **kwargs):
            self.calls.append((rect, min_y, max_y, kwargs))
            painter.fillRect(rect, self.color)

    first = Track("GR", 100, "#ff0000")
    image = Track("Image", 300, "#0000ff", is_image=True)
    widget = SimpleNamespace(track_containers=[first, image], scale_control=None)

    rendered = PlotAnalysisRenderer(widget).render(["Image", "GR"], 1000, 1004, width=800, height=600)
    metadata = rendered["metadata"]

    assert [track["name"] for track in metadata["tracks"]] == ["GR", "Image"]
    assert [track["pixel_width"] for track in metadata["tracks"]] == [200, 600]
    assert metadata["tracks"][0]["pixel_left"] == 0
    assert metadata["tracks"][1]["pixel_right"] == 800
    assert metadata["depth_start"] == 1000
    assert metadata["depth_end"] == 1004
    assert rendered["png_bytes"].startswith(b"\x89PNG")
    assert first.calls[0][1:3] == (1000.0, 1004.0)


def test_analysis_renderer_auto_includes_depth_track_and_preserves_source_aspect():
    QApplication.instance() or QApplication([])

    class Header:
        items = []

        def adjust_height(self):
            pass

        def height(self):
            return 80

    class Track:
        def __init__(self, name, width, plot_widget):
            self.track_name = name
            self._width = width
            self.header = Header()
            self.plot_widget = plot_widget

        def width(self):
            return self._width

        def height(self):
            return 900

        def render_to(self, painter, rect, _min_y, _max_y, **_kwargs):
            painter.fillRect(rect, QColor("#ffffff"))

    depth_widget = PainterDepthTrack()
    depth = Track("Depth", 80, depth_widget)
    image_widget = SimpleNamespace(curves=[{
        "is_image": True,
        "info": {"name": "IMAGE", "unit": "ohm.m", "min": 0, "max": 260},
    }])
    image = Track("Image", 320, image_widget)
    widget = SimpleNamespace(track_containers=[depth, image], scale_control=None)

    rendered = PlotAnalysisRenderer(widget).render(
        ["Image"],
        8074,
        8077,
        width=1600,
        height=1600,
        include_depth_track=True,
        preserve_aspect=True,
    )
    metadata = rendered["metadata"]

    assert [track["name"] for track in metadata["tracks"]] == ["Depth", "Image"]
    assert metadata["auto_included_depth_tracks"] == ["Depth"]
    assert metadata["preserve_aspect"] is True
    assert metadata["width"] == 711
    assert metadata["height"] == 1600
    assert metadata["render_scale"] == pytest.approx(711 / 400)


def test_analysis_renderer_respects_current_vertical_scale_for_requested_depth_crop():
    QApplication.instance() or QApplication([])

    class Header:
        items = []

        def adjust_height(self):
            pass

        def height(self):
            return 80

    class Track:
        def __init__(self, name, width):
            self.track_name = name
            self._width = width
            self.header = Header()
            self.plot_widget = SimpleNamespace(curves=[])

        def width(self):
            return self._width

        def height(self):
            return 900

        def render_to(self, painter, rect, _min_y, _max_y, **_kwargs):
            painter.fillRect(rect, QColor("#ffffff"))

    viewbox = SimpleNamespace(viewRange=lambda: [[0, 1], [1000, 1010]])
    widget = SimpleNamespace(
        track_containers=[Track("Depth", 80), Track("Image", 320)],
        scale_control=None,
        get_master_viewbox=lambda: viewbox,
    )

    rendered = PlotAnalysisRenderer(widget).render(
        ["Depth", "Image"],
        1002,
        1005,
        width=1600,
        height=1600,
        preserve_aspect=True,
        respect_current_vertical_scale=True,
    )
    metadata = rendered["metadata"]

    assert metadata["source_height"] == 900
    assert metadata["effective_source_height"] == pytest.approx(326)
    assert metadata["current_visible_depth_range"] == [1000.0, 1010.0]
    assert metadata["vertical_scale_applied"] is True
    assert metadata["width"] == 1600
    assert metadata["height"] == 1304
    assert metadata["output_dpi"] == pytest.approx(384)
    assert rendered["image"].dotsPerMeterY() == pytest.approx(384 / 0.0254, abs=1)


def test_analysis_renderer_vertical_scale_rerenders_data_without_narrowing_tracks():
    QApplication.instance() or QApplication([])

    class Header:
        items = []

        def adjust_height(self):
            pass

        def height(self):
            return 80

    class Track:
        def __init__(self, name, width):
            self.track_name = name
            self._width = width
            self.header = Header()
            self.plot_widget = SimpleNamespace(curves=[])

        def width(self):
            return self._width

        def height(self):
            return 900

        def render_to(self, painter, rect, _min_y, _max_y, **_kwargs):
            painter.fillRect(rect, QColor("#ffffff"))

    widget = SimpleNamespace(
        track_containers=[Track("Depth", 80), Track("Image", 320)],
        scale_control=None,
        get_master_viewbox=lambda: SimpleNamespace(viewRange=lambda: [[0, 1], [1000, 1010]]),
    )
    rendered = PlotAnalysisRenderer(widget).render(
        ["Depth", "Image"],
        1002,
        1005,
        width=1600,
        height=3000,
        preserve_aspect=True,
        respect_current_vertical_scale=True,
        vertical_scale=2.0,
    )

    metadata = rendered["metadata"]
    assert metadata["width"] == 1600
    assert metadata["height"] == 2288
    assert metadata["vertical_scale"] == pytest.approx(2.0)
    assert metadata["actual_vertical_scale"] == pytest.approx(2.0)
    assert [track["pixel_width"] for track in metadata["tracks"]] == [320, 1280]
