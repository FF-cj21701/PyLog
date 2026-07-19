from __future__ import annotations

import base64
import copy
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
MIN_STABLE_FIT_AZIMUTH_SPAN_DEG = 90.0
MAX_TRACE_POINTS = 8
MAX_CORRECTION_ROUNDS = 5
MAX_REVIEW_VIEWS = 6
MAX_REVIEW_ACTIONS = 8
MAX_AUDIT_VIEWS = 8
MAX_AUDIT_ACTIONS = 12
ASSOCIATION_AZIMUTH_BINS = 8
ASSOCIATION_MAX_PHASE_DELTA_DEG = 30.0
ASSOCIATION_MAX_AMPLITUDE_RELATIVE_DELTA = 0.40
ASSOCIATION_MIN_ENVELOPE_OVERLAP = 0.45
ASSOCIATION_MAX_ANCHOR_JACCARD = 0.70
ASSOCIATION_MIN_MERGED_RMSE_M = 0.08
ASSOCIATION_MAX_MERGED_RMSE_M = 0.12
ASSOCIATION_MAX_MERGED_RMSE_AMPLITUDE_RATIO = 0.20
AUDIT_CONFLICT_MIN_RELATIVE_ENVELOPE = 0.35
AUDIT_CONFLICT_MIN_ANCHOR_SPAN_DEG = 90.0
CANDIDATE_CROP_PADDING_RATIO = 0.35
CANDIDATE_CROP_MIN_PADDING_M = 0.30

