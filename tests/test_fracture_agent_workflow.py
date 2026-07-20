import base64

import pytest
from PySide6.QtCore import QByteArray, QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage

from plugins.ai_assistant.services.fracture_agent_workflow import (
    AdaptiveFractureViewRenderer,
    FRACTURE_EXPLORATION_ACTION_SCHEMA,
    FractureAgentBudget,
    FractureAgentState,
    FractureAgentViewRequest,
)
from plugins.ai_assistant.services.fracture_vision_service import FractureVisionPipeline
from plugins.ai_assistant.services.fracture_detection_service import FractureDetectionRequest


def rendered_plot():
    image = QImage(800, 600, QImage.Format_ARGB32)
    image.fill(QColor("#808080"))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "PNG")
    return {
        "data_url": "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii"),
        "metadata": {
            "width": 800,
            "height": 600,
            "plot_top": 100,
            "plot_bottom": 600,
            "depth_start": 1000.0,
            "depth_end": 1010.0,
            "tracks": [
                {
                    "name": "Depth",
                    "label": "Depth",
                    "is_depth": True,
                    "pixel_left": 0,
                    "pixel_right": 200,
                },
                {
                    "name": "Image",
                    "label": "Track 1 / IMAGE",
                    "is_depth": False,
                    "is_image": True,
                    "pixel_left": 200,
                    "pixel_right": 800,
                },
            ],
        },
    }


def test_exploration_contract_uses_actions_instead_of_fixed_segments():
    schema = FRACTURE_EXPLORATION_ACTION_SCHEMA["schema"]

    assert schema["properties"]["action"]["enum"] == [
        "inspect_view", "register_trace_fragment", "test_sinusoid_hypothesis",
        "register_candidate", "finish_exploration",
    ]
    view = schema["properties"]["view"]
    assert "depth_start" in view["properties"]
    assert "depth_end" in view["properties"]
    assert view["properties"]["scale"] == {"type": "number", "minimum": 0.5, "maximum": 4.0}
    assert "scale" in view["required"]
    assert "segment_index" not in view["properties"]
    assert "segment_count" not in view["properties"]


def test_view_request_clamps_to_source_and_rejects_empty_ranges():
    metadata = rendered_plot()["metadata"]
    request = FractureAgentViewRequest.build({
        "depth_start": 999.0,
        "depth_end": 1004.0,
        "azimuth_start_deg": 45.0,
        "azimuth_end_deg": 270.0,
        "detail_level": "close",
        "include_depth_track": False,
    }, metadata)

    assert request.depth_start == pytest.approx(1000.0)
    assert request.depth_end == pytest.approx(1004.0)
    assert request.azimuth_start_deg == pytest.approx(45.0)
    assert request.is_full_azimuth is False
    assert request.scale == pytest.approx(1.0)
    scaled = FractureAgentViewRequest.build({
        "depth_start": 1001.0,
        "depth_end": 1003.0,
        "scale": 2.5,
    }, metadata)
    assert scaled.scale == pytest.approx(2.5)
    assert scaled.key() != FractureAgentViewRequest(1001.0, 1003.0).key()
    with pytest.raises(ValueError, match="scale"):
        FractureAgentViewRequest.build({"depth_start": 1001, "depth_end": 1002, "scale": 4.1}, metadata)
    with pytest.raises(ValueError, match="depth_start"):
        FractureAgentViewRequest.build({"depth_start": 1005, "depth_end": 1004}, metadata)


def test_adaptive_renderer_preserves_requested_depth_and_azimuth_metadata():
    output = AdaptiveFractureViewRenderer().render(
        rendered_plot(),
        "Track 1 / IMAGE",
        {
            "depth_start": 1002.0,
            "depth_end": 1005.0,
            "azimuth_start_deg": 90.0,
            "azimuth_end_deg": 270.0,
            "detail_level": "detail",
            "include_depth_track": True,
        },
        view_id="view-3",
    )

    metadata = output["metadata"]
    target = metadata["tracks"][-1]
    assert metadata["depth_start"] == pytest.approx(1002.0)
    assert metadata["depth_end"] == pytest.approx(1005.0)
    assert metadata["view_id"] == "view-3"
    assert target["azimuth_start_deg"] == pytest.approx(90.0)
    assert target["azimuth_end_deg"] == pytest.approx(270.0)
    assert target["full_azimuth"] is False
    assert metadata["uniform_scale"] == 1.0
    assert (metadata["width"], metadata["height"]) == (500, 150)


