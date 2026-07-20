import base64
import json
import time
from dataclasses import replace
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
from plugins.ai_assistant.services.fracture_complete_workflow import (
    FAST_BATCH_AUDIT_SCHEMA,
    FAST_PARAMETER_REVIEW_SCHEMA,
    FINAL_PARAMETER_REVIEW_SCHEMA,
    WINDOW_ASSESSMENT_SCHEMA,
)
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


def test_feedback_image_uses_large_visible_anchor_markers():
    feedback = FractureVisionPipeline._build_feedback_image(
        rendered(),
        [[0, 1005.0], [180, 1005.2], [360, 1005.0]],
        "Track 1 / IMAGE",
    )
    image = QImage.fromData(base64.b64decode(feedback.split(",", 1)[1]), "PNG")
    yellow_x = []
    for y in range(340, 381):
        for x in range(480, 521):
            color = image.pixelColor(x, y)
            if color.red() > 220 and color.green() > 180 and color.blue() < 80:
                yellow_x.append(x)

    assert max(yellow_x) - min(yellow_x) >= 18


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


def _provisional_candidate(candidate_id, center, amplitude, phase, azimuths, *, depth_top, depth_bottom):
    parameters = annotation_from_fracture_parameters(center, amplitude, phase)
    radians = np.deg2rad(np.asarray(azimuths, dtype=float))
    depths = center + amplitude * np.sin(radians + np.deg2rad(phase))
    points = [[float(azimuth), float(depth)] for azimuth, depth in zip(azimuths, depths)]
    candidate = {
        "candidate_id": candidate_id,
        "fracture_type": "Conductive",
        "depth_top": depth_top,
        "depth_bottom": depth_bottom,
        "confidence": 0.9,
    }
    return {
        "candidate": candidate,
        "candidate_rendered": rendered(),
        "annotation": {
            "candidate_id": candidate_id,
            "fracture_type": "Conductive",
            "confidence": 0.9,
            "points": points,
            **parameters,
        },
        "evaluation": {"candidate": dict(candidate), "status": "fitted"},
        "anchor_response": {"points": points},
        "points": points,
    }


def test_association_merges_complementary_partial_candidate_fits_before_review():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    provisional = [
        _provisional_candidate(
            "F1", 1005.10, 0.60, 180.0, [0, 45, 90, 135],
            depth_top=1004.45, depth_bottom=1005.20,
        ),
        _provisional_candidate(
            "F2", 1004.92, 0.62, 187.0, [180, 225, 270, 315],
            depth_top=1004.80, depth_bottom=1005.65,
        ),
    ]

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), rendered(), provisional,
    )

    assert len(associated) == 1
    merged = associated[0]
    assert merged["annotation"]["associated_candidate_ids"] == ["F1", "F2"]
    assert merged["annotation"]["association_status"] == "merged_complementary_fragments"
    assert "fragment_association_status" not in merged["annotation"]
    assert len(merged["annotation"]["points"]) == 8
    assert diagnostics["input_count"] == 2
    assert diagnostics["output_count"] == 1
    assert diagnostics["comparisons"][0]["compatible"] is True
    assert merged["candidate_rendered"]["metadata"]["depth_start"] < 1004.45
    assert merged["candidate_rendered"]["metadata"]["depth_end"] > 1005.65


def test_short_trace_fragments_merge_and_promote_before_review():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    first = _provisional_candidate(
        "F1", 1005.0, 0.6, 180.0, [0, 30, 60],
        depth_top=1004.4, depth_bottom=1005.2,
    )
    second = _provisional_candidate(
        "F2", 1005.0, 0.6, 180.0, [180, 210, 240],
        depth_top=1004.8, depth_bottom=1005.6,
    )
    for item in (first, second):
        item["fragment_only"] = True
        item["annotation"]["anchor_evidence_status"] = "fragment"
        item["annotation"]["anchor_azimuth_span_deg"] = 60.0

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), rendered(), [first, second],
    )

    assert len(associated) == 1
    assert diagnostics["comparisons"][0]["fragment_involved"] is True
    assert associated[0]["fragment_only"] is False
    assert associated[0]["annotation"]["fragment_association_status"] == "promoted"
    assert associated[0]["annotation"]["associated_fragment_candidate_ids"] == ["F1", "F2"]
    assert associated[0]["annotation"]["anchor_azimuth_span_deg"] >= 90.0


def test_unresolved_short_trace_fragment_does_not_reach_review():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    fragment = _provisional_candidate(
        "F1", 1005.0, 0.6, 180.0, [0, 30, 60],
        depth_top=1004.4, depth_bottom=1005.2,
    )
    fragment["fragment_only"] = True
    fragment["annotation"]["anchor_evidence_status"] = "fragment"
    fragment["annotation"]["anchor_azimuth_span_deg"] = 60.0
    discarded = []

    resolved, unresolved = pipeline.complete_workflow._remove_unresolved_trace_fragments(
        [fragment], discarded, Context(),
    )

    assert resolved == []
    assert unresolved[0]["candidate_id"] == "F1"
    assert unresolved[0]["stage"] == "fragment_association"
    assert discarded == unresolved
    assert fragment["evaluation"]["status"] == "unresolved_trace_fragment"


def test_association_does_not_merge_similar_fits_without_complementary_anchors():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    provisional = [
        _provisional_candidate(
            "F1", 1005.00, 0.50, 180.0, [0, 45, 90, 135],
            depth_top=1004.4, depth_bottom=1005.2,
        ),
        _provisional_candidate(
            "F2", 1005.10, 0.52, 184.0, [0, 45, 90, 135],
            depth_top=1004.5, depth_bottom=1005.3,
        ),
    ]

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), rendered(), provisional,
    )

    assert len(associated) == 2
    assert diagnostics["comparisons"][0]["compatible"] is False
    assert diagnostics["comparisons"][0]["complementary_anchors"] is False


def test_association_uses_merged_fit_when_partial_fit_centers_are_biased():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    source = rendered()
    source["metadata"] = dict(source["metadata"], depth_start=8074.0, depth_end=8077.0)
    left = _provisional_candidate(
        "F1", 8075.136515708297, 0.44661668383529435, 164.13578848033777,
        [19.8, 37.8, 59.4, 81.0, 113.4, 135.0, 160.2, 178.2],
        depth_top=8074.55, depth_bottom=8075.15,
    )
    left["points"] = left["annotation"]["points"] = [
        [19.8, 8075.0705], [37.8, 8074.9895], [59.4, 8074.8545],
        [81.0, 8074.7375], [113.4, 8074.6835], [135.0, 8074.7285],
        [160.2, 8074.8545], [178.2, 8075.0345],
    ]
    right = _provisional_candidate(
        "F2", 8075.457193485556, 0.5288014624086544, 181.95744309755756,
        [206.28, 219.24, 231.12, 246.96, 268.2, 293.4, 314.64],
        depth_top=8075.7, depth_bottom=8076.15,
    )
    right["points"] = right["annotation"]["points"] = [
        [206.28, 8075.7225], [219.24, 8075.79], [231.12, 8075.8725],
        [246.96, 8075.95125], [268.2, 8075.99625], [293.4, 8075.93625],
        [314.64, 8075.81625],
    ]

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), source, [left, right],
    )

    comparison = diagnostics["comparisons"][0]
    assert comparison["center_compatible"] is False
    assert comparison["merged_fit"]["rmse_m"] == pytest.approx(0.094208754, rel=1e-5)
    assert comparison["merged_fit"]["acceptable"] is True
    assert comparison["compatible"] is True
    assert len(associated) == 1
    assert associated[0]["annotation"]["associated_candidate_ids"] == ["F1", "F2"]


