from __future__ import annotations

import base64
import copy
import json
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional


FRACTURE_TYPES = ("Conductive", "Resistive", "Bedding")
TERMINAL_STATUSES = {"completed", "cancelled", "failed"}


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _failure_message(error):
    detail = " ".join(str(error or "").split())
    if not detail:
        return "Detection failed"
    if len(detail) > 240:
        detail = detail[:237].rstrip() + "..."
    return f"Detection failed: {detail}"


@dataclass(frozen=True)
class FractureDetectionRequest:
    window_id: str
    tracks: tuple[str, ...]
    target_image_track: str
    depth_start: float
    depth_end: float
    fracture_types: tuple[str, ...]
    borehole_diameter_in: float = 8.0
    min_confidence: float = 0.60
    sliding_window_m: float = 3.0
    pick_entry_level: Optional[str] = None
    fast_mode: bool = False

    @classmethod
    def build(
        cls,
        window_id,
        track=None,
        depth_start=None,
        depth_end=None,
        fracture_types=None,
        tracks=None,
        target_image_track=None,
        borehole_diameter_in=8.0,
        min_confidence=0.60,
        sliding_window_m=None,
        pick_entry_level=None,
        fast_mode=False,
    ):
        window_id = str(window_id or "").strip()
        if not window_id:
            raise ValueError("window_id is required")
        selected_tracks = tuple(dict.fromkeys(
            str(item).strip() for item in (tracks or ([track] if track else [])) if str(item).strip()
        ))
        if not selected_tracks:
            raise ValueError("at least one analysis track is required")
        target = str(target_image_track or "").strip()
        if not target and len(selected_tracks) == 1:
            target = selected_tracks[0]
        if not target:
            raise ValueError("target_image_track is required when multiple tracks are selected")
        if target not in selected_tracks:
            raise ValueError("target_image_track must be included in tracks")
        start, end = float(depth_start), float(depth_end)
        if start >= end:
            raise ValueError("depth_start must be less than depth_end")
        selected = tuple(dict.fromkeys(str(item) for item in (fracture_types or ())))
        invalid = [item for item in selected if item not in FRACTURE_TYPES]
        if not selected:
            raise ValueError("at least one fracture type is required")
        if invalid:
            raise ValueError(f"unsupported fracture types: {', '.join(invalid)}")
        diameter = float(borehole_diameter_in)
        if diameter <= 0:
            raise ValueError("borehole_diameter_in must be positive")
        confidence = float(min_confidence)
        if not 0 <= confidence <= 1:
            raise ValueError("min_confidence must be between 0 and 1")
        window_size = end - start if sliding_window_m is None else float(sliding_window_m)
        if window_size <= 0:
            raise ValueError("sliding_window_m must be positive")
        entry_level = None if pick_entry_level is None else str(pick_entry_level).strip().lower()
        if entry_level not in (None, "confirmed", "suspected"):
            raise ValueError("pick_entry_level must be confirmed or suspected")
        return cls(
            window_id, selected_tracks, target, start, end, selected,
            diameter, confidence, min(window_size, end - start), entry_level, bool(fast_mode),
        )

    def to_dict(self):
        payload = asdict(self)
        payload["tracks"] = list(self.tracks)
        payload["fracture_types"] = list(self.fracture_types)
        return payload