def test_detail_level_does_not_change_crop_scale_or_duplicate_identity():
    renderer = AdaptiveFractureViewRenderer()
    source = rendered_plot()
    detail = FractureAgentViewRequest(1002.0, 1005.0, detail_level="detail")
    close = FractureAgentViewRequest(1002.0, 1005.0, detail_level="close")

    detail_output = renderer.render(source, "Track 1 / IMAGE", detail)
    close_output = renderer.render(source, "Track 1 / IMAGE", close)

    assert detail.key() == close.key()
    assert detail_output["metadata"]["uniform_scale"] == 1.0
    assert close_output["metadata"]["uniform_scale"] == 1.0
    assert detail_output["metadata"]["width"] == close_output["metadata"]["width"]
    assert detail_output["metadata"]["height"] == close_output["metadata"]["height"]


def test_pipeline_uses_plot_rerender_provider_for_non_unit_vertical_scale():
    calls = []

    def provider(request):
        calls.append(request)
        return rendered_plot()

    pipeline = FractureVisionPipeline(agent_view_provider=provider)
    output = pipeline.render_agent_view(
        rendered_plot(),
        "Track 1 / IMAGE",
        FractureAgentViewRequest(1002.0, 1005.0, scale=2.0),
        view_id="scaled-view",
    )

    assert len(calls) == 1
    assert calls[0].scale == pytest.approx(2.0)
    assert output["metadata"]["render_mode"] == "plot_data_rerender"
    assert output["metadata"]["vertical_scale"] == pytest.approx(2.0)
    assert output["metadata"]["actual_vertical_scale"] == pytest.approx(1.0)
    assert output["metadata"]["uniform_scale"] == pytest.approx(1.0)


def test_pipeline_builds_overlapping_sliding_windows():
    windows = FractureVisionPipeline._sliding_windows(1000.0, 1010.0, 3.0)

    expected = [
        (1000.0, 1003.0),
        (1002.4, 1005.4),
        (1004.8, 1007.8),
        (1007.2, 1010.0),
    ]
    assert len(windows) == len(expected)
    for actual, wanted in zip(windows, expected):
        assert actual == pytest.approx(wanted)
    assert FractureVisionPipeline._sliding_windows(1000.0, 1002.0, 3.0) == [(1000.0, 1002.0)]

    schedule = FractureVisionPipeline._window_schedule(windows)
    assert [item["kind"] for item in schedule] == [
        "primary_window",
        "primary_window",
        "primary_window",
        "primary_window",
    ]
    assert (
        schedule[0]["ownership_depth_start"], schedule[0]["ownership_depth_end"]
    ) == pytest.approx((1000.0, 1002.7))
    assert (
        schedule[1]["ownership_depth_start"], schedule[1]["ownership_depth_end"]
    ) == pytest.approx((1002.7, 1005.1))
    assert FractureVisionPipeline._candidate_owned_by_pass({"offset": 1002.65}, schedule[0]) is True
    assert FractureVisionPipeline._candidate_owned_by_pass({"offset": 1002.75}, schedule[0]) is False
    assert FractureVisionPipeline._candidate_owned_by_pass({"offset": 1002.75}, schedule[1]) is True