def test_association_threshold_uses_complete_merged_amplitude_for_complementary_halves():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    source = rendered()
    source["metadata"] = dict(source["metadata"], depth_start=8074.0, depth_end=8077.0)
    left = _provisional_candidate(
        "F1", 8075.157396395763, 0.4392724834929531, 175.65490285784384,
        [11.88, 38.16, 70.56, 114.48, 134.64, 155.16, 172.8],
        depth_top=8074.66, depth_bottom=8075.18,
    )
    left["points"] = left["annotation"]["points"] = [
        [11.88, 8075.0717], [38.16, 8074.94542], [70.56, 8074.76584],
        [114.48, 8074.7191], [134.64, 8074.81668], [155.16, 8074.94788],
        [172.8, 8075.08154],
    ]
    right = _provisional_candidate(
        "F2", 8075.717330147055, 0.3112562244390441, 161.89844913818362,
        [197.28, 209.88, 221.4, 232.56, 250.2, 265.68, 297.36, 333.36],
        depth_top=8075.66, depth_bottom=8076.08,
    )
    right["points"] = right["annotation"]["points"] = [
        [197.28, 8075.67992], [209.88, 8075.77784], [221.4, 8075.86496],
        [232.56, 8075.92328], [250.2, 8075.97224], [265.68, 8075.99168],
        [297.36, 8075.98448], [333.36, 8075.96216],
    ]

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), source, [left, right],
    )

    merged_fit = diagnostics["comparisons"][0]["merged_fit"]
    assert merged_fit["rmse_m"] == pytest.approx(0.105713976, rel=1e-5)
    assert merged_fit["threshold_m"] == pytest.approx(0.12)
    assert merged_fit["acceptable"] is True
    assert len(associated) == 1


def test_stable_fit_azimuth_span_uses_shortest_circular_coverage():
    workflow = FractureVisionPipeline(Config()).complete_workflow

    assert workflow._azimuth_coverage_span([[350, 1], [5, 1], [20, 1]]) == pytest.approx(30.0)
    assert workflow._azimuth_coverage_span([[190, 1], [203, 1], [219, 1]]) == pytest.approx(29.0)
    assert workflow._azimuth_coverage_span([[10, 1], [100, 1], [190, 1]]) == pytest.approx(180.0)


def test_cross_window_nms_prefers_complete_fit_over_partial_fit_of_same_trace():
    workflow = FractureVisionPipeline(Config()).complete_workflow

    def candidate(candidate_id, center, amplitude, phase, azimuths, *, pass_kind, complete, confidence):
        annotation = annotation_from_fracture_parameters(center, amplitude, phase)
        points = [
            [float(azimuth), center + amplitude * np.sin(np.deg2rad(azimuth + phase))]
            for azimuth in azimuths
        ]
        return {
            **annotation,
            "candidate_id": candidate_id,
            "fracture_type": "Resistive",
            "confidence": confidence,
            "points": points,
            "final_points": points,
            "local_completeness": {"complete": complete, "score": 2.85 if complete else 2.70},
            "detection_pass_kind": pass_kind,
            "sliding_window_index": None if pass_kind == "merged_observation" else 4,
            "merged_observation_group": 1 if pass_kind == "merged_observation" else None,
        }

    complete = candidate(
        "G1-F2", 8079.185793233563, 0.31137306482717053, 176.56881825712904,
        [28.8, 57.6, 111.6, 194.4, 237.6, 284.4, 327.6],
        pass_kind="merged_observation", complete=True, confidence=0.60,
    )
    partial = candidate(
        "W4-F1", 8079.258749472609, 0.19667245240448475, 166.34319510315075,
        [195.84, 210.6, 229.68, 265.32, 293.4, 329.76, 354.96],
        pass_kind="primary_window", complete=False, confidence=0.72,
    )

    source = rendered()
    source["metadata"] = dict(source["metadata"], depth_start=8078.0, depth_end=8081.5)
    kept, discarded = workflow._non_maximum_suppression([partial, complete], source)

    assert [item["candidate_id"] for item in kept] == ["G1-F2"]
    assert discarded[0]["candidate_id"] == "W4-F1"
    assert discarded[0]["duplicate_metrics"]["mean_curve_distance_px"] > 8.0
    assert discarded[0]["duplicate_metrics"]["subset_anchor_alignment"] >= 0.70


def test_cross_window_association_merges_complementary_primary_window_fits():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow

    def candidate(candidate_id, window_index, azimuths):
        center, amplitude, phase = 1005.0, 0.60, 180.0
        points = [
            [float(azimuth), center + amplitude * np.sin(np.deg2rad(azimuth + phase))]
            for azimuth in azimuths
        ]
        return {
            **annotation_from_fracture_parameters(center, amplitude, phase),
            "candidate_id": candidate_id,
            "fracture_type": "Resistive",
            "confidence": 0.8,
            "points": points,
            "final_points": points,
            "sliding_window_index": window_index,
            "detection_pass_kind": "primary_window",
        }

    associated, diagnostics = workflow.associate_annotations_across_windows(
        request(),
        Context(),
        rendered(),
        [
            candidate("W1-F1", 1, [0, 45, 90, 135]),
            candidate("W2-F1", 2, [180, 225, 270, 315]),
        ],
    )

    assert len(associated) == 1
    assert associated[0]["detection_pass_kind"] == "cross_window_association"
    assert associated[0]["associated_candidate_ids"] == ["W1-F1", "W2-F1"]
    assert diagnostics["groups"][0]["source_candidate_ids"] == ["W1-F1", "W2-F1"]


def test_merged_review_plan_adds_adjacent_window_at_fit_boundary():
    workflow = FractureVisionPipeline(Config(), evidence_scorer=Scorer()).complete_workflow
    annotation = {
        **annotation_from_fracture_parameters(1005.2, 0.2, 180.0),
        "candidate_id": "W2-F1",
        "sliding_window_index": 2,
    }

    plan = workflow._merged_review_plan(
        replace(request(), sliding_window_m=3.0), annotation, round_number=1,
    )

    assert plan["source_window_indices"] == [2, 3]
    assert plan["depth_range"] == pytest.approx([1002.4, 1007.8])
    assert "lower window boundary" in " ".join(plan["reasons"])


