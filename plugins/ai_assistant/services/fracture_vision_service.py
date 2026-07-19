from __future__ import annotations

import base64
from dataclasses import replace

import numpy as np
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ..ai_core.config import AIConfig
from .fracture_agent_workflow import (
    AdaptiveFractureViewRenderer,
    FractureAgentBudget,
    FractureAgentState,
    FractureAgentViewRequest,
)
from .fracture_complete_workflow import CompleteFractureWorkflow
from .fracture_evidence_service import FractureEvidenceScorer
from scripts.rendering.fracture_annotations import (
    enrich_fracture_interpretation,
    fit_sinusoidal_fracture,
    fracture_parameters,
    sinusoidal_fracture_xy,
)

try:
    import openai
except ImportError:
    openai = None


FRACTURE_FEEDBACK_POINT_RADIUS = 12.0
FRACTURE_FEEDBACK_POINT_OUTLINE_WIDTH = 3.0


class _SlidingWindowContext:
    """Map one window's workflow progress into the parent detection run."""

    def __init__(self, parent, index, total, diagnostics_sink, label, pass_details):
        self._parent = parent
        self._index = int(index)
        self._total = max(1, int(total))
        self._diagnostics_sink = diagnostics_sink
        self._label = str(label)
        self._pass_details = dict(pass_details)
        self.run_id = parent.run_id

    @property
    def cancelled(self):
        return self._parent.cancelled

    @property
    def defer_batch_audit(self):
        return True

    @property
    def defer_candidate_review(self):
        return True

    def update(self, stage, progress, message=""):
        mapped = 0.02 + 0.82 * ((self._index + max(0.0, min(1.0, float(progress)))) / self._total)
        prefix = f"{self._label} ({self._index + 1}/{self._total})"
        self._parent.update(stage, mapped, f"{prefix}: {message}" if message else prefix)

    def set_diagnostics(self, diagnostics):
        self._diagnostics_sink.append({**self._pass_details, "diagnostics": diagnostics})

    def qualify_candidate_id(self, candidate_id):
        prefix = (
            f"G{self._pass_details['group_index']}"
            if self._pass_details.get("kind") == "merged_observation"
            else f"W{self._pass_details['primary_index']}"
        )
        return f"{prefix}-{candidate_id}"

    def set_candidate_payload(self, candidate_id, payload):
        qualified_id = self.qualify_candidate_id(candidate_id)
        enriched = dict(payload or {})
        metadata = dict(enriched.get("metadata") or {})
        metadata["diagnostic_candidate_id"] = qualified_id
        enriched["metadata"] = metadata
        self._parent.set_candidate_payload(qualified_id, enriched)

    def set_view_payload(self, view_id, payload):
        self._parent.set_view_payload(self.qualify_candidate_id(view_id), payload)

    def __getattr__(self, name):
        return getattr(self._parent, name)