@dataclass
class FractureDetectionRun:
    run_id: str
    request: FractureDetectionRequest
    status: str = "pending"
    stage: str = "pending"
    progress: float = 0.0
    message: str = "Queued"
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    error: Optional[str] = None
    result_count: int = 0
    diagnostics: dict = field(default_factory=dict)
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    input_payload: Optional[dict] = field(default=None, repr=False)
    candidate_payloads: dict = field(default_factory=dict, repr=False)
    view_payloads: dict = field(default_factory=dict, repr=False)
    deferred_completion: bool = field(default=False, repr=False)
    playback: dict = field(default_factory=dict)
    exploration: dict = field(default_factory=dict)
    monitor_events: list = field(default_factory=list, repr=False)
    monitor: dict = field(default_factory=dict, repr=False)

    def to_dict(self):
        return {
            "run_id": self.run_id,
            "request": self.request.to_dict(),
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "result_count": self.result_count,
            "diagnostics": self.diagnostics,
            "cancel_requested": self.cancel_event.is_set(),
            "playback": dict(self.playback),
            "exploration": dict(self.exploration),
            "current_fracture_index": self.playback.get("current_fracture_index", 0),
            "total_fractures": self.playback.get("total_fractures", 0),
            "current_point_index": self.playback.get("current_point_index", 0),
            "total_points": self.playback.get("total_points", 0),
            "correction_round": self.playback.get("correction_round", 0),
            "review_action_count": self.playback.get("review_action_count", 0),
            "review_view_count": self.playback.get("review_view_count", 0),
            "review_view_id": self.playback.get("review_view_id"),
            "applied_count": self.playback.get("applied_count", 0),
            "needs_review_count": self.playback.get("needs_review_count", 0),
            "candidate_index": self.playback.get("current_fracture_index", 0),
            "candidate_count": self.playback.get("total_fractures", 0),
            "staged_count": self.playback.get("staged_count", 0),
            "discarded_count": self.playback.get("discarded_count", 0),
            "audit_stage": self.playback.get("audit_stage"),
            "audit_action_count": self.playback.get("audit_action_count", 0),
            "audit_view_count": self.playback.get("audit_view_count", 0),
            "audit_view_id": self.playback.get("audit_view_id"),
            "exploration_action_count": self.exploration.get("action_count", 0),
            "exploration_view_count": self.exploration.get("view_count", 0),
            "exploration_candidate_count": self.exploration.get("candidate_count", 0),
        }


class FractureDetectionContext:
    def __init__(self, manager, run_id):
        self._manager = manager
        self.run_id = run_id

    @property
    def cancelled(self):
        run = self._manager._get_run(self.run_id)
        return bool(run and run.cancel_event.is_set())

    def update(self, stage, progress, message=""):
        self._manager._update(self.run_id, stage=stage, progress=progress, message=message)

    def set_diagnostics(self, diagnostics):
        self._manager._set_diagnostics(self.run_id, diagnostics)

    def defer_completion(self):
        self._manager.defer_completion(self.run_id)

    def set_candidate_payload(self, candidate_id, payload):
        self._manager.set_candidate_payload(self.run_id, candidate_id, payload)

    def set_view_payload(self, view_id, payload):
        self._manager.set_view_payload(self.run_id, view_id, payload)

    def update_exploration(self, **details):
        self._manager.update_exploration(self.run_id, **details)

    def record_event(self, stage, action, reason="", status="running", **details):
        self._manager.append_monitor_event(
            self.run_id,
            stage=stage,
            action=action,
            reason=reason,
            status=status,
            **details,
        )

    def update_monitor(self, **details):
        self._manager.update_monitor(self.run_id, **details)

    def set_monitor_media(self, slot, payload, **details):
        self._manager.set_monitor_media(self.run_id, slot, payload, **details)