def test_merged_review_plan_uses_cross_window_sources_and_caps_context_at_three_windows():
    workflow = FractureVisionPipeline(Config(), evidence_scorer=Scorer()).complete_workflow
    annotation = {
        **annotation_from_fracture_parameters(1005.0, 0.6, 180.0),
        "candidate_id": "X-W1-F1+W2-F1",
        "associated_candidate_ids": ["W1-F1", "W2-F1"],
        "detection_pass_kind": "cross_window_association",
    }

    plan = workflow._merged_review_plan(
        replace(request(), sliding_window_m=3.0), annotation, round_number=1,
    )

    assert plan["source_window_indices"] == [1, 2, 3]
    assert plan["depth_range"] == pytest.approx([1000.0, 1007.8])
    assert "cross-window candidate association" in plan["reasons"]


def test_merged_review_plan_expands_after_parameter_correction():
    workflow = FractureVisionPipeline(Config(), evidence_scorer=Scorer()).complete_workflow
    annotation = {
        **annotation_from_fracture_parameters(1004.0, 0.1, 180.0),
        "candidate_id": "W2-F1",
        "sliding_window_index": 2,
    }

    sliding_request = replace(request(), sliding_window_m=3.0)
    first = workflow._merged_review_plan(sliding_request, annotation, round_number=1)
    second = workflow._merged_review_plan(
        sliding_request, annotation, round_number=2, previous_action="adjust_parameters",
    )

    assert first is None
    assert second["source_window_indices"] == [1, 2, 3]
    assert second["depth_range"] == pytest.approx([1000.0, 1007.8])


def test_candidate_review_rerenders_conditional_merged_context(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    view_requests = []
    review_metadata = []

    def provide(view_request):
        view_requests.append(view_request)
        payload = rendered()
        payload["metadata"] = dict(
            payload["metadata"],
            depth_start=view_request.depth_start,
            depth_end=view_request.depth_end,
        )
        return payload

    pipeline.agent_view_provider = provide

    def review(_request, candidate_rendered, annotation, **_kwargs):
        review_metadata.append(candidate_rendered["metadata"])
        return {
            "action": "keep",
            "aligned": True,
            "decision_continuity": "initial",
            "confidence": 0.9,
            "reason": "aligned in merged context",
            "corrected_points": [],
            "parameters": {
                "center_depth_m": 1005.2,
                "amplitude_m": 0.2,
                "phase_deg": 180.0,
            },
            "local_completeness": {
                "available": True,
                "complete": True,
                "score": 3.0,
                "coverage": 0.8,
                "min_quadrant_coverage": 0.7,
            },
            "corrected_local_completeness": None,
            "needs_review": False,
            "review_views": [],
            "review_events": [],
            "review_action_count": 1,
        }

    monkeypatch.setattr(workflow, "review_candidate_parameters", review)
    annotation = {
        **annotation_from_fracture_parameters(1005.2, 0.2, 180.0),
        "candidate_id": "W2-F1",
        "fracture_type": "Conductive",
        "sliding_window_index": 2,
        "points": [[0, 1005.2], [90, 1005.0], [180, 1005.2], [270, 1005.4]],
        "ai_final_parameters": {
            "center_depth_m": 1005.2,
            "amplitude_m": 0.2,
            "phase_deg": 180.0,
        },
    }

    kept, discarded = workflow._review_candidate_until_final(
        replace(request(), sliding_window_m=3.0),
        Context(),
        rendered(),
        rendered(),
        annotation,
        index=0,
        total=1,
    )

    assert discarded is None
    assert kept["candidate_id"] == "W2-F1"
    assert len(view_requests) == 1
    assert [view_requests[0].depth_start, view_requests[0].depth_end] == pytest.approx(
        [1002.4, 1007.8]
    )
    assert review_metadata[0]["render_mode"] == "plot_data_rerender"
    assert review_metadata[0]["merged_review_context"]["source_window_indices"] == [2, 3]


def test_cross_window_association_does_not_merge_candidates_from_same_window():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    first = {
        **annotation_from_fracture_parameters(1005.0, 0.60, 180.0),
        "candidate_id": "W1-F1",
        "fracture_type": "Resistive",
        "points": [[0, 1005.0], [45, 1004.58], [90, 1004.4], [135, 1004.58]],
        "sliding_window_index": 1,
    }
    second = {
        **annotation_from_fracture_parameters(1005.0, 0.60, 180.0),
        "candidate_id": "W1-F2",
        "fracture_type": "Resistive",
        "points": [[180, 1005.0], [225, 1005.42], [270, 1005.6], [315, 1005.42]],
        "sliding_window_index": 1,
    }

    associated, diagnostics = workflow.associate_annotations_across_windows(
        request(), Context(), rendered(), [first, second],
    )

    assert len(associated) == 2
    assert diagnostics["groups"] == []


def test_cross_window_association_preserves_existing_same_window_merge_identity():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    annotation = {
        **annotation_from_fracture_parameters(1005.0, 0.60, 180.0),
        "candidate_id": "W2-F1",
        "fracture_type": "Resistive",
        "points": [[0, 1005.0], [90, 1004.4], [180, 1005.0], [270, 1005.6]],
        "final_points": [[0, 1005.0], [90, 1004.4], [180, 1005.0], [270, 1005.6]],
        "associated_candidate_ids": ["W2-F1", "W2-F2"],
        "sliding_window_index": 2,
        "detection_pass_kind": "primary_window",
    }

    associated, diagnostics = workflow.associate_annotations_across_windows(
        request(), Context(), rendered(), [annotation],
    )

    assert associated[0]["candidate_id"] == "W2-F1"
    assert associated[0]["detection_pass_kind"] == "primary_window"
    assert associated[0]["associated_candidate_ids"] == ["W2-F1", "W2-F2"]
    assert diagnostics["groups"] == []


def test_secondary_nms_does_not_merge_parameter_similar_candidates_from_same_pass():
    workflow = FractureVisionPipeline(Config()).complete_workflow
    first = {
        **annotation_from_fracture_parameters(1005.0, 0.30, 175.0),
        "candidate_id": "F1",
        "fracture_type": "Resistive",
        "confidence": 0.8,
        "points": [[200.0, 1005.1], [240.0, 1005.2], [280.0, 1005.25]],
        "detection_pass_kind": "primary_window",
        "sliding_window_index": 2,
    }
    second = {
        **annotation_from_fracture_parameters(1005.13, 0.25, 165.0),
        "candidate_id": "F2",
        "fracture_type": "Resistive",
        "confidence": 0.75,
        "points": [[200.0, 1005.12], [240.0, 1005.18], [280.0, 1005.22]],
        "detection_pass_kind": "primary_window",
        "sliding_window_index": 2,
    }

    source = rendered()
    source["metadata"] = dict(source["metadata"], depth_start=1004.0, depth_end=1006.0)
    kept, discarded = workflow._non_maximum_suppression([first, second], source)

    assert len(kept) == 2
    assert discarded == []


def test_association_rejects_complementary_anchors_with_poor_merged_fit():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    left = _provisional_candidate(
        "F1", 1005.0, 0.60, 180.0, [0, 45, 90, 135],
        depth_top=1004.3, depth_bottom=1005.2,
    )
    right = _provisional_candidate(
        "F2", 1005.1, 0.62, 185.0, [180, 225, 270, 315],
        depth_top=1004.8, depth_bottom=1005.8,
    )
    right["points"] = [[azimuth, depth + 0.6] for azimuth, depth in right["points"]]
    right["annotation"]["points"] = right["points"]

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), rendered(), [left, right],
    )

    comparison = diagnostics["comparisons"][0]
    assert comparison["complementary_anchors"] is True
    assert comparison["merged_fit"]["acceptable"] is False
    assert comparison["compatible"] is False
    assert len(associated) == 2


