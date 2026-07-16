import base64
import json
import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from plugins.ai_assistant.services.fracture_detection_service import (
    FractureDetectionRequest,
    get_fracture_detection_manager,
)
from plugins.ai_assistant.services.fracture_evidence_service import FractureEvidenceScorer
from plugins.ai_assistant.services.fracture_vision_service import FractureVisionPipeline
from plugins.ai_assistant.tools.fracture_detection_tool import StartFractureDetectionTool
from scripts.rendering.fracture_annotations import annotation_from_fracture_parameters


class Config:
    def get_resolved_vision_config(self):
        return {
            "api_key": "test-key",
            "base_url": "https://example.test/v1",
            "model": "vision-model",
            "timeout_seconds": 30,
        }


class Context:
    run_id = "run-1"
    cancelled = False

    def __init__(self):
        self.updates = []
        self.diagnostics = None

    def update(self, stage, progress, message=""):
        self.updates.append((stage, progress, message))

    def set_diagnostics(self, diagnostics):
        self.diagnostics = diagnostics


class Scorer:
    def __init__(self, available=True, complete=True):
        self.available = available
        self.complete = complete

    def evaluate(self, *_args):
        return {
            "available": self.available,
            "complete": self.complete if self.available else None,
            "score": 3.0 if self.complete else 1.0,
            "coverage": 0.8 if self.complete else 0.25,
            "min_quadrant_coverage": 0.7 if self.complete else 0.1,
        }


def request():
    return FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["GR", "Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000,
        depth_end=1010,
        fracture_types=["Conductive", "Bedding"],
        min_confidence=0.6,
    )


