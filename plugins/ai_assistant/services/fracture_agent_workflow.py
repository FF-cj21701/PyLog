from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field

from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter


EXPLORATION_ACTIONS = (
    "inspect_view",
    "register_trace_fragment",
    "test_sinusoid_hypothesis",
    "register_candidate",
    "finish_exploration",
)
DETAIL_LEVELS = ("overview", "detail", "close")
TRACE_SLOPE_DIRECTIONS = ("rising", "falling", "flat", "curved", "uncertain")


FRACTURE_AGENT_VIEW_SCHEMA = {
    "type": ["object", "null"],
    "properties": {
        "depth_start": {"type": "number"},
        "depth_end": {"type": "number"},
        "azimuth_start_deg": {"type": "number", "minimum": 0, "maximum": 360},
        "azimuth_end_deg": {"type": "number", "minimum": 0, "maximum": 360},
        "detail_level": {"type": "string", "enum": list(DETAIL_LEVELS)},
        "include_depth_track": {"type": "boolean"},
        "scale": {"type": "number", "minimum": 0.5, "maximum": 4.0},
    },
    "required": [
        "depth_start", "depth_end", "azimuth_start_deg", "azimuth_end_deg",
        "detail_level", "include_depth_track", "scale",
    ],
    "additionalProperties": False,
}


FRACTURE_EXPLORATION_ACTION_SCHEMA = {
    "name": "fracture_exploration_action",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": list(EXPLORATION_ACTIONS)},
            "reason": {"type": "string"},
            "view": FRACTURE_AGENT_VIEW_SCHEMA,
            "fragment": {
                "type": ["object", "null"],
                "properties": {
                    "fragment_id": {"type": "string"},
                    "fracture_type": {
                        "type": "string",
                        "enum": ["Conductive", "Resistive", "Bedding"],
                    },
                    "depth_top": {"type": "number"},
                    "depth_bottom": {"type": "number"},
                    "azimuth_start_deg": {"type": "number", "minimum": 0, "maximum": 360},
                    "azimuth_end_deg": {"type": "number", "minimum": 0, "maximum": 360},
                    "slope_direction": {
                        "type": "string",
                        "enum": list(TRACE_SLOPE_DIRECTIONS),
                    },
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "continuity_reason": {"type": "string"},
                },
                "required": [
                    "fragment_id", "fracture_type", "depth_top", "depth_bottom",
                    "azimuth_start_deg", "azimuth_end_deg", "slope_direction",
                    "confidence", "continuity_reason",
                ],
                "additionalProperties": False,
            },
            "hypothesis": {
                "type": ["object", "null"],
                "properties": {
                    "hypothesis_id": {"type": "string"},
                    "fragment_ids": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string"},
                    },
                    "fracture_type": {
                        "type": "string",
                        "enum": ["Conductive", "Resistive", "Bedding"],
                    },
                    "center_depth_m": {"type": "number"},
                    "amplitude_m": {"type": "number", "exclusiveMinimum": 0},
                    "phase_deg": {"type": "number"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": [
                    "hypothesis_id", "fragment_ids", "fracture_type", "center_depth_m",
                    "amplitude_m", "phase_deg", "confidence",
                ],
                "additionalProperties": False,
            },
            "candidate": {
                "type": ["object", "null"],
                "properties": {
                    "candidate_id": {"type": "string"},
                    "fracture_type": {
                        "type": "string",
                        "enum": ["Conductive", "Resistive", "Bedding"],
                    },
                    "depth_top": {"type": "number"},
                    "depth_bottom": {"type": "number"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "continuity_reason": {"type": "string"},
                },
                "required": [
                    "candidate_id", "fracture_type", "depth_top", "depth_bottom",
                    "confidence", "continuity_reason",
                ],
                "additionalProperties": False,
            },
        },
        "required": ["action", "reason", "view", "fragment", "hypothesis", "candidate"],
        "additionalProperties": False,
    },
}


@dataclass(frozen=True)
class FractureAgentBudget:
    max_views: int = 20
    max_actions: int = 40
    max_candidates: int = 24
    max_fragments: int = 48
    max_hypotheses: int = 24
    max_duplicate_views: int = 1

    def __post_init__(self):
        for name, value in asdict(self).items():
            if int(value) <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True)