def test_pipeline_runs_each_sliding_window_and_prefixes_candidate_ids():
    class Workflow:
        def __init__(self):
            self.ranges = []
            self.rendered_inputs = []
            self.merged_overlays = []
            self.audit_ranges = []

        def detect(self, request, context, _rendered):
            self.ranges.append((request.depth_start, request.depth_end))
            self.rendered_inputs.append(_rendered)
            first_pass = len(self.ranges) == 1
            context.set_diagnostics({
                "range": self.ranges[-1],
                "discarded_count": 1 if first_pass else 0,
                "discarded": ([{
                    "candidate_id": "rejected",
                    "reason": "window audit rejected it",
                    "stage": "batch_audit",
                }] if first_pass else []),
                "candidate_evaluations": ([{
                    "candidate": {"candidate_id": "local-fragment"},
                    "status": "discarded",
                }] if first_pass else []),
                "comparison_candidates": ([{
                    "candidate_id": "local-fragment",
                    "fracture_type": "Conductive",
                    "offset": 1001.5,
                    "sin_coeff": 0.2,
                    "cos_coeff": 0.0,
                }] if first_pass else []),
            })
            context.set_candidate_payload("F1", {
                "data_url": _rendered["data_url"],
                "metadata": _rendered["metadata"],
            })
            return [{
                "candidate_id": "F1",
                "offset": (request.depth_start + request.depth_end) / 2.0,
                "sin_coeff": 0.1,
                "cos_coeff": 0.0,
            }]

        def _non_maximum_suppression(self, candidates, _rendered):
            return list(candidates), []

        def _audit_staged_candidates(
            self,
            _request,
            _context,
            rendered,
            candidates,
            *,
            force_visual,
        ):
            assert force_visual is True
            metadata = rendered["metadata"]
            self.audit_ranges.append((metadata["depth_start"], metadata["depth_end"]))
            return {
                "kept": list(candidates),
                "discarded": [],
                "audit_status": "completed",
                "audit_action_count": len(candidates),
                "audit_views": [],
                "audit_events": [],
            }

        def _build_batch_feedback_image(self, rendered, candidates, _target):
            self.merged_overlays.append([item["candidate_id"] for item in candidates])
            return rendered["data_url"] + "-overlay"

    class Context:
        run_id = "run-1"
        cancelled = False

        def __init__(self):
            self.diagnostics = None
            self.candidate_payloads = {}
            self.monitor_media = {}
            self.events = []
            self.monitor = {}

        def update(self, *_args):
            pass

        def set_diagnostics(self, diagnostics):
            self.diagnostics = diagnostics

        def set_candidate_payload(self, candidate_id, payload):
            self.candidate_payloads[candidate_id] = payload

        def set_monitor_media(self, slot, payload, **_details):
            self.monitor_media[slot] = payload

        def record_event(self, stage, action, reason, **details):
            self.events.append({
                "stage": stage, "action": action, "reason": reason, **details,
            })

        def update_monitor(self, **details):
            self.monitor.update(details)

    pipeline = FractureVisionPipeline(config=object())
    workflow = Workflow()
    pipeline.complete_workflow = workflow
    context = Context()
    request = FractureDetectionRequest.build(
        "Plot",
        "Track 1 / IMAGE",
        1000.0,
        1010.0,
        ["Conductive"],
        sliding_window_m=3.0,
    )

    results = pipeline.detect(request, context, rendered_plot())

    assert len(workflow.ranges) == 4
    assert [item["candidate_id"] for item in results] == [
        "W1-F1", "W2-F1", "W3-F1", "W4-F1",
    ]
    assert context.diagnostics["sliding_window_m"] == pytest.approx(3.0)
    assert len(context.diagnostics["window_diagnostics"]) == 4
    assert context.diagnostics["merged_observations"] == []
    assert len(context.diagnostics["window_batches"]) == 2
    assert [
        item["source_window_indices"]
        for item in context.diagnostics["window_batches"]
    ] == [[1, 2, 3], [4]]
    assert all(
        len(item["source_window_indices"]) <= 3
        for item in context.diagnostics["window_batches"]
    )
    assert set(context.candidate_payloads) == {
        "W1-F1", "W2-F1", "W3-F1", "W4-F1",
    }
    assert workflow.merged_overlays == [
        ["W1-F1", "W2-F1", "W3-F1"],
        ["W1-F1"],
        ["W1-F1", "W2-F1", "W3-F1", "W4-F1"],
    ]
    assert len(workflow.audit_ranges) == 2
    assert workflow.audit_ranges[0] == pytest.approx((1000.0, 1007.8))
    assert workflow.audit_ranges[1] == pytest.approx((1007.2, 1010.0))
    assert context.diagnostics["discarded_count"] == 1
    assert context.diagnostics["kept_candidate_ids"] == [
        "W1-F1", "W2-F1", "W3-F1", "W4-F1",
    ]
    assert context.monitor["kept_count"] == 4
    assert context.monitor["discarded_count"] == 1
    assert context.monitor["current_candidate"] == ""
    assert context.diagnostics["discarded"][0]["candidate_id"] == "W1-rejected"
    assert all("prior_candidate_overlays" not in item["metadata"] for item in workflow.rendered_inputs)
    assert context.monitor_media["final_overlay"]["data_url"].endswith("-overlay")
    assert context.monitor_media["final_overlay"]["metadata"]["depth_start"] == pytest.approx(1000.0)
    assert context.monitor_media["final_overlay"]["metadata"]["depth_end"] == pytest.approx(1010.0)
    assert context.diagnostics["final_overlay_scope"] == "full_detection_depth_range_summary_only"
    assert context.diagnostics["global_batch_audit"] == {
        "audit_status": "performed_per_window_batch",
        "visual_global_audit_skipped": True,
    }
    assert any(
        event["action"] == "final_batch_summary_overlay_prepared"
        for event in context.events
    )


