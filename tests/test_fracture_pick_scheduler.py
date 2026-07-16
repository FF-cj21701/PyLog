import time

from PySide6.QtWidgets import QApplication

from scripts.rendering.fracture_pick_scheduler import FracturePickPlaybackScheduler


class DummyTrack:
    def __init__(self):
        self.session = None
        self.begin_calls = 0
        self.points = []
        self.metadata = {}
        self.committed = []
        self.staged = []

    def begin_programmatic_fracture_pick(self, session_id, fracture_type, metadata=None):
        self.begin_calls += 1
        self.session = session_id
        self.fracture_type = fracture_type
        self.metadata = dict(metadata or {})
        self.points = []
        return True

    def append_programmatic_fracture_point(self, session_id, azimuth, depth):
        if session_id != self.session:
            return False
        self.points.append([azimuth, depth])
        return True

    def cancel_programmatic_fracture_pick(self, session_id=None):
        if session_id is not None and session_id != self.session:
            return False
        self.session = None
        self.points = []
        return True

    def update_programmatic_fracture_metadata(self, session_id, metadata):
        if session_id != self.session:
            return False
        self.metadata.update(dict(metadata or {}))
        return True

    def commit_programmatic_fracture_pick(self, session_id):
        if session_id != self.session:
            return None
        result = {
            "fracture_type": self.fracture_type,
            "points": [list(point) for point in self.points],
            **self.metadata,
        }
        self.committed.append(result)
        self.session = None
        self.points = []
        return result

    def stage_programmatic_fracture_pick(self, session_id):
        if session_id != self.session:
            return None
        result = {
            "type": "sinusoidal_fracture",
            "fracture_type": self.fracture_type,
            "points": [list(point) for point in self.points],
            **self.metadata,
        }
        self.staged.append(result)
        self.session = None
        self.points = []
        return result

    def set_ai_staged_fractures(self, annotations):
        self.staged = [dict(item) for item in annotations]
        return self.staged

    def clear_ai_staged_fractures(self):
        self.staged = []

    def commit_ai_staged_fractures(self, annotations=None):
        selected = [dict(item) for item in (annotations if annotations is not None else self.staged)]
        self.committed.extend(selected)
        self.staged = []
        return selected


def wait_until(predicate, timeout=1.0):
    app = QApplication.instance() or QApplication([])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("condition was not reached")


def candidate(points=None):
    return {
        "type": "sinusoidal_fracture",
        "fracture_type": "Conductive",
        "color": "#0099CC",
        "points": points or [[0, 1000.0], [90, 1000.2], [180, 1000.0]],
        "confidence": 0.9,
        "ai_generated": True,
        "detection_run_id": "run-1",
    }


def test_scheduler_atomically_stages_and_commits_candidate_without_point_replay():
    app = QApplication.instance() or QApplication([])
    track = DummyTrack()
    scheduler = FracturePickPlaybackScheduler(interval_ms=1)
    finished = []
    scheduler.finished.connect(lambda *args: finished.append(args))

    scheduler.start(
        "run-1",
        track,
        [candidate()],
    )
    wait_until(lambda: bool(finished))

    assert finished == [("run-1", 1, 0, 0)]
    assert track.committed[0]["points"] == [[0.0, 1000.0], [90.0, 1000.2], [180.0, 1000.0]]
    assert track.committed[0]["color"] == "#0099CC"
    assert track.committed[0]["ai_correction_rounds"] == 0
    assert track.begin_calls == 0
    app.processEvents()


def test_scheduler_reports_backend_and_invalid_gui_candidate_discards():
    track = DummyTrack()
    scheduler = FracturePickPlaybackScheduler(interval_ms=1)
    finished = []
    scheduler.finished.connect(lambda *args: finished.append(args))
    scheduler.start(
        "run-2",
        track,
        [candidate(points=[[0, 1000.0], [180, 1000.1]])],
        initial_discarded_count=2,
    )
    wait_until(lambda: bool(finished))

    assert finished == [("run-2", 0, 0, 3)]
    assert track.committed == []
    assert track.staged == []


def test_scheduler_cancel_before_gui_commit_preserves_existing_candidates():
    track = DummyTrack()
    track.committed = [{"candidate_id": "existing"}]
    scheduler = FracturePickPlaybackScheduler(interval_ms=1000)
    cancelled = []
    scheduler.cancelled.connect(lambda *args: cancelled.append(args))
    scheduler.start("run-3", track, [candidate()])

    assert scheduler.cancel() is True
    assert cancelled == [("run-3", 0)]
    assert track.points == []
    assert track.committed == [{"candidate_id": "existing"}]


def test_scheduler_observes_external_agent_cancellation_during_playback():
    track = DummyTrack()
    scheduler = FracturePickPlaybackScheduler(interval_ms=1000)
    cancellation = {"requested": False}
    cancelled = []
    scheduler.cancelled.connect(lambda *args: cancelled.append(args))

    scheduler.start(
        "run-4",
        track,
        [candidate()],
        cancel_requested=lambda: cancellation["requested"],
    )
    cancellation["requested"] = True
    scheduler._check_cancel_requested()

    assert cancelled == [("run-4", 0)]
    assert track.committed == []