def test_association_treats_partial_amplitude_difference_as_diagnostic_only():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    source = rendered()
    source["metadata"] = dict(source["metadata"], depth_start=8073.0, depth_end=8076.0)
    left = _provisional_candidate(
        "F1", 8075.222588859354, 0.4846525653237524, 177.82578005202765,
        [14.76, 32.76, 53.28, 76.68, 110.16, 133.56, 160.2],
        depth_top=8074.58, depth_bottom=8075.12,
    )
    left["points"] = left["annotation"]["points"] = [
        [14.76, 8075.0894], [32.76, 8074.99532], [53.28, 8074.87688],
        [76.68, 8074.7366], [110.16, 8074.75004], [133.56, 8074.8542],
        [160.2, 8075.05328],
    ]
    right = _provisional_candidate(
        "F2", 8075.696236085809, 0.24222402640677795, 170.62408659922318,
        [196.2, 209.52, 223.56, 237.96, 254.16, 264.96],
        depth_top=8075.74, depth_bottom=8076.0,
    )
    right["points"] = right["annotation"]["points"] = [
        [196.2, 8075.73186], [209.52, 8075.76712], [223.56, 8075.83313],
        [237.96, 8075.88602], [254.16, 8075.9139], [264.96, 8075.92907],
    ]

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), source, [left, right],
    )

    comparison = diagnostics["comparisons"][0]
    assert comparison["amplitude_compatible"] is False
    assert comparison["merged_fit"]["acceptable"] is True
    assert comparison["compatible"] is True
    assert len(associated) == 1


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


@pytest.mark.parametrize(
    ("entry_level", "classification", "should_explore"),
    [
        ("confirmed", "suspected", False),
        ("suspected", "suspected", True),
        ("confirmed", "confirmed", True),
        ("suspected", "none", False),
    ],
)
def test_window_classification_routes_into_or_past_picking(entry_level, classification, should_explore):
    pipeline = FractureVisionPipeline(Config())
    pipeline.complete_workflow.assess_window = lambda *_args, **_kwargs: {
        "classification": classification,
        "confidence": 0.74,
        "reason": "window-level triage",
        "candidates": [],
        "normalizations": [],
    }
    selected_request = FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000,
        depth_end=1010,
        fracture_types=["Conductive", "Resistive"],
        pick_entry_level=entry_level,
        fast_mode=True,
    )
    context = Context()

    assert pipeline.detect(selected_request, context, rendered()) == []
    assert context.diagnostics["window_classification"]["classification"] == classification
    assert context.diagnostics.get("skipped_before_picking", False) is (not should_explore)