class FractureAgentViewRequest:
    depth_start: float
    depth_end: float
    azimuth_start_deg: float = 0.0
    azimuth_end_deg: float = 360.0
    detail_level: str = "detail"
    include_depth_track: bool = True
    scale: float = 1.0

    @classmethod
    def build(cls, payload, source_metadata):
        payload = dict(payload or {})
        source_start = float(source_metadata["depth_start"])
        source_end = float(source_metadata["depth_end"])
        depth_start = max(source_start, min(source_end, float(payload.get("depth_start", source_start))))
        depth_end = max(source_start, min(source_end, float(payload.get("depth_end", source_end))))
        azimuth_start = max(0.0, min(360.0, float(payload.get("azimuth_start_deg", 0.0))))
        azimuth_end = max(0.0, min(360.0, float(payload.get("azimuth_end_deg", 360.0))))
        detail_level = str(payload.get("detail_level") or "detail")
        scale = float(payload.get("scale", 1.0))
        if depth_end <= depth_start:
            raise ValueError("Requested view depth_start must be less than depth_end")
        if azimuth_end <= azimuth_start:
            raise ValueError("Requested view azimuth_start_deg must be less than azimuth_end_deg")
        if detail_level not in DETAIL_LEVELS:
            raise ValueError(f"Unsupported detail level: {detail_level}")
        if not 0.5 <= scale <= 4.0:
            raise ValueError("Requested view scale must be between 0.5 and 4.0")
        return cls(
            depth_start=depth_start,
            depth_end=depth_end,
            azimuth_start_deg=azimuth_start,
            azimuth_end_deg=azimuth_end,
            detail_level=detail_level,
            include_depth_track=bool(payload.get("include_depth_track", True)),
            scale=scale,
        )

    @property
    def is_full_azimuth(self):
        return self.azimuth_start_deg <= 0.0 and self.azimuth_end_deg >= 360.0

    def key(self):
        return (
            round(self.depth_start, 6),
            round(self.depth_end, 6),
            round(self.azimuth_start_deg, 3),
            round(self.azimuth_end_deg, 3),
            self.include_depth_track,
            round(self.scale, 3),
        )


