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
