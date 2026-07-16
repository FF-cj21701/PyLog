import time
from types import SimpleNamespace

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from plugins.ai_assistant.services.fracture_detection_service import (
    FractureDetectionManager,
    FractureDetectionRequest,
)
from scripts.ui.dialogs.ai_pick_monitor_dialog import AIPickMonitorDialog


def _request():
    return FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000.0,
        depth_end=1002.0,
        fracture_types=["Conductive"],
    )


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("condition was not reached")


def test_detection_manager_exposes_thread_safe_monitor_history_and_media():
    manager = FractureDetectionManager()
    payload = {"data_url": "data:image/png;base64,AA==", "metadata": {"depth_start": 1000.0}}

    def worker(_request, context, _input):
        context.record_event("exploring", "inspect_view", "zoom requested", status="accepted")
        context.set_monitor_media(
            "overlay",
            payload,
            parameters={"center_depth_m": 1001.0, "amplitude_m": 0.2, "phase_deg": 45.0},
        )
        return []

    run = manager.start(_request(), input_payload=payload, worker=worker)
    _wait_for(lambda: manager.get_status(run["run_id"])["status"] == "completed")
    snapshot = manager.get_monitor_snapshot(run["run_id"])

    assert any(event["action"] == "inspect_view" for event in snapshot["events"])
    assert snapshot["monitor"]["media"]["input_view"] == payload
    assert snapshot["monitor"]["media"]["overlay"] == payload
    assert snapshot["monitor"]["parameters"]["center_depth_m"] == 1001.0
    assert snapshot["run"]["status"] == "completed"


def test_monitor_close_only_hides_and_stop_uses_plot_cancel(monkeypatch):
    app = QApplication.instance() or QApplication([])
    cancelled = []
    snapshot = {
        "run": {"status": "running", "stage": "reviewing"},
        "events": [{
            "timestamp": "2026-07-15T10:00:00+00:00",
            "stage": "reviewing",
            "action": "inspect_view",
            "status": "accepted",
            "reason": "A long review reason that must wrap across multiple lines instead of being elided by the timeline column width. " * 3,
        }],
        "monitor": {"media": {}, "api_status": "reviewing"},
        "diagnostics": {},
    }
    fake_manager = SimpleNamespace(get_monitor_snapshot=lambda _run_id: snapshot)
    monkeypatch.setattr(
        "plugins.ai_assistant.services.fracture_detection_service.get_fracture_detection_manager",
        lambda: fake_manager,
    )
    log_widget = SimpleNamespace(cancel_ai_fracture_detection=lambda: cancelled.append(True))
    dialog = AIPickMonitorDialog(log_widget)
    shown = []
    monkeypatch.setattr(dialog, "show", lambda: shown.append("show"))
    monkeypatch.setattr(dialog, "raise_", lambda: shown.append("raise"))
    monkeypatch.setattr(dialog, "activateWindow", lambda: shown.append("activate"))

    dialog.show_for_run("run-1")
    assert shown == ["show", "raise", "activate"]
    timeline_item = dialog.timeline.topLevelItem(0)
    assert timeline_item.sizeHint(4).height() > dialog.timeline.fontMetrics().height()
    close_event = QCloseEvent()
    dialog.closeEvent(close_event)
    assert not close_event.isAccepted()
    assert dialog.run_id == "run-1"

    dialog._stop_ai()
    assert cancelled == [True]
    dialog._timer.stop()
    dialog.deleteLater()
