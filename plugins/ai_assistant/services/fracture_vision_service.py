from __future__ import annotations

import base64

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ..ai_core.config import AIConfig
from .fracture_agent_workflow import (
    AdaptiveFractureViewRenderer,
    FractureAgentBudget,
    FractureAgentState,
)
from .fracture_complete_workflow import CompleteFractureWorkflow
from .fracture_evidence_service import FractureEvidenceScorer
from scripts.rendering.fracture_annotations import fit_sinusoidal_fracture, sinusoidal_fracture_xy

try:
    import openai
except ImportError:
    openai = None


class FractureVisionPipeline:
    """OpenAI-compatible client facade for the complete-fracture workflow."""

    def __init__(self, config=None, client_factory=None, evidence_scorer=None):
        self.config = config or AIConfig()
        self.client_factory = client_factory
        self.evidence_scorer = evidence_scorer or FractureEvidenceScorer()
        self.view_renderer = AdaptiveFractureViewRenderer()
        self.complete_workflow = CompleteFractureWorkflow(self)

    def detect(self, request, context, rendered):
        return self.complete_workflow.detect(request, context, rendered)

    def discover_candidate_windows(self, request, rendered):
        return self.complete_workflow.discover_candidate_windows(request, rendered)

    def render_candidate_window(self, rendered, candidate, target_image_track):
        return self.complete_workflow.render_candidate_window(rendered, candidate, target_image_track)

    def create_agent_state(self, budget=None):
        return FractureAgentState(budget=budget or FractureAgentBudget())

    def render_agent_view(self, rendered, target_image_track, view_request, view_id=None):
        return self.view_renderer.render(
            rendered,
            target_image_track,
            view_request,
            view_id=view_id,
        )

    def pick_candidate_anchors(self, request, candidate_rendered, candidate):
        return self.complete_workflow.pick_candidate_anchors(request, candidate_rendered, candidate)

    def review_candidate(self, request, rendered, annotation, correction_round=1):
        candidate_rendered = annotation.get("_candidate_rendered") or rendered
        return self.review_candidate_parameters(
            request,
            candidate_rendered,
            annotation,
            round_number=correction_round,
        )

    def review_candidate_parameters(
        self,
        request,
        candidate_rendered,
        annotation,
        round_number=1,
        *,
        source_rendered=None,
        view_recorder=None,
        status_callback=None,
    ):
        return self.complete_workflow.review_candidate_parameters(
            request,
            candidate_rendered,
            annotation,
            round_number=round_number,
            source_rendered=source_rendered,
            view_recorder=view_recorder,
            status_callback=status_callback,
        )

    def audit_candidate_batch(
        self,
        request,
        rendered,
        staged_candidates,
        *,
        view_recorder=None,
        status_callback=None,
    ):
        return self.complete_workflow.audit_candidate_batch(
            request,
            rendered,
            staged_candidates,
            view_recorder=view_recorder,
            status_callback=status_callback,
        )

    def _create_client(self, config):
        if self.client_factory:
            return self.client_factory(config)
        if openai is None:
            raise ImportError("OpenAI library is not installed")
        kwargs = {
            "api_key": config["api_key"],
            "timeout": float(config.get("timeout_seconds", 120)),
        }
        if str(config.get("base_url") or "").strip():
            kwargs["base_url"] = config["base_url"]
        return openai.OpenAI(**kwargs)

    @staticmethod
    def _request(client, model, messages, response_schema=None):
        if response_schema is None:
            raise ValueError("A structured response schema is required")
        params = {
            "model": model,
            "messages": messages,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": response_schema,
            },
        }
        try:
            return client.chat.completions.create(**params)
        except Exception as exc:
            message = str(exc).lower()
            if not any(term in message for term in ("response_format", "json_schema", "structured output")):
                raise
            params["response_format"] = {"type": "json_object"}
            return client.chat.completions.create(**params)

    @staticmethod
    def _build_feedback_image(rendered, points, target_image_track):
        raw = str(rendered["data_url"]).split(",", 1)[-1]
        image = QImage.fromData(base64.b64decode(raw), "PNG")
        if image.isNull():
            raise ValueError("Unable to decode fracture analysis image")
        metadata = rendered["metadata"]
        target = next(
            (
                track for track in metadata.get("tracks", [])
                if target_image_track in (track.get("name"), track.get("label"))
                and track.get("pixel_left") is not None
                and track.get("pixel_right") is not None
            ),
            None,
        )
        if target is None:
            raise ValueError("Target image track bounds are absent from render metadata")
        left, right = float(target["pixel_left"]), float(target["pixel_right"])
        azimuth_start = float(target.get("azimuth_start_deg", 0.0))
        azimuth_end = float(target.get("azimuth_end_deg", 360.0))
        top = float(metadata.get("plot_top", 0.0))
        bottom = float(metadata.get("plot_bottom", image.height()))
        depth_start = float(metadata["depth_start"])
        depth_end = float(metadata["depth_end"])
        depth_span = depth_end - depth_start
        if right <= left or bottom <= top or depth_span <= 0 or azimuth_end <= azimuth_start:
            raise ValueError("Invalid fracture feedback coordinate bounds")

        def pixel_point(azimuth, depth):
            return QPointF(
                left + (float(azimuth) - azimuth_start) / (azimuth_end - azimuth_start) * (right - left),
                top + (float(depth) - depth_start) / depth_span * (bottom - top),
            )

        fit = fit_sinusoidal_fracture(points, min_points=3)
        x_values, y_values = sinusoidal_fracture_xy(fit, samples=361)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor("#FF00A8"), 4.0))
        previous = None
        for azimuth, depth in zip(x_values, y_values):
            if not azimuth_start <= float(azimuth) <= azimuth_end:
                previous = None
                continue
            current = pixel_point(azimuth, depth)
            if previous is not None:
                painter.drawLine(previous, current)
            previous = current
        painter.setPen(QPen(QColor("#101010"), 2.0))
        painter.setBrush(QColor("#FFE600"))
        for azimuth, depth in points:
            if azimuth_start <= float(azimuth) <= azimuth_end:
                painter.drawEllipse(pixel_point(azimuth, depth), 7.0, 7.0)
        painter.end()

        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Unable to encode fracture feedback image")
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")