def _png_data_url(width=800, height=600):
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(QColor("#707070"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")


def rendered():
    return {
        "data_url": _png_data_url(),
        "metadata": {
            "width": 800,
            "height": 600,
            "plot_top": 100,
            "plot_bottom": 600,
            "depth_start": 1000,
            "depth_end": 1010,
            "tracks": [
                {
                    "name": "Depth",
                    "label": "Depth",
                    "is_image": False,
                    "is_depth": True,
                    "pixel_left": 0,
                    "pixel_right": 200,
                    "curves": [],
                },
                {
                    "name": "Track 1",
                    "label": "Track 1 / IMAGE",
                    "is_image": True,
                    "is_depth": False,
                    "pixel_left": 200,
                    "pixel_right": 800,
                    "curves": [{"name": "IMAGE", "is_image": True}],
                },
            ],
        },
    }


def response(payload):
    message = SimpleNamespace(content=json.dumps(payload))
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class SequenceCompletions:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return response(self.payloads.pop(0))


def test_local_evidence_scorer_distinguishes_complete_sine_from_wrong_curve():
    height, width = 220, 320
    rows = np.arange(height)
    gray = np.repeat((125 + 35 * np.sin(rows / 7))[:, None], width, axis=1).astype(np.uint8)
    columns = np.arange(width)
    trace = 110 + 32 * np.sin(2 * np.pi * columns / (width - 1) + 0.4)
    for x, y in zip(columns, np.rint(trace).astype(int)):
        gray[max(0, y - 1):min(height, y + 2), x] = 255

    scorer = FractureEvidenceScorer()
    evidence, valid_columns = scorer.build_evidence(gray)
    metadata = {"depth_start": 1000.0, "depth_end": 1011.0}
    depth_per_pixel = 11.0 / (height - 1)
    complete = scorer.score_annotation(evidence, valid_columns, {
        "offset": 1000.0 + 110 * depth_per_pixel,
        "sin_coeff": 32 * depth_per_pixel * np.cos(0.4),
        "cos_coeff": 32 * depth_per_pixel * np.sin(0.4),
    }, metadata)
    wrong = scorer.score_annotation(evidence, valid_columns, {
        "offset": 1005.5,
        "sin_coeff": 0.0,
        "cos_coeff": 0.0,
    }, metadata)

    assert complete["complete"] is True
    assert wrong["complete"] is False
    assert wrong["score"] < complete["score"]


def test_local_evidence_scorer_ignores_unmeasured_azimuth_quadrants():
    height, width = 100, 120
    evidence = np.zeros((height, width), dtype=float)
    valid_columns = np.zeros(width, dtype=bool)
    valid_columns[5:50] = True
    evidence[49:52, valid_columns] = 2.0

    result = FractureEvidenceScorer.score_annotation(
        evidence,
        valid_columns,
        {"offset": 1005.0, "sin_coeff": 0.0, "cos_coeff": 0.0},
        {"depth_start": 1000.0, "depth_end": 1010.0},
    )

    assert result["complete"] is True
    assert result["supported_quadrant_count"] == 2
    assert result["quadrant_valid_column_count"][2:] == [0, 0]


def test_pipeline_discovers_windows_then_picks_focused_anchors():
    completions = SequenceCompletions([
        {
            "action": "inspect_view",
            "reason": "The overview suggests a complete trace in the middle interval",
            "view": {
                "depth_start": 1001.0,
                "depth_end": 1009.0,
                "azimuth_start_deg": 0.0,
                "azimuth_end_deg": 360.0,
                "detail_level": "detail",
                "include_depth_track": True,
            },
            "candidate": None,
        },
        {
            "action": "register_candidate",
            "reason": "The full-width detail supports one continuous cycle",
            "view": None,
            "candidate": {
                "candidate_id": "F1",
                "fracture_type": "Conductive",
                "depth_top": 1002.0,
                "depth_bottom": 1008.0,
                "confidence": 0.9,
                "continuity_reason": "continuous across gaps",
            },
        },
        {
            "action": "finish_exploration",
            "reason": "The full requested interval has been examined",
            "view": None,
            "candidate": None,
        },
        {
            "confidence": 0.88,
            "reason": "full-width trace",
            "points": [
                {"x_norm": 0.0, "y_norm": 0.5},
                {"x_norm": 0.5, "y_norm": 0.6},
                {"x_norm": 1.0, "y_norm": 0.5},
            ],
        },
        {
            "action": "keep",
            "view": None,
            "aligned": True,
            "center_depth_m": None,
            "amplitude_m": None,
            "phase_deg": None,
            "corrected_points": [],
            "confidence": 0.92,
            "reason": "The fitted curve follows one complete trace",
        },
        {
            "action": "finalize_audit",
            "reason": "The batch contains one complete non-duplicate fracture",
            "view": None,
            "decisions": [
                {"candidate_id": "F1", "action": "keep", "reason": "complete"},
            ],
        },
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    context = Context()
    pipeline = FractureVisionPipeline(
        Config(),
        client_factory=lambda _config: client,
        evidence_scorer=Scorer(),
    )

    results = pipeline.detect(request(), context, rendered())

    assert len(results) == 1
    fracture = results[0]
    assert fracture["candidate_id"] == "F1"
    assert fracture["candidate_depth_window"] == [1002.0, 1008.0]
    assert fracture["local_completeness"]["complete"] is True
    assert fracture["ai_initial_parameters"] == fracture["ai_final_parameters"]
    assert fracture["_candidate_rendered"]["metadata"]["plot_top"] == 0
    assert [call["response_format"]["json_schema"]["name"] for call in completions.calls] == [
        "fracture_exploration_action",
        "fracture_exploration_action",
        "fracture_exploration_action",
        "complete_fracture_anchor_points",
        "complete_fracture_parameter_review",
        "complete_fracture_batch_audit",
    ]
    assert context.updates[0][0] == "exploring"
    assert "candidate_rendering" in [item[0] for item in context.updates]
    assert "reviewing" in [item[0] for item in context.updates]
    assert "auditing" in [item[0] for item in context.updates]
    assert context.updates[-1][0] == "staging"
    assert context.diagnostics["accepted_count"] == 1
    assert context.diagnostics["batch_audit"]["audit_status"] == "completed"
    assert context.diagnostics["exploration"]["action_count"] == 3
    assert len(context.diagnostics["exploration"]["views"]) == 2
    exploration_prompt = json.dumps(completions.calls[0]["messages"])
    assert "possible high-amplitude fracture" in exploration_prompt
    assert "entire peak-to-trough envelope" in exploration_prompt
    assert "seam behavior" in exploration_prompt


def test_exploration_can_register_from_partial_evidence_without_requiring_full_azimuth():
    completions = SequenceCompletions([
        {
            "action": "inspect_view",
            "reason": "Inspect the ambiguous right half",
            "view": {
                "depth_start": 1003.0,
                "depth_end": 1007.0,
                "azimuth_start_deg": 180.0,
                "azimuth_end_deg": 360.0,
                "detail_level": "close",
                "include_depth_track": False,
            },
            "candidate": None,
        },
        {
            "action": "register_candidate",
            "reason": "The local detail looks continuous",
            "view": None,
            "candidate": {
                "candidate_id": "F1",
                "fracture_type": "Conductive",
                "depth_top": 1003.2,
                "depth_bottom": 1006.8,
                "confidence": 0.9,
                "continuity_reason": "local detail",
            },
        },
        {
            "action": "inspect_view",
            "reason": "Return to a full-width view before registering",
            "view": {
                "depth_start": 1002.5,
                "depth_end": 1007.5,
                "azimuth_start_deg": 0.0,
                "azimuth_end_deg": 360.0,
                "detail_level": "detail",
                "include_depth_track": True,
            },
            "candidate": None,
        },
        {
            "action": "register_candidate",
            "reason": "The full cycle is now confirmed",
            "view": None,
            "candidate": {
                "candidate_id": "F1",
                "fracture_type": "Conductive",
                "depth_top": 1003.2,
                "depth_bottom": 1006.8,
                "confidence": 0.9,
                "continuity_reason": "confirmed across 0-360 degrees",
            },
        },
        {
            "action": "finish_exploration",
            "reason": "No other complete traces",
            "view": None,
            "candidate": None,
        },
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)

    candidates, diagnostics = pipeline.complete_workflow.explore_candidate_windows(
        request(),
        rendered(),
        client=client,
        model="vision-model",
    )

    assert [item["candidate_id"] for item in candidates] == ["F1"]
    assert len(diagnostics["views"]) == 3
    assert diagnostics["events"][1]["outcome"] == "accepted"
    assert diagnostics["events"][3]["outcome"] == "rejected"
    assert "Duplicate candidate_id" in diagnostics["events"][3]["error"]


def test_exploration_can_register_fragments_and_test_a_full_sinusoid_hypothesis():
    def action(name, reason, *, fragment=None, hypothesis=None, candidate=None):
        return {
            "action": name,
            "reason": reason,
            "view": None,
            "fragment": fragment,
            "hypothesis": hypothesis,
            "candidate": candidate,
        }

    completions = SequenceCompletions([
        action("register_trace_fragment", "Preserve the visible left arc", fragment={
            "fragment_id": "T1",
            "fracture_type": "Conductive",
            "depth_top": 1002.0,
            "depth_bottom": 1004.5,
            "azimuth_start_deg": 0.0,
            "azimuth_end_deg": 130.0,
            "slope_direction": "rising",
            "confidence": 0.82,
            "continuity_reason": "clear left arc entering a pad gap",
        }),
        action("register_trace_fragment", "Preserve the complementary right arc", fragment={
            "fragment_id": "T2",
            "fracture_type": "Conductive",
            "depth_top": 1005.5,
            "depth_bottom": 1008.0,
            "azimuth_start_deg": 210.0,
            "azimuth_end_deg": 360.0,
            "slope_direction": "falling",
            "confidence": 0.8,
            "continuity_reason": "right arc has compatible curvature",
        }),
        action("test_sinusoid_hypothesis", "Test whether both arcs form one full cycle", hypothesis={
            "hypothesis_id": "H1",
            "fragment_ids": ["T1", "T2"],
            "fracture_type": "Conductive",
            "center_depth_m": 1005.0,
            "amplitude_m": 2.2,
            "phase_deg": 180.0,
            "confidence": 0.77,
        }),
        action("register_candidate", "The overlaid full-period curve follows both arcs", candidate={
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "depth_top": 1002.0,
            "depth_bottom": 1008.0,
            "confidence": 0.88,
            "continuity_reason": "one sinusoid bridges both fragments and closes at the seam",
        }),
        action("finish_exploration", "The interval is fully inspected"),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    source = rendered()

    candidates, diagnostics = pipeline.complete_workflow.explore_candidate_windows(
        request(),
        source,
        client=client,
        model="vision-model",
    )

    assert [item["candidate_id"] for item in candidates] == ["F1"]
    assert [item["fragment_id"] for item in diagnostics["trace_fragments"]] == ["T1", "T2"]
    assert diagnostics["sinusoid_hypotheses"][0]["hypothesis_id"] == "H1"
    assert diagnostics["sinusoid_hypotheses"][0]["revision"] == 1
    assert candidates[0]["agent_hypothesis_verified"] is True
    assert candidates[0]["agent_hypothesis_id"] == "H1"
    assert candidates[0]["agent_fragment_ids"] == ["T1", "T2"]
    assert diagnostics["views"][-1]["variant"] == "hypothesis:H1:r1"
    hypothesis_image = completions.calls[3]["messages"][1]["content"][1]["image_url"]["url"]
    assert hypothesis_image != source["data_url"]
    prompt = completions.calls[3]["messages"][1]["content"][0]["text"]
    assert "test_sinusoid_hypothesis" in prompt
    assert "T1" in prompt and "T2" in prompt


def test_candidate_crop_keeps_only_depth_and_target_with_exact_depth_mapping():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    crop = pipeline.render_candidate_window(
        rendered(),
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "depth_top": 1004.0,
            "depth_bottom": 1005.0,
            "confidence": 0.9,
        },
        "Track 1 / IMAGE",
    )

    metadata = crop["metadata"]
    assert metadata["depth_start"] == pytest.approx(1003.8)
    assert metadata["depth_end"] == pytest.approx(1005.2)
    assert [track["label"] for track in metadata["tracks"]] == ["Depth", "Track 1 / IMAGE"]
    assert metadata["uniform_scale"] == 1.0
    assert (metadata["width"], metadata["height"]) == (800, 70)


def test_parameter_review_prefers_absolute_parameters_and_generates_standard_points(monkeypatch):
    completions = SequenceCompletions([{
        "action": "adjust_parameters",
        "view": None,
        "aligned": False,
        "center_depth_m": 1005.0,
        "amplitude_m": 0.5,
        "phase_deg": 90.0,
        "corrected_points": [],
        "confidence": 0.82,
        "reason": "adjust amplitude and phase",
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(
        Config(),
        client_factory=lambda _config: client,
        evidence_scorer=Scorer(),
    )
    monkeypatch.setattr(pipeline, "_build_feedback_image", lambda *_args: _png_data_url())
    focused = rendered()
    result = pipeline.review_candidate_parameters(
        request(),
        focused,
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "points": [[0, 1005.0], [90, 1005.2], [180, 1005.0]],
        },
        round_number=1,
    )

    assert result["action"] == "adjust_parameters"
    assert result["parameters"]["center_depth_m"] == pytest.approx(1005.0)
    assert result["parameters"]["amplitude_m"] == pytest.approx(0.5)
    assert result["parameters"]["phase_deg"] == pytest.approx(90.0)
    assert 3 <= len(result["corrected_points"]) <= 7
    assert result["corrected_local_completeness"]["complete"] is True


def test_parameter_review_can_inspect_multiple_views_before_adjusting(monkeypatch):
    def review_payload(action, *, view=None, center=None, amplitude=None, phase=None, reason=""):
        return {
            "action": action,
            "view": view,
            "aligned": False,
            "center_depth_m": center,
            "amplitude_m": amplitude,
            "phase_deg": phase,
            "corrected_points": [],
            "confidence": 0.84,
            "reason": reason,
        }

    completions = SequenceCompletions([
        review_payload("inspect_view", view={
            "depth_start": 1003.0,
            "depth_end": 1007.0,
            "azimuth_start_deg": 90.0,
            "azimuth_end_deg": 270.0,
            "detail_level": "close",
            "include_depth_track": False,
        }, reason="Inspect the obscured middle azimuths"),
        review_payload(
            "adjust_parameters",
            center=1005.0,
            amplitude=0.5,
            phase=90.0,
            reason="Premature adjustment from a partial view",
        ),
        review_payload("inspect_view", view={
            "depth_start": 1002.0,
            "depth_end": 1008.0,
            "azimuth_start_deg": 0.0,
            "azimuth_end_deg": 360.0,
            "detail_level": "detail",
            "include_depth_track": True,
        }, reason="Confirm the adjusted shape across the full circumference"),
        review_payload(
            "adjust_parameters",
            center=1005.0,
            amplitude=0.5,
            phase=90.0,
            reason="Full-width evidence supports the correction",
        ),
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(
        Config(),
        client_factory=lambda _config: client,
        evidence_scorer=Scorer(),
    )
    recorded = []
    focused = pipeline.render_candidate_window(
        rendered(),
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "depth_top": 1003.0,
            "depth_bottom": 1007.0,
            "confidence": 0.9,
        },
        "Track 1 / IMAGE",
    )
    result = pipeline.review_candidate_parameters(
        request(),
        focused,
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "points": [[0, 1005.0], [90, 1005.2], [180, 1005.0], [270, 1004.8], [360, 1005.0]],
        },
        source_rendered=rendered(),
        view_recorder=lambda view_id, payload: recorded.append((view_id, payload)),
    )

    assert result["action"] == "adjust_parameters"
    assert result["review_action_count"] == 2
    assert len(result["review_views"]) == 1
    assert len(recorded) == 1


def test_visual_keep_is_not_blocked_by_advisory_local_completeness(monkeypatch):
    payload = {
        "action": "keep",
        "view": None,
        "aligned": True,
        "center_depth_m": None,
        "amplitude_m": None,
        "phase_deg": None,
        "corrected_points": [],
        "confidence": 0.9,
        "reason": "aligned",
    }
    monkeypatch.setattr(FractureVisionPipeline, "_build_feedback_image", lambda *_args: _png_data_url())

    def run(scorer):
        completions = SequenceCompletions([payload])
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client, evidence_scorer=scorer)
        return pipeline.review_candidate_parameters(
            request(), rendered(),
            {"candidate_id": "F1", "fracture_type": "Conductive", "points": [[0, 1005], [180, 1005.2], [360, 1005]]},
        )

    failed = run(Scorer(available=True, complete=False))
    unavailable = run(Scorer(available=False, complete=False))
    assert failed["aligned"] is True
    assert failed["action"] == "keep"
    assert failed["needs_review"] is True
    assert unavailable["aligned"] is True
    assert unavailable["needs_review"] is True


def test_visual_keep_with_complete_local_score_needs_no_review(monkeypatch):
    payload = {
        "action": "keep",
        "view": None,
        "aligned": True,
        "center_depth_m": None,
        "amplitude_m": None,
        "phase_deg": None,
        "corrected_points": [],
        "confidence": 0.9,
        "reason": "aligned",
    }
    completions = SequenceCompletions([payload])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    monkeypatch.setattr(FractureVisionPipeline, "_build_feedback_image", lambda *_args: _png_data_url())
    pipeline = FractureVisionPipeline(
        Config(),
        client_factory=lambda _config: client,
        evidence_scorer=Scorer(available=True, complete=True),
    )

    result = pipeline.review_candidate_parameters(
        request(), rendered(),
        {"candidate_id": "F1", "fracture_type": "Conductive", "points": [[0, 1005], [180, 1005.2], [360, 1005]]},
    )

    assert result["action"] == "keep"
    assert result["aligned"] is True
    assert result["needs_review"] is False


def test_batch_audit_applies_nms_before_visual_keep_decisions():
    completions = SequenceCompletions([{
        "action": "finalize_audit",
        "reason": "All candidates were checked on the full-width overview",
        "view": None,
        "decisions": [
            {"candidate_id": "F1", "action": "keep", "reason": "complete"},
            {"candidate_id": "F2", "action": "keep", "reason": "complete"},
        ],
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client, evidence_scorer=Scorer())

    def candidate(candidate_id, center, confidence):
        return {
            "type": "sinusoidal_fracture",
            "candidate_id": candidate_id,
            "fracture_type": "Conductive",
            "confidence": confidence,
            "local_completeness": {"score": 3.0, "complete": True},
            **annotation_from_fracture_parameters(center, 0.4, 45.0),
        }

    result = pipeline.audit_candidate_batch(
        request(),
        rendered(),
        [candidate("F1", 1004.0, 0.95), candidate("F1-copy", 1004.01, 0.8), candidate("F2", 1007.0, 0.9)],
    )

    assert [item["candidate_id"] for item in result["kept"]] == ["F1", "F2"]
    assert result["discarded"][0]["candidate_id"] == "F1-copy"
    assert result["discarded"][0]["stage"] == "nms"


def test_batch_audit_overlay_uses_fracture_type_colors():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    candidates = [
        {
            "candidate_id": candidate_id,
            "fracture_type": fracture_type,
            **annotation_from_fracture_parameters(1003.0 + index * 2.0, 0.3, 180.0),
        }
        for index, (candidate_id, fracture_type) in enumerate((
            ("F1", "Conductive"),
            ("F2", "Resistive"),
            ("F3", "Bedding"),
        ))
    ]

    pipeline.complete_workflow._build_batch_feedback_image(
        rendered(), candidates, "Track 1 / IMAGE"
    )

    assert [item["_audit_color"] for item in candidates] == [
        "#0099CC", "#FF2D2D", "#16A951",
    ]


def test_batch_audit_can_finalize_from_partial_evidence_when_other_sectors_are_unclear():
    decisions = [
        {"candidate_id": "F1", "action": "keep", "reason": "complete"},
        {"candidate_id": "F2", "action": "discard", "reason": "local fragment"},
    ]
    completions = SequenceCompletions([
        {
            "action": "inspect_view",
            "reason": "Inspect the right half where the traces are weak",
            "view": {
                "depth_start": 1002.0,
                "depth_end": 1008.0,
                "azimuth_start_deg": 180.0,
                "azimuth_end_deg": 360.0,
                "detail_level": "close",
                "include_depth_track": False,
            },
            "decisions": [],
        },
        {
            "action": "finalize_audit",
            "reason": "Premature decision from a partial view",
            "view": None,
            "decisions": decisions,
        },
        {
            "action": "inspect_view",
            "reason": "Return to a full-width comparison",
            "view": {
                "depth_start": 1001.0,
                "depth_end": 1009.0,
                "azimuth_start_deg": 0.0,
                "azimuth_end_deg": 360.0,
                "detail_level": "detail",
                "include_depth_track": True,
            },
            "decisions": [],
        },
        {
            "action": "finalize_audit",
            "reason": "Every candidate was checked across the full circumference",
            "view": None,
            "decisions": decisions,
        },
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client, evidence_scorer=Scorer())

    def candidate(candidate_id, center):
        return {
            "type": "sinusoidal_fracture",
            "candidate_id": candidate_id,
            "fracture_type": "Conductive",
            "confidence": 0.9,
            "local_completeness": {"score": 3.0, "complete": True},
            **annotation_from_fracture_parameters(center, 0.35, 45.0),
        }

    recorded = []
    result = pipeline.audit_candidate_batch(
        request(),
        rendered(),
        [candidate("F1", 1004.0), candidate("F2", 1007.0)],
        view_recorder=lambda view_id, payload: recorded.append((view_id, payload)),
    )

    assert [item["candidate_id"] for item in result["kept"]] == ["F1"]
    assert result["discarded"][0]["candidate_id"] == "F2"
    assert result["audit_action_count"] == 2
    assert len(result["audit_views"]) == 1
    assert len(recorded) == 1


def test_batch_audit_budget_exhaustion_keeps_nms_results_for_review():
    class InvalidAuditCompletions:
        def create(self, **_kwargs):
            return response({
                "action": "finalize_audit",
                "reason": "Missing candidate decisions",
                "view": None,
                "decisions": [],
            })

    client = SimpleNamespace(chat=SimpleNamespace(completions=InvalidAuditCompletions()))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client, evidence_scorer=Scorer())
    candidate = {
        "type": "sinusoidal_fracture",
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "confidence": 0.9,
        "local_completeness": {"score": 3.0, "complete": True},
        **annotation_from_fracture_parameters(1004.0, 0.35, 45.0),
    }

    result = pipeline.audit_candidate_batch(request(), rendered(), [candidate])

    assert [item["candidate_id"] for item in result["kept"]] == ["F1"]
    assert result["kept"][0]["needs_review"] is True
    assert result["audit_status"] == "budget_exhausted_fallback"
    assert result["audit_action_count"] == 12
    assert result["discarded"] == []


def test_batch_audit_conflict_keeps_strong_candidate_for_human_review():
    completions = SequenceCompletions([{
        "action": "finalize_audit",
        "reason": "The visible portions are ambiguous",
        "view": None,
        "decisions": [{
            "candidate_id": "F1",
            "action": "discard",
            "reason": "The curve may cross unrelated horizontal textures",
        }],
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    candidate = {
        "type": "sinusoidal_fracture",
        "candidate_id": "F1",
        "fracture_type": "Resistive",
        "confidence": 0.94,
        "ai_alignment_status": "aligned",
        "agent_hypothesis_verified": True,
        "agent_hypothesis_id": "H1",
        "local_completeness": {"available": True, "score": 2.8, "complete": True},
        **annotation_from_fracture_parameters(1005.0, 0.7, 180.0),
    }

    result = pipeline.audit_candidate_batch(request(), rendered(), [candidate])

    assert [item["candidate_id"] for item in result["kept"]] == ["F1"]
    assert result["discarded"] == []
    assert result["kept"][0]["needs_review"] is True
    assert result["kept"][0]["batch_audit_status"] == "kept_after_audit_conflict"
    assert "unrelated horizontal textures" in result["kept"][0]["batch_audit_conflict_reason"]


def test_backend_audit_failure_keeps_nms_results_and_marks_review(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    candidates = [
        {
            "type": "sinusoidal_fracture",
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "confidence": 0.9,
            **annotation_from_fracture_parameters(1004.0, 0.35, 45.0),
        },
        {
            "type": "sinusoidal_fracture",
            "candidate_id": "F1-copy",
            "fracture_type": "Conductive",
            "confidence": 0.7,
            **annotation_from_fracture_parameters(1004.01, 0.35, 45.0),
        },
    ]
    monkeypatch.setattr(workflow, "audit_candidate_batch", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    result = workflow._audit_staged_candidates(request(), Context(), rendered(), candidates)

    assert result["audit_status"] == "failed_fallback"
    assert [item["candidate_id"] for item in result["kept"]] == ["F1"]
    assert result["kept"][0]["needs_review"] is True
    assert result["kept"][0]["batch_audit_error"] == "offline"
    assert result["discarded"][0]["candidate_id"] == "F1-copy"


def test_pipeline_falls_back_to_json_object_for_compatible_providers():
    formats = []

    class Completions:
        def create(self, **kwargs):
            formats.append(kwargs["response_format"]["type"])
            if len(formats) == 1:
                raise RuntimeError("response_format json_schema is not supported")
            return response({
                "action": "finish_exploration",
                "reason": "No complete fractures are visible",
                "view": None,
                "candidate": None,
            })

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    assert pipeline.detect(request(), Context(), rendered()) == []
    assert formats == ["json_schema", "json_object"]


def test_pipeline_rejects_missing_target_track_metadata_before_model_call():
    payload = rendered()
    payload["metadata"]["tracks"] = payload["metadata"]["tracks"][:1]
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: None)))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    with pytest.raises(ValueError, match="Target image track"):
        pipeline.detect(request(), Context(), payload)


def test_start_tool_renders_then_applies_one_completed_batch(monkeypatch):
    applied = []

    class Widget:
        def get_plot_details(self):
            return {
                "window_title": "Log Plot 1",
                "tracks": [
                    {"index": 0, "name": "GR", "label": "GR", "curves": [{"name": "GR", "is_image": False}]},
                    {
                        "index": 1,
                        "name": "Track 1",
                        "label": "Track 1 / IMAGE",
                        "curves": [{"name": "IMAGE", "is_image": True}],
                    },
                ],
            }

        def render_analysis_tracks(self, tracks, depth_start, depth_end, **kwargs):
            payload = rendered()
            assert list(tracks) == ["GR", "Track 1 / IMAGE"]
            assert (depth_start, depth_end) == (1000.0, 1010.0)
            return {"png_bytes": b"png", "metadata": payload["metadata"]}

        def apply_ai_fracture_results(self, target, annotations):
            assert target == "Track 1 / IMAGE"
            applied.extend(annotations)
            return annotations

    widget = Widget()
    sub = SimpleNamespace(windowTitle=lambda: "Log Plot 1", widget=lambda: widget)
    main_window = SimpleNamespace(mdi_area=SimpleNamespace(subWindowList=lambda: [sub]))

    class Pipeline:
        def detect(self, run_request, context, input_payload):
            assert input_payload["data_url"].startswith("data:image/png;base64,")
            return [{"type": "sinusoidal_fracture", "offset": 1005.0, "target_track_label": run_request.target_image_track}]

    monkeypatch.setattr("plugins.ai_assistant.tools.fracture_detection_tool.FractureVisionPipeline", Pipeline)
    result = StartFractureDetectionTool(main_window=main_window).execute(
        window_id="Log Plot 1",
        tracks=["GR", "Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000,
        depth_end=1010,
        fracture_types=["Conductive"],
    )
    run_id = result["run"]["run_id"]
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        status = get_fracture_detection_manager().get_status(run_id)
        if status["status"] in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.01)

    assert status["status"] == "completed"
    assert status["result_count"] == 1
    assert len(applied) == 1