def test_window_classification_prompt_defines_confirmed_as_ready_for_fitting():
    completions = SequenceCompletions([{
        "classification": "confirmed",
        "confidence": 0.8,
        "reason": "visible curved trace is ready for fitting",
        "candidates": [{
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "depth_top": 1002.0,
            "depth_bottom": 1004.0,
            "confidence": 0.8,
            "continuity_reason": "fitting-ready trace",
        }],
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    workflow = FractureVisionPipeline(
        Config(), client_factory=lambda _config: client,
    ).complete_workflow

    workflow.assess_window(request(), rendered(), client=client, model="vision-model")

    messages = json.dumps(completions.calls[0]["messages"])
    assert "Assess this borehole-image window once" in messages
    assert "does not require complete visible 0-360 coverage" in messages
    assert "window boundaries" in messages
    assert "do not split one high-amplitude trace" in messages
    assert "conductive fracture commonly appears as a narrow dark sinusoidal" in messages
    assert "resistive fracture commonly appears as a narrow bright sinusoidal" in messages
    assert "Bedding is not necessarily horizontal" in messages
    assert "cuts across several bedding bands" in messages


def test_normal_mode_keeps_triage_but_uses_autonomous_exploration():
    pipeline = FractureVisionPipeline(Config())
    assessment = {
        "classification": "confirmed",
        "confidence": 0.91,
        "reason": "clear curved fracture evidence",
        "candidates": [],
        "normalizations": [],
    }
    pipeline.complete_workflow.assess_window = lambda *_args, **_kwargs: assessment
    entered = []

    def explore(*_args, **_kwargs):
        entered.append("normal")
        return [], {"mode": "autonomous_exploration", "finished": True}

    pipeline.complete_workflow.explore_candidate_windows = explore
    selected_request = FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000,
        depth_end=1010,
        fracture_types=["Conductive", "Resistive"],
        pick_entry_level="confirmed",
        fast_mode=False,
    )

    assert pipeline.detect(selected_request, Context(), rendered()) == []
    assert entered == ["normal"]


def test_direct_candidate_pick_does_not_request_navigation_actions():
    completions = SequenceCompletions([{
        "reason": "Two candidates are visible in the current image",
        "candidates": [
            {
                "candidate_id": "F1",
                "fracture_type": "Conductive",
                "depth_top": 1002.0,
                "depth_bottom": 1004.0,
                "confidence": 0.86,
                "continuity_reason": "compatible arc across pad gaps",
            },
            {
                "candidate_id": "F2",
                "fracture_type": "Resistive",
                "depth_top": 1006.0,
                "depth_bottom": 1007.0,
                "confidence": 0.40,
                "continuity_reason": "weak local texture",
            },
        ],
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    selected_request = FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000,
        depth_end=1010,
        fracture_types=["Conductive", "Resistive"],
        min_confidence=0.6,
        pick_entry_level="confirmed",
    )

    candidates, diagnostics = pipeline.complete_workflow.pick_candidates_directly(
        selected_request,
        rendered(),
        classification={"classification": "confirmed", "confidence": 0.9},
        client=client,
        model="vision-model",
    )

    assert [item["candidate_id"] for item in candidates] == ["F1"]
    assert diagnostics["mode"] == "direct_candidate_pick"
    assert diagnostics["views"] == []
    assert diagnostics["trace_fragments"] == []
    assert diagnostics["sinusoid_hypotheses"] == []
    direct_prompt = json.dumps(completions.calls[0]["messages"])
    assert "regular, repeated family of approximately parallel curves" in direct_prompt
    assert "Distinguish a fracture from bedding by relational evidence, not orientation alone" in direct_prompt
    schema = completions.calls[0]["response_format"]["json_schema"]
    assert schema["name"] == "direct_fracture_candidates"
    assert FAST_PARAMETER_REVIEW_SCHEMA["schema"]["properties"]["action"]["enum"] == [
        "keep", "adjust_parameters", "replace_points", "discard",
    ]
    assert FAST_BATCH_AUDIT_SCHEMA["schema"]["properties"]["action"]["enum"] == [
        "finalize_audit",
    ]


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
    ]
    assert context.updates[0][0] == "exploring"
    assert "candidate_rendering" in [item[0] for item in context.updates]
    assert "reviewing" in [item[0] for item in context.updates]
    assert "auditing" in [item[0] for item in context.updates]
    assert context.updates[-1][0] == "staging"
    assert context.diagnostics["accepted_count"] == 1
    assert context.diagnostics["batch_audit"]["audit_status"] == "skipped_no_conflicts"
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
    assert metadata["depth_start"] == pytest.approx(1003.65)
    assert metadata["depth_end"] == pytest.approx(1005.35)
    assert [track["label"] for track in metadata["tracks"]] == ["Depth", "Track 1 / IMAGE"]
    assert metadata["uniform_scale"] == 1.0
    assert (metadata["width"], metadata["height"]) == (800, 86)


def test_candidate_crop_uses_plot_provider_when_padding_crosses_sliding_window_boundary():
    calls = []

    def provider(view_request):
        calls.append(view_request)
        source = rendered()
        source["metadata"] = {
            **source["metadata"],
            "depth_start": view_request.depth_start,
            "depth_end": view_request.depth_end,
        }
        return source

    pipeline = FractureVisionPipeline(
        Config(),
        evidence_scorer=Scorer(),
        agent_view_provider=provider,
    )
    source = rendered()
    source["metadata"] = {**source["metadata"], "depth_start": 1000.0, "depth_end": 1003.0}

    crop = pipeline.render_candidate_window(
        source,
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "depth_top": 1000.1,
            "depth_bottom": 1000.5,
            "confidence": 0.9,
        },
        "Track 1 / IMAGE",
    )

    assert len(calls) == 1
    assert calls[0].depth_start == pytest.approx(999.8)
    assert calls[0].depth_end == pytest.approx(1000.8)
    assert crop["metadata"]["candidate_used_external_source"] is True


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


def test_parameter_review_receives_previous_round_decision_and_deltas(monkeypatch):
    completions = SequenceCompletions([{
        "action": "keep",
        "view": None,
        "aligned": True,
        "center_depth_m": None,
        "amplitude_m": None,
        "phase_deg": None,
        "corrected_points": [],
        "confidence": 0.86,
        "decision_continuity": "maintain",
        "reason": "Maintain the previous conclusion because the geometry is unchanged.",
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(
        Config(),
        client_factory=lambda _config: client,
        evidence_scorer=Scorer(),
    )
    monkeypatch.setattr(pipeline, "_build_feedback_image", lambda *_args: _png_data_url())
    previous = {
        "round": 1,
        "action": "adjust_parameters",
        "decision_continuity": "initial",
        "confidence": 0.82,
        "reason": "The trace is aligned; retain it with a negligible adjustment.",
        "input_parameters": {
            "center_depth_m": 1005.0,
            "amplitude_m": 0.5004,
            "phase_deg": 90.04,
        },
        "output_parameters": {
            "center_depth_m": 1005.0003,
            "amplitude_m": 0.5,
            "phase_deg": 90.0,
        },
        "parameter_change": {
            "center_depth_m": 0.0003,
            "amplitude_m": -0.0004,
            "phase_deg": -0.04,
        },
        "input_local_completeness": {
            "score": 2.40,
            "coverage": 0.582,
            "min_quadrant_coverage": 0.55,
            "complete": True,
        },
        "output_local_completeness": {
            "score": 2.39,
            "coverage": 0.577,
            "min_quadrant_coverage": 0.55,
            "complete": False,
        },
        "score_change": {
            "score": -0.01,
            "coverage": -0.005,
            "min_quadrant_coverage": 0.0,
            "complete_before": True,
            "complete_after": False,
        },
    }

    result = pipeline.review_candidate_parameters(
        request(),
        rendered(),
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "points": [[0, 1005.0], [90, 1005.5], [180, 1005.0], [270, 1004.5]],
            "ai_correction_history": [previous],
        },
        round_number=2,
    )

    prompt = next(
        item["text"]
        for item in completions.calls[0]["messages"][1]["content"]
        if item.get("type") == "text"
    )
    assert '"previous_round"' in prompt
    assert '"action": "adjust_parameters"' in prompt
    assert '"coverage": -0.005' in prompt
    assert "must explicitly explain why the previous conclusion is maintained or overturned" in prompt
    assert result["decision_continuity"] == "maintain"


def test_review_loop_records_previous_parameter_and_score_changes_for_next_round(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    local_before = {
        "available": True,
        "complete": True,
        "score": 2.40,
        "coverage": 0.582,
        "min_quadrant_coverage": 0.55,
    }
    local_after = {
        "available": True,
        "complete": False,
        "score": 2.39,
        "coverage": 0.577,
        "min_quadrant_coverage": 0.55,
    }
    responses = [
        {
            "action": "adjust_parameters",
            "aligned": False,
            "confidence": 0.82,
            "decision_continuity": "initial",
            "reason": "Retain with a negligible adjustment.",
            "parameters": {
                "center_depth_m": 1005.0003,
                "amplitude_m": 0.5,
                "phase_deg": 90.0,
            },
            "corrected_points": [
                [0, 1005.5], [90, 1005.0], [180, 1004.5], [270, 1005.0],
            ],
            "local_completeness": local_before,
            "corrected_local_completeness": local_after,
        },
        {
            "action": "keep",
            "aligned": True,
            "confidence": 0.84,
            "decision_continuity": "maintain",
            "reason": "Maintain the previous conclusion.",
            "parameters": None,
            "corrected_points": [],
            "local_completeness": local_after,
            "corrected_local_completeness": None,
        },
    ]
    received = []

    def review(_request, _candidate_rendered, annotation, **_kwargs):
        received.append(json.loads(json.dumps(annotation)))
        return responses.pop(0)

    monkeypatch.setattr(workflow, "review_candidate_parameters", review)
    annotation = {
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "points": [[0, 1005.5], [90, 1005.0], [180, 1004.5], [270, 1005.0]],
        **annotation_from_fracture_parameters(1005.0, 0.5, 90.0),
    }

    kept, discard = workflow._review_candidate_until_final(
        request(), Context(), rendered(), rendered(), annotation, index=0, total=1,
    )

    assert discard is None
    assert kept["ai_alignment_status"] == "aligned"
    assert len(received) == 2
    previous = received[1]["ai_correction_history"][0]
    assert previous["action"] == "adjust_parameters"
    assert previous["decision_continuity"] == "initial"
    assert previous["parameter_change"]["amplitude_m"] == pytest.approx(0.0)
    assert previous["score_change"]["coverage"] == pytest.approx(-0.005)
    assert previous["score_change"]["complete_before"] is True
    assert previous["score_change"]["complete_after"] is False


def test_parameter_review_rejects_dynamic_view_navigation():
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

    assert result["action"] == "unsupported_inspect_view"
    assert result["review_action_count"] == 1
    assert result["review_views"] == []
    assert recorded == []


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


def test_candidate_review_compares_raw_and_overlay_images(monkeypatch):
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
        Config(), client_factory=lambda _config: client, evidence_scorer=Scorer(),
    )

    pipeline.review_candidate_parameters(
        request(), rendered(),
        {
            "candidate_id": "F1",
            "fracture_type": "Conductive",
            "points": [[0, 1005.0], [180, 1005.2], [360, 1005.0]],
        },
    )

    content = completions.calls[0]["messages"][1]["content"]
    assert len([item for item in content if item["type"] == "image_url"]) == 2
    prompt = json.dumps(content)
    assert "raw candidate review evidence" in prompt
    assert "current sine and anchors" in prompt


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
    audit_content = completions.calls[0]["messages"][1]["content"]
    assert len([item for item in audit_content if item["type"] == "image_url"]) == 2
    audit_prompt = json.dumps(audit_content)
    assert "Image 1 - raw Plot evidence without candidate curves" in audit_prompt
    assert "comparative consistency check" in audit_prompt
    assert "candidate_continuity_reason" in audit_prompt


def test_single_unflagged_candidate_skips_conflict_audit():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    candidate = {
        "type": "sinusoidal_fracture",
        "candidate_id": "F1",
        "fracture_type": "Resistive",
        "confidence": 0.9,
        "needs_review": False,
        **annotation_from_fracture_parameters(1005.0, 0.6, 180.0),
    }

    result = pipeline.complete_workflow._audit_staged_candidates(
        request(), Context(), rendered(), [candidate],
    )

    assert result["audit_status"] == "skipped_no_conflicts"
    assert result["audit_action_count"] == 0
    assert result["discarded"] == []
    assert result["kept"][0]["candidate_id"] == "F1"
    assert result["kept"][0]["needs_review"] is False
    assert result["kept"][0]["batch_audit_status"] == "skipped_no_conflicts"


def test_cross_window_identity_alone_does_not_force_visual_audit(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    candidate = {
        "type": "sinusoidal_fracture",
        "candidate_id": "X-W1-F1+W2-F1",
        "fracture_type": "Resistive",
        **annotation_from_fracture_parameters(1005.0, 0.6, 180.0),
    }
    calls = []

    def audit(*_args, **_kwargs):
        calls.append(True)
        return {
            "kept": [candidate],
            "discarded": [],
            "audit_status": "completed",
            "audit_views": [],
            "audit_events": [],
            "audit_action_count": 1,
            "audit_decisions": [{
                "candidate_id": candidate["candidate_id"],
                "action": "keep",
                "reason": "confirmed on the full Plot",
            }],
        }

    monkeypatch.setattr(pipeline.complete_workflow, "audit_candidate_batch", audit)
    result = pipeline.complete_workflow._audit_staged_candidates(
        request(), Context(), rendered(), [candidate], force_visual=True,
    )

    assert calls == []
    assert result["audit_status"] == "skipped_no_conflicts"


def test_review_discard_keeps_strong_merged_candidate_for_human_review(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    local = {
        "available": True,
        "complete": True,
        "score": 3.02,
        "coverage": 0.73,
        "min_quadrant_coverage": 0.71,
    }
    monkeypatch.setattr(workflow, "review_candidate_parameters", lambda *_args, **_kwargs: {
        "action": "discard",
        "aligned": False,
        "confidence": 0.72,
        "reason": "The curve may follow unrelated horizontal bands",
        "corrected_points": [],
        "parameters": None,
        "local_completeness": local,
        "corrected_local_completeness": None,
        "review_views": [],
        "review_events": [],
        "review_action_count": 1,
    })
    annotation = {
        "candidate_id": "F1",
        "fracture_type": "Resistive",
        "points": [[0, 1005.0], [90, 1004.4], [180, 1005.0], [270, 1005.6]],
        "local_completeness": local,
        "association_status": "merged_complementary_fragments",
        "association_merged_fit": {"available": True, "acceptable": True, "rmse_m": 0.05},
        "ai_final_parameters": {
            "center_depth_m": 1005.0,
            "amplitude_m": 0.6,
            "phase_deg": 180.0,
        },
        **annotation_from_fracture_parameters(1005.0, 0.6, 180.0),
    }

    kept, discard = workflow._review_candidate_until_final(
        request(), Context(), rendered(), rendered(), annotation, index=0, total=1,
    )

    assert discard is None
    assert kept["needs_review"] is True
    assert kept["ai_alignment_status"] == "kept_after_review_conflict"
    assert "horizontal bands" in kept["ai_review_conflict_reason"]

    ordinary = dict(annotation)
    ordinary.pop("association_status")
    rejected, discard = workflow._review_candidate_until_final(
        request(), Context(), rendered(), rendered(), ordinary, index=0, total=1,
    )
    assert rejected is None
    assert discard["stage"] == "reviewing"

    corroborated = dict(ordinary)
    corroborated["cross_window_corroboration"] = {
        "support_count": 2,
        "fit_acceptable": True,
    }
    kept, discard = workflow._review_candidate_until_final(
        request(), Context(), rendered(), rendered(), corroborated, index=0, total=1,
    )
    assert discard is None
    assert kept["needs_review"] is True
    assert kept["ai_alignment_status"] == "kept_after_review_conflict"


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


def test_batch_audit_uses_one_fixed_comparison_view():
    decisions = [
        {"candidate_id": "F1", "action": "keep", "reason": "complete"},
        {"candidate_id": "F2", "action": "discard", "reason": "local fragment"},
    ]
    completions = SequenceCompletions([{
        "action": "finalize_audit",
        "reason": "Every conflicting candidate was checked in the fixed comparison",
        "view": None,
        "decisions": decisions,
    }])
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
    assert result["audit_action_count"] == 1
    assert result["audit_views"] == []
    assert recorded == []


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
    assert result["audit_action_count"] == 1
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


def test_batch_audit_bedding_discard_preserves_substantial_cross_cutting_reviewed_pick():
    completions = SequenceCompletions([{
        "action": "finalize_audit",
        "reason": "Final batch comparison",
        "view": None,
        "decisions": [{
            "candidate_id": "F1",
            "action": "discard",
            "reason": "The curve is near-horizontal bedding in the full Plot overview",
        }],
    }])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    candidate = {
        "type": "sinusoidal_fracture",
        "candidate_id": "F1",
        "fracture_type": "Resistive",
        "confidence": 0.88,
        "ai_alignment_status": "aligned",
        "candidate_depth_window": [1004.3, 1006.4],
        "candidate_continuity_reason": "A narrow bright trace cuts across repeated bedding bands",
        "ai_review_reason": "The fitted curve is distinct from the surrounding parallel layering",
        "local_completeness": {"available": True, "score": 1.9, "complete": False},
        "points": [[18.0, 1005.0], [70.0, 1004.7], [130.0, 1005.1], [190.0, 1005.8]],
        **annotation_from_fracture_parameters(1005.4, 0.72, 215.0),
    }

    result = pipeline.audit_candidate_batch(request(), rendered(), [candidate])

    assert [item["candidate_id"] for item in result["kept"]] == ["F1"]
    assert result["discarded"] == []
    assert result["kept"][0]["needs_review"] is True
    assert result["kept"][0]["batch_audit_status"] == "kept_after_audit_conflict"


def test_backend_audit_failure_keeps_conflict_results_and_marks_review(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    candidates = [
        {
            "type": "sinusoidal_fracture",
            "candidate_id": "F1",
            "fracture_type": "Conductive",
                "confidence": 0.9,
                "needs_review": True,
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


def test_window_assessment_normalizes_contradictory_responses():
    workflow = FractureVisionPipeline(Config()).complete_workflow
    valid_candidate = {
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "depth_top": 1002.0,
        "depth_bottom": 1004.0,
        "confidence": 0.9,
        "continuity_reason": "visible trace",
    }

    none = workflow._normalize_window_assessment(
        request(), rendered(), {
            "classification": "none",
            "confidence": 0.9,
            "reason": "contradictory response",
            "candidates": [valid_candidate],
        },
    )
    empty_confirmed = workflow._normalize_window_assessment(
        request(), rendered(), {
            "classification": "confirmed",
            "confidence": 0.9,
            "reason": "missing localization",
            "candidates": [],
        },
    )

    assert none["candidates"] == []
    assert "none_ignored_returned_candidates" in none["normalizations"]
    assert empty_confirmed["classification"] == "suspected"
    assert (
        "confirmed_without_candidates_downgraded_to_suspected"
        in empty_confirmed["normalizations"]
    )


def test_fast_mode_uses_one_window_assessment_for_classification_and_localization():
    completions = SequenceCompletions([
        {
            "classification": "confirmed",
            "confidence": 0.91,
            "reason": "one fitting-ready trace",
            "candidates": [{
                "candidate_id": "F1",
                "fracture_type": "Conductive",
                "depth_top": 1003.0,
                "depth_bottom": 1007.0,
                "confidence": 0.88,
                "continuity_reason": "consistent curvature across pads",
            }],
        },
        {
            "confidence": 0.9,
            "reason": "boundary, crest, trough, and slope anchors",
            "points": [
                {"x_norm": 0.0, "y_norm": 0.5},
                {"x_norm": 0.25, "y_norm": 0.3},
                {"x_norm": 0.75, "y_norm": 0.7},
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
            "confidence": 0.9,
            "decision_continuity": "initial",
            "reason": "fixed evidence supports the fit",
            "fracture_type": "Conductive",
            "decision_basis": "geometry_aligned",
        },
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(
        Config(), client_factory=lambda _config: client, evidence_scorer=Scorer(),
    )
    selected_request = FractureDetectionRequest.build(
        window_id="Log Plot 1",
        tracks=["Track 1 / IMAGE"],
        target_image_track="Track 1 / IMAGE",
        depth_start=1000,
        depth_end=1010,
        fracture_types=["Conductive", "Resistive"],
        pick_entry_level="confirmed",
        fast_mode=True,
        sliding_window_m=20.0,
    )
    context = Context()

    results = pipeline.complete_workflow.detect(selected_request, context, rendered())

    schemas = [call["response_format"]["json_schema"]["name"] for call in completions.calls]
    assert len(results) == 1
    assert schemas == [
        "fracture_window_assessment",
        "complete_fracture_anchor_points",
        "fast_complete_fracture_parameter_review",
    ]
    assert schemas.count("fracture_window_assessment") == 1
    assert context.diagnostics["window_assessment"]["classification"] == "confirmed"
    assert context.diagnostics["visual_requests"]["visual_call_count"] == 3


def test_geometry_association_merges_type_conflict_into_one_evidence_record():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    left = _provisional_candidate(
        "F1", 1005.0, 0.6, 180.0, [0, 45, 90, 135],
        depth_top=1004.4, depth_bottom=1005.2,
    )
    right = _provisional_candidate(
        "F2", 1005.0, 0.6, 180.0, [180, 225, 270, 315],
        depth_top=1004.8, depth_bottom=1005.6,
    )
    right["candidate"]["fracture_type"] = "Resistive"
    right["annotation"]["fracture_type"] = "Resistive"

    associated, diagnostics = pipeline.complete_workflow._associate_provisional_candidates(
        request(), Context(), rendered(), [left, right],
    )

    assert len(associated) == 1
    annotation = associated[0]["annotation"]
    assert annotation["type_conflict"] is True
    assert set(annotation["source_fracture_types"]) == {"Conductive", "Resistive"}
    assert annotation["source_candidate_ids"] == ["F1", "F2"]
    assert annotation["evidence_id"].startswith("EV-")
    assert diagnostics["comparisons"][0]["type_conflict"] is True


def test_two_review_rounds_keep_same_raw_view_and_use_final_schema():
    completions = SequenceCompletions([
        {
            "action": "adjust_parameters",
            "view": None,
            "aligned": False,
            "center_depth_m": 1005.1,
            "amplitude_m": 0.45,
            "phase_deg": 95.0,
            "corrected_points": [],
            "confidence": 0.84,
            "decision_continuity": "initial",
            "reason": "adjust the trough and phase",
            "fracture_type": "Conductive",
            "decision_basis": "parameter_adjustment",
        },
        {
            "action": "keep",
            "view": None,
            "aligned": True,
            "center_depth_m": None,
            "amplitude_m": None,
            "phase_deg": None,
            "corrected_points": [],
            "confidence": 0.9,
            "decision_continuity": "maintain",
            "reason": "the adjusted geometry remains aligned in the same evidence view",
            "fracture_type": "Conductive",
            "decision_basis": "geometry_aligned",
        },
    ])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(
        Config(), client_factory=lambda _config: client, evidence_scorer=Scorer(),
    )
    selected_request = replace(request(), fast_mode=True, sliding_window_m=20.0)
    center, amplitude, phase = 1005.0, 0.4, 90.0
    points = [
        [float(azimuth), center + amplitude * np.sin(np.deg2rad(azimuth + phase))]
        for azimuth in (0, 90, 180, 270, 360)
    ]
    annotation = {
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "points": points,
        "final_points": points,
        **annotation_from_fracture_parameters(center, amplitude, phase),
    }

    kept, discard = pipeline.complete_workflow._review_candidate_until_final(
        selected_request, Context(), rendered(), rendered(), annotation, index=0, total=1,
    )

    assert discard is None
    assert kept["decision_state"] == "kept"
    assert len(completions.calls) == 2
    assert [call["response_format"]["json_schema"]["name"] for call in completions.calls] == [
        "fast_complete_fracture_parameter_review",
        "final_complete_fracture_parameter_review",
    ]
    first_images = [
        item["image_url"]["url"]
        for item in completions.calls[0]["messages"][1]["content"]
        if item.get("type") == "image_url"
    ]
    second_images = [
        item["image_url"]["url"]
        for item in completions.calls[1]["messages"][1]["content"]
        if item.get("type") == "image_url"
    ]
    assert first_images[0] == second_images[0]
    assert first_images[1] != second_images[1]
    hashes = [item["canonical_raw_image_hash"] for item in kept["ai_correction_history"]]
    assert len(set(hashes)) == 1


def test_second_round_overturn_without_geometry_change_is_retained_for_review(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    center, amplitude, phase = 1005.0, 0.5, 90.0
    points = [
        [float(azimuth), center + amplitude * np.sin(np.deg2rad(azimuth + phase))]
        for azimuth in (0, 90, 180, 270)
    ]
    local = Scorer().evaluate()
    responses = [
        {
            "action": "adjust_parameters",
            "aligned": False,
            "confidence": 0.8,
            "decision_continuity": "initial",
            "decision_basis": "parameter_adjustment",
            "fracture_type": "Conductive",
            "reason": "restate the same geometry",
            "parameters": {
                "center_depth_m": center,
                "amplitude_m": amplitude,
                "phase_deg": phase,
            },
            "corrected_points": points,
            "local_completeness": local,
            "corrected_local_completeness": local,
        },
        {
            "action": "discard",
            "aligned": False,
            "confidence": 0.8,
            "decision_continuity": "overturn",
            "decision_basis": "wrong_texture",
            "fracture_type": "Conductive",
            "reason": "reverse the first decision without new evidence",
            "parameters": None,
            "corrected_points": [],
            "local_completeness": local,
            "corrected_local_completeness": None,
        },
    ]
    monkeypatch.setattr(
        workflow,
        "review_candidate_parameters",
        lambda *_args, **_kwargs: responses.pop(0),
    )
    annotation = {
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "points": points,
        **annotation_from_fracture_parameters(center, amplitude, phase),
    }

    kept, discard = workflow._review_candidate_until_final(
        request(), Context(), rendered(), rendered(), annotation, index=0, total=1,
    )

    assert discard is None
    assert kept["needs_review"] is True
    assert kept["decision_state"] == "needs_review"
    assert "illegal_second_round_overturn_without_new_evidence" in kept[
        "ai_review_conflict_reason"
    ]


def test_invalid_parameter_correction_keeps_last_valid_fit_for_review():
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    annotation = {
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "points": [[0, 1005.0], [90, 1005.5], [180, 1005.0]],
    }
    normalized = workflow._normalize_review(
        {
            "action": "adjust_parameters",
            "aligned": False,
            "center_depth_m": None,
            "amplitude_m": None,
            "phase_deg": None,
            "corrected_points": [],
            "confidence": 0.8,
            "decision_continuity": "initial",
            "reason": "invalid correction",
            "fracture_type": "Conductive",
            "decision_basis": "parameter_adjustment",
        },
        annotation,
        rendered(),
        request(),
        Scorer().evaluate(),
    )

    assert normalized["action"] == "retry"
    assert normalized["corrected_points"] == []


def test_conflict_audit_receives_only_flagged_candidates(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    safe = {
        "candidate_id": "F-safe",
        "fracture_type": "Conductive",
        "needs_review": False,
        **annotation_from_fracture_parameters(1002.0, 0.2, 45.0),
    }
    conflict = {
        "candidate_id": "F-review",
        "fracture_type": "Resistive",
        "needs_review": True,
        **annotation_from_fracture_parameters(1008.0, 0.2, 135.0),
    }
    received = []

    def audit(_request, _rendered, candidates, **_kwargs):
        received.extend(item["candidate_id"] for item in candidates)
        return {
            "kept": list(candidates),
            "discarded": [],
            "audit_status": "completed",
            "audit_views": [],
            "audit_events": [],
            "audit_action_count": 1,
            "audit_decisions": [],
        }

    monkeypatch.setattr(workflow, "audit_candidate_batch", audit)
    result = workflow._audit_staged_candidates(
        request(), Context(), rendered(), [safe, conflict],
    )

    assert received == ["F-review"]
    assert {item["candidate_id"] for item in result["kept"]} == {"F-safe", "F-review"}


def test_request_uses_provider_default_temperature():
    class DefaultTemperatureCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return response({"ok": True})

    completions = DefaultTemperatureCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config())
    pipeline._reset_request_metrics()

    pipeline._request(
        client,
        "vision-model",
        [{"role": "user", "content": [{"type": "text", "text": "test"}]}],
        response_schema=WINDOW_ASSESSMENT_SCHEMA,
    )

    assert len(completions.calls) == 1
    assert "temperature" not in completions.calls[0]
    metrics = pipeline.request_metrics_snapshot()
    assert metrics["visual_call_count"] == 1
    assert metrics["api_attempt_count"] == 1


def test_combined_assessment_timeout_does_not_issue_legacy_split_requests():
    class TimeoutCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            raise TimeoutError("Request timed out.")

    completions = TimeoutCompletions()
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    pipeline = FractureVisionPipeline(Config(), client_factory=lambda _config: client)
    selected_request = replace(
        request(),
        pick_entry_level="confirmed",
        fast_mode=True,
    )

    with pytest.raises(TimeoutError, match="Request timed out"):
        pipeline.complete_workflow.assess_window(
            selected_request,
            rendered(),
            context=Context(),
            client=client,
            model="vision-model",
        )

    assert len(completions.calls) == 1
    schema = completions.calls[0]["response_format"]["json_schema"]["name"]
    assert schema == "fracture_window_assessment"


def test_create_client_disables_sdk_automatic_retries(monkeypatch):
    captured = {}

    def create_client(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(
        "plugins.ai_assistant.services.fracture_vision_service.openai",
        SimpleNamespace(OpenAI=create_client),
    )
    pipeline = FractureVisionPipeline(Config())

    pipeline._create_client(Config().get_resolved_vision_config())

    assert captured["max_retries"] == 0


def test_boundary_association_reviews_only_the_new_merged_candidate(monkeypatch):
    pipeline = FractureVisionPipeline(Config(), evidence_scorer=Scorer())
    workflow = pipeline.complete_workflow
    carried = {
        "candidate_id": "W3-F1",
        "fracture_type": "Conductive",
        **annotation_from_fracture_parameters(1005.0, 0.5, 180.0),
    }
    current = {
        "candidate_id": "W4-F1",
        "fracture_type": "Conductive",
        **annotation_from_fracture_parameters(1005.0, 0.5, 180.0),
    }
    merged = {
        "candidate_id": "X-W3-F1+W4-F1",
        "associated_candidate_ids": ["W3-F1", "W4-F1"],
        "fracture_type": "Conductive",
        **annotation_from_fracture_parameters(1005.0, 0.5, 180.0),
    }
    reviewed = []
    audited = []
    monkeypatch.setattr(
        workflow,
        "associate_annotations_across_windows",
        lambda *_args, **_kwargs: ([merged], {"groups": [{"candidate_id": merged["candidate_id"]}]}),
    )

    def review(_request, _context, _rendered, annotations):
        reviewed.extend(item["candidate_id"] for item in annotations)
        return list(annotations), []

    def audit(_request, _context, _rendered, annotations, **_kwargs):
        audited.extend(item["candidate_id"] for item in annotations)
        return {"kept": list(annotations), "discarded": [], "audit_status": "completed"}

    monkeypatch.setattr(workflow, "review_annotations_after_association", review)
    monkeypatch.setattr(workflow, "_audit_staged_candidates", audit)

    output, _record, discards = pipeline._associate_boundary_candidates(
        request(), Context(), rendered(), [carried], [current],
    )

    assert [item["candidate_id"] for item in output] == [merged["candidate_id"]]
    assert reviewed == [merged["candidate_id"]]
    assert audited == [merged["candidate_id"]]
    assert discards == []


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