def test_merged_observation_vision_messages_compare_raw_and_overlay_images():
    raw = "data:image/png;base64,raw"
    overlay = "data:image/png;base64,overlay"

    images = FractureVisionPipeline(config=object()).complete_workflow._analysis_images({
        "data_url": raw,
        "overlay_data_url": overlay,
    })
    messages = FractureVisionPipeline(config=object()).complete_workflow._vision_messages(
        "system", "prompt", images,
    )
    content = messages[1]["content"]
    image_blocks = [item for item in content if item["type"] == "image_url"]
    labels = [item["text"] for item in content if item["type"] == "text"]

    assert [item["image_url"]["url"] for item in image_blocks] == [raw, overlay]
    assert any("authoritative source" in label for label in labels)
    assert any("annotations, not raw fracture evidence" in label for label in labels)


def test_pipeline_promotes_context_candidate_when_owner_window_has_no_match():
    class Workflow:
        def detect(self, request, context, _rendered):
            context.set_diagnostics({"discarded": [], "discarded_count": 0})
            if request.depth_start < 1002.0:
                return []
            return [{
                "candidate_id": "F1",
                "offset": 1002.5,
                "sin_coeff": 0.35,
                "cos_coeff": 0.0,
                "confidence": 0.85,
                "needs_review": False,
            }]

        def _non_maximum_suppression(self, candidates, _rendered):
            return list(candidates), []

    class Context:
        run_id = "run-context-fallback"
        cancelled = False

        def __init__(self):
            self.diagnostics = None

        def update(self, *_args):
            pass

        def set_diagnostics(self, diagnostics):
            self.diagnostics = diagnostics

    pipeline = FractureVisionPipeline(config=object())
    pipeline.complete_workflow = Workflow()
    context = Context()
    selected_request = FractureDetectionRequest.build(
        "Plot", "Track 1 / IMAGE", 1000.0, 1004.0, ["Conductive"],
        sliding_window_m=3.0,
    )

    results = pipeline.detect(selected_request, context, rendered_plot())

    assert [item["candidate_id"] for item in results] == ["W2-F1"]
    assert results[0]["ownership_fallback_promoted"] is True
    assert results[0]["needs_review"] is True
    assert context.diagnostics["promoted_context_candidates"] == ["W2-F1"]
    assert context.diagnostics["context_only_candidates"][0]["status"] == "promoted_after_owner_miss"


def test_matching_context_candidate_merges_support_into_owner():
    owner = {
        "candidate_id": "W3-F2",
        "fracture_type": "Resistive",
        "sliding_window_index": 3,
        "confidence": 0.68,
        "final_points": [[180, 1005.0], [225, 1005.14], [270, 1005.2], [315, 1005.14]],
        "offset": 1005.0,
        "sin_coeff": 0.0,
        "cos_coeff": -0.2,
    }
    support = {
        "candidate_id": "W4-F1",
        "fracture_type": "Resistive",
        "sliding_window_index": 4,
        "confidence": 0.72,
        "final_points": [[180, 1005.01], [225, 1005.15], [270, 1005.21], [315, 1005.15]],
        "offset": 1005.01,
        "sin_coeff": 0.0,
        "cos_coeff": -0.2,
    }

    corroboration = FractureVisionPipeline._merge_window_ownership_support(
        owner, support, rendered_plot(), borehole_diameter=8.0,
    )

    assert corroboration["support_count"] == 2
    assert corroboration["candidate_ids"] == ["W3-F2", "W4-F1"]
    assert corroboration["source_window_indices"] == [3, 4]
    assert corroboration["fit_acceptable"] is True
    assert owner["cross_window_corroboration"] == corroboration
    assert owner["confidence"] == pytest.approx(0.72)
    assert len(owner["final_points"]) == 8