FRACTURE_MORPHOLOGY_GUIDANCE = (
    "Apply this borehole-image morphology definition consistently. In FMI/EMI/UBI-like unwrapped images, a "
    "conductive fracture commonly appears as a narrow dark sinusoidal or curved anomaly, while a resistive fracture "
    "commonly appears as a narrow bright sinusoidal or curved anomaly. Fracture traces are typically elongated and "
    "continuous or semi-continuous; their boundaries may be sharp or interrupted by pad gaps, weak imaging, or noise. "
    "Bedding is not necessarily horizontal: it may also form sinusoidal traces, but it usually occurs as a regular, "
    "repeated family of approximately parallel curves with stable extension and similar geometry. Distinguish a "
    "fracture from bedding by relational evidence, not orientation alone. A narrow, distinct trace that cuts across "
    "several bedding bands, departs from the repeated bedding family, or has a clearly different angle is positive "
    "fracture evidence. Do not classify one isolated bedding band as a fracture merely because it is sinusoidal, and "
    "do not reject a fracture merely because it is near-horizontal when it remains sharp, distinct, and cross-cuts "
    "the surrounding repeated layering. "
)


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
            "decision_continuity": {
                "type": "string",
                "enum": ["initial", "maintain", "overturn"],
            },
            "reason": {"type": "string"},
        },
        "required": [
            "action", "view", "aligned", "center_depth_m", "amplitude_m", "phase_deg",
            "corrected_points", "confidence", "decision_continuity", "reason",
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

FAST_PARAMETER_REVIEW_SCHEMA = copy.deepcopy(PARAMETER_REVIEW_SCHEMA)
FAST_PARAMETER_REVIEW_SCHEMA["name"] = "fast_complete_fracture_parameter_review"
FAST_PARAMETER_REVIEW_SCHEMA["schema"]["properties"]["action"]["enum"] = [
    "keep", "adjust_parameters", "replace_points", "discard",
]

FAST_BATCH_AUDIT_SCHEMA = copy.deepcopy(BATCH_AUDIT_SCHEMA)
FAST_BATCH_AUDIT_SCHEMA["name"] = "fast_complete_fracture_batch_audit"
FAST_BATCH_AUDIT_SCHEMA["schema"]["properties"]["action"]["enum"] = ["finalize_audit"]


WINDOW_CLASSIFICATION_SCHEMA = {
    "name": "fracture_window_classification",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "classification": {
                "type": "string",
                "enum": ["confirmed", "suspected", "none"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "reason": {"type": "string"},
            "suspected_depth_ranges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "depth_top": {"type": "number"},
                        "depth_bottom": {"type": "number"},
                    },
                    "required": ["depth_top", "depth_bottom"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["classification", "confidence", "reason", "suspected_depth_ranges"],
        "additionalProperties": False,
    },
}


DIRECT_CANDIDATE_SCHEMA = {
    "name": "direct_fracture_candidates",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "reason": {"type": "string"},
            "candidates": {
                "type": "array",
                "maxItems": 12,
                "items": {
                    "type": "object",
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
        },
        "required": ["reason", "candidates"],
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
        classification = None
        if request.pick_entry_level:
            context.update("classifying", 0.06, "AI: classifying fracture evidence in current window")
            classification = self.classify_window(
                request,
                rendered,
                client=client,
                model=model,
            )
            classification_value = classification["classification"]
            enters_picking = (
                classification_value == "confirmed"
                or (
                    request.pick_entry_level == "suspected"
                    and classification_value == "suspected"
                )
            )
            prior_overlays = list((rendered.get("metadata") or {}).get("prior_candidate_overlays") or [])
            has_reconsiderable_overlays = any(
                str(item.get("candidate_status") or "").lower() not in {"accepted", "kept"}
                for item in prior_overlays
            )
            if classification_value == "suspected" and has_reconsiderable_overlays:
                enters_picking = True
            if hasattr(context, "record_event"):
                context.record_event(
                    "classifying",
                    "window_classification",
                    classification.get("reason", ""),
                    status="accepted" if enters_picking else "skipped",
                    classification=classification_value,
                    confidence=classification.get("confidence"),
                    pick_entry_level=request.pick_entry_level,
                )
            if hasattr(context, "update_monitor"):
                context.update_monitor(
                    api_status="classified",
                    window_classification=classification_value,
                    classification_confidence=classification.get("confidence"),
                )
            if not enters_picking:
                diagnostics = {
                    "render_metadata": rendered["metadata"],
                    "window_classification": classification,
                    "pick_entry_level": request.pick_entry_level,
                    "skipped_before_picking": True,
                    "candidate_windows": [],
                    "accepted_count": 0,
                }
                context.set_diagnostics(diagnostics)
                context.update(
                    "window_skipped",
                    0.89,
                    f"AI: {classification_value}, moving to next window",
                )
                return []
        context.update("exploring", 0.10, "AI: picking fracture candidates from current window")
        if hasattr(context, "set_monitor_media"):
            context.set_monitor_media("input_view", rendered, api_status="requesting")
        if request.fast_mode:
            candidates, exploration = self.pick_candidates_directly(
                request,
                rendered,
                classification=classification,
                context=context,
                client=client,
                model=model,
            )
        else:
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
            "window_classification": classification,
            "pick_entry_level": request.pick_entry_level,
            "exploration": exploration,
            "candidate_evaluations": [],
        }
        provisional = []
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
                azimuth_span = self._azimuth_coverage_span(points)
                evaluation["anchor_azimuth_span_deg"] = azimuth_span
                fragment_only = azimuth_span < MIN_STABLE_FIT_AZIMUTH_SPAN_DEG
                fit = fit_sinusoidal_fracture(points, min_points=MIN_TRACE_POINTS)
                parameters = fracture_parameters(fit)
                style = FRACTURE_TYPE_STYLES[candidate["fracture_type"]]
                local = self.pipeline.evidence_scorer.evaluate(
                    candidate_rendered,
                    request.target_image_track,
                    fit,
                )
                diagnostic_candidate_id = (
                    context.qualify_candidate_id(candidate["candidate_id"])
                    if hasattr(context, "qualify_candidate_id")
                    else candidate["candidate_id"]
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
                    "candidate_continuity_reason": str(candidate.get("continuity_reason") or ""),
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
                    "anchor_evidence_status": "fragment" if fragment_only else "stable_candidate",
                    "anchor_azimuth_span_deg": azimuth_span,
                    "needs_review": False,
                    "initial_points": [list(point) for point in points],
                    "final_points": [list(point) for point in points],
                    "_candidate_render_key": diagnostic_candidate_id,
                }, borehole_diameter=request.borehole_diameter_in)
                if hasattr(context, "set_candidate_payload"):
                    context.set_candidate_payload(candidate["candidate_id"], candidate_rendered)
                else:
                    annotation["_candidate_rendered"] = candidate_rendered
                provisional.append({
                    "candidate": candidate,
                    "candidate_rendered": candidate_rendered,
                    "annotation": annotation,
                    "evaluation": evaluation,
                    "anchor_response": anchor_result,
                    "points": points,
                    "fragment_only": fragment_only,
                })
                evaluation.update({
                    "status": "fragment_pending_association" if fragment_only else "fitted",
                    "anchor_response": anchor_result,
                    "points": points,
                    "initial_parameters": parameters,
                    "local_completeness": local,
                    "candidate_render_metadata": candidate_rendered["metadata"],
                })
                if fragment_only and hasattr(context, "record_event"):
                    context.record_event(
                        "associating",
                        "trace_fragment_staged",
                        (
                            f"Anchor span {azimuth_span:.1f} deg is insufficient for an independent "
                            "fracture but remains available for complementary-fragment association"
                        ),
                        status="pending",
                        candidate_id=candidate.get("candidate_id"),
                        anchor_azimuth_span_deg=azimuth_span,
                    )
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
        context.update(
            "associating",
            0.64,
            f"Associating {len(provisional)} provisional candidate fit(s)",
        )
        provisional, association = self._associate_provisional_candidates(
            request,
            context,
            rendered,
            provisional,
        )
        provisional, unresolved_fragments = self._remove_unresolved_trace_fragments(
            provisional,
            discarded,
            context,
        )
        association["unresolved_fragments"] = unresolved_fragments
        association["promoted_fragment_groups"] = [
            {
                "candidate_id": item["candidate"].get("candidate_id"),
                "source_candidate_ids": list(
                    item["annotation"].get("associated_candidate_ids") or []
                ),
                "anchor_azimuth_span_deg": item["annotation"].get("anchor_azimuth_span_deg"),
            }
            for item in provisional
            if item["annotation"].get("fragment_association_status") == "promoted"
        ]
        diagnostics["candidate_association"] = association
        diagnostics["comparison_candidates"] = [
            self._diagnostic_annotation(item["annotation"])
            for item in provisional
        ]

        if bool(getattr(context, "defer_candidate_review", False)):
            results = []
            for item in provisional:
                annotation = item["annotation"]
                item["evaluation"].update({
                    "status": "deferred_to_global_review",
                    "final_parameters": annotation.get("ai_final_parameters"),
                    "review_history": [],
                })
                results.append(annotation)
            diagnostics["staged_count"] = len(results)
            diagnostics["accepted_count"] = len(results)
            diagnostics["discarded_count"] = len(discarded)
            diagnostics["discarded"] = discarded
            diagnostics["kept_candidate_ids"] = [
                item.get("candidate_id") for item in results
            ]
            diagnostics["batch_audit"] = {
                "audit_status": "deferred_to_global_review_and_audit",
                "audit_views": [],
                "audit_events": [],
                "audit_action_count": 0,
                "audit_decisions": [],
            }
            context.set_diagnostics(diagnostics)
            context.update(
                "staging",
                0.89,
                f"Deferred {len(results)} fitted candidate(s) to cross-window review",
            )
            return results

        review_total = max(1, len(provisional))
        for index, item in enumerate(provisional):
            if context.cancelled:
                return []
            candidate = item["candidate"]
            candidate_rendered = item["candidate_rendered"]
            annotation = item["annotation"]
            evaluation = item["evaluation"]
            reviewed, review_discard = self._review_candidate_until_final(
                request,
                context,
                rendered,
                candidate_rendered,
                annotation,
                index=index,
                total=review_total,
            )
            diagnostic_annotation = reviewed or annotation
            diagnostic_payload = dict(candidate_rendered)
            final_points = self._clean_depth_points(diagnostic_annotation.get("final_points"))
            if len(final_points) >= MIN_TRACE_POINTS:
                diagnostic_payload["overlay_data_url"] = self.pipeline._build_feedback_image(
                    candidate_rendered,
                    final_points,
                    request.target_image_track,
                )
            diagnostic_payload["annotation"] = self._diagnostic_annotation(diagnostic_annotation)
            if hasattr(context, "set_candidate_payload"):
                context.set_candidate_payload(candidate["candidate_id"], diagnostic_payload)
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
                "final_parameters": reviewed.get("ai_final_parameters"),
                "review_history": list(reviewed.get("ai_correction_history") or []),
            })

        if context.cancelled:
            return []
        if bool(getattr(context, "defer_batch_audit", False)):
            deferred_kept, deferred_discarded = self._non_maximum_suppression(staged, rendered)
            audit_result = {
                "kept": deferred_kept,
                "discarded": deferred_discarded,
                "audit_status": "deferred_to_global_audit",
                "audit_views": [],
                "audit_events": [],
                "audit_action_count": 0,
                "audit_decisions": [],
            }
            context.update(
                "staging",
                0.84,
                f"Deferred {len(deferred_kept)} candidate(s) to global audit",
            )
        else:
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

    def associate_annotations_across_windows(
        self,
        request,
        context,
        rendered,
        annotations,
    ):
        """Associate complementary fitted traces from different primary windows."""
        provisional = []
        passthrough = []
        for annotation in annotations:
            points = self._clean_depth_points(
                annotation.get("final_points")
                or annotation.get("points")
                or annotation.get("initial_points")
            )
            if len(points) < MIN_TRACE_POINTS:
                passthrough.append(dict(annotation))
                continue
            parameters = fracture_parameters(annotation)
            center = float(parameters["center_depth_m"])
            amplitude = abs(float(parameters["amplitude_m"]))
            candidate = {
                "candidate_id": str(annotation.get("candidate_id") or "candidate"),
                "fracture_type": str(annotation.get("fracture_type") or "Conductive"),
                "depth_top": center - amplitude,
                "depth_bottom": center + amplitude,
                "confidence": float(annotation.get("confidence", 0.0)),
                "continuity_reason": "Cross-window fitted candidate",
            }
            provisional.append({
                "candidate": candidate,
                "candidate_rendered": self.render_candidate_window(
                    rendered,
                    candidate,
                    request.target_image_track,
                ),
                "annotation": dict(annotation),
                "evaluation": {},
                "anchor_response": {},
                "points": points,
            })

        if len(provisional) < 2:
            return list(annotations), {
                "input_count": len(annotations),
                "fitted_count": len(provisional),
                "output_count": len(annotations),
                "groups": [],
                "comparisons": [],
            }

        associated, diagnostics = self._associate_provisional_candidates(
            request,
            context,
            rendered,
            provisional,
            cross_window_only=True,
        )
        cross_window_groups = {
            str(group.get("candidate_id")): list(group.get("source_candidate_ids") or [])
            for group in diagnostics.get("groups") or []
        }
        output = list(passthrough)
        for item in associated:
            annotation = dict(item["annotation"])
            group_id = str(item["candidate"].get("candidate_id") or "")
            source_ids = cross_window_groups.get(group_id, [])
            if source_ids:
                annotation["candidate_id"] = "X-" + "+".join(source_ids)
                annotation["detection_pass_kind"] = "cross_window_association"
                annotation["sliding_window_index"] = None
                annotation["merged_observation_group"] = None
                annotation["needs_review"] = True
            output.append(annotation)
        diagnostics = dict(diagnostics)
        diagnostics["fitted_count"] = len(provisional)
        diagnostics["passthrough_candidate_ids"] = [
            item.get("candidate_id") for item in passthrough
        ]
        output.sort(key=lambda item: float(item.get("offset", 0.0)))
        return output, diagnostics

    def review_annotations_after_association(
        self,
        request,
        context,
        rendered,
        annotations,
    ):
        """Review final fitted candidates only after cross-window association is complete."""
        reviewed = []
        discarded = []
        total = max(1, len(annotations))
        for index, annotation in enumerate(annotations):
            if context.cancelled:
                return [], discarded
            parameters = fracture_parameters(annotation)
            center = float(parameters["center_depth_m"])
            amplitude = abs(float(parameters["amplitude_m"]))
            candidate = {
                "candidate_id": str(annotation.get("candidate_id") or f"F{index + 1}"),
                "fracture_type": str(annotation.get("fracture_type") or "Conductive"),
                "depth_top": center - amplitude,
                "depth_bottom": center + amplitude,
                "confidence": float(annotation.get("confidence", 0.0)),
            }
            candidate_rendered = self.render_candidate_window(
                rendered,
                candidate,
                request.target_image_track,
            )
            result, review_discard = self._review_candidate_until_final(
                request,
                context,
                rendered,
                candidate_rendered,
                annotation,
                index=index,
                total=total,
            )
            diagnostic_annotation = result or annotation
            diagnostic_payload = dict(candidate_rendered)
            final_points = self._clean_depth_points(
                diagnostic_annotation.get("final_points")
                or diagnostic_annotation.get("points")
            )
            if len(final_points) >= MIN_TRACE_POINTS:
                diagnostic_payload["overlay_data_url"] = self.pipeline._build_feedback_image(
                    candidate_rendered,
                    final_points,
                    request.target_image_track,
                )
            diagnostic_payload["annotation"] = self._diagnostic_annotation(
                diagnostic_annotation
            )
            if hasattr(context, "set_candidate_payload"):
                context.set_candidate_payload(candidate["candidate_id"], diagnostic_payload)
            if review_discard is not None:
                discarded.append(review_discard)
            elif result is not None:
                reviewed.append(result)
        reviewed.sort(key=lambda item: float(item.get("offset", 0.0)))
        return reviewed, discarded

    def pick_candidates_directly(
        self,
        request,
        rendered,
        *,
        classification,
        context=None,
        client=None,
        model=None,
    ):
        if client is None or model is None:
            _config, client, model = self._client()
        metadata = rendered["metadata"]
        prior_overlays = list(metadata.get("prior_candidate_overlays") or [])
        prior_instruction = (
            "Two images are supplied: Image 1 is the unmodified raw Plot evidence and Image 2 is the same view with "
            "colored numbered curves for candidates already picked in earlier windows. Read fracture texture only "
            "from Image 1. Use Image 2 and prior_candidate_overlays only to avoid returning those same physical traces, "
            "Accepted or kept overlays represent committed prior picks and must not be returned again. Overlays marked "
            "discarded_in_local_window are provisional local interpretations: if the raw merged view shows that two "
            "or more such arcs belong to one physical sinusoid, return one consolidated candidate spanning the full "
            "peak-to-trough envelope rather than repeating each fragment. "
            if prior_overlays else ""
        )
        prompt = (
            FRACTURE_MORPHOLOGY_GUIDANCE
            +
            "Immediately identify all fracture candidates in this already-triaged borehole-image window. Do not "
            "request another view, do not adjust the window or image scale, and do not return an action plan. Return "
            "candidate depth windows only; anchor selection and sinusoid fitting are performed by the next stage. "
            "Treat compatible arcs separated by pad gaps as one candidate rather than splitting one physical fracture. "
            "Ignore isolated textures that cannot plausibly belong to a fracture trace. Do not register ordinary "
            "horizontal bedding, repeated background bands, pad edges, or irregular borehole artifacts as conductive "
            "or resistive fractures. A near-horizontal candidate requires a distinct fracture expression traceable on "
            "multiple measured pads and distinguishable from neighboring parallel bands. Respect the allowed fracture "
            "types and use exact metadata depths rather than OCR. "
            + prior_instruction + "Return JSON only.\n"
            + json.dumps({
                "depth_start": metadata["depth_start"],
                "depth_end": metadata["depth_end"],
                "target_image_track": request.target_image_track,
                "allowed_fracture_types": list(request.fracture_types),
                "minimum_candidate_confidence": request.min_confidence,
                "window_classification": classification,
                "prior_candidate_overlays": prior_overlays,
            }, ensure_ascii=False)
        )
        response = self.pipeline._request(
            client,
            model,
            self._vision_messages(
                "You directly locate fracture candidate depth windows without navigating to other views.",
                prompt,
                self._analysis_images(rendered),
            ),
            response_schema=DIRECT_CANDIDATE_SCHEMA,
        )
        payload = _json_payload(response)
        source_start = float(metadata["depth_start"])
        source_end = float(metadata["depth_end"])
        candidates = []
        seen_ids = set()
        rejected = []
        for index, candidate in enumerate(payload.get("candidates") or []):
            item = dict(candidate)
            candidate_id = str(item.get("candidate_id") or f"F{index + 1}").strip()
            fracture_type = str(item.get("fracture_type") or "")
            confidence = max(0.0, min(1.0, float(item.get("confidence", 0.0))))
            top = max(source_start, min(source_end, float(item["depth_top"])))
            bottom = max(source_start, min(source_end, float(item["depth_bottom"])))
            reason = None
            if candidate_id in seen_ids:
                reason = "duplicate_candidate_id"
            elif fracture_type not in request.fracture_types:
                reason = "unsupported_fracture_type"
            elif confidence < request.min_confidence:
                reason = "below_minimum_confidence"
            elif bottom <= top:
                reason = "empty_depth_window"
            if reason:
                rejected.append({"candidate_id": candidate_id, "reason": reason})
                continue
            seen_ids.add(candidate_id)
            candidates.append({
                "candidate_id": candidate_id,
                "fracture_type": fracture_type,
                "depth_top": top,
                "depth_bottom": bottom,
                "confidence": confidence,
                "continuity_reason": str(item.get("continuity_reason") or ""),
            })
        candidates.sort(key=lambda item: (item["depth_top"], item["candidate_id"]))
        if context is not None and hasattr(context, "record_event"):
            context.record_event(
                "exploring",
                "direct_candidate_pick",
                str(payload.get("reason") or ""),
                status="accepted",
                candidate_count=len(candidates),
                rejected_count=len(rejected),
            )
        if context is not None and hasattr(context, "update_exploration"):
            context.update_exploration(
                action_count=1,
                view_count=1,
                fragment_count=0,
                hypothesis_count=0,
                candidate_count=len(candidates),
                finished=True,
            )
        return candidates, {
            "mode": "direct_candidate_pick",
            "action_count": 1,
            "views": [],
            "trace_fragments": [],
            "sinusoid_hypotheses": [],
            "events": [{
                "action": "direct_candidate_pick",
                "reason": str(payload.get("reason") or ""),
                "candidate_count": len(candidates),
            }],
            "rejected_candidates": rejected,
            "finished": True,
        }

    def classify_window(self, request, rendered, *, client=None, model=None):
        if client is None or model is None:
            _config, client, model = self._client()
        metadata = rendered["metadata"]
        prior_overlays = list(metadata.get("prior_candidate_overlays") or [])
        overlay_instruction = (
            "Two images are supplied: Image 1 is the unmodified raw Plot evidence and Image 2 is the same view with "
            "prior picks overlaid. Colored numbered curves in Image 2 are annotations, not raw image evidence. Assess "
            "texture from Image 1 and do not classify an interval as confirmed solely because an overlay is present. "
            "However, when discarded_in_local_window overlays mark complementary arcs and Image 1 supports one smooth "
            "physical sinusoid, classify the merged interval as confirmed so the consolidated candidate can be tested. "
            if prior_overlays else ""
        )
        prompt = (
            FRACTURE_MORPHOLOGY_GUIDANCE
            +
            "Classify whether the current borehole-image window is ready to enter fracture fitting. This classification "
            "is an entry decision, not a final geological acceptance decision. Return confirmed when at least one "
            "visible curved or oblique trace, or a set of separated compatible arcs, is sufficiently distinct from the "
            "local background to justify anchor picking and sinusoid fitting. confirmed does not require proving a "
            "complete 0-360 degree fracture, seeing both extrema, resolving every pad gap, or deciding that the fitted "
            "result will ultimately be kept. A high-amplitude fracture may cross a sliding-window boundary, so a clear "
            "crest, trough, or substantial curved side visible in this window is confirmed-for-fitting when its texture "
            "and curvature are meaningful. Return suspected only for weak, very short, low-contrast, or background-like "
            "anomalies that are not yet strong enough to justify direct fitting. Return none when there is no meaningful "
            "fracture evidence. Do not downgrade a fitting-ready trace merely because identity across missing pads, blank "
            "azimuth sectors, or the window boundary remains unresolved; fitting, fragment association, Review, and Audit "
            "will resolve those questions later. This is triage only: do not choose anchors, fit parameters, or register "
            "candidates. Depth ranges must use metadata coordinates, not OCR. "
            + overlay_instruction + "Return JSON only.\n"
            + json.dumps({
                "depth_start": metadata["depth_start"],
                "depth_end": metadata["depth_end"],
                "target_image_track": request.target_image_track,
                "allowed_fracture_types": list(request.fracture_types),
                "pick_entry_level": request.pick_entry_level,
                "prior_candidate_overlays": prior_overlays,
            })
        )
        response = self.pipeline._request(
            client,
            model,
            self._vision_messages(
                "You decide whether visible fracture evidence is ready for fitting, without pre-judging final acceptance.",
                prompt,
                self._analysis_images(rendered),
            ),
            response_schema=WINDOW_CLASSIFICATION_SCHEMA,
        )
        payload = _json_payload(response)
        ranges = []
        source_start = float(metadata["depth_start"])
        source_end = float(metadata["depth_end"])
        for item in payload.get("suspected_depth_ranges") or []:
            top = max(source_start, min(source_end, float(item["depth_top"])))
            bottom = max(source_start, min(source_end, float(item["depth_bottom"])))
            if bottom > top:
                ranges.append({"depth_top": top, "depth_bottom": bottom})
        return {
            "classification": str(payload["classification"]),
            "confidence": max(0.0, min(1.0, float(payload["confidence"]))),
            "reason": str(payload.get("reason") or ""),
            "suspected_depth_ranges": ranges,
        }

    def _associate_provisional_candidates(
        self,
        request,
        context,
        rendered,
        provisional,
        *,
        cross_window_only=False,
    ):
        """Merge complementary partial fits before any candidate can be discarded by review."""
        count = len(provisional)
        if count < 2:
            return provisional, {
                "input_count": count,
                "output_count": count,
                "groups": [],
                "comparisons": [],
            }

        comparisons = []
        compatibility = {}
        for left in range(count):
            for right in range(left + 1, count):
                metrics = self._candidate_association_metrics(provisional[left], provisional[right])
                if cross_window_only:
                    left_source = provisional[left]["annotation"].get("sliding_window_index")
                    right_source = provisional[right]["annotation"].get("sliding_window_index")
                    different_windows = bool(
                        left_source is not None
                        and right_source is not None
                        and left_source != right_source
                    )
                    metrics["different_primary_windows"] = different_windows
                    metrics["compatible"] = bool(metrics["compatible"] and different_windows)
                comparisons.append(metrics)
                compatibility[(left, right)] = bool(metrics["compatible"])

        # Complete-link grouping prevents an A-B-C compatibility chain from merging A and C
        # when those two fits do not independently describe the same physical trace.
        grouped = []
        for index in range(count):
            matching_group = next((
                group for group in grouped
                if all(compatibility.get(tuple(sorted((member, index))), False) for member in group)
            ), None)
            if matching_group is None:
                grouped.append([index])
            else:
                matching_group.append(index)

        output = []
        groups = []
        for member_indexes in grouped:
            members = [provisional[index] for index in member_indexes]
            if len(members) == 1:
                output.append(members[0])
                continue
            merged = self._merge_provisional_candidate_group(
                request,
                context,
                rendered,
                members,
            )
            output.append(merged)
            group_info = {
                "candidate_id": merged["candidate"]["candidate_id"],
                "source_candidate_ids": list(merged["annotation"]["associated_candidate_ids"]),
                "parameters": dict(merged["annotation"]["ai_initial_parameters"]),
                "point_count": len(merged["points"]),
            }
            groups.append(group_info)
            if hasattr(context, "record_event"):
                context.record_event(
                    "associating",
                    "candidates_merged",
                    "Complementary azimuth fragments were merged and refitted before review",
                    status="accepted",
                    **group_info,
                )

        output.sort(key=lambda item: (
            float(item["candidate"]["depth_top"]),
            str(item["candidate"]["candidate_id"]),
        ))
        if hasattr(context, "update_monitor"):
            context.update_monitor(
                candidate_count=len(output),
                api_status="candidates_associated",
            )
        return output, {
            "input_count": count,
            "output_count": len(output),
            "groups": groups,
            "comparisons": comparisons,
        }

    def _remove_unresolved_trace_fragments(self, provisional, discarded, context):
        resolved = []
        unresolved = []
        for item in provisional:
            if not bool(item.get("fragment_only")):
                resolved.append(item)
                continue
            candidate_id = item["candidate"].get("candidate_id")
            span = float(item["annotation"].get("anchor_azimuth_span_deg", 0.0))
            reason = (
                f"Trace fragment retained only {span:.1f} deg of azimuth evidence and did not "
                "gain complementary support; no standalone fracture was submitted"
            )
            item["evaluation"].update({
                "status": "unresolved_trace_fragment",
                "discard_reason": reason,
            })
            record = {
                "candidate_id": candidate_id,
                "reason": reason,
                "stage": "fragment_association",
                "anchor_azimuth_span_deg": span,
            }
            discarded.append(record)
            unresolved.append(record)
            if hasattr(context, "record_event"):
                context.record_event(
                    "associating",
                    "trace_fragment_unresolved",
                    reason,
                    status="skipped",
                    candidate_id=candidate_id,
                    anchor_azimuth_span_deg=span,
                )
        return resolved, unresolved

    def _candidate_association_metrics(self, left, right):
        left_annotation = left["annotation"]
        right_annotation = right["annotation"]
        left_parameters = fracture_parameters(left_annotation)
        right_parameters = fracture_parameters(right_annotation)
        left_amplitude = abs(float(left_parameters["amplitude_m"]))
        right_amplitude = abs(float(right_parameters["amplitude_m"]))
        maximum_amplitude = max(left_amplitude, right_amplitude, 1e-9)
        amplitude_relative_delta = abs(left_amplitude - right_amplitude) / maximum_amplitude
        amplitude_compatible = (
            amplitude_relative_delta <= ASSOCIATION_MAX_AMPLITUDE_RELATIVE_DELTA
        )
        center_delta = abs(
            float(left_parameters["center_depth_m"])
            - float(right_parameters["center_depth_m"])
        )
        phase_delta = self._circular_phase_delta(
            float(left_parameters["phase_deg"]),
            float(right_parameters["phase_deg"]),
        )
        left_envelope = (
            float(left_parameters["center_depth_m"]) - left_amplitude,
            float(left_parameters["center_depth_m"]) + left_amplitude,
        )
        right_envelope = (
            float(right_parameters["center_depth_m"]) - right_amplitude,
            float(right_parameters["center_depth_m"]) + right_amplitude,
        )
        overlap = max(0.0, min(left_envelope[1], right_envelope[1]) - max(left_envelope[0], right_envelope[0]))
        minimum_envelope_span = max(1e-9, min(
            left_envelope[1] - left_envelope[0],
            right_envelope[1] - right_envelope[0],
        ))
        envelope_overlap = overlap / minimum_envelope_span
        left_bins = self._anchor_azimuth_bins(left.get("points"))
        right_bins = self._anchor_azimuth_bins(right.get("points"))
        union_bins = left_bins | right_bins
        intersection_bins = left_bins & right_bins
        anchor_jaccard = len(intersection_bins) / max(1, len(union_bins))
        complementary_anchors = bool(
            left_bins - right_bins
            and right_bins - left_bins
            and len(union_bins) >= 4
            and anchor_jaccard <= ASSOCIATION_MAX_ANCHOR_JACCARD
        )
        center_tolerance = max(0.20, 0.45 * maximum_amplitude)
        merged_fit = self._merged_anchor_fit_metrics(
            left.get("points"),
            right.get("points"),
            maximum_amplitude,
        )
        same_type = (
            left["candidate"].get("fracture_type")
            == right["candidate"].get("fracture_type")
        )
        fragment_involved = bool(left.get("fragment_only") or right.get("fragment_only"))
        common_compatibility = bool(
            same_type
            and (fragment_involved or phase_delta <= ASSOCIATION_MAX_PHASE_DELTA_DEG)
            and complementary_anchors
        )
        center_compatible = center_delta <= center_tolerance
        compatible = bool(
            common_compatibility
            and merged_fit["acceptable"]
        )
        return {
            "left_candidate_id": left["candidate"].get("candidate_id"),
            "right_candidate_id": right["candidate"].get("candidate_id"),
            "same_type": same_type,
            "center_delta_m": center_delta,
            "center_tolerance_m": center_tolerance,
            "center_compatible": center_compatible,
            "amplitude_relative_delta": amplitude_relative_delta,
            "amplitude_compatible": amplitude_compatible,
            "phase_delta_deg": phase_delta,
            "envelope_overlap": envelope_overlap,
            "left_anchor_bins": sorted(left_bins),
            "right_anchor_bins": sorted(right_bins),
            "anchor_jaccard": anchor_jaccard,
            "complementary_anchors": complementary_anchors,
            "fragment_involved": fragment_involved,
            "merged_fit": merged_fit,
            "compatible": compatible,
        }

    def _merged_anchor_fit_metrics(self, left_points, right_points, reference_amplitude):
        points = self._clean_depth_points(list(left_points or []) + list(right_points or []))
        preliminary_threshold = max(
            ASSOCIATION_MIN_MERGED_RMSE_M,
            ASSOCIATION_MAX_MERGED_RMSE_AMPLITUDE_RATIO * max(float(reference_amplitude), 0.0),
        )
        if len(points) < MIN_TRACE_POINTS:
            return {
                "available": False,
                "acceptable": False,
                "point_count": len(points),
                "rmse_m": None,
                "threshold_m": preliminary_threshold,
                "parameters": None,
            }
        try:
            fit = fit_sinusoidal_fracture(points, min_points=MIN_TRACE_POINTS)
            azimuth = np.deg2rad(np.asarray([point[0] for point in points], dtype=float))
            depth = np.asarray([point[1] for point in points], dtype=float)
            predicted = (
                float(fit["offset"])
                + float(fit["sin_coeff"]) * np.sin(azimuth)
                + float(fit["cos_coeff"]) * np.cos(azimuth)
            )
            rmse = float(np.sqrt(np.mean(np.square(depth - predicted))))
            parameters = fracture_parameters(fit)
            merged_amplitude = abs(float(parameters["amplitude_m"]))
            threshold = max(
                preliminary_threshold,
                ASSOCIATION_MAX_MERGED_RMSE_AMPLITUDE_RATIO * merged_amplitude,
            )
            threshold = min(ASSOCIATION_MAX_MERGED_RMSE_M, threshold)
            return {
                "available": True,
                "acceptable": bool(math.isfinite(rmse) and rmse <= threshold),
                "point_count": len(points),
                "rmse_m": rmse,
                "threshold_m": threshold,
                "parameters": parameters,
            }
        except Exception as exc:
            return {
                "available": False,
                "acceptable": False,
                "point_count": len(points),
                "rmse_m": None,
                "threshold_m": preliminary_threshold,
                "parameters": None,
                "reason": str(exc),
            }

    def _merge_provisional_candidate_group(self, request, context, rendered, members):
        members = sorted(members, key=lambda item: (
            float(item["candidate"]["depth_top"]),
            str(item["candidate"]["candidate_id"]),
        ))
        source_ids = [str(item["candidate"]["candidate_id"]) for item in members]
        points = []
        for item in members:
            points.extend(self._clean_depth_points(item.get("points")))
        points.sort(key=lambda point: (point[0], point[1]))
        fit = fit_sinusoidal_fracture(points, min_points=MIN_TRACE_POINTS)
        parameters = fracture_parameters(fit)
        reference_amplitude = max(
            abs(float(fracture_parameters(item["annotation"])["amplitude_m"]))
            for item in members
        )
        merged_fit_metrics = self._merged_anchor_fit_metrics(
            points,
            [],
            reference_amplitude,
        )
        center = float(parameters["center_depth_m"])
        amplitude = abs(float(parameters["amplitude_m"]))
        candidate = dict(members[0]["candidate"])
        candidate["depth_top"] = max(
            float(rendered["metadata"]["depth_start"]),
            min([float(item["candidate"]["depth_top"]) for item in members] + [center - amplitude]),
        )
        candidate["depth_bottom"] = min(
            float(rendered["metadata"]["depth_end"]),
            max([float(item["candidate"]["depth_bottom"]) for item in members] + [center + amplitude]),
        )
        candidate["confidence"] = max(float(item["candidate"].get("confidence", 0.0)) for item in members)
        candidate["continuity_reason"] = "Merged complementary fragments: " + ", ".join(source_ids)
        candidate["associated_candidate_ids"] = source_ids
        candidate_rendered = self.render_candidate_window(rendered, candidate, request.target_image_track)
        local = self.pipeline.evidence_scorer.evaluate(
            candidate_rendered,
            request.target_image_track,
            fit,
        )
        base = dict(members[0]["annotation"])
        base.update(fit)
        base.update({
            "confidence": max(float(item["annotation"].get("confidence", 0.0)) for item in members),
            "candidate_depth_window": [candidate["depth_top"], candidate["depth_bottom"]],
            "candidate_continuity_reason": str(candidate.get("continuity_reason") or ""),
            "ai_initial_parameters": dict(parameters),
            "ai_final_parameters": dict(parameters),
            "local_completeness": local,
            "initial_points": [list(point) for point in points],
            "final_points": [list(point) for point in points],
            "points": [list(point) for point in points],
            "associated_candidate_ids": source_ids,
            "association_status": "merged_complementary_fragments",
            "association_merged_fit": merged_fit_metrics,
        })
        merged_span = self._azimuth_coverage_span(points)
        fragment_only = merged_span < MIN_STABLE_FIT_AZIMUTH_SPAN_DEG
        fragment_source_ids = [
            str(item["candidate"].get("candidate_id"))
            for item in members
            if bool(item.get("fragment_only"))
        ]
        base.update({
            "anchor_azimuth_span_deg": merged_span,
            "anchor_evidence_status": "fragment" if fragment_only else "stable_candidate",
        })
        if fragment_source_ids:
            base.update({
                "fragment_association_status": "unresolved" if fragment_only else "promoted",
                "associated_fragment_candidate_ids": fragment_source_ids,
            })
        base = enrich_fracture_interpretation(base, borehole_diameter=request.borehole_diameter_in)
        if hasattr(context, "set_candidate_payload"):
            context.set_candidate_payload(candidate["candidate_id"], candidate_rendered)
        else:
            base["_candidate_rendered"] = candidate_rendered

        primary_evaluation = members[0]["evaluation"]
        primary_evaluation.update({
            "status": "associated",
            "associated_candidate_ids": source_ids,
            "merged_points": [list(point) for point in points],
            "merged_parameters": dict(parameters),
            "local_completeness": local,
            "candidate_render_metadata": candidate_rendered["metadata"],
        })
        for item in members[1:]:
            item["evaluation"].update({
                "status": "merged_into_candidate",
                "merged_into_candidate_id": candidate["candidate_id"],
            })
        return {
            "candidate": candidate,
            "candidate_rendered": candidate_rendered,
            "annotation": base,
            "evaluation": primary_evaluation,
            "anchor_response": {"merged_from": source_ids},
            "points": points,
            "fragment_only": fragment_only,
        }

    @staticmethod
    def _anchor_azimuth_bins(points):
        bins = set()
        for point in points or []:
            try:
                azimuth = float(point[0]) % 360.0
            except (IndexError, TypeError, ValueError):
                continue
            bins.add(min(ASSOCIATION_AZIMUTH_BINS - 1, int(
                azimuth / 360.0 * ASSOCIATION_AZIMUTH_BINS
            )))
        return bins

    @staticmethod
    def _azimuth_coverage_span(points):
        azimuths = sorted({float(point[0]) % 360.0 for point in points or []})
        if len(azimuths) < 2:
            return 0.0
        circular_gaps = [
            azimuths[index + 1] - azimuths[index]
            for index in range(len(azimuths) - 1)
        ]
        circular_gaps.append(azimuths[0] + 360.0 - azimuths[-1])
        return 360.0 - max(circular_gaps)

    @staticmethod
    def _circular_phase_delta(left, right):
        return abs((left - right + 180.0) % 360.0 - 180.0)

    @classmethod
    def _review_parameter_change(cls, before, after):
        if not isinstance(before, dict) or not isinstance(after, dict):
            return None
        try:
            return {
                "center_depth_m": float(after["center_depth_m"]) - float(before["center_depth_m"]),
                "amplitude_m": float(after["amplitude_m"]) - float(before["amplitude_m"]),
                "phase_deg": (
                    (float(after["phase_deg"]) - float(before["phase_deg"]) + 180.0) % 360.0
                    - 180.0
                ),
            }
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _review_score_change(before, after):
        if not isinstance(before, dict) or not isinstance(after, dict):
            return None
        change = {
            "complete_before": before.get("complete"),
            "complete_after": after.get("complete"),
        }
        for name in ("score", "coverage", "min_quadrant_coverage"):
            try:
                change[name] = float(after[name]) - float(before[name])
            except (KeyError, TypeError, ValueError):
                change[name] = None
        return change

    @staticmethod
    def _previous_review_context(annotation):
        history = list(annotation.get("ai_correction_history") or [])
        if not history:
            return None
        previous = history[-1]
        return {
            "round": previous.get("round"),
            "action": previous.get("action"),
            "decision_continuity": previous.get("decision_continuity"),
            "confidence": previous.get("confidence"),
            "reason": previous.get("reason"),
            "input_parameters": previous.get("input_parameters"),
            "output_parameters": previous.get("output_parameters") or previous.get("parameters"),
            "parameter_change": previous.get("parameter_change"),
            "input_local_completeness": previous.get("input_local_completeness"),
            "output_local_completeness": (
                previous.get("output_local_completeness") or previous.get("local_completeness")
            ),
            "score_change": previous.get("score_change"),
        }

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

            review_input_parameters = fracture_parameters(current)
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
            input_local = result.get("local_completeness")
            output_local = result.get("corrected_local_completeness") or input_local
            output_parameters = result.get("parameters")
            history.append({
                "round": round_number,
                "action": action,
                "decision_continuity": result.get("decision_continuity"),
                "confidence": result.get("confidence"),
                "parameters": output_parameters,
                "input_parameters": review_input_parameters,
                "output_parameters": output_parameters,
                "parameter_change": self._review_parameter_change(
                    review_input_parameters,
                    output_parameters,
                ),
                "input_local_completeness": input_local,
                "output_local_completeness": output_local,
                "score_change": self._review_score_change(input_local, output_local),
                "points": [list(point) for point in result.get("corrected_points", [])],
                "reason": result.get("reason"),
                "local_completeness": output_local,
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
                local = current.get("corrected_local_completeness") or current.get("local_completeness") or {}
                merged_fit = current.get("association_merged_fit") or {}
                preserve_after_conflict = bool(
                    current.get("association_status") == "merged_complementary_fragments"
                    and merged_fit.get("acceptable") is True
                    and local.get("available") is True
                    and local.get("complete") is True
                )
                corroboration = current.get("cross_window_corroboration") or {}
                preserve_after_conflict = bool(
                    preserve_after_conflict
                    or (
                        int(corroboration.get("support_count", 0)) >= 2
                        and corroboration.get("fit_acceptable") is True
                    )
                )
                if preserve_after_conflict:
                    current["needs_review"] = True
                    current["ai_alignment_status"] = "kept_after_review_conflict"
                    current["ai_correction_rounds"] = round_number - 1
                    current["ai_review_conflict_reason"] = (
                        result.get("reason") or "discarded_by_visual_review"
                    )
                    current["final_points"] = [list(point) for point in current.get("points", [])]
                    if hasattr(context, "record_event"):
                        context.record_event(
                            "reviewing",
                            "review_discard_overridden",
                            current["ai_review_conflict_reason"],
                            status="needs_review",
                            candidate_id=current.get("candidate_id"),
                            correction_round=round_number,
                        )
                    if hasattr(context, "update_monitor"):
                        context.update_monitor(
                            parameters=current.get("ai_final_parameters"),
                            api_status="candidate_kept_after_review_conflict",
                        )
                    return current, None
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

    def _audit_staged_candidates(
        self,
        request,
        context,
        rendered,
        staged,
        *,
        force_visual=False,
    ):
        if not staged:
            return {
                "kept": [],
                "discarded": [],
                "audit_status": "completed",
                "audit_views": [],
                "audit_events": [],
                "audit_action_count": 0,
            }
        if len(staged) == 1 and not force_visual:
            candidate = dict(staged[0])
            candidate["batch_audit_status"] = "skipped_single_candidate"
            final_overlay = self._build_batch_feedback_image(
                rendered,
                [candidate],
                request.target_image_track,
            )
            if hasattr(context, "set_monitor_media"):
                context.set_monitor_media(
                    "final_overlay",
                    {"data_url": final_overlay, "metadata": rendered.get("metadata") or {}},
                    api_status="audit_skipped_single_candidate",
                )
            if hasattr(context, "record_event"):
                context.record_event(
                    "auditing",
                    "audit_skipped_single_candidate",
                    "Single candidate already passed parameter review; batch comparison is unnecessary",
                    status="accepted",
                    kept_count=1,
                    discarded_count=0,
                )
            return {
                "kept": [candidate],
                "discarded": [],
                "audit_status": "skipped_single_candidate",
                "audit_views": [],
                "audit_events": [{
                    "action": "skip_single_candidate_audit",
                    "outcome": "accepted",
                    "reason": "Candidate already passed parameter review",
                }],
                "audit_action_count": 0,
                "audit_decisions": [{
                    "candidate_id": candidate.get("candidate_id"),
                    "action": "keep",
                    "reason": "Single reviewed candidate retained without redundant batch audit",
                }],
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
            FRACTURE_MORPHOLOGY_GUIDANCE
            +
            "You control an autonomous inspection loop for complete borehole-image fractures. Choose exactly one next "
            "action. You are not restricted to a fixed number of depth segments. Use inspect_view whenever another "
            "depth interval, wider or narrower crop, or partial azimuth view is needed. Set scale=1 for a source crop. "
            "Set scale between 0.5 and 4.0 to request a Plot-data rerender with that vertical scale multiplier; this changes "
            "pixels per depth unit and is not bitmap enlargement. detail_level is only a semantic label. Do not repeat "
            "identical depth, azimuth, and scale bounds with another detail_level. Partial-azimuth views are "
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
                self._analysis_images(current_rendered),
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
        source_start = float(metadata["depth_start"])
        source_end = float(metadata["depth_end"])
        span = float(candidate["depth_bottom"]) - float(candidate["depth_top"])
        padding = max(span * CANDIDATE_CROP_PADDING_RATIO, CANDIDATE_CROP_MIN_PADDING_M)
        requested_start = float(candidate["depth_top"]) - padding
        requested_end = float(candidate["depth_bottom"]) + padding
        source_rendered = rendered
        if (
            callable(self.pipeline.agent_view_provider)
            and (requested_start < source_start or requested_end > source_end)
        ):
            source_rendered = self.pipeline.agent_view_provider(FractureAgentViewRequest(
                depth_start=requested_start,
                depth_end=requested_end,
                azimuth_start_deg=0.0,
                azimuth_end_deg=360.0,
                detail_level="detail",
                include_depth_track=True,
                scale=1.0,
            ))
            self._validate_rendered(source_rendered)
            metadata = source_rendered["metadata"]
            source_start = float(metadata["depth_start"])
            source_end = float(metadata["depth_end"])
        image = self._decode_image(source_rendered["data_url"])
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
            "candidate_continuity_reason": str(candidate.get("continuity_reason") or ""),
            "source_render_size": [metadata.get("width"), metadata.get("height")],
            "candidate_requested_depth_range": [requested_start, requested_end],
            "candidate_used_external_source": source_rendered is not rendered,
            "uniform_scale": 1.0,
        }
        return {"data_url": self._encode_image(canvas), "metadata": candidate_metadata}

    def pick_candidate_anchors(self, request, candidate_rendered, candidate, *, client=None, model=None):
        if client is None or model is None:
            _config, client, model = self._client()
        metadata = candidate_rendered["metadata"]
        prompt = (
            FRACTURE_MORPHOLOGY_GUIDANCE
            +
            "Trace exactly one physical fracture in this focused borehole-image window. Return 3 to 8 anchor points "
            "on clearly visible parts of the same trace. Prefer a crest, trough, and visible mid-slope sections; include "
            "left or right seam points only when those sectors are actually readable. Do not place invented anchors in "
            "blank, missing-pad, or low-clarity sectors. Separated visible arcs may belong to one fracture when position, "
            "slope, curvature, and the tested fixed-period sinusoid connect them. Do not stitch unrelated textures. x_norm is relative to the target "
            "image track; y_norm is relative to the focused crop depth range. When core_depth_top and core_depth_bottom "
            "are present, the larger view is context added after a boundary check: continue tracing the same fracture "
            "that intersects that original core range and do not switch to a neighboring anomaly. Return JSON only.\n"
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
        previous_round = self._previous_review_context(annotation)
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
            view_instruction = (
                "Do not request another view or adjust the window or image scale; decide directly from the current "
                "candidate image and overlay. Set view=null. "
                if request.fast_mode else
                "You may use inspect_view to request another depth interval, a narrower or wider crop, or a "
                "partial-azimuth diagnostic view before deciding. Set scale=1 for a source crop, or scale=0.5..4.0 "
                "for a Plot-data vertical rerender. detail_level is only semantic. "
            )
            prompt = (
                FRACTURE_MORPHOLOGY_GUIDANCE
                +
                "Review one fitted complete fracture. The magenta curve is the current fixed-period sine fit and yellow "
                "circles are its anchors. " + view_instruction + "Prefer "
                "adjust_parameters and return absolute center depth, amplitude, and phase using "
                "D(theta)=c+A*sin(theta+phase). Use replace_points only when the fit follows the wrong texture. Use "
                "discard for an isolated local segment with no compatible continuation, stitched unrelated textures, "
                "or a fit that merely follows dominant background layering, pad-edge artifacts, or irregular borehole "
                "texture. Do not discard merely because some azimuth sectors are unclear or absent. Keep requires "
                "positive fracture evidence: a trace distinguishable from adjacent texture and compatible position, "
                "slope, and curvature on multiple measured pads. Absence of a contradiction is not sufficient evidence "
                "to keep. Scrutinize very low-amplitude, near-horizontal fits against neighboring parallel bands. Such a "
                "fit may be kept only when it has a distinct conductive or resistive fracture expression rather than "
                "ordinary bedding or background banding. cross_window_corroboration means an independently rendered "
                "overlapping window produced a geometrically matching fit. Treat acceptable corroboration as positive "
                "repeat evidence, while still checking that both fits did not merely follow the same background band. The local "
                "completeness score is advisory diagnostic evidence: a failed or unavailable local score must not by "
                "itself force correction or discard, but a failed score combined with weak visual evidence supports "
                "discard. If previous_round is present, decision_continuity must be maintain or overturn, and the reason "
                "must explicitly explain why the previous conclusion is maintained or overturned. To overturn it, cite "
                "new visible evidence or a materially meaningful geometry/evidence change. Do not reverse the previous "
                "conclusion solely because a negligible parameter adjustment moved one advisory score across a hard "
                "threshold. If previous_round is null, set decision_continuity=initial. For final actions set view=null. "
                "Return JSON only.\n"
                + json.dumps({
                    "candidate_id": annotation.get("candidate_id"),
                    "fracture_type": annotation.get("fracture_type"),
                    "correction_round": int(round_number),
                    "current_parameters": parameters,
                    "local_completeness": local,
                    "previous_round": previous_round,
                    "cross_window_corroboration": annotation.get("cross_window_corroboration"),
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
                response_schema=(
                    FAST_PARAMETER_REVIEW_SCHEMA if request.fast_mode else PARAMETER_REVIEW_SCHEMA
                ),
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
            audit_view_instruction = (
                "Do not request another view or adjust the window or image scale. Finalize the audit directly and set "
                "view=null. "
                if request.fast_mode else
                "Use inspect_view when another depth range, crop, or partial-azimuth detail is needed. "
            )
            prompt = (
                FRACTURE_MORPHOLOGY_GUIDANCE
                +
                "Autonomously audit the final staged complete-fracture batch. Image 1 is the authoritative raw Plot "
                "evidence and Image 2 contains the numbered fitted curves. Choose one action. This batch audit is a "
                "comparative consistency check, not a fresh replacement for candidate-level geological review. Focus "
                "on duplicates, unresolved local fragments, and curves demonstrably stitched across unrelated textures. "
                + audit_view_instruction + "Final decisions may only keep or discard existing "
                "candidates. Missing or unclear azimuth sectors caused by pad coverage, blank strips, or poor imaging are "
                "not a discard reason. Treat compatible visible arcs as one fracture when position, slope, curvature, and "
                "a tested fixed-period sinusoid connect them. Discard duplicates, isolated fragments without a compatible "
                "continuation, curves demonstrably stitched across unrelated visible textures, and candidates that "
                "merely follow a repeated bedding family, pad edges, or irregular borehole artifacts without a "
                "distinct fracture trace. Never merge candidates, create a new "
                "curve, or alter parameters during batch audit. Local completeness scores and needs_review flags are "
                "advisory; never discard a visually complete candidate solely because its local score failed or was "
                "unavailable. However, do not keep a candidate merely because the score is advisory or because no direct "
                "contradiction is visible. Each kept candidate must have positive support on multiple measured pads and "
                "must be distinguishable from neighboring parallel bands. Give extra scrutiny to low-amplitude, "
                "near-horizontal candidates: discard them when they are better explained as bedding or background "
                "banding, even if the sine fit is numerically aligned. cross_window_corroboration records a matching "
                "fit from an independently rendered overlapping window; acceptable corroboration is positive repeat "
                "evidence but does not excuse following background banding. Candidate continuity and review reasons are "
                "prior evidence, not final truth, but a discard that contradicts them must identify concrete contrary "
                "texture in the raw image. When discarding as bedding, explain which repeated parallel family the curve "
                "follows and why previously reported cross-cutting evidence is incorrect. Do not call a visibly "
                "high-amplitude curve near-horizontal merely because the full Plot is vertically compressed. Do not split "
                "one tested sinusoid into multiple "
                "picks. finalize_audit must return exactly one decision for "
                "every candidate id. For finalize_audit set view=null. Return JSON only.\n"
                + json.dumps({
                    "candidates": [
                        {
                            "candidate_id": item.get("candidate_id"),
                            "fracture_type": item.get("fracture_type"),
                            "overlay_color": item.get("_audit_color"),
                            "parameters": fracture_parameters(item),
                            "local_completeness": item.get("local_completeness"),
                            "cross_window_corroboration": item.get("cross_window_corroboration"),
                            "needs_review": bool(item.get("needs_review", False)),
                            "candidate_continuity_reason": item.get("candidate_continuity_reason"),
                            "candidate_review_reason": item.get("ai_review_reason"),
                            "candidate_review_confidence": item.get("ai_review_confidence"),
                            "candidate_alignment_status": item.get("ai_alignment_status"),
                            "candidate_depth_window": item.get("candidate_depth_window"),
                            "anchor_azimuth_span_deg": item.get("anchor_azimuth_span_deg"),
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
                self._vision_messages(
                    "You autonomously audit a staged batch of complete fracture picks.",
                    prompt,
                    [
                        (
                            "Image 1 - raw Plot evidence without candidate curves. Use this image to judge geology.",
                            current_rendered["data_url"],
                        ),
                        (
                            "Image 2 - the same view with numbered candidate curves. Use it to locate each fit.",
                            feedback,
                        ),
                    ],
                ),
                response_schema=(FAST_BATCH_AUDIT_SCHEMA if request.fast_mode else BATCH_AUDIT_SCHEMA),
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
                elif (
                    self._has_strong_pre_audit_support(candidate)
                    or self._audit_discard_conflicts_with_pre_audit_evidence(
                        candidate,
                        decision.get("reason"),
                    )
                ):
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
        corroboration = candidate.get("cross_window_corroboration") or {}
        corroborated = bool(
            int(corroboration.get("support_count", 0)) >= 2
            and corroboration.get("fit_acceptable") is True
        )
        return (aligned and (local_supported or hypothesis_supported)) or corroborated

    @staticmethod
    def _audit_discard_conflicts_with_pre_audit_evidence(candidate, audit_reason):
        """Preserve a geometrically substantial reviewed pick when a bedding discard is contradictory."""
        alignment = str(candidate.get("ai_alignment_status") or "")
        if alignment not in {"aligned", "kept_after_review_conflict"}:
            return False

        reason = str(audit_reason or "").lower()
        if not any(term in reason for term in ("bedding", "banding", "near-horizontal", "near horizontal")):
            return False

        parameters = fracture_parameters(candidate)
        amplitude = abs(float(parameters.get("amplitude_m", 0.0)))
        depth_window = candidate.get("candidate_depth_window") or []
        try:
            window_span = abs(float(depth_window[1]) - float(depth_window[0]))
        except (IndexError, TypeError, ValueError):
            window_span = 0.0
        relative_envelope = (2.0 * amplitude / window_span) if window_span > 1e-9 else 0.0
        if relative_envelope < AUDIT_CONFLICT_MIN_RELATIVE_ENVELOPE:
            return False

        points = CompleteFractureWorkflow._clean_depth_points(
            candidate.get("final_points") or candidate.get("points") or candidate.get("initial_points")
        )
        if CompleteFractureWorkflow._azimuth_coverage_span(points) < AUDIT_CONFLICT_MIN_ANCHOR_SPAN_DEG:
            return False

        prior_evidence = " ".join((
            str(candidate.get("candidate_continuity_reason") or ""),
            str(candidate.get("ai_review_reason") or ""),
        )).lower()
        return any(term in prior_evidence for term in (
            "cut across", "cuts across", "cross-cut", "crosses", "departs from", "distinct from", "separate from",
        ))

    def _normalize_review(self, payload, annotation, candidate_rendered, request, local):
        action = str(payload.get("action") or "discard")
        reason = str(payload.get("reason") or "")
        confidence = max(0.0, min(1.0, float(payload.get("confidence", 0.0))))
        has_previous_round = bool(annotation.get("ai_correction_history"))
        decision_continuity = str(payload.get("decision_continuity") or "").strip().lower()
        allowed_continuity = {"maintain", "overturn"} if has_previous_round else {"initial"}
        if decision_continuity not in allowed_continuity:
            decision_continuity = "maintain" if has_previous_round else "initial"
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
            "decision_continuity": decision_continuity,
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
            anchor_span = self._azimuth_coverage_span(
                item.get("final_points") or item.get("points") or item.get("initial_points")
            )
            return (
                2.0 * float(local.get("complete") is True)
                + anchor_span / 360.0
                + float(item.get("confidence", 0.0))
                + 0.1 * float(local.get("score", 0.0))
            )

        selected, discarded = [], []
        for candidate in sorted((dict(item) for item in candidates), key=rank, reverse=True):
            x, y = sinusoidal_fracture_xy(candidate, samples=181)
            duplicate = None
            duplicate_metrics = None
            for kept in selected:
                _kx, ky = sinusoidal_fracture_xy(kept, samples=181)
                mean_distance_px = float(np.mean(np.abs(y - ky))) * px_per_depth
                metrics = self._cross_window_duplicate_metrics(candidate, kept)
                if mean_distance_px < threshold_px or metrics["compatible"]:
                    duplicate = kept
                    duplicate_metrics = {
                        "mean_curve_distance_px": mean_distance_px,
                        **metrics,
                    }
                    break
            if duplicate is None:
                selected.append(candidate)
            else:
                discarded.append({
                    "candidate_id": candidate.get("candidate_id"),
                    "reason": f"nms_duplicate_of_{duplicate.get('candidate_id')}",
                    "stage": "nms",
                    "duplicate_metrics": duplicate_metrics,
                    "annotation": self._diagnostic_annotation(candidate),
                })
        selected.sort(key=lambda item: float(item.get("offset", 0.0)))
        return selected, discarded

    def _cross_window_duplicate_metrics(self, candidate, kept):
        candidate_parameters = fracture_parameters(candidate)
        kept_parameters = fracture_parameters(kept)
        candidate_amplitude = abs(float(candidate_parameters["amplitude_m"]))
        kept_amplitude = abs(float(kept_parameters["amplitude_m"]))
        maximum_amplitude = max(candidate_amplitude, kept_amplitude, 1e-9)
        minimum_amplitude = min(candidate_amplitude, kept_amplitude)
        center_delta = abs(
            float(candidate_parameters["center_depth_m"])
            - float(kept_parameters["center_depth_m"])
        )
        phase_delta = self._circular_phase_delta(
            float(candidate_parameters["phase_deg"]),
            float(kept_parameters["phase_deg"]),
        )
        amplitude_relative_delta = abs(candidate_amplitude - kept_amplitude) / maximum_amplitude
        candidate_envelope = (
            float(candidate_parameters["center_depth_m"]) - candidate_amplitude,
            float(candidate_parameters["center_depth_m"]) + candidate_amplitude,
        )
        kept_envelope = (
            float(kept_parameters["center_depth_m"]) - kept_amplitude,
            float(kept_parameters["center_depth_m"]) + kept_amplitude,
        )
        overlap = max(
            0.0,
            min(candidate_envelope[1], kept_envelope[1])
            - max(candidate_envelope[0], kept_envelope[0]),
        )
        envelope_overlap = overlap / max(2.0 * minimum_amplitude, 1e-9)

        candidate_points = self._clean_depth_points(
            candidate.get("final_points") or candidate.get("points") or candidate.get("initial_points")
        )
        kept_points = self._clean_depth_points(
            kept.get("final_points") or kept.get("points") or kept.get("initial_points")
        )
        candidate_span = self._azimuth_coverage_span(candidate_points)
        kept_span = self._azimuth_coverage_span(kept_points)
        subset_points, reference = (
            (candidate_points, kept)
            if candidate_span <= kept_span
            else (kept_points, candidate)
        )
        anchor_tolerance_m = max(0.08, 0.20 * maximum_amplitude)
        aligned_count = 0
        for azimuth_deg, depth in subset_points:
            azimuth = math.radians(float(azimuth_deg))
            predicted = (
                float(reference["offset"])
                + float(reference.get("sin_coeff", 0.0)) * math.sin(azimuth)
                + float(reference.get("cos_coeff", 0.0)) * math.cos(azimuth)
            )
            if abs(float(depth) - predicted) <= anchor_tolerance_m:
                aligned_count += 1
        anchor_alignment = aligned_count / max(1, len(subset_points))
        different_passes = (
            candidate.get("detection_pass_kind") != kept.get("detection_pass_kind")
            or candidate.get("sliding_window_index") != kept.get("sliding_window_index")
            or candidate.get("merged_observation_group") != kept.get("merged_observation_group")
        )
        compatible = bool(
            different_passes
            and candidate.get("fracture_type") == kept.get("fracture_type")
            and center_delta <= max(0.12, 0.45 * maximum_amplitude)
            and phase_delta <= 20.0
            and amplitude_relative_delta <= 0.50
            and envelope_overlap >= 0.70
            and len(subset_points) >= MIN_TRACE_POINTS
            and anchor_alignment >= 0.70
        )
        return {
            "compatible": compatible,
            "different_passes": different_passes,
            "center_delta_m": center_delta,
            "phase_delta_deg": phase_delta,
            "amplitude_relative_delta": amplitude_relative_delta,
            "envelope_overlap": envelope_overlap,
            "candidate_anchor_span_deg": candidate_span,
            "kept_anchor_span_deg": kept_span,
            "subset_anchor_alignment": anchor_alignment,
            "anchor_tolerance_m": anchor_tolerance_m,
        }

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
    def _analysis_images(rendered):
        overlay_data_url = rendered.get("overlay_data_url")
        if not overlay_data_url:
            return rendered["data_url"]
        images = [(
            "Image 1 - raw Plot evidence. Use this image as the authoritative source for borehole texture.",
            rendered["data_url"],
        )]
        images.append((
            "Image 2 - the same Plot view with previously picked fracture curves overlaid. Use it only to "
            "compare continuity, omissions, and duplicates. Colored curves and points are annotations, not "
            "raw fracture evidence.",
            overlay_data_url,
        ))
        return images

    @staticmethod
    def _vision_messages(system, prompt, image_url):
        images = image_url if isinstance(image_url, (list, tuple)) else [(None, image_url)]
        content = [{"type": "text", "text": prompt}]
        for label, url in images:
            if label:
                content.append({"type": "text", "text": str(label)})
            content.append({"type": "image_url", "image_url": {"url": url, "detail": "high"}})
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": content},
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