class FractureDetectionManager:
    """Thread-safe lifecycle manager. The vision worker is installed in Phase 2."""

    def __init__(self):
        self._runs = {}
        self._lock = threading.RLock()
        self._worker: Optional[Callable] = None

    @property
    def pipeline_ready(self):
        return callable(self._worker)

    def set_worker(self, worker):
        self._worker = worker

    def clear_worker(self):
        self._worker = None

    def start(self, request, input_payload=None, worker=None):
        selected_worker = worker or self._worker
        if not callable(selected_worker):
            raise RuntimeError("Fracture detection pipeline is not available until the image-analysis backend is installed.")
        run = FractureDetectionRun(run_id=str(uuid.uuid4()), request=request, input_payload=input_payload)
        if input_payload:
            run.monitor["media"] = {"input_view": dict(input_payload)}
        run.monitor.update({
            "current_candidate": None,
            "correction_round": 0,
            "api_status": "queued",
        })
        with self._lock:
            self._runs[run.run_id] = run
        threading.Thread(target=self._run_worker, args=(run.run_id, selected_worker), daemon=True).start()
        return run.to_dict()

    def get_status(self, run_id):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        return run.to_dict()

    def cancel(self, run_id):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        with self._lock:
            if run.status in TERMINAL_STATUSES:
                return run.to_dict()
            run.cancel_event.set()
            run.message = "Cancellation requested"
            run.updated_at = _utc_now()
            if run.status == "pending":
                run.status = "cancelled"
                run.stage = "cancelled"
        return run.to_dict()

    def defer_completion(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            run.deferred_completion = True
            run.updated_at = _utc_now()

    def get_request(self, run_id):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        return run.request

    def get_input_payload(self, run_id):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        return run.input_payload

    def set_candidate_payload(self, run_id, candidate_id, payload):
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            run.candidate_payloads[str(candidate_id)] = payload
            run.monitor.setdefault("media", {})["input_view"] = dict(payload or {})
            run.monitor["current_candidate"] = str(candidate_id)
            run.updated_at = _utc_now()

    def get_candidate_payload(self, run_id, candidate_id):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        return run.candidate_payloads.get(str(candidate_id))

    def set_view_payload(self, run_id, view_id, payload):
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            run.view_payloads[str(view_id)] = payload
            run.monitor.setdefault("media", {})["input_view"] = dict(payload or {})
            run.monitor["current_view_id"] = str(view_id)
            run.updated_at = _utc_now()

    def get_view_payload(self, run_id, view_id):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        return run.view_payloads.get(str(view_id))

    def update_exploration(self, run_id, **details):
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            run.exploration.update({key: value for key, value in details.items() if value is not None})
            run.updated_at = _utc_now()

    def append_monitor_event(self, run_id, *, stage, action, reason="", status="running", **details):
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            event = {
                "timestamp": _utc_now(),
                "stage": str(stage or run.stage),
                "action": str(action or "status"),
                "reason": str(reason or ""),
                "status": str(status or run.status),
            }
            event.update({key: value for key, value in details.items() if value is not None})
            run.monitor_events.append(event)
            run.updated_at = _utc_now()

    def update_monitor(self, run_id, **details):
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            run.monitor.update({key: value for key, value in details.items() if value is not None})
            run.updated_at = _utc_now()

    def set_monitor_media(self, run_id, slot, payload, **details):
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            media = run.monitor.setdefault("media", {})
            media[str(slot)] = dict(payload or {})
            run.monitor.update({key: value for key, value in details.items() if value is not None})
            run.updated_at = _utc_now()

    def get_monitor_snapshot(self, run_id):
        with self._lock:
            run = self._runs.get(str(run_id or ""))
            if not run:
                raise KeyError(f"Unknown fracture detection run: {run_id}")
            return {
                "run": run.to_dict(),
                "events": copy.deepcopy(run.monitor_events),
                "monitor": copy.deepcopy(run.monitor),
                "diagnostics": copy.deepcopy(run.diagnostics),
            }

    def update_playback(self, run_id, *, stage="playback", progress=None, message=None, **details):
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            run.playback.update({key: value for key, value in details.items() if value is not None})
        self._update(run_id, stage=stage, progress=progress, message=message)

    def append_diagnostic_event(self, run_id, event):
        with self._lock:
            run = self._runs.get(run_id)
            if not run:
                return
            clean = dict(event or {})
            events = run.diagnostics.setdefault("playback_events", [])
            events.append(clean)
            run.monitor_events.append({
                "timestamp": _utc_now(),
                "stage": str(clean.get("stage") or run.stage or "playback"),
                "action": str(clean.get("event") or "playback"),
                "reason": str(clean.get("reason") or clean.get("error") or ""),
                "status": "running",
                **{
                    key: clean.get(key) for key in (
                        "candidate_id", "candidate_index", "applied_count",
                        "discarded_count", "needs_review_count",
                    ) if clean.get(key) is not None
                },
            })
            run.updated_at = _utc_now()

    def complete(self, run_id, result_count=0, message=None):
        self._update(
            run_id,
            status="completed",
            stage="completed",
            progress=1.0,
            message=message or f"Completed with {int(result_count)} result(s)",
            result_count=result_count,
        )

    def finish_cancelled(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            if not run or run.status in TERMINAL_STATUSES:
                return
            run.cancel_event.set()
            run.status = "cancelled"
            run.stage = "cancelled"
            run.message = "Cancelled"
            run.updated_at = _utc_now()

    def fail(self, run_id, error):
        self._update(
            run_id,
            status="failed",
            stage="failed",
            message=_failure_message(error),
            error=str(error or ""),
        )

    def export_debug_bundle(self, run_id, root_directory=None):
        run = self._get_run(run_id)
        if not run:
            raise KeyError(f"Unknown fracture detection run: {run_id}")
        output_dir = Path(root_directory or Path.cwd() / "logs" / "fracture_detection") / run.run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = run.input_payload or {}
        data_url = str(payload.get("data_url") or "")
        if not data_url.startswith("data:image/png;base64,"):
            raise ValueError("The detection run does not contain a PNG analysis image")
        image_path = output_dir / "analysis_input.png"
        image_path.write_bytes(base64.b64decode(data_url.split(",", 1)[1]))

        report = run.to_dict()
        report["render_metadata"] = payload.get("metadata") or {}
        candidate_inputs = []
        for candidate_id, candidate_payload in run.candidate_payloads.items():
            candidate_url = str((candidate_payload or {}).get("data_url") or "")
            if not candidate_url.startswith("data:image/png;base64,"):
                continue
            safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in candidate_id)
            candidate_path = output_dir / f"candidate_{safe_id or 'unknown'}.png"
            candidate_path.write_bytes(base64.b64decode(candidate_url.split(",", 1)[1]))
            candidate_record = {
                "candidate_id": candidate_id,
                "image_path": str(candidate_path.resolve()),
                "metadata": (candidate_payload or {}).get("metadata") or {},
            }
            overlay_url = str((candidate_payload or {}).get("overlay_data_url") or "")
            if overlay_url.startswith("data:image/png;base64,"):
                overlay_path = output_dir / f"candidate_{safe_id or 'unknown'}_overlay.png"
                overlay_path.write_bytes(base64.b64decode(overlay_url.split(",", 1)[1]))
                candidate_record["overlay_image_path"] = str(overlay_path.resolve())
            candidate_inputs.append(candidate_record)
        report["candidate_inputs"] = candidate_inputs
        exploration_views = []
        for view_id, view_payload in run.view_payloads.items():
            view_url = str((view_payload or {}).get("data_url") or "")
            if not view_url.startswith("data:image/png;base64,"):
                continue
            safe_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in view_id)
            view_path = output_dir / f"view_{safe_id or 'unknown'}.png"
            view_path.write_bytes(base64.b64decode(view_url.split(",", 1)[1]))
            view_record = {
                "view_id": view_id,
                "image_path": str(view_path.resolve()),
                "metadata": (view_payload or {}).get("metadata") or {},
            }
            overlay_url = str((view_payload or {}).get("overlay_data_url") or "")
            if overlay_url.startswith("data:image/png;base64,"):
                overlay_path = output_dir / f"view_{safe_id or 'unknown'}_overlay.png"
                overlay_path.write_bytes(base64.b64decode(overlay_url.split(",", 1)[1]))
                view_record["overlay_image_path"] = str(overlay_path.resolve())
            exploration_views.append(view_record)
        report["exploration_views"] = exploration_views

        monitor_media = []
        for slot, media_payload in (run.monitor.get("media") or {}).items():
            safe_slot = "".join(char if char.isalnum() or char in "-_" else "_" for char in str(slot))
            media_record = {
                "slot": str(slot),
                "metadata": (media_payload or {}).get("metadata") or {},
            }
            media_url = str((media_payload or {}).get("data_url") or "")
            if media_url.startswith("data:image/png;base64,"):
                media_path = output_dir / f"monitor_{safe_slot or 'unknown'}.png"
                media_path.write_bytes(base64.b64decode(media_url.split(",", 1)[1]))
                media_record["image_path"] = str(media_path.resolve())
            overlay_url = str((media_payload or {}).get("overlay_data_url") or "")
            if overlay_url.startswith("data:image/png;base64,"):
                overlay_path = output_dir / f"monitor_{safe_slot or 'unknown'}_overlay.png"
                overlay_path.write_bytes(base64.b64decode(overlay_url.split(",", 1)[1]))
                media_record["overlay_image_path"] = str(overlay_path.resolve())
            if media_record.get("image_path") or media_record.get("overlay_image_path"):
                monitor_media.append(media_record)
        report["monitor_media"] = monitor_media
        report_path = output_dir / "diagnostics.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "directory": str(output_dir.resolve()),
            "image_path": str(image_path.resolve()),
            "candidate_image_paths": [item["image_path"] for item in candidate_inputs],
            "candidate_overlay_image_paths": [
                item["overlay_image_path"] for item in candidate_inputs if item.get("overlay_image_path")
            ],
            "view_image_paths": [item["image_path"] for item in exploration_views],
            "view_overlay_image_paths": [
                item["overlay_image_path"] for item in exploration_views
                if item.get("overlay_image_path")
            ],
            "monitor_image_paths": [
                item["image_path"] for item in monitor_media if item.get("image_path")
            ],
            "monitor_overlay_image_paths": [
                item["overlay_image_path"] for item in monitor_media
                if item.get("overlay_image_path")
            ],
            "report_path": str(report_path.resolve()),
        }

    def _get_run(self, run_id):
        with self._lock:
            return self._runs.get(str(run_id or ""))

    def _set_diagnostics(self, run_id, diagnostics):
        with self._lock:
            run = self._runs.get(run_id)
            if run:
                run.diagnostics = dict(diagnostics or {})
                run.updated_at = _utc_now()

    def _update(self, run_id, *, status="running", stage=None, progress=None, message=None, error=None, result_count=None):
        with self._lock:
            run = self._runs[run_id]
            if run.status in TERMINAL_STATUSES:
                return
            if run.cancel_event.is_set():
                run.status = "cancelled"
                run.stage = "cancelled"
                run.message = "Cancelled"
            else:
                run.status = status
                if stage is not None:
                    run.stage = str(stage)
                if progress is not None:
                    run.progress = max(0.0, min(1.0, float(progress)))
                if message is not None:
                    run.message = str(message)
                if error is not None:
                    run.error = str(error)
                if result_count is not None:
                    run.result_count = int(result_count)
            run.updated_at = _utc_now()
            run.monitor["api_status"] = run.stage
            event_stage = run.stage
            event_status = run.status
            event_reason = run.message
            previous = run.monitor_events[-1] if run.monitor_events else None
            if not previous or (
                previous.get("stage"), previous.get("action"), previous.get("reason"), previous.get("status")
            ) != (event_stage, "status", event_reason, event_status):
                run.monitor_events.append({
                    "timestamp": run.updated_at,
                    "stage": event_stage,
                    "action": "status",
                    "reason": event_reason,
                    "status": event_status,
                })

    def _run_worker(self, run_id, worker):
        context = FractureDetectionContext(self, run_id)
        run = self._get_run(run_id)
        if not run or run.status == "cancelled":
            return
        self._update(run_id, stage="rendering", progress=0.0, message="Preparing image data")
        try:
            result = worker(run.request, context, run.input_payload)
            if context.cancelled:
                self._update(run_id, status="cancelled", stage="cancelled", message="Cancelled")
                return
            run = self._get_run(run_id)
            if run and run.deferred_completion:
                return
            count = len(result) if isinstance(result, (list, tuple)) else int((result or {}).get("result_count", 0))
            self._update(
                run_id,
                status="completed",
                stage="completed",
                progress=1.0,
                message=f"Completed with {count} result(s)",
                result_count=count,
            )
        except Exception as exc:
            if context.cancelled:
                self._update(run_id, status="cancelled", stage="cancelled", message="Cancelled")
            else:
                self._update(
                    run_id,
                    status="failed",
                    stage="failed",
                    message=_failure_message(exc),
                    error=str(exc),
                )


_manager = FractureDetectionManager()


def get_fracture_detection_manager():
    return _manager
