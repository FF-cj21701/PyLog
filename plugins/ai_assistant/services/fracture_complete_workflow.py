from __future__ import annotations

import base64
import json
import math
import re
from dataclasses import asdict

import numpy as np
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from .fracture_agent_workflow import (
    FRACTURE_AGENT_VIEW_SCHEMA,
    FRACTURE_EXPLORATION_ACTION_SCHEMA,
    FractureAgentViewRequest,
)
from scripts.rendering.fracture_annotations import (
    FRACTURE_TYPE_STYLES,
    annotation_from_fracture_parameters,
    canonical_fracture_points,
    enrich_fracture_interpretation,
    fit_sinusoidal_fracture,
    fracture_parameters,
    sinusoidal_fracture_xy,
)


MIN_TRACE_POINTS = 3
MAX_TRACE_POINTS = 8
MAX_CORRECTION_ROUNDS = 5
MAX_REVIEW_VIEWS = 6
MAX_REVIEW_ACTIONS = 8
MAX_AUDIT_VIEWS = 8
MAX_AUDIT_ACTIONS = 12


def _point_schema():
    return {
        "type": "object",
        "properties": {
            "x_norm": {"type": "number", "minimum": 0, "maximum": 1},
            "y_norm": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["x_norm", "y_norm"],
        "additionalProperties": False,
    }


ANCHOR_SCHEMA = {
    "name": "complete_fracture_anchor_points",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
            "points": {
                "type": "array",
                "minItems": MIN_TRACE_POINTS,
                "maxItems": MAX_TRACE_POINTS,
                "items": _point_schema(),
            },
        },
        "required": ["confidence", "reason", "points"],
        "additionalProperties": False,
    },
}


PARAMETER_REVIEW_SCHEMA = {
    "name": "complete_fracture_parameter_review",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["inspect_view", "keep", "adjust_parameters", "replace_points", "discard"],
            },
            "view": FRACTURE_AGENT_VIEW_SCHEMA,
            "aligned": {"type": "boolean"},
            "center_depth_m": {"type": ["number", "null"]},
            "amplitude_m": {"type": ["number", "null"]},
            "phase_deg": {"type": ["number", "null"]},
            "corrected_points": {
                "type": "array",
                "maxItems": MAX_TRACE_POINTS,
                "items": _point_schema(),
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
        },
        "required": [
            "action", "view", "aligned", "center_depth_m", "amplitude_m", "phase_deg",
            "corrected_points", "confidence", "reason",
        ],
        "additionalProperties": False,
    },
}


BATCH_AUDIT_SCHEMA = {
    "name": "complete_fracture_batch_audit",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["inspect_view", "finalize_audit"]},
            "reason": {"type": "string"},
            "view": FRACTURE_AGENT_VIEW_SCHEMA,
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "action": {"type": "string", "enum": ["keep", "discard"]},
                        "reason": {"type": "string"},
                    },
                    "required": ["candidate_id", "action", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["action", "reason", "view", "decisions"],
        "additionalProperties": False,
    },
}