@dataclass
class FractureAgentState:
    budget: FractureAgentBudget = field(default_factory=FractureAgentBudget)
    action_count: int = 0
    views: list[dict] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    fragments: list[dict] = field(default_factory=list)
    hypotheses: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    finished: bool = False
    _view_counts: dict[tuple, int] = field(default_factory=dict, repr=False)

    def record_action(self, action):
        if self.finished:
            raise RuntimeError("Fracture exploration is already finished")
        if self.action_count >= self.budget.max_actions:
            raise RuntimeError("Fracture exploration action budget exhausted")
        self.action_count += 1
        if action not in EXPLORATION_ACTIONS:
            raise ValueError(f"Unsupported exploration action: {action}")

    def record_event(self, action, reason="", *, outcome="accepted", error=None):
        event = {
            "action_index": self.action_count,
            "action": str(action or ""),
            "reason": str(reason or ""),
            "outcome": str(outcome or ""),
        }
        if error:
            event["error"] = str(error)
        self.events.append(event)
        return event

    def record_view(self, request, view_id, *, variant="source"):
        if len(self.views) >= self.budget.max_views:
            raise RuntimeError("Fracture exploration view budget exhausted")
        key = (request.key(), str(variant or "source"))
        count = self._view_counts.get(key, 0)
        if count >= self.budget.max_duplicate_views:
            raise ValueError("The requested fracture exploration view is a duplicate")
        self._view_counts[key] = count + 1
        item = {"view_id": str(view_id), "variant": str(variant or "source"), **asdict(request)}
        self.views.append(item)
        return item

    def register_trace_fragment(self, fragment, allowed_types, source_metadata):
        if len(self.fragments) >= self.budget.max_fragments:
            raise RuntimeError("Fracture exploration fragment budget exhausted")
        fragment = dict(fragment or {})
        fracture_type = str(fragment.get("fracture_type") or "")
        if fracture_type not in tuple(allowed_types):
            raise ValueError(f"Unsupported fracture type for this run: {fracture_type}")
        fragment_id = str(fragment.get("fragment_id") or f"T{len(self.fragments) + 1}").strip()
        if not fragment_id:
            raise ValueError("Trace fragment id is required")
        if any(item["fragment_id"] == fragment_id for item in self.fragments):
            raise ValueError(f"Duplicate fragment_id: {fragment_id}")
        top = max(float(source_metadata["depth_start"]), float(fragment["depth_top"]))
        bottom = min(float(source_metadata["depth_end"]), float(fragment["depth_bottom"]))
        azimuth_start = max(0.0, min(360.0, float(fragment["azimuth_start_deg"])))
        azimuth_end = max(0.0, min(360.0, float(fragment["azimuth_end_deg"])))
        slope_direction = str(fragment.get("slope_direction") or "uncertain")
        if bottom <= top:
            raise ValueError("Trace fragment depth window is empty")
        if azimuth_end <= azimuth_start:
            raise ValueError("Trace fragment azimuth range is empty")
        if slope_direction not in TRACE_SLOPE_DIRECTIONS:
            raise ValueError(f"Unsupported trace slope direction: {slope_direction}")
        clean = {
            "fragment_id": fragment_id,
            "fracture_type": fracture_type,
            "depth_top": top,
            "depth_bottom": bottom,
            "azimuth_start_deg": azimuth_start,
            "azimuth_end_deg": azimuth_end,
            "slope_direction": slope_direction,
            "confidence": max(0.0, min(1.0, float(fragment.get("confidence", 0.0)))),
            "continuity_reason": str(fragment.get("continuity_reason") or ""),
        }
        self.fragments.append(clean)
        return clean

    def register_hypothesis(self, hypothesis, allowed_types, source_metadata):
        if len(self.hypotheses) >= self.budget.max_hypotheses:
            raise RuntimeError("Fracture exploration hypothesis budget exhausted")
        hypothesis = dict(hypothesis or {})
        hypothesis_id = str(hypothesis.get("hypothesis_id") or f"H{len(self.hypotheses) + 1}").strip()
        fracture_type = str(hypothesis.get("fracture_type") or "")
        if fracture_type not in tuple(allowed_types):
            raise ValueError(f"Unsupported fracture type for this run: {fracture_type}")
        fragment_ids = [str(item).strip() for item in hypothesis.get("fragment_ids", []) if str(item).strip()]
        known_fragments = {item["fragment_id"]: item for item in self.fragments}
        missing = [item for item in fragment_ids if item not in known_fragments]
        if not fragment_ids:
            raise ValueError("A sinusoid hypothesis requires at least one registered trace fragment")
        if missing:
            raise ValueError(f"Unknown trace fragment id(s): {', '.join(missing)}")
        if any(known_fragments[item]["fracture_type"] != fracture_type for item in fragment_ids):
            raise ValueError("Hypothesis type must match all referenced trace fragments")
        center = float(hypothesis["center_depth_m"])
        amplitude = abs(float(hypothesis["amplitude_m"]))
        source_start = float(source_metadata["depth_start"])
        source_end = float(source_metadata["depth_end"])
        if amplitude <= 0.0:
            raise ValueError("Sinusoid hypothesis amplitude must be positive")
        if center + amplitude < source_start or center - amplitude > source_end:
            raise ValueError("Sinusoid hypothesis does not intersect the source depth interval")
        revision = 1 + sum(item["hypothesis_id"] == hypothesis_id for item in self.hypotheses)
        clean = {
            "hypothesis_id": hypothesis_id,
            "revision": revision,
            "fragment_ids": list(dict.fromkeys(fragment_ids)),
            "fracture_type": fracture_type,
            "center_depth_m": center,
            "amplitude_m": amplitude,
            "phase_deg": float(hypothesis["phase_deg"]) % 360.0,
            "confidence": max(0.0, min(1.0, float(hypothesis.get("confidence", 0.0)))),
        }
        self.hypotheses.append(clean)
        return clean

    def register_candidate(self, candidate, allowed_types, source_metadata):
        if len(self.candidates) >= self.budget.max_candidates:
            raise RuntimeError("Fracture exploration candidate budget exhausted")
        candidate = dict(candidate or {})
        fracture_type = str(candidate.get("fracture_type") or "")
        if fracture_type not in tuple(allowed_types):
            raise ValueError(f"Unsupported fracture type for this run: {fracture_type}")
        top = max(float(source_metadata["depth_start"]), float(candidate["depth_top"]))
        bottom = min(float(source_metadata["depth_end"]), float(candidate["depth_bottom"]))
        if bottom <= top:
            raise ValueError("Candidate depth window is empty")
        candidate_id = str(candidate.get("candidate_id") or f"F{len(self.candidates) + 1}").strip()
        if any(item["candidate_id"] == candidate_id for item in self.candidates):
            raise ValueError(f"Duplicate candidate_id: {candidate_id}")
        clean = {
            "candidate_id": candidate_id,
            "fracture_type": fracture_type,
            "depth_top": top,
            "depth_bottom": bottom,
            "confidence": max(0.0, min(1.0, float(candidate.get("confidence", 0.0)))),
            "continuity_reason": str(candidate.get("continuity_reason") or ""),
        }
        self.candidates.append(clean)
        return clean

    def finish(self):
        self.finished = True

    def prompt_context(self):
        return {
            "budget": asdict(self.budget),
            "actions_used": self.action_count,
            "views_used": len(self.views),
            "candidate_count": len(self.candidates),
            "fragment_count": len(self.fragments),
            "hypothesis_count": len(self.hypotheses),
            "recent_views": self.views[-6:],
            "trace_fragments": list(self.fragments),
            "recent_hypotheses": self.hypotheses[-6:],
            "candidates": list(self.candidates),
            "recent_events": self.events[-8:],
        }