class FractureVisionPipeline:
    """OpenAI-compatible client facade for the complete-fracture workflow."""

    def __init__(self, config=None, client_factory=None, evidence_scorer=None, agent_view_provider=None):
        self.config = config or AIConfig()
        self.client_factory = client_factory
        self.evidence_scorer = evidence_scorer or FractureEvidenceScorer()
        self.view_renderer = AdaptiveFractureViewRenderer()
        self.agent_view_provider = agent_view_provider
        self.complete_workflow = CompleteFractureWorkflow(self)

    def detect(self, request, context, rendered):
        windows = self._sliding_windows(request.depth_start, request.depth_end, request.sliding_window_m)
        if len(windows) == 1:
            return self.complete_workflow.detect(request, context, rendered)

        all_annotations = []
        window_diagnostics = []
        context_only_candidates = []
        context_only_annotations = []
        schedule = self._window_schedule(windows)
        for index, pass_info in enumerate(schedule):
            if context.cancelled:
                return []
            depth_start = pass_info["depth_start"]
            depth_end = pass_info["depth_end"]
            label = f"Window {pass_info['primary_index']}"
            context.update(
                "window_rendering",
                0.02 + 0.82 * index / len(schedule),
                f"AI: {label.lower()}, {depth_start:.3f}-{depth_end:.3f} m",
            )
            view_request = FractureAgentViewRequest(
                depth_start=depth_start,
                depth_end=depth_end,
                detail_level="overview",
                include_depth_track=True,
                scale=1.0,
            )
            if callable(self.agent_view_provider):
                window_rendered = self.agent_view_provider(view_request)
            else:
                window_rendered = self.view_renderer.render(
                    rendered,
                    request.target_image_track,
                    view_request,
                    view_id=(
                        f"window-{pass_info['primary_index']}"
                    ),
                )
            window_request = replace(request, depth_start=depth_start, depth_end=depth_end)
            window_context = _SlidingWindowContext(
                context,
                index,
                len(schedule),
                window_diagnostics,
                label,
                pass_info,
            )
            annotations = self.complete_workflow.detect(window_request, window_context, window_rendered)
            for annotation in annotations:
                item = dict(annotation)
                original_id = str(item.get("candidate_id") or "candidate")
                prefix = f"W{pass_info['primary_index']}"
                item["candidate_id"] = f"{prefix}-{original_id}"
                source_ids = list(item.get("associated_candidate_ids") or [])
                if source_ids:
                    item["associated_candidate_ids"] = [
                        str(source_id)
                        if str(source_id).startswith(("W", "G", "X-"))
                        else f"{prefix}-{source_id}"
                        for source_id in source_ids
                    ]
                item["sliding_window_index"] = pass_info.get("primary_index")
                item["merged_observation_group"] = pass_info.get("group_index")
                item["detection_pass_kind"] = pass_info["kind"]
                item["sliding_window_depth_range"] = [depth_start, depth_end]
                if not self._candidate_owned_by_pass(item, pass_info):
                    context_record = {
                        "candidate_id": item["candidate_id"],
                        "center_depth": item.get("offset"),
                        "source_window_index": pass_info["primary_index"],
                        "ownership_depth_range": [
                            pass_info["ownership_depth_start"],
                            pass_info["ownership_depth_end"],
                        ],
                        "reason": "center_depth_outside_window_ownership",
                        "status": "pending_owner_result",
                    }
                    context_only_candidates.append(context_record)
                    context_only_annotations.append((item, context_record))
                    if hasattr(context, "record_event"):
                        context.record_event(
                            "window_ownership",
                            "context_only_candidate",
                            "Candidate center belongs to an adjacent sliding window",
                            status="skipped",
                            candidate_id=item["candidate_id"],
                            center_depth=item.get("offset"),
                            source_window_index=pass_info["primary_index"],
                        )
                    continue
                all_annotations.append(item)

        promoted_context_candidates = []
        for annotation, record in context_only_annotations:
            matching_owned = next((
                item for item in all_annotations
                if self._annotations_match_for_window_ownership(
                    annotation,
                    item,
                    rendered,
                )
            ), None)
            if matching_owned is not None:
                record["status"] = "covered_by_owner_window"
                record["matching_candidate_id"] = matching_owned.get("candidate_id")
                corroboration = self._merge_window_ownership_support(
                    matching_owned,
                    annotation,
                    rendered,
                    borehole_diameter=request.borehole_diameter_in,
                )
                record["corroboration"] = corroboration
                if hasattr(context, "record_event"):
                    context.record_event(
                        "window_ownership",
                        "context_evidence_merged",
                        "Matching adjacent-window evidence was merged into the owner candidate",
                        status="accepted",
                        candidate_id=matching_owned.get("candidate_id"),
                        supporting_candidate_id=annotation.get("candidate_id"),
                        **corroboration,
                    )
                continue
            promoted = dict(annotation)
            promoted["ownership_fallback_promoted"] = True
            promoted["ownership_fallback_source_window"] = record["source_window_index"]
            promoted["needs_review"] = True
            all_annotations.append(promoted)
            promoted_context_candidates.append(promoted["candidate_id"])
            record["status"] = "promoted_after_owner_miss"
            if hasattr(context, "record_event"):
                context.record_event(
                    "window_ownership",
                    "context_candidate_promoted",
                    "Owner window produced no matching accepted fracture",
                    status="accepted",
                    candidate_id=promoted["candidate_id"],
                    center_depth=promoted.get("offset"),
                    source_window_index=record["source_window_index"],
                )

        associate_batch = getattr(
            self.complete_workflow,
            "associate_annotations_across_windows",
            None,
        )
        if callable(associate_batch):
            all_annotations, cross_window_association = associate_batch(
                request,
                context,
                rendered,
                all_annotations,
            )
        else:
            cross_window_association = {
                "input_count": len(all_annotations),
                "output_count": len(all_annotations),
                "groups": [],
                "comparisons": [],
            }

        review_batch = getattr(
            self.complete_workflow,
            "review_annotations_after_association",
            None,
        )
        if callable(review_batch):
            all_annotations, cross_window_review_discards = review_batch(
                request,
                context,
                rendered,
                all_annotations,
            )
        else:
            cross_window_review_discards = []

        nms_kept, duplicate_discards = self.complete_workflow._non_maximum_suppression(
            all_annotations,
            rendered,
        )
        global_audit = getattr(self.complete_workflow, "_audit_staged_candidates", None)
        if callable(global_audit):
            context.update(
                "auditing",
                0.86,
                f"AI: globally auditing {len(nms_kept)} cross-window candidate(s)",
            )
            global_audit_result = global_audit(
                request,
                context,
                rendered,
                nms_kept,
                force_visual=True,
            )
            kept = list(global_audit_result.get("kept") or [])
            global_audit_discards = list(global_audit_result.get("discarded") or [])
        else:
            kept = nms_kept
            global_audit_discards = []
            global_audit_result = {
                "audit_status": "unavailable",
                "audit_action_count": 0,
                "audit_views": [],
                "audit_events": [],
            }
        window_discards = []
        for window_record in window_diagnostics:
            pass_prefix = (
                f"G{window_record.get('group_index')}"
                if window_record.get("kind") == "merged_observation"
                else f"W{window_record.get('primary_index')}"
            )
            for discard in (window_record.get("diagnostics") or {}).get("discarded") or []:
                discard_record = dict(discard)
                local_id = str(discard_record.get("candidate_id") or "candidate")
                discard_record["candidate_id"] = f"{pass_prefix}-{local_id}"
                discard_record["detection_pass_kind"] = window_record.get("kind")
                window_discards.append(discard_record)
        aggregate_discards = (
            window_discards
            + list(cross_window_review_discards)
            + list(duplicate_discards)
            + global_audit_discards
        )
        build_final_overlay = getattr(self.complete_workflow, "_build_batch_feedback_image", None)
        if callable(build_final_overlay):
            final_overlay = build_final_overlay(
                rendered,
                kept,
                request.target_image_track,
            )
            if hasattr(context, "set_monitor_media"):
                context.set_monitor_media(
                    "final_overlay",
                    {
                        "data_url": final_overlay,
                        "metadata": rendered.get("metadata") or {},
                    },
                    api_status="sliding_windows_completed",
                )
            if hasattr(context, "record_event"):
                context.record_event(
                    "staging",
                    "final_sliding_overlay_prepared",
                    "Prepared the full-depth overlay from all retained sliding-window candidates",
                    status="accepted",
                    kept_count=len(kept),
                )
        context.set_diagnostics({
            "render_metadata": rendered.get("metadata") or {},
            "sliding_window_m": request.sliding_window_m,
            "sliding_window_overlap_fraction": 0.20,
            "sliding_windows": [
                {"index": index + 1, "depth_start": start, "depth_end": end}
                for index, (start, end) in enumerate(windows)
            ],
            "merged_observations": [item for item in schedule if item["kind"] == "merged_observation"],
            "window_diagnostics": window_diagnostics,
            "cross_window_association": cross_window_association,
            "cross_window_review_discards": cross_window_review_discards,
            "cross_window_duplicates": duplicate_discards,
            "global_batch_audit": {
                key: value
                for key, value in global_audit_result.items()
                if key not in {"kept", "discarded"}
            },
            "discarded": aggregate_discards,
            "discarded_count": len(aggregate_discards),
            "kept_candidate_ids": [item.get("candidate_id") for item in kept],
            "context_only_candidates": context_only_candidates,
            "promoted_context_candidates": promoted_context_candidates,
            "accepted_count": len(kept),
            "final_overlay_scope": "full_detection_depth_range",
        })
        if hasattr(context, "update_monitor"):
            context.update_monitor(
                candidate_count=len(kept) + len(aggregate_discards),
                kept_count=len(kept),
                discarded_count=len(aggregate_discards),
                current_candidate="",
                correction_round=0,
                api_status="ready_for_gui",
            )
        context.update(
            "staging",
            0.89,
            f"Prepared {len(kept)} candidate(s) from {len(windows)} windows and "
            f"{len(schedule) - len(windows)} merged observation(s)",
        )
        return kept

    @staticmethod
    def _sliding_windows(depth_start, depth_end, window_size, overlap_fraction=0.20):
        start, end = float(depth_start), float(depth_end)
        size = min(float(window_size), end - start)
        if size >= end - start:
            return [(start, end)]
        step = size * (1.0 - float(overlap_fraction))
        windows = []
        cursor = start
        while cursor < end:
            window_end = min(end, cursor + size)
            windows.append((cursor, window_end))
            if window_end >= end:
                break
            cursor += step
        return windows

    @staticmethod
    def _window_schedule(windows):
        schedule = []
        for index, (depth_start, depth_end) in enumerate(windows):
            ownership_start = (
                depth_start
                if index == 0
                else (windows[index - 1][1] + depth_start) / 2.0
            )
            ownership_end = (
                depth_end
                if index == len(windows) - 1
                else (depth_end + windows[index + 1][0]) / 2.0
            )
            schedule.append({
                "kind": "primary_window",
                "primary_index": index + 1,
                "group_index": None,
                "depth_start": depth_start,
                "depth_end": depth_end,
                "ownership_depth_start": ownership_start,
                "ownership_depth_end": ownership_end,
                "owns_end_boundary": index == len(windows) - 1,
            })
        return schedule

    @staticmethod
    def _candidate_owned_by_pass(annotation, pass_info):
        try:
            center = float(annotation["offset"])
        except (KeyError, TypeError, ValueError):
            return True
        start = float(pass_info["ownership_depth_start"])
        end = float(pass_info["ownership_depth_end"])
        return center >= start and (
            center < end
            or (bool(pass_info.get("owns_end_boundary")) and center <= end)
        )

    @staticmethod
    def _annotations_match_for_window_ownership(left, right, rendered, threshold_px=8.0):
        left_type = str(left.get("fracture_type") or "")
        right_type = str(right.get("fracture_type") or "")
        if left_type and right_type and left_type != right_type:
            return False
        metadata = rendered.get("metadata") or {}
        depth_span = float(metadata.get("depth_end", 0.0)) - float(metadata.get("depth_start", 0.0))
        plot_height = float(metadata.get("plot_bottom", metadata.get("height", 0.0))) - float(
            metadata.get("plot_top", 0.0)
        )
        if depth_span <= 0.0 or plot_height <= 0.0:
            return False
        _left_x, left_depth = sinusoidal_fracture_xy(left, samples=181)
        _right_x, right_depth = sinusoidal_fracture_xy(right, samples=181)
        mean_distance_px = float(np.mean(np.abs(left_depth - right_depth))) * plot_height / depth_span
        return mean_distance_px < float(threshold_px)

    @staticmethod
    def _merge_window_ownership_support(owner, support, rendered, *, borehole_diameter):
        def clean_points(annotation):
            output = []
            for point in (
                annotation.get("final_points")
                or annotation.get("points")
                or annotation.get("initial_points")
                or []
            ):
                try:
                    azimuth, depth = float(point[0]) % 360.0, float(point[1])
                except (IndexError, TypeError, ValueError):
                    continue
                if np.isfinite(azimuth) and np.isfinite(depth):
                    output.append([azimuth, depth])
            return output

        owner_id = str(owner.get("candidate_id") or "owner")
        support_id = str(support.get("candidate_id") or "support")
        source_ids = list(dict.fromkeys(
            list(owner.get("ownership_support_candidate_ids") or [owner_id]) + [support_id]
        ))
        source_windows = list(dict.fromkeys(
            value for value in (
                *(owner.get("ownership_support_window_indices") or []),
                owner.get("sliding_window_index"),
                support.get("sliding_window_index"),
            )
            if value is not None
        ))
        owner_points = clean_points(owner)
        support_points = clean_points(support)
        combined_points = owner_points + support_points
        fit_acceptable = False
        rmse = None
        threshold = None
        if len(combined_points) >= 3:
            fit = fit_sinusoidal_fracture(combined_points, min_points=3)
            azimuth = np.deg2rad(np.asarray([point[0] for point in combined_points], dtype=float))
            depth = np.asarray([point[1] for point in combined_points], dtype=float)
            predicted = (
                float(fit["offset"])
                + float(fit["sin_coeff"]) * np.sin(azimuth)
                + float(fit["cos_coeff"]) * np.cos(azimuth)
            )
            rmse = float(np.sqrt(np.mean(np.square(depth - predicted))))
            parameters = fracture_parameters(fit)
            threshold = min(0.12, max(0.08, 0.20 * abs(parameters["amplitude_m"])))
            fit_acceptable = bool(np.isfinite(rmse) and rmse <= threshold)
            if fit_acceptable:
                owner.update(fit)
                owner["ai_final_parameters"] = dict(parameters)
                owner["points"] = [list(point) for point in combined_points]
                owner["final_points"] = [list(point) for point in combined_points]
                owner["candidate_depth_window"] = [
                    max(
                        float(rendered["metadata"]["depth_start"]),
                        parameters["center_depth_m"] - abs(parameters["amplitude_m"]),
                    ),
                    min(
                        float(rendered["metadata"]["depth_end"]),
                        parameters["center_depth_m"] + abs(parameters["amplitude_m"]),
                    ),
                ]
                owner.update(enrich_fracture_interpretation(
                    owner,
                    borehole_diameter=borehole_diameter,
                ))

        corroboration = {
            "support_count": len(source_ids),
            "candidate_ids": source_ids,
            "source_window_indices": source_windows,
            "owner_point_count": len(owner_points),
            "support_point_count": len(support_points),
            "combined_point_count": len(combined_points),
            "combined_fit_rmse_m": rmse,
            "combined_fit_threshold_m": threshold,
            "fit_acceptable": fit_acceptable,
        }
        owner["ownership_support_candidate_ids"] = source_ids
        owner["ownership_support_window_indices"] = source_windows
        owner["cross_window_corroboration"] = corroboration
        owner["confidence"] = max(
            float(owner.get("confidence", 0.0)),
            float(support.get("confidence", 0.0)),
        )
        return corroboration

    def discover_candidate_windows(self, request, rendered):
        return self.complete_workflow.discover_candidate_windows(request, rendered)

    def render_candidate_window(self, rendered, candidate, target_image_track):
        return self.complete_workflow.render_candidate_window(rendered, candidate, target_image_track)

    def create_agent_state(self, budget=None):
        return FractureAgentState(budget=budget or FractureAgentBudget())

    def render_agent_view(self, rendered, target_image_track, view_request, view_id=None):
        request = (
            view_request
            if isinstance(view_request, FractureAgentViewRequest)
            else FractureAgentViewRequest.build(view_request, rendered["metadata"])
        )
        source = rendered
        if request.scale != 1.0 and callable(self.agent_view_provider):
            source = self.agent_view_provider(request)
        output = self.view_renderer.render(
            source,
            target_image_track,
            request,
            view_id=view_id,
        )
        overlay_data_url = rendered.get("overlay_data_url")
        if overlay_data_url and source is rendered:
            overlay_source = {**rendered, "data_url": overlay_data_url}
            overlay_output = self.view_renderer.render(
                overlay_source,
                target_image_track,
                request,
                view_id=f"{view_id}-overlay" if view_id else None,
            )
            output["overlay_data_url"] = overlay_output["data_url"]
        if source is not rendered:
            output["metadata"]["render_mode"] = "plot_data_rerender"
            output["metadata"]["source_render_size"] = [
                source["metadata"].get("width"), source["metadata"].get("height"),
            ]
        return output

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
        painter.setPen(QPen(QColor("#101010"), FRACTURE_FEEDBACK_POINT_OUTLINE_WIDTH))
        painter.setBrush(QColor("#FFE600"))
        for azimuth, depth in points:
            if azimuth_start <= float(azimuth) <= azimuth_end:
                painter.drawEllipse(
                    pixel_point(azimuth, depth),
                    FRACTURE_FEEDBACK_POINT_RADIUS,
                    FRACTURE_FEEDBACK_POINT_RADIUS,
                )
        painter.end()

        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise RuntimeError("Unable to encode fracture feedback image")
        return "data:image/png;base64," + base64.b64encode(bytes(data)).decode("ascii")