def _json_payload(response):
    content = response.choices[0].message.content if response.choices else ""
    if isinstance(content, dict):
        return content
    text = str(content or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Vision response must be a JSON object")
    return payload


class CompleteFractureWorkflow:
    """Two-stage complete-fracture interpretation built on a vision pipeline client."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def detect(self, request, context, rendered):
        if context.cancelled:
            return []
        self._validate_rendered(rendered)
        _config, client, model = self._client()
        context.update("exploring", 0.10, "AI: inspecting complete Plot overview")
        if hasattr(context, "set_monitor_media"):
            context.set_monitor_media("input_view", rendered, api_status="requesting")
        candidates, exploration = self.explore_candidate_windows(
            request,
            rendered,
            context=context,
            client=client,
            model=model,
        )
        diagnostics = {
            "coordinate_contract": {
                "x_norm": "0..1 within the candidate target image track",
                "y_norm": "0..1 within the candidate crop depth range",
            },
            "render_metadata": rendered["metadata"],
            "candidate_windows": candidates,
            "exploration": exploration,
            "candidate_evaluations": [],
        }
        staged = []
        discarded = []
        total = max(1, len(candidates))
        for index, candidate in enumerate(candidates):
            if context.cancelled:
                return []
            context.update(
                "candidate_rendering",
                0.20 + 0.45 * index / total,
                f"Rendering candidate {index + 1}/{len(candidates)}",
            )
            if hasattr(context, "update_monitor"):
                context.update_monitor(
                    current_candidate=candidate.get("candidate_id"),
                    candidate_index=index + 1,
                    candidate_count=len(candidates),
                    correction_round=0,
                    api_status="rendering",
                )
            candidate_rendered = self.render_candidate_window(rendered, candidate, request.target_image_track)
            context.update(
                "anchoring",
                0.25 + 0.45 * index / total,
                f"Picking anchors for candidate {index + 1}/{len(candidates)}",
            )
            evaluation = {"candidate": dict(candidate), "status": "rejected"}
            diagnostics["candidate_evaluations"].append(evaluation)
            try:
                anchor_result = self.pick_candidate_anchors(
                    request,
                    candidate_rendered,
                    candidate,
                    client=client,
                    model=model,
                )
                if hasattr(context, "record_event"):
                    context.record_event(
                        "anchoring",
                        "anchors_selected",
                        anchor_result.get("reason", ""),
                        status="accepted",
                        candidate_id=candidate.get("candidate_id"),
                    )
                points = self._normalized_points_to_depth(
                    anchor_result.get("points"),
                    candidate_rendered["metadata"],
                )
                if len(points) < MIN_TRACE_POINTS:
                    raise ValueError("Vision model returned fewer than three valid anchor points")
                fit = fit_sinusoidal_fracture(points, min_points=MIN_TRACE_POINTS)
                parameters = fracture_parameters(fit)
                style = FRACTURE_TYPE_STYLES[candidate["fracture_type"]]
                local = self.pipeline.evidence_scorer.evaluate(
                    candidate_rendered,
                    request.target_image_track,
                    fit,
                )
                annotation = enrich_fracture_interpretation({
                    "type": "sinusoidal_fracture",
                    "fracture_type": candidate["fracture_type"],
                    "color": style["color"],
                    "line_width": 2.0,
                    **fit,
                    "confidence": min(float(candidate["confidence"]), float(anchor_result.get("confidence", 0.0))),
                    "ai_generated": True,
                    "detection_run_id": context.run_id,
                    "candidate_id": candidate["candidate_id"],
                    "candidate_depth_window": [candidate["depth_top"], candidate["depth_bottom"]],
                    "source_track_label": request.target_image_track,
                    "target_track_label": request.target_image_track,
                    "borehole_diameter_in": request.borehole_diameter_in,
                    "ai_initial_parameters": dict(parameters),
                    "ai_final_parameters": dict(parameters),
                    "ai_correction_history": [],
                    "ai_correction_rounds": 0,
                    "ai_alignment_status": "pending",
                    "local_completeness": local,
                    "agent_hypothesis_verified": bool(candidate.get("agent_hypothesis_verified", False)),
                    "agent_hypothesis_id": candidate.get("agent_hypothesis_id"),
                    "agent_hypothesis_revision": candidate.get("agent_hypothesis_revision"),
                    "agent_fragment_ids": list(candidate.get("agent_fragment_ids") or []),
                    "needs_review": False,
                    "initial_points": [list(point) for point in points],
                    "final_points": [list(point) for point in points],
                    "_candidate_render_key": candidate["candidate_id"],
                }, borehole_diameter=request.borehole_diameter_in)
                if hasattr(context, "set_candidate_payload"):
                    context.set_candidate_payload(candidate["candidate_id"], candidate_rendered)
                else:
                    annotation["_candidate_rendered"] = candidate_rendered
                reviewed, review_discard = self._review_candidate_until_final(
                    request,
                    context,
                    rendered,
                    candidate_rendered,
                    annotation,
                    index=index,
                    total=len(candidates),
                )
                if review_discard is not None:
                    discarded.append(review_discard)
                    evaluation.update({
                        "status": "discarded",
                        "discard_reason": review_discard["reason"],
                        "review_history": list(annotation.get("ai_correction_history") or []),
                    })
                    continue
                staged.append(reviewed)
                evaluation.update({
                    "status": "accepted",
                    "anchor_response": anchor_result,
                    "points": points,
                    "initial_parameters": parameters,
                    "local_completeness": local,
                    "candidate_render_metadata": candidate_rendered["metadata"],
                    "final_parameters": reviewed.get("ai_final_parameters"),
                    "review_history": list(reviewed.get("ai_correction_history") or []),
                })
            except Exception as exc:
                if context.cancelled:
                    return []
                evaluation["reason"] = str(exc)
                if hasattr(context, "record_event"):
                    context.record_event(
                        "candidate_processing",
                        "candidate_failed",
                        str(exc),
                        status="rejected",
                        candidate_id=candidate.get("candidate_id"),
                    )
                discarded.append({
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": str(exc),
                    "stage": "candidate_processing",
                })

        if context.cancelled:
            return []
        context.update("auditing", 0.84, f"Auditing {len(staged)} staged candidate(s)")
        audit_result = self._audit_staged_candidates(
            request,
            context,
            rendered,
            staged,
        )
        results = list(audit_result["kept"])
        discarded.extend(audit_result["discarded"])
        diagnostics["staged_count"] = len(staged)
        diagnostics["accepted_count"] = len(results)
        diagnostics["discarded_count"] = len(discarded)
        diagnostics["discarded"] = discarded
        diagnostics["kept_candidate_ids"] = [item.get("candidate_id") for item in results]
        diagnostics["batch_audit"] = {
            key: value for key, value in audit_result.items() if key not in {"kept", "discarded"}
        }
        if hasattr(context, "set_diagnostics"):
            context.set_diagnostics(diagnostics)
        if hasattr(context, "update_monitor"):
            context.update_monitor(
                candidate_count=len(candidates),
                kept_count=len(results),
                discarded_count=len(discarded),
                api_status="ready_for_gui",
            )
        context.update("staging", 0.89, f"Prepared {len(results)} audited candidate(s) for GUI playback")
        return results

    def _review_candidate_until_final(
        self,
        request,
        context,
        source_rendered,
        candidate_rendered,
        annotation,
        *,
        index,
        total,
    ):
        current = dict(annotation)
        history = list(current.get("ai_correction_history") or [])
        for round_number in range(1, MAX_CORRECTION_ROUNDS + 1):
            if context.cancelled:
                return None, {
                    "candidate_id": current.get("candidate_id"),
                    "reason": "cancelled",
                    "stage": "reviewing",
                }
            progress = 0.66 + 0.16 * ((index + (round_number - 1) / MAX_CORRECTION_ROUNDS) / max(1, total))
            context.update(
                "reviewing",
                progress,
                f"Reviewing candidate {index + 1}/{total}, round {round_number}/{MAX_CORRECTION_ROUNDS}",
            )

            result = self.review_candidate_parameters(
                request,
                candidate_rendered,
                current,
                round_number=round_number,
                source_rendered=source_rendered,
                view_recorder=(
                    (lambda view_id, payload: context.set_view_payload(view_id, payload))
                    if hasattr(context, "set_view_payload") else None
                ),
                status_callback=lambda details: (
                    context.update_monitor(
                        current_candidate=current.get("candidate_id"),
                        correction_round=round_number,
                        view_budget_used=details.get("view_count", 0),
                        view_budget_limit=details.get("max_views", MAX_REVIEW_VIEWS),
                        budget_stage="review",
                        api_status="reviewing",
                    ) if hasattr(context, "update_monitor") else None
                ),
                monitor_callback=lambda update: self._forward_monitor_update(context, update),
                cancel_requested=lambda: context.cancelled,
            )
            action = str(result.get("action") or "retry")
            history.append({
                "round": round_number,
                "action": action,
                "parameters": result.get("parameters"),
                "points": [list(point) for point in result.get("corrected_points", [])],
                "reason": result.get("reason"),
                "local_completeness": (
                    result.get("corrected_local_completeness") or result.get("local_completeness")
                ),
                "review_action_count": result.get("review_action_count"),
                "review_views": list(result.get("review_views") or []),
            })
            if hasattr(context, "record_event"):
                for decision in result.get("audit_decisions", []):
                    context.record_event(
                        "auditing",
                        decision.get("action", "keep"),
                        decision.get("reason", ""),
                        status="accepted" if decision.get("action") == "keep" else "rejected",
                        candidate_id=decision.get("candidate_id"),
                    )
                context.record_event(
                    "reviewing",
                    action,
                    result.get("reason", ""),
                    status="accepted" if action in {"keep", "adjust_parameters", "replace_points"} else "rejected",
                    candidate_id=current.get("candidate_id"),
                    correction_round=round_number,
                )
            current["ai_correction_history"] = history
            current["ai_review_confidence"] = result.get("confidence")
            current["ai_review_reason"] = result.get("reason")
            current["ai_review_views"] = list(result.get("review_views") or [])
            current["ai_review_events"] = list(result.get("review_events") or [])
            if result.get("local_completeness") is not None:
                current["local_completeness"] = result["local_completeness"]
            if result.get("corrected_local_completeness") is not None:
                current["corrected_local_completeness"] = result["corrected_local_completeness"]

            if action == "discard":
                return None, {
                    "candidate_id": current.get("candidate_id"),
                    "reason": result.get("reason") or "discarded_by_visual_review",
                    "stage": "reviewing",
                    "annotation": self._diagnostic_annotation(current),
                }
            if action == "keep" and bool(result.get("aligned", False)):
                current["ai_alignment_status"] = "aligned"
                current["ai_correction_rounds"] = round_number - 1
                current["needs_review"] = bool(result.get("needs_review", False))
                current["final_points"] = [list(point) for point in current.get("points", [])]
                if hasattr(context, "update_monitor"):
                    context.update_monitor(
                        parameters=current.get("ai_final_parameters"),
                        api_status="candidate_kept",
                    )
                return current, None

            corrected = self._clean_depth_points(result.get("corrected_points"))
            if len(corrected) < MIN_TRACE_POINTS:
                continue
            fit = fit_sinusoidal_fracture(corrected, min_points=MIN_TRACE_POINTS)
            current.update(fit)
            current = enrich_fracture_interpretation(
                current,
                borehole_diameter=request.borehole_diameter_in,
            )
            current["points"] = [list(point) for point in corrected]
            current["final_points"] = [list(point) for point in corrected]
            current["ai_final_parameters"] = fracture_parameters(current)
            current["ai_alignment_status"] = "adjusted"
            current["ai_correction_rounds"] = round_number
            if hasattr(context, "update_monitor"):
                context.update_monitor(
                    parameters=current.get("ai_final_parameters"),
                    correction_round=round_number,
                    api_status="parameters_adjusted",
                )

        return None, {
            "candidate_id": current.get("candidate_id"),
            "reason": "completeness_not_passed_after_five_rounds",
            "stage": "reviewing",
            "annotation": self._diagnostic_annotation(current),
        }

    def _audit_staged_candidates(self, request, context, rendered, staged):
        if not staged:
            return {
                "kept": [],
                "discarded": [],
                "audit_status": "completed",
                "audit_views": [],
                "audit_events": [],
                "audit_action_count": 0,
            }
        def update_audit_status(details):
            context.update(
                "auditing",
                0.84 + 0.04 * min(1.0, details.get("action_count", 0) / MAX_AUDIT_ACTIONS),
                f"Auditing batch view {details.get('view_count', 0)}/{details.get('max_views', 0)}",
            )
            if hasattr(context, "update_monitor"):
                context.update_monitor(
                    view_budget_used=details.get("view_count", 0),
                    view_budget_limit=details.get("max_views", MAX_AUDIT_VIEWS),
                    budget_stage="audit",
                    api_status="auditing",
                )

        try:
            result = self.audit_candidate_batch(
                request,
                rendered,
                staged,
                view_recorder=(
                    (lambda view_id, payload: context.set_view_payload(view_id, payload))
                    if hasattr(context, "set_view_payload") else None
                ),
                status_callback=update_audit_status,
                monitor_callback=lambda update: self._forward_monitor_update(context, update),
                cancel_requested=lambda: context.cancelled,
            )
            if context.cancelled:
                return {"kept": [], "discarded": [], "audit_status": "cancelled"}
            final_overlay = self._build_batch_feedback_image(
                rendered,
                result.get("kept", []),
                request.target_image_track,
            )
            if hasattr(context, "set_monitor_media"):
                context.set_monitor_media(
                    "final_overlay",
                    {"data_url": final_overlay, "metadata": rendered.get("metadata") or {}},
                    api_status="audit_completed",
                )
            if hasattr(context, "record_event"):
                context.record_event(
                    "auditing",
                    "audit_completed",
                    result.get("audit_status", "completed"),
                    status="accepted",
                    kept_count=len(result.get("kept", [])),
                    discarded_count=len(result.get("discarded", [])),
                )
            return result
        except Exception as exc:
            if context.cancelled:
                return {"kept": [], "discarded": [], "audit_status": "cancelled"}
            kept, discarded = self._non_maximum_suppression(staged, rendered)
            fallback = []
            for candidate in kept:
                clean = dict(candidate)
                clean["needs_review"] = True
                clean["batch_audit_status"] = "failed_fallback"
                clean["batch_audit_error"] = str(exc)
                fallback.append(clean)
            final_overlay = self._build_batch_feedback_image(
                rendered,
                fallback,
                request.target_image_track,
            )
            if hasattr(context, "set_monitor_media"):
                context.set_monitor_media(
                    "final_overlay",
                    {"data_url": final_overlay, "metadata": rendered.get("metadata") or {}},
                    api_status="audit_failed_fallback",
                )
            if hasattr(context, "record_event"):
                context.record_event(
                    "auditing",
                    "audit_failed_fallback",
                    str(exc),
                    status="needs_review",
                )
            return {
                "kept": fallback,
                "discarded": discarded,
                "audit_status": "failed_fallback",
                "audit_error": str(exc),
                "audit_views": [],
                "audit_events": [],
                "audit_action_count": 0,
                "audit_decisions": [
                    {
                        "candidate_id": item.get("candidate_id"),
                        "action": "keep",
                        "reason": "Audit failed; retained NMS result for human review",
                    }
                    for item in fallback
                ],
            }

    def discover_candidate_windows(self, request, rendered, *, client=None, model=None):
        candidates, _diagnostics = self.explore_candidate_windows(
            request,
            rendered,
            client=client,
            model=model,
        )
        return candidates

    def explore_candidate_windows(self, request, rendered, *, context=None, client=None, model=None):
        """Let the vision model choose its own sequence of Plot observations."""
        self._validate_rendered(rendered)
        metadata = rendered["metadata"]
        self._target_track(metadata, request.target_image_track)
        if client is None or model is None:
            _config, client, model = self._client()

        state = self.pipeline.create_agent_state()
        overview_request = FractureAgentViewRequest(
            float(metadata["depth_start"]),
            float(metadata["depth_end"]),
            detail_level="overview",
            include_depth_track=True,
        )
        state.record_view(overview_request, "overview")
        current_rendered = rendered
        current_view = state.views[-1]
        if context is not None and hasattr(context, "set_view_payload"):
            context.set_view_payload("overview", rendered)

        while not state.finished:
            if context is not None and context.cancelled:
                break
            if state.action_count >= state.budget.max_actions:
                state.record_event("finish_exploration", "Action budget exhausted", outcome="forced")
                state.finish()
                break

            if context is not None:
                progress = 0.10 + 0.10 * min(1.0, state.action_count / state.budget.max_actions)
                context.update(
                    "exploring",
                    progress,
                    f"AI: exploring view {len(state.views)}/{state.budget.max_views}, "
                    f"{len(state.fragments)} fragment(s), {len(state.hypotheses)} hypothesis test(s), "
                    f"{len(state.candidates)} candidate(s)",
                )
                if hasattr(context, "update_exploration"):
                    context.update_exploration(
                        action_count=state.action_count,
                        view_count=len(state.views),
                        fragment_count=len(state.fragments),
                        hypothesis_count=len(state.hypotheses),
                        candidate_count=len(state.candidates),
                        current_view_id=current_view["view_id"],
                    )
                if hasattr(context, "update_monitor"):
                    context.update_monitor(
                        view_budget_used=len(state.views),
                        view_budget_limit=state.budget.max_views,
                        budget_stage="exploration",
                        fragment_count=len(state.fragments),
                        hypothesis_count=len(state.hypotheses),
                        candidate_count=len(state.candidates),
                        api_status="exploring",
                    )

            payload = self._request_exploration_action(
                request,
                current_rendered,
                current_view,
                state,
                client,
                model,
            )
            action = str(payload.get("action") or "")
            reason = str(payload.get("reason") or "")
            try:
                state.record_action(action)
                if action == "inspect_view":
                    if payload.get("view") is None:
                        raise ValueError("inspect_view requires a view request")
                    view_request = FractureAgentViewRequest.build(payload["view"], metadata)
                    view_id = f"view-{len(state.views):03d}"
                    state.record_view(view_request, view_id)
                    current_rendered = self.pipeline.render_agent_view(
                        rendered,
                        request.target_image_track,
                        view_request,
                        view_id=view_id,
                    )
                    current_view = state.views[-1]
                    if context is not None and hasattr(context, "set_view_payload"):
                        context.set_view_payload(view_id, current_rendered)
                    state.record_event(action, reason)
                    if context is not None and hasattr(context, "record_event"):
                        context.record_event("exploring", action, reason, status="accepted", view_id=view_id)
                elif action == "register_trace_fragment":
                    if payload.get("fragment") is None:
                        raise ValueError("register_trace_fragment requires fragment data")
                    fragment = state.register_trace_fragment(
                        payload["fragment"],
                        request.fracture_types,
                        metadata,
                    )
                    state.record_event(action, reason)
                    if context is not None and hasattr(context, "record_event"):
                        context.record_event(
                            "exploring",
                            action,
                            reason,
                            status="accepted",
                            fragment_id=fragment["fragment_id"],
                        )
                elif action == "test_sinusoid_hypothesis":
                    if payload.get("hypothesis") is None:
                        raise ValueError("test_sinusoid_hypothesis requires hypothesis data")
                    hypothesis = state.register_hypothesis(
                        payload["hypothesis"],
                        request.fracture_types,
                        metadata,
                    )
                    view_id = (
                        f"hypothesis-{hypothesis['hypothesis_id']}-"
                        f"r{hypothesis['revision']}"
                    )
                    current_rendered, view_request = self._render_sinusoid_hypothesis(
                        rendered,
                        request.target_image_track,
                        hypothesis,
                        view_id=view_id,
                    )
                    state.record_view(
                        view_request,
                        view_id,
                        variant=f"hypothesis:{hypothesis['hypothesis_id']}:r{hypothesis['revision']}",
                    )
                    current_view = state.views[-1]
                    if context is not None and hasattr(context, "set_view_payload"):
                        context.set_view_payload(view_id, current_rendered)
                    state.record_event(action, reason)
                    if context is not None and hasattr(context, "record_event"):
                        context.record_event(
                            "exploring",
                            action,
                            reason,
                            status="accepted",
                            view_id=view_id,
                            hypothesis_id=hypothesis["hypothesis_id"],
                        )
                elif action == "register_candidate":
                    if payload.get("candidate") is None:
                        raise ValueError("register_candidate requires candidate data")
                    confidence = float(payload["candidate"].get("confidence", 0.0))
                    if confidence < request.min_confidence:
                        raise ValueError(
                            f"Candidate confidence {confidence:.3f} is below the run minimum "
                            f"{request.min_confidence:.3f}"
                        )
                    registered = state.register_candidate(
                        payload["candidate"], request.fracture_types, metadata
                    )
                    variant = str(current_view.get("variant") or "")
                    matching = None
                    if variant.startswith("hypothesis:"):
                        parts = variant.split(":")
                        hypothesis_id = parts[1] if len(parts) > 1 else ""
                        matching = next(
                            (
                                item for item in reversed(state.hypotheses)
                                if item.get("hypothesis_id") == hypothesis_id
                            ),
                            None,
                        )
                    else:
                        candidate_payload = payload["candidate"]
                        candidate_top = float(candidate_payload["depth_top"])
                        candidate_bottom = float(candidate_payload["depth_bottom"])
                        matching = next(
                            (
                                item for item in reversed(state.hypotheses)
                                if item.get("fracture_type") == candidate_payload.get("fracture_type")
                                and float(item.get("center_depth_m", 0.0))
                                + float(item.get("amplitude_m", 0.0)) >= candidate_top
                                and float(item.get("center_depth_m", 0.0))
                                - float(item.get("amplitude_m", 0.0)) <= candidate_bottom
                            ),
                            None,
                        )
                        hypothesis_id = str(matching.get("hypothesis_id") or "") if matching else ""
                    if matching is not None:
                        registered["agent_hypothesis_verified"] = True
                        registered["agent_hypothesis_id"] = hypothesis_id
                        registered["agent_hypothesis_revision"] = (
                            matching.get("revision") if matching else None
                        )
                        registered["agent_fragment_ids"] = list(
                            matching.get("fragment_ids", []) if matching else []
                        )
                    state.record_event(action, reason)
                    if context is not None and hasattr(context, "record_event"):
                        context.record_event(
                            "exploring",
                            action,
                            reason,
                            status="accepted",
                            candidate_id=payload["candidate"].get("candidate_id"),
                        )
                elif action == "finish_exploration":
                    state.record_event(action, reason)
                    if context is not None and hasattr(context, "record_event"):
                        context.record_event("exploring", action, reason, status="accepted")
                    state.finish()
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                state.record_event(action, reason, outcome="rejected", error=exc)
                if context is not None and hasattr(context, "record_event"):
                    context.record_event("exploring", action, f"{reason}: {exc}", status="rejected")
                if state.action_count >= state.budget.max_actions:
                    state.finish()

        candidates = sorted(
            state.candidates,
            key=lambda item: (item["depth_top"], item["candidate_id"]),
        )
        diagnostics = {
            "budget": asdict(state.budget),
            "action_count": state.action_count,
            "views": list(state.views),
            "trace_fragments": list(state.fragments),
            "sinusoid_hypotheses": list(state.hypotheses),
            "events": list(state.events),
            "finished": state.finished,
        }
        if context is not None and hasattr(context, "update_exploration"):
            context.update_exploration(
                action_count=state.action_count,
                view_count=len(state.views),
                fragment_count=len(state.fragments),
                hypothesis_count=len(state.hypotheses),
                candidate_count=len(candidates),
                current_view_id=current_view["view_id"],
                finished=state.finished,
            )
        return candidates, diagnostics

    def _request_exploration_action(self, request, current_rendered, current_view, state, client, model):
        metadata = current_rendered["metadata"]
        prompt = (
            "You control an autonomous inspection loop for complete borehole-image fractures. Choose exactly one next "
            "action. You are not restricted to a fixed number of depth segments. Use inspect_view whenever another "
            "depth interval, wider or narrower crop, or partial azimuth view is needed. Requested views are cropped "
            "from the immutable analysis image at its original pixel scale; detail_level does not magnify or add image "
            "resolution, so never repeat identical depth and azimuth bounds with another detail_level. Partial-azimuth views are "
            "diagnostic only. Use register_trace_fragment to preserve a visible local arc as structured evidence when "
            "it is not yet sufficient to register a complete fracture. Record its observed depth and azimuth bounds, "
            "local slope direction, type, and continuity evidence. Do not register the same physical fragment twice. "
            "When complementary fragments might be portions of one high-amplitude complete trace, use "
            "test_sinusoid_hypothesis with their fragment ids and absolute parameters for "
            "D(theta)=c+A*sin(theta+phase). The application will return a source-scale crop with the complete periodic "
            "hypothesis curve overlaid. Inspect that overlay on the next action, then adjust the same hypothesis id, "
            "register a candidate, inspect another crop, or abandon it. A hypothesis is diagnostic and does not create "
            "a candidate. A physical fracture may be incompletely visible because pads, blank strips, tool coverage, "
            "noise, or low-clarity intervals hide parts of the circumference. Missing visible evidence is not evidence "
            "that the fracture stops. Preserve visible arcs with register_trace_fragment and test whether separated arcs "
            "share one fixed-period sinusoid before registering or rejecting them. Do "
            "not reject a possible high-amplitude fracture merely because its visible evidence appears as separated "
            "arcs at different depths or in different azimuth sectors. Before rejecting such fragments, test whether "
            "they can belong to one fixed-period sinusoid using compatible position, slope, curvature, peak/trough "
            "order, and seam behavior. Request a wider depth view that contains the entire "
            "peak-to-trough envelope plus surrounding margin; do not decide from isolated close crops alone. Treat "
            "complementary arcs on opposite sides of pad gaps or low-clarity zones as one hypothesis when a smooth "
            "sinusoid can bridge them. Still reject fragments that require switching to an unrelated texture, violate "
            "sinusoidal slope or curvature. Do not register isolated local segments without a compatible counterpart, "
            "stitched unrelated textures, or duplicate windows. Register one candidate at a time. Use "
            "finish_exploration only after the requested depth interval has been examined sufficiently, including this "
            "wide-window continuity check for unresolved high-amplitude fragments. "
            "Set only the payload for the selected action: view for inspect_view, fragment for "
            "register_trace_fragment, hypothesis for test_sinusoid_hypothesis, and candidate for register_candidate. "
            "Set every other action payload to null. For finish_exploration set all four payloads to null. "
            "All depth values must use exact metadata, never OCR estimates. Return JSON only.\n"
            + json.dumps({
                "run_bounds": {
                    "depth_start": request.depth_start,
                    "depth_end": request.depth_end,
                    "target_image_track": request.target_image_track,
                    "fracture_types": list(request.fracture_types),
                    "minimum_confidence": request.min_confidence,
                },
                "current_view": current_view,
                "current_view_metadata": {
                    "depth_start": metadata["depth_start"],
                    "depth_end": metadata["depth_end"],
                    "tracks": metadata.get("tracks", []),
                },
                "exploration_state": state.prompt_context(),
            }, ensure_ascii=False)
        )
        response = self.pipeline._request(
            client,
            model,
            self._vision_messages(
                "You autonomously navigate Plot views to find complete borehole-image fractures.",
                prompt,
                current_rendered["data_url"],
            ),
            response_schema=FRACTURE_EXPLORATION_ACTION_SCHEMA,
        )
        return _json_payload(response)

    def _render_sinusoid_hypothesis(self, rendered, target_image_track, hypothesis, *, view_id):
        metadata = rendered["metadata"]
        center = float(hypothesis["center_depth_m"])
        amplitude = float(hypothesis["amplitude_m"])
        margin = max(0.15, amplitude * 0.4)
        view_request = FractureAgentViewRequest(
            depth_start=max(float(metadata["depth_start"]), center - amplitude - margin),
            depth_end=min(float(metadata["depth_end"]), center + amplitude + margin),
            azimuth_start_deg=0.0,
            azimuth_end_deg=360.0,
            detail_level="detail",
            include_depth_track=True,
        )
        cropped = self.pipeline.render_agent_view(
            rendered,
            target_image_track,
            view_request,
            view_id=view_id,
        )
        points = canonical_fracture_points(
            center,
            amplitude,
            float(hypothesis["phase_deg"]),
        )
        overlay = self.pipeline._build_feedback_image(cropped, points, target_image_track)
        output = {
            "data_url": overlay,
            "metadata": dict(cropped["metadata"]),
        }
        output["metadata"]["hypothesis"] = dict(hypothesis)
        output["metadata"]["hypothesis_points"] = [list(point) for point in points]
        return output, view_request

    def render_candidate_window(self, rendered, candidate, target_image_track):
        self._validate_rendered(rendered)
        metadata = rendered["metadata"]
        image = self._decode_image(rendered["data_url"])
        source_start = float(metadata["depth_start"])
        source_end = float(metadata["depth_end"])
        span = float(candidate["depth_bottom"]) - float(candidate["depth_top"])
        padding = max(span * 0.20, 0.15)
        crop_start = max(source_start, float(candidate["depth_top"]) - padding)
        crop_end = min(source_end, float(candidate["depth_bottom"]) + padding)
        top = float(metadata.get("plot_top", 0.0))
        bottom = float(metadata.get("plot_bottom", image.height()))
        source_span = source_end - source_start
        y0 = int(round(top + (crop_start - source_start) / source_span * (bottom - top)))
        y1 = int(round(top + (crop_end - source_start) / source_span * (bottom - top)))
        y0, y1 = max(0, y0), min(image.height(), y1)
        if y1 <= y0:
            raise ValueError("Candidate depth window maps to an empty image crop")

        target = self._target_track(metadata, target_image_track)
        depth_tracks = [track for track in metadata.get("tracks", []) if track.get("is_depth")]
        pieces = depth_tracks[:1] + [target]
        widths = [int(round(float(item["pixel_right"]) - float(item["pixel_left"]))) for item in pieces]
        canvas = QImage(sum(widths), y1 - y0, QImage.Format_ARGB32)
        canvas.fill(QColor("#FFFFFF"))
        painter = QPainter(canvas)
        x_offset = 0
        tracks = []
        for item, width in zip(pieces, widths):
            left = int(round(float(item["pixel_left"])))
            part = image.copy(left, y0, width, y1 - y0)
            painter.drawImage(x_offset, 0, part)
            copied = dict(item)
            copied["pixel_left"] = x_offset
            copied["pixel_right"] = x_offset + width
            copied["pixel_width"] = width
            tracks.append(copied)
            x_offset += width
        painter.end()

        candidate_metadata = {
            "width": canvas.width(),
            "height": canvas.height(),
            "plot_top": 0,
            "plot_bottom": canvas.height(),
            "depth_start": crop_start,
            "depth_end": crop_end,
            "tracks": tracks,
            "target_image_track": target_image_track,
            "candidate_id": candidate["candidate_id"],
            "candidate_depth_window": [candidate["depth_top"], candidate["depth_bottom"]],
            "source_render_size": [metadata.get("width"), metadata.get("height")],
            "uniform_scale": 1.0,
        }
        return {"data_url": self._encode_image(canvas), "metadata": candidate_metadata}

    def pick_candidate_anchors(self, request, candidate_rendered, candidate, *, client=None, model=None):
        if client is None or model is None:
            _config, client, model = self._client()
        metadata = candidate_rendered["metadata"]
        prompt = (
            "Trace exactly one physical fracture in this focused borehole-image window. Return 3 to 8 anchor points "
            "on clearly visible parts of the same trace. Prefer a crest, trough, and visible mid-slope sections; include "
            "left or right seam points only when those sectors are actually readable. Do not place invented anchors in "
            "blank, missing-pad, or low-clarity sectors. Separated visible arcs may belong to one fracture when position, "
            "slope, curvature, and the tested fixed-period sinusoid connect them. Do not stitch unrelated textures. x_norm is relative to the target "
            "image track; y_norm is relative to the focused crop depth range. Return JSON only.\n"
            + json.dumps({
                "candidate": candidate,
                "target_image_track": request.target_image_track,
                "depth_start": metadata["depth_start"],
                "depth_end": metadata["depth_end"],
                "target_bounds": self._target_track(metadata, request.target_image_track),
            }, ensure_ascii=False)
        )
        response = self.pipeline._request(
            client,
            model,
            self._vision_messages("You place anchor points on one complete borehole-image fracture.", prompt, candidate_rendered["data_url"]),
            response_schema=ANCHOR_SCHEMA,
        )
        return _json_payload(response)

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
        monitor_callback=None,
        cancel_requested=None,
    ):
        self._validate_rendered(candidate_rendered)
        points = self._clean_depth_points(annotation.get("points"))
        if len(points) < MIN_TRACE_POINTS:
            raise ValueError("At least three candidate points are required for review")
        _config, client, model = self._client()
        fit = fit_sinusoidal_fracture(points, min_points=MIN_TRACE_POINTS)
        parameters = fracture_parameters(fit)
        local = self.pipeline.evidence_scorer.evaluate(
            candidate_rendered,
            request.target_image_track,
            fit,
        )
        source = source_rendered or candidate_rendered
        self._validate_rendered(source)
        current_rendered = candidate_rendered
        review_views = []
        review_view_keys = set()
        review_events = []
        action_count = 0

        while action_count < MAX_REVIEW_ACTIONS:
            if callable(cancel_requested) and cancel_requested():
                raise RuntimeError("Fracture detection cancelled")
            if callable(status_callback):
                status_callback({
                    "action_count": action_count,
                    "view_count": len(review_views),
                    "max_views": MAX_REVIEW_VIEWS,
                    "round_number": int(round_number),
                })
            feedback = self.pipeline._build_feedback_image(
                current_rendered,
                points,
                request.target_image_track,
            )
            if callable(monitor_callback):
                monitor_callback({
                    "media_slot": "overlay",
                    "payload": {"data_url": feedback, "metadata": current_rendered.get("metadata") or {}},
                    "parameters": parameters,
                    "api_status": "requesting_review",
                })
            current_metadata = current_rendered["metadata"]
            current_target = self._target_track(current_metadata, request.target_image_track)
            prompt = (
                "Review one fitted complete fracture. The magenta curve is the current fixed-period sine fit and yellow "
                "circles are its anchors. You may use inspect_view to request another depth interval, a narrower or "
                "wider crop, or a partial-azimuth diagnostic view before deciding. Views retain the source pixel scale; "
                "detail_level does not magnify or add resolution. Do not request identical depth and azimuth bounds "
                "again with another detail_level. A partial-azimuth view may support a final decision when other "
                "azimuth sectors are blank, obscured, or not measured. Prefer "
                "adjust_parameters and return absolute center depth, amplitude, and phase using "
                "D(theta)=c+A*sin(theta+phase). Use replace_points only when the fit follows the wrong texture. Use "
                "discard only for an isolated local segment with no compatible continuation, or for stitched unrelated "
                "textures. Do not discard merely because some azimuth sectors are unclear or absent. Use keep when "
                "the visible arcs are compatible with one fixed-period fracture. The local "
                "completeness score is advisory diagnostic evidence: a failed or unavailable local score must not by "
                "itself force correction or discard. For inspect_view provide view and leave "
                "parameter fields null; for all final actions set view=null. Return JSON only.\n"
                + json.dumps({
                    "candidate_id": annotation.get("candidate_id"),
                    "fracture_type": annotation.get("fracture_type"),
                    "correction_round": int(round_number),
                    "current_parameters": parameters,
                    "local_completeness": local,
                    "current_view": {
                        "depth_start": current_metadata["depth_start"],
                        "depth_end": current_metadata["depth_end"],
                        "azimuth_start_deg": current_target.get("azimuth_start_deg", 0.0),
                        "azimuth_end_deg": current_target.get("azimuth_end_deg", 360.0),
                        "full_azimuth": bool(current_target.get("full_azimuth", True)),
                    },
                    "review_budget": {
                        "max_actions": MAX_REVIEW_ACTIONS,
                        "max_inspection_views": MAX_REVIEW_VIEWS,
                        "actions_used": action_count,
                        "inspection_views_used": len(review_views),
                    },
                    "recent_events": review_events[-6:],
                }, ensure_ascii=False)
            )
            response = self.pipeline._request(
                client,
                model,
                self._vision_messages("You autonomously refine one complete borehole-image fracture fit.", prompt, feedback),
                response_schema=PARAMETER_REVIEW_SCHEMA,
            )
            payload = _json_payload(response)
            if callable(cancel_requested) and cancel_requested():
                raise RuntimeError("Fracture detection cancelled")
            action_count += 1
            action = str(payload.get("action") or "discard")
            reason = str(payload.get("reason") or "")
            if callable(monitor_callback):
                monitor_callback({
                    "event": {
                        "stage": "reviewing",
                        "action": action,
                        "reason": reason,
                        "status": "response",
                    },
                    "api_status": "review_response_received",
                })

            if action == "inspect_view":
                if len(review_views) >= MAX_REVIEW_VIEWS:
                    review_events.append({
                        "action": action,
                        "outcome": "rejected",
                        "reason": "Candidate review view budget exhausted",
                    })
                    continue
                try:
                    if payload.get("view") is None:
                        raise ValueError("inspect_view requires a view request")
                    view_request = FractureAgentViewRequest.build(payload.get("view"), source["metadata"])
                    view_key = view_request.key()
                    if view_key in review_view_keys:
                        raise ValueError("Duplicate crop bounds were already inspected")
                    review_view_keys.add(view_key)
                    view_id = (
                        f"review-{annotation.get('candidate_id') or 'candidate'}-"
                        f"r{int(round_number)}-v{len(review_views) + 1}"
                    )
                    current_rendered = self.pipeline.render_agent_view(
                        source,
                        request.target_image_track,
                        view_request,
                        view_id=view_id,
                    )
                    view_record = {"view_id": view_id, **asdict(view_request), "reason": reason}
                    review_views.append(view_record)
                    review_events.append({"action": action, "outcome": "accepted", **view_record})
                    if callable(view_recorder):
                        view_recorder(view_id, current_rendered)
                    if callable(status_callback):
                        status_callback({
                            "action_count": action_count,
                            "view_count": len(review_views),
                            "max_views": MAX_REVIEW_VIEWS,
                            "round_number": int(round_number),
                            "current_view_id": view_id,
                        })
                except (TypeError, ValueError, RuntimeError) as exc:
                    review_events.append({
                        "action": action,
                        "outcome": "rejected",
                        "reason": reason,
                        "error": str(exc),
                    })
                continue

            result = self._normalize_review(payload, annotation, current_rendered, request, local)
            result["review_views"] = review_views
            result["review_events"] = review_events
            result["review_action_count"] = action_count
            return result

        return {
            "action": "retry",
            "aligned": False,
            "confidence": 0.0,
            "corrected_points": [list(point) for point in points],
            "parameters": parameters,
            "reason": "candidate_review_action_budget_exhausted",
            "local_completeness": local,
            "corrected_local_completeness": None,
            "needs_review": False,
            "review_views": review_views,
            "review_events": review_events,
            "review_action_count": action_count,
        }

    def audit_candidate_batch(
        self,
        request,
        rendered,
        staged_candidates,
        *,
        view_recorder=None,
        status_callback=None,
        monitor_callback=None,
        cancel_requested=None,
    ):
        nms_kept, nms_discarded = self._non_maximum_suppression(staged_candidates, rendered)
        if not nms_kept:
            return {
                "kept": [],
                "discarded": nms_discarded,
                "audit_status": "completed",
                "audit_views": [],
                "audit_events": [],
                "audit_action_count": 0,
            }
        _config, client, model = self._client()
        current_rendered = rendered
        audit_views = []
        audit_view_keys = set()
        audit_events = []
        action_count = 0
        expected_ids = [str(item.get("candidate_id")) for item in nms_kept]

        while action_count < MAX_AUDIT_ACTIONS:
            if callable(cancel_requested) and cancel_requested():
                raise RuntimeError("Fracture detection cancelled")
            if callable(status_callback):
                status_callback({
                    "action_count": action_count,
                    "view_count": len(audit_views),
                    "max_views": MAX_AUDIT_VIEWS,
                })
            feedback = self._build_batch_feedback_image(
                current_rendered,
                nms_kept,
                request.target_image_track,
            )
            if callable(monitor_callback):
                monitor_callback({
                    "media_slot": "overlay",
                    "payload": {"data_url": feedback, "metadata": current_rendered.get("metadata") or {}},
                    "api_status": "requesting_audit",
                })
            current_metadata = current_rendered["metadata"]
            current_target = self._target_track(current_metadata, request.target_image_track)
            prompt = (
                "Autonomously audit the final staged complete-fracture batch. Choose one action. Use inspect_view when "
                "another depth range, a narrower or wider crop, or partial-azimuth detail is needed. Views retain the "
                "source pixel scale; detail_level does not magnify or add resolution. Do not request identical depth "
                "and azimuth bounds again with another detail_level. Final decisions may only keep or discard existing "
                "candidates. Missing or unclear azimuth sectors caused by pad coverage, blank strips, or poor imaging are "
                "not a discard reason. Treat compatible visible arcs as one fracture when position, slope, curvature, and "
                "a tested fixed-period sinusoid connect them. Discard duplicates, isolated fragments without a compatible "
                "continuation, and curves demonstrably stitched across unrelated visible textures. Never merge candidates, create a new "
                "curve, or alter parameters during batch audit. Local completeness scores and needs_review flags are "
                "advisory; never discard a visually complete candidate solely because its local score failed or was "
                "unavailable. Do not split one tested sinusoid into multiple picks. A candidate already supported by an "
                "individual aligned review plus either local evidence or a tested fragment hypothesis should normally be "
                "kept; report uncertainty in the reason instead of discarding it. finalize_audit must return exactly one decision for "
                "every candidate id. For inspect_view set decisions=[]; for finalize_audit set view=null. Return JSON only.\n"
                + json.dumps({
                    "candidates": [
                        {
                            "candidate_id": item.get("candidate_id"),
                            "fracture_type": item.get("fracture_type"),
                            "overlay_color": item.get("_audit_color"),
                            "parameters": fracture_parameters(item),
                            "local_completeness": item.get("local_completeness"),
                            "needs_review": bool(item.get("needs_review", False)),
                        }
                        for item in nms_kept
                    ],
                    "current_view": {
                        "depth_start": current_metadata["depth_start"],
                        "depth_end": current_metadata["depth_end"],
                        "azimuth_start_deg": current_target.get("azimuth_start_deg", 0.0),
                        "azimuth_end_deg": current_target.get("azimuth_end_deg", 360.0),
                        "full_azimuth": bool(current_target.get("full_azimuth", True)),
                    },
                    "audit_budget": {
                        "max_actions": MAX_AUDIT_ACTIONS,
                        "max_inspection_views": MAX_AUDIT_VIEWS,
                        "actions_used": action_count,
                        "inspection_views_used": len(audit_views),
                    },
                    "recent_events": audit_events[-8:],
                }, ensure_ascii=False)
            )
            response = self.pipeline._request(
                client,
                model,
                self._vision_messages("You autonomously audit a staged batch of complete fracture picks.", prompt, feedback),
                response_schema=BATCH_AUDIT_SCHEMA,
            )
            payload = _json_payload(response)
            if callable(cancel_requested) and cancel_requested():
                raise RuntimeError("Fracture detection cancelled")
            action_count += 1
            action = str(payload.get("action") or "")
            reason = str(payload.get("reason") or "")
            if callable(monitor_callback):
                monitor_callback({
                    "event": {
                        "stage": "auditing",
                        "action": action,
                        "reason": reason,
                        "status": "response",
                    },
                    "api_status": "audit_response_received",
                })

            if action == "inspect_view":
                if len(audit_views) >= MAX_AUDIT_VIEWS:
                    audit_events.append({
                        "action": action,
                        "outcome": "rejected",
                        "reason": "Batch audit view budget exhausted",
                    })
                    continue
                try:
                    if payload.get("view") is None:
                        raise ValueError("inspect_view requires a view request")
                    view_request = FractureAgentViewRequest.build(payload["view"], rendered["metadata"])
                    view_key = view_request.key()
                    if view_key in audit_view_keys:
                        raise ValueError("Duplicate crop bounds were already inspected")
                    audit_view_keys.add(view_key)
                    view_id = f"audit-v{len(audit_views) + 1}"
                    current_rendered = self.pipeline.render_agent_view(
                        rendered,
                        request.target_image_track,
                        view_request,
                        view_id=view_id,
                    )
                    view_record = {"view_id": view_id, **asdict(view_request), "reason": reason}
                    audit_views.append(view_record)
                    audit_events.append({"action": action, "outcome": "accepted", **view_record})
                    if callable(view_recorder):
                        view_recorder(view_id, current_rendered)
                    if callable(status_callback):
                        status_callback({
                            "action_count": action_count,
                            "view_count": len(audit_views),
                            "max_views": MAX_AUDIT_VIEWS,
                            "current_view_id": view_id,
                        })
                except (TypeError, ValueError, RuntimeError) as exc:
                    audit_events.append({
                        "action": action,
                        "outcome": "rejected",
                        "reason": reason,
                        "error": str(exc),
                    })
                continue

            if action != "finalize_audit":
                audit_events.append({
                    "action": action,
                    "outcome": "rejected",
                    "reason": "Unsupported batch audit action",
                })
                continue
            decision_items = [item for item in payload.get("decisions", []) if isinstance(item, dict)]
            decision_ids = [str(item.get("candidate_id")) for item in decision_items]
            if len(decision_ids) != len(set(decision_ids)) or set(decision_ids) != set(expected_ids):
                audit_events.append({
                    "action": action,
                    "outcome": "rejected",
                    "reason": "Final audit must contain exactly one decision for every candidate id",
                    "received_candidate_ids": decision_ids,
                })
                current_rendered = rendered
                continue

            decisions = {str(item.get("candidate_id")): item for item in decision_items}
            kept, discarded = [], list(nms_discarded)
            for candidate in nms_kept:
                candidate_id = str(candidate.get("candidate_id"))
                decision = decisions[candidate_id]
                if decision.get("action") == "keep":
                    clean = dict(candidate)
                    clean["batch_audit_status"] = "kept"
                    clean["batch_audit_views"] = list(audit_views)
                    clean["batch_audit_action_count"] = action_count
                    kept.append(clean)
                elif self._has_strong_pre_audit_support(candidate):
                    clean = dict(candidate)
                    clean["needs_review"] = True
                    clean["batch_audit_status"] = "kept_after_audit_conflict"
                    clean["batch_audit_conflict_reason"] = (
                        decision.get("reason") or "discarded_by_batch_audit"
                    )
                    clean["batch_audit_views"] = list(audit_views)
                    clean["batch_audit_action_count"] = action_count
                    kept.append(clean)
                else:
                    discarded.append({
                        "candidate_id": candidate_id,
                        "reason": decision.get("reason") or "discarded_by_batch_audit",
                        "stage": "batch_audit",
                        "annotation": self._diagnostic_annotation(candidate),
                    })
            audit_events.append({"action": action, "outcome": "accepted", "reason": reason})
            return {
                "kept": kept,
                "discarded": discarded,
                "audit_status": "completed",
                "audit_views": audit_views,
                "audit_events": audit_events,
                "audit_action_count": action_count,
                "audit_decisions": decision_items,
            }

        fallback = []
        for candidate in nms_kept:
            clean = dict(candidate)
            clean["needs_review"] = True
            clean["batch_audit_status"] = "budget_exhausted_fallback"
            fallback.append(clean)
        return {
            "kept": fallback,
            "discarded": list(nms_discarded),
            "audit_status": "budget_exhausted_fallback",
            "audit_views": audit_views,
            "audit_events": audit_events,
            "audit_action_count": action_count,
            "audit_decisions": [
                {
                    "candidate_id": item.get("candidate_id"),
                    "action": "keep",
                    "reason": "Audit budget exhausted; retained NMS result for human review",
                }
                for item in fallback
            ],
        }

    @staticmethod
    def _has_strong_pre_audit_support(candidate):
        local = (
            candidate.get("corrected_local_completeness")
            or candidate.get("local_completeness")
            or {}
        )
        aligned = str(candidate.get("ai_alignment_status") or "") == "aligned"
        local_supported = bool(local.get("available", False) and local.get("complete", False))
        hypothesis_supported = bool(candidate.get("agent_hypothesis_verified", False))
        return aligned and (local_supported or hypothesis_supported)

    def _normalize_review(self, payload, annotation, candidate_rendered, request, local):
        action = str(payload.get("action") or "discard")
        reason = str(payload.get("reason") or "")
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
        corrected_points = []
        parameters = None
        if action == "adjust_parameters":
            try:
                parameters = {
                    "center_depth_m": float(payload["center_depth_m"]),
                    "amplitude_m": abs(float(payload["amplitude_m"])),
                    "phase_deg": float(payload["phase_deg"]) % 360.0,
                }
                if not all(math.isfinite(value) for value in parameters.values()):
                    raise ValueError
                corrected_points = canonical_fracture_points(**parameters)
            except (KeyError, TypeError, ValueError):
                action = "discard"
                reason = reason or "invalid_parameter_correction"
        elif action == "replace_points":
            corrected_points = self._normalized_points_to_depth(
                payload.get("corrected_points"),
                candidate_rendered["metadata"],
            )
            if len(corrected_points) < MIN_TRACE_POINTS:
                action = "discard"
                reason = reason or "invalid_replacement_points"
        corrected_local = None
        if corrected_points:
            corrected_fit = fit_sinusoidal_fracture(corrected_points, min_points=MIN_TRACE_POINTS)
            parameters = fracture_parameters(corrected_fit)
            corrected_local = self.pipeline.evidence_scorer.evaluate(
                candidate_rendered,
                request.target_image_track,
                corrected_fit,
            )

        local_available = bool(local.get("available", False))
        local_complete = bool(local.get("complete", False)) if local_available else False
        aligned = bool(payload.get("aligned", False)) and action == "keep"
        if action == "keep" and not aligned:
            action = "retry"
            corrected_points = self._clean_depth_points(annotation.get("points"))
            reason = reason or "visual_alignment_not_confirmed"
        return {
            "action": action,
            "aligned": aligned,
            "confidence": confidence,
            "corrected_points": corrected_points,
            "parameters": parameters,
            "reason": reason,
            "local_completeness": local,
            "corrected_local_completeness": corrected_local,
            "needs_review": bool(aligned and (not local_available or not local_complete)),
        }

    def _non_maximum_suppression(self, candidates, rendered, threshold_px=8.0):
        metadata = rendered["metadata"]
        depth_span = float(metadata["depth_end"]) - float(metadata["depth_start"])
        plot_height = float(metadata.get("plot_bottom", metadata["height"])) - float(metadata.get("plot_top", 0))
        px_per_depth = plot_height / depth_span if depth_span > 0 else 0.0

        def rank(item):
            local = item.get("local_completeness") or {}
            return float(item.get("confidence", 0.0)) + 0.1 * float(local.get("score", 0.0))

        selected, discarded = [], []
        for candidate in sorted((dict(item) for item in candidates), key=rank, reverse=True):
            x, y = sinusoidal_fracture_xy(candidate, samples=181)
            duplicate = None
            for kept in selected:
                _kx, ky = sinusoidal_fracture_xy(kept, samples=181)
                if float(np.mean(np.abs(y - ky))) * px_per_depth < threshold_px:
                    duplicate = kept
                    break
            if duplicate is None:
                selected.append(candidate)
            else:
                discarded.append({
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": f"nms_duplicate_of_{duplicate.get('candidate_id')}",
                    "stage": "nms",
                    "annotation": self._diagnostic_annotation(candidate),
                })
        selected.sort(key=lambda item: float(item.get("offset", 0.0)))
        return selected, discarded

    def _build_batch_feedback_image(self, rendered, candidates, target_image_track):
        image = self._decode_image(rendered["data_url"])
        metadata = rendered["metadata"]
        target = self._target_track(metadata, target_image_track)
        left, right = float(target["pixel_left"]), float(target["pixel_right"])
        azimuth_start = float(target.get("azimuth_start_deg", 0.0))
        azimuth_end = float(target.get("azimuth_end_deg", 360.0))
        top = float(metadata.get("plot_top", 0.0))
        bottom = float(metadata.get("plot_bottom", image.height()))
        start, end = float(metadata["depth_start"]), float(metadata["depth_end"])
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        for index, candidate in enumerate(candidates):
            fracture_type = str(candidate.get("fracture_type") or "Conductive")
            style = FRACTURE_TYPE_STYLES.get(fracture_type, FRACTURE_TYPE_STYLES["Conductive"])
            color_name = str(candidate.get("color") or style["color"])
            candidate["_audit_color"] = color_name
            color = QColor(color_name)
            painter.setPen(QPen(color, 4.0))
            x_values, y_values = sinusoidal_fracture_xy(candidate, samples=361)
            previous = None
            for azimuth, depth in zip(x_values, y_values):
                if not azimuth_start <= float(azimuth) <= azimuth_end:
                    previous = None
                    continue
                point = QPointF(
                    left + (float(azimuth) - azimuth_start) / (azimuth_end - azimuth_start) * (right - left),
                    top + (float(depth) - start) / (end - start) * (bottom - top),
                )
                if previous is not None:
                    painter.drawLine(previous, point)
                previous = point
            first_azimuth = azimuth_start
            first_depth = float(candidate["offset"])
            first_depth += float(candidate.get("sin_coeff", 0.0)) * math.sin(math.radians(first_azimuth))
            first_depth += float(candidate.get("cos_coeff", 0.0)) * math.cos(math.radians(first_azimuth))
            seam_point = QPointF(left + 6, top + (first_depth - start) / (end - start) * (bottom - top))
            painter.setBrush(color)
            painter.drawEllipse(seam_point, 7.0, 7.0)
            self._draw_vector_candidate_number(painter, seam_point + QPointF(10.0, -14.0), index + 1, color)
        painter.end()
        return self._encode_image(image)

    @staticmethod
    def _draw_vector_candidate_number(painter, origin, number, color):
        """Draw an F-prefixed candidate number without requiring Qt's font database."""
        painter.setPen(QPen(color, 3.0))
        x0, y0 = float(origin.x()), float(origin.y())
        painter.drawLine(QPointF(x0, y0), QPointF(x0, y0 + 14.0))
        painter.drawLine(QPointF(x0, y0), QPointF(x0 + 7.0, y0))
        painter.drawLine(QPointF(x0, y0 + 6.0), QPointF(x0 + 6.0, y0 + 6.0))

        segments = {
            "0": "ab cdef".replace(" ", ""), "1": "bc", "2": "abdeg",
            "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg",
            "7": "abc", "8": "abcdefg", "9": "abcdfg",
        }
        segment_lines = {
            "a": ((0, 0), (6, 0)), "b": ((6, 0), (6, 7)),
            "c": ((6, 7), (6, 14)), "d": ((0, 14), (6, 14)),
            "e": ((0, 7), (0, 14)), "f": ((0, 0), (0, 7)),
            "g": ((0, 7), (6, 7)),
        }
        cursor = x0 + 11.0
        for digit in str(max(1, int(number))):
            for segment in segments[digit]:
                start, end = segment_lines[segment]
                painter.drawLine(
                    QPointF(cursor + start[0], y0 + start[1]),
                    QPointF(cursor + end[0], y0 + end[1]),
                )
            cursor += 10.0

    @staticmethod
    def _forward_monitor_update(context, update):
        if not isinstance(update, dict):
            return
        if update.get("media_slot") and hasattr(context, "set_monitor_media"):
            context.set_monitor_media(
                update["media_slot"],
                update.get("payload") or {},
                parameters=update.get("parameters"),
                api_status=update.get("api_status"),
            )
        elif update.get("api_status") and hasattr(context, "update_monitor"):
            context.update_monitor(api_status=update.get("api_status"))
        event = update.get("event")
        if isinstance(event, dict) and hasattr(context, "record_event"):
            context.record_event(
                event.get("stage", "running"),
                event.get("action", "status"),
                event.get("reason", ""),
                status=event.get("status", "running"),
            )

    def _client(self):
        config = self.pipeline.config.get_resolved_vision_config()
        api_key = str(config.get("api_key") or "").strip()
        model = str(config.get("model") or "").strip()
        if not api_key or not model:
            raise RuntimeError("Vision model is not configured")
        return config, self.pipeline._create_client(config), model

    @staticmethod
    def _vision_messages(system, prompt, image_url):
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
            ]},
        ]

    @staticmethod
    def _normalized_points_to_depth(points, metadata):
        start, end = float(metadata["depth_start"]), float(metadata["depth_end"])
        clean = []
        for point in points or []:
            try:
                x = float(point.get("x_norm"))
                y = float(point.get("y_norm"))
            except (AttributeError, TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y) and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0:
                clean.append([x * 360.0, start + y * (end - start)])
        return clean

    @staticmethod
    def _clean_depth_points(points):
        clean = []
        for point in points or []:
            try:
                x, y = float(point[0]), float(point[1])
            except (IndexError, TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(y):
                clean.append([max(0.0, min(360.0, x)), y])
        return clean

    @staticmethod
    def _target_track(metadata, target_image_track):
        target = next(
            (
                track for track in metadata.get("tracks", [])
                if target_image_track in (track.get("name"), track.get("label"))
            ),
            None,
        )
        if target is None:
            raise ValueError(f"Target image track '{target_image_track}' is absent from render metadata")
        return target

    @staticmethod
    def _validate_rendered(rendered):
        if not rendered or not rendered.get("data_url") or not rendered.get("metadata"):
            raise ValueError("Rendered plot image and metadata are required")

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
            raise RuntimeError("Unable to encode candidate image")
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")

    @staticmethod
    def _diagnostic_annotation(annotation):
        return {
            key: value for key, value in dict(annotation).items()
            if not str(key).startswith("_") and key != "item"
        }