class AdaptiveFractureViewRenderer:
    """Render model-requested views from one immutable Plot analysis image."""

    def render(self, rendered, target_image_track, view_request, view_id=None):
        if not rendered or not rendered.get("data_url") or not rendered.get("metadata"):
            raise ValueError("Rendered Plot image and metadata are required")
        metadata = rendered["metadata"]
        request = (
            view_request
            if isinstance(view_request, FractureAgentViewRequest)
            else FractureAgentViewRequest.build(view_request, metadata)
        )
        image = self._decode_image(rendered["data_url"])
        target = self._target_track(metadata, target_image_track)
        source_start = float(metadata["depth_start"])
        source_end = float(metadata["depth_end"])
        plot_top = float(metadata.get("plot_top", 0.0))
        plot_bottom = float(metadata.get("plot_bottom", image.height()))
        source_span = source_end - source_start
        y0 = int(round(plot_top + (request.depth_start - source_start) / source_span * (plot_bottom - plot_top)))
        y1 = int(round(plot_top + (request.depth_end - source_start) / source_span * (plot_bottom - plot_top)))
        y0, y1 = max(0, y0), min(image.height(), y1)
        if y1 <= y0:
            raise ValueError("Requested depth range maps to an empty image view")

        pieces = []
        if request.include_depth_track:
            depth_track = next((item for item in metadata.get("tracks", []) if item.get("is_depth")), None)
            if depth_track is not None:
                pieces.append((depth_track, 0.0, 1.0))
        pieces.append((target, request.azimuth_start_deg / 360.0, request.azimuth_end_deg / 360.0))

        source_pieces = []
        for track, start_fraction, end_fraction in pieces:
            track_left = float(track["pixel_left"])
            track_right = float(track["pixel_right"])
            left = int(round(track_left + start_fraction * (track_right - track_left)))
            right = int(round(track_left + end_fraction * (track_right - track_left)))
            if right <= left:
                raise ValueError("Requested azimuth range maps to an empty image view")
            source_pieces.append((track, left, right))

        canvas = QImage(sum(right - left for _track, left, right in source_pieces), y1 - y0, QImage.Format_ARGB32)
        canvas.fill(QColor("#FFFFFF"))
        painter = QPainter(canvas)
        output_tracks = []
        x_offset = 0
        for track, left, right in source_pieces:
            width = right - left
            painter.drawImage(x_offset, 0, image.copy(left, y0, width, y1 - y0))
            copied = dict(track)
            copied.update({"pixel_left": x_offset, "pixel_right": x_offset + width, "pixel_width": width})
            if track is target:
                copied.update({
                    "azimuth_start_deg": request.azimuth_start_deg,
                    "azimuth_end_deg": request.azimuth_end_deg,
                    "full_azimuth": request.is_full_azimuth,
                })
            output_tracks.append(copied)
            x_offset += width
        painter.end()

        output_metadata = {
            "width": canvas.width(),
            "height": canvas.height(),
            "plot_top": 0,
            "plot_bottom": canvas.height(),
            "depth_start": request.depth_start,
            "depth_end": request.depth_end,
            "tracks": output_tracks,
            "target_image_track": target_image_track,
            "view_id": str(view_id or ""),
            "view_request": asdict(request),
            "source_render_size": [metadata.get("width"), metadata.get("height")],
            "uniform_scale": 1.0,
            "vertical_scale": request.scale,
            "actual_vertical_scale": metadata.get("actual_vertical_scale", 1.0),
            "render_mode": "source_crop",
        }
        return {"data_url": self._encode_image(canvas), "metadata": output_metadata}

    @staticmethod
    def _target_track(metadata, target_image_track):
        target = next(
            (
                item for item in metadata.get("tracks", [])
                if target_image_track in (item.get("name"), item.get("label"))
            ),
            None,
        )
        if target is None:
            raise ValueError(f"Target image track '{target_image_track}' is absent from render metadata")
        return target

    @staticmethod
    def _decode_image(data_url):
        image = QImage.fromData(base64.b64decode(str(data_url).split(",", 1)[-1]), "PNG")
        if image.isNull():
            raise ValueError("Unable to decode rendered analysis image")
        return image

    @staticmethod
    def _encode_image(image):
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Unable to encode fracture exploration view")
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")