def test_agent_state_enforces_budgets_and_records_decisions():
    state = FractureAgentState(FractureAgentBudget(
        max_views=2,
        max_actions=4,
        max_candidates=2,
        max_duplicate_views=1,
    ))
    request = FractureAgentViewRequest(1001.0, 1002.0)
    state.record_action("inspect_view")
    state.record_view(request, "view-1")
    with pytest.raises(ValueError, match="duplicate"):
        state.record_view(request, "view-2")

    state.record_action("register_candidate")
    candidate = state.register_candidate({
        "candidate_id": "F1",
        "fracture_type": "Conductive",
        "depth_top": 1001.1,
        "depth_bottom": 1001.9,
        "confidence": 0.85,
        "continuity_reason": "trace remains continuous across a pad gap",
    }, ["Conductive"], rendered_plot()["metadata"])
    state.record_action("finish_exploration")
    state.finish()

    assert candidate["candidate_id"] == "F1"
    assert state.prompt_context()["views_used"] == 1
    assert state.prompt_context()["candidate_count"] == 1
    with pytest.raises(RuntimeError, match="already finished"):
        state.record_action("inspect_view")


def test_agent_state_registers_fragments_and_revisable_sinusoid_hypotheses():
    state = FractureAgentState()
    metadata = rendered_plot()["metadata"]
    left = state.register_trace_fragment({
        "fragment_id": "T-left",
        "fracture_type": "Conductive",
        "depth_top": 1002.0,
        "depth_bottom": 1004.0,
        "azimuth_start_deg": 0.0,
        "azimuth_end_deg": 120.0,
        "slope_direction": "rising",
        "confidence": 0.82,
        "continuity_reason": "visible left arc",
    }, ["Conductive", "Resistive"], metadata)
    right = state.register_trace_fragment({
        "fragment_id": "T-right",
        "fracture_type": "Conductive",
        "depth_top": 1006.0,
        "depth_bottom": 1008.0,
        "azimuth_start_deg": 210.0,
        "azimuth_end_deg": 360.0,
        "slope_direction": "falling",
        "confidence": 0.79,
        "continuity_reason": "compatible right arc",
    }, ["Conductive", "Resistive"], metadata)
    first = state.register_hypothesis({
        "hypothesis_id": "H1",
        "fragment_ids": [left["fragment_id"], right["fragment_id"]],
        "fracture_type": "Conductive",
        "center_depth_m": 1005.0,
        "amplitude_m": 2.0,
        "phase_deg": 180.0,
        "confidence": 0.76,
    }, ["Conductive", "Resistive"], metadata)
    revised = state.register_hypothesis({
        "hypothesis_id": "H1",
        "fragment_ids": ["T-left", "T-right"],
        "fracture_type": "Conductive",
        "center_depth_m": 1005.1,
        "amplitude_m": 1.8,
        "phase_deg": 190.0,
        "confidence": 0.84,
    }, ["Conductive", "Resistive"], metadata)

    assert first["revision"] == 1
    assert revised["revision"] == 2
    assert state.prompt_context()["fragment_count"] == 2
    assert state.prompt_context()["hypothesis_count"] == 2
    with pytest.raises(ValueError, match="Unknown trace fragment"):
        state.register_hypothesis({
            "hypothesis_id": "H2",
            "fragment_ids": ["missing"],
            "fracture_type": "Conductive",
            "center_depth_m": 1005.0,
            "amplitude_m": 1.0,
            "phase_deg": 0.0,
            "confidence": 0.5,
        }, ["Conductive"], metadata)


def test_invalid_model_actions_still_consume_the_action_budget():
    state = FractureAgentState(FractureAgentBudget(max_actions=2))

    with pytest.raises(ValueError, match="Unsupported"):
        state.record_action("invent_tool")
    assert state.action_count == 1
    with pytest.raises(ValueError, match="Unsupported"):
        state.record_action("run_python")
    with pytest.raises(RuntimeError, match="budget exhausted"):
        state.record_action("inspect_view")


def test_vision_pipeline_exposes_agent_state_and_view_renderer():
    pipeline = FractureVisionPipeline(config=object())
    state = pipeline.create_agent_state(FractureAgentBudget(max_views=3))
    output = pipeline.render_agent_view(
        rendered_plot(),
        "Track 1 / IMAGE",
        FractureAgentViewRequest(1000.0, 1010.0, detail_level="overview"),
        view_id="overview",
    )

    assert state.budget.max_views == 3
    assert output["metadata"]["view_id"] == "overview"
    assert output["metadata"]["tracks"][-1]["full_azimuth"] is True
