from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal


class FracturePickPlaybackScheduler(QObject):
    """Stage audited AI annotations and atomically commit them on the GUI thread."""

    statusChanged = Signal(str, object)
    finished = Signal(str, int, int, int)
    cancelled = Signal(str, int)
    failed = Signal(str, str)
    diagnosticEvent = Signal(str, object)

    def __init__(self, parent=None, interval_ms=120):
        super().__init__(parent)
        # Retained for API compatibility; final candidates are no longer replayed point by point.
        self.interval_ms = int(interval_ms)
        self._guard_timer = QTimer(self)
        self._guard_timer.setInterval(100)
        self._guard_timer.timeout.connect(self._check_cancel_requested)
        self._reset()

    @property
    def active(self):
        return bool(self._run_id)

    @property
    def run_id(self):
        return self._run_id

    def start(
        self,
        run_id,
        target_track,
        candidates,
        target_validator=None,
        cancel_requested=None,
        initial_discarded_count=0,
    ):
        if self.active:
            raise RuntimeError("AI fracture commit is already active")
        self._reset()
        self._run_id = str(run_id)
        self._target_track = target_track
        self._target_validator = target_validator
        self._cancel_requested = cancel_requested
        self._initial_discarded_count = max(0, int(initial_discarded_count))
        self._candidates = [dict(item) for item in (candidates or []) if isinstance(item, dict)]
        self._clear_staged_track_items()
        self._guard_timer.start()
        QTimer.singleShot(0, self._stage_final_candidates)

    def cancel(self):
        if not self.active:
            return False
        run_id = self._run_id
        self._clear_staged_track_items()
        self._reset()
        self.cancelled.emit(run_id, 0)
        return True

    def _reset(self):
        if hasattr(self, "_guard_timer"):
            self._guard_timer.stop()
        self._run_id = None
        self._target_track = None
        self._target_validator = None
        self._cancel_requested = None
        self._candidates = []
        self._staged = []
        self._discarded = []
        self._needs_review_count = 0
        self._initial_discarded_count = 0

    def _check_cancel_requested(self):
        if not self.active or self._cancel_requested is None:
            return
        try:
            requested = bool(self._cancel_requested())
        except Exception:
            requested = False
        if requested:
            self.cancel()

    def _target_is_valid(self):
        if self._target_track is None:
            return False
        if self._target_validator is None:
            return True
        try:
            return bool(self._target_validator(self._target_track))
        except Exception:
            return False

    @staticmethod
    def _clean_points(points):
        clean = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                x = max(0.0, min(360.0, float(point[0])))
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            if x == x and y == y and abs(y) != float("inf"):
                clean.append([x, y])
        return clean

    def _normalize_candidate(self, candidate, index):
        points = self._clean_points(candidate.get("points") or candidate.get("final_points"))
        if candidate.get("type") != "sinusoidal_fracture":
            return None, "unsupported_annotation_type"
        if not candidate.get("fracture_type"):
            return None, "missing_fracture_type"
        if len(points) < 3:
            return None, "insufficient_initial_points"
        clean = dict(candidate)
        clean["points"] = [list(point) for point in points]
        clean["final_points"] = [list(point) for point in points]
        clean.setdefault("initial_points", [list(point) for point in points])
        clean.setdefault("ai_generated", True)
        clean.setdefault("detection_run_id", self._run_id)
        clean.setdefault("ai_correction_rounds", 0)
        clean.setdefault("ai_alignment_status", "pending")
        clean["needs_review"] = bool(clean.get("needs_review", False))
        return clean, None

    def _stage_final_candidates(self):
        if not self.active:
            return
        if not self._target_is_valid():
            self._fail("Target image track is no longer available")
            return

        valid = []
        for index, candidate in enumerate(self._candidates):
            clean, error = self._normalize_candidate(candidate, index)
            if clean is None:
                record = {
                    "candidate_id": candidate.get("candidate_id"),
                    "candidate_index": index,
                    "reason": error,
                    "stage": "gui_staging",
                    "last_points": self._clean_points(candidate.get("points")),
                    "last_parameters": candidate.get("ai_final_parameters"),
                }
                self._discarded.append(record)
                self.diagnosticEvent.emit(self._run_id, {"event": "candidate_discarded", **record})
                continue
            valid.append(clean)

        try:
            staged = self._target_track.set_ai_staged_fractures(valid)
        except Exception as exc:
            self._fail(f"Unable to stage final AI fractures: {exc}")
            return
        self._staged = list(staged or [])
        self._needs_review_count = sum(bool(item.get("needs_review", False)) for item in self._staged)
        for index, annotation in enumerate(self._staged):
            self.diagnosticEvent.emit(self._run_id, {
                "event": "candidate_staged",
                "candidate_index": index,
                "candidate_id": annotation.get("candidate_id"),
                "final_points": [list(point) for point in annotation.get("points", [])],
                "final_parameters": annotation.get("ai_final_parameters"),
                "correction_rounds": int(annotation.get("ai_correction_rounds", 0)),
                "needs_review": bool(annotation.get("needs_review", False)),
            })
        self._emit_progress("staging")
        # Keep cancellation responsive and let Qt paint the already-final preview once before commit.
        QTimer.singleShot(0, self._commit_staged)

    def _commit_staged(self):
        if not self.active:
            return
        if not self._target_is_valid():
            self._fail("Target image track is no longer available")
            return
        self._emit_progress("committing")
        try:
            committed = self._target_track.commit_ai_staged_fractures(list(self._staged))
        except Exception as exc:
            self._fail(f"Unable to commit final AI fractures: {exc}")
            return
        run_id = self._run_id
        applied = len(committed)
        needs_review = sum(bool(item.get("needs_review", False)) for item in committed)
        discarded = self._initial_discarded_count + len(self._discarded)
        self.diagnosticEvent.emit(run_id, {
            "event": "batch_committed",
            "applied_count": applied,
            "needs_review_count": needs_review,
            "discarded_count": discarded,
        })
        self._reset()
        self.finished.emit(run_id, applied, needs_review, discarded)

    def _clear_staged_track_items(self):
        if self._target_track is not None and hasattr(self._target_track, "clear_ai_staged_fractures"):
            try:
                self._target_track.clear_ai_staged_fractures()
            except Exception:
                pass

    def _emit_progress(self, stage):
        total = len(self._candidates)
        details = {
            "stage": stage,
            "current_fracture_index": total if self._staged else 0,
            "total_fractures": total,
            "current_point_index": 0,
            "total_points": 0,
            "correction_round": 0,
            "staged_count": len(self._staged),
            "discarded_count": self._initial_discarded_count + len(self._discarded),
            "applied_count": 0,
            "needs_review_count": self._needs_review_count,
            "audit_stage": "completed",
            "message": (
                "AI: committing final fractures"
                if stage == "committing"
                else f"AI: prepared {len(self._staged)} final fracture(s)"
            ),
        }
        self.statusChanged.emit(self._run_id, details)

    def _fail(self, message):
        if not self.active:
            return
        run_id = self._run_id
        self._clear_staged_track_items()
        self._reset()
        self.failed.emit(run_id, str(message))
