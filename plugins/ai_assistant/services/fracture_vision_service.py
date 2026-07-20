from __future__ import annotations

import base64
import copy
import hashlib
import re
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
from .fracture_complete_workflow import (
    PROMPT_VERSION,
    WORKFLOW_VERSION,
    CompleteFractureWorkflow,
)
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
MAX_REVIEW_WINDOWS_PER_BATCH = 3


def _offset_window_identity(value, offset):
    if not value or not offset:
        return value
    return re.sub(
        r"W(\d+)-",
        lambda match: f"W{int(match.group(1)) + int(offset)}-",
        str(value),
    )


class _WindowBatchContext:
    """Map one bounded window batch into the parent run and keep its diagnostics."""

    def __init__(self, parent, batch_index, batch_count, window_offset, diagnostics_sink):
        self._parent = parent
        self._batch_index = int(batch_index)
        self._batch_count = max(1, int(batch_count))
        self._window_offset = int(window_offset)
        self._diagnostics_sink = diagnostics_sink
        self.run_id = parent.run_id

    @property
    def cancelled(self):
        return self._parent.cancelled

    def update(self, stage, progress, message=""):
        mapped = 0.02 + 0.87 * (
            (self._batch_index + max(0.0, min(1.0, float(progress)))) / self._batch_count
        )
        prefix = f"Batch {self._batch_index + 1}/{self._batch_count}"
        self._parent.update(stage, mapped, f"{prefix}: {message}" if message else prefix)

    def set_diagnostics(self, diagnostics):
        self._diagnostics_sink.append({
            "batch_index": self._batch_index + 1,
            "window_index_offset": self._window_offset,
            "diagnostics": copy.deepcopy(diagnostics or {}),
        })

    def set_candidate_payload(self, candidate_id, payload):
        enriched = copy.deepcopy(payload or {})
        metadata = dict(enriched.get("metadata") or {})
        if metadata.get("diagnostic_candidate_id"):
            metadata["diagnostic_candidate_id"] = _offset_window_identity(
                metadata["diagnostic_candidate_id"],
                self._window_offset,
            )
        enriched["metadata"] = metadata
        self._parent.set_candidate_payload(
            _offset_window_identity(candidate_id, self._window_offset),
            enriched,
        )

    def set_view_payload(self, view_id, payload):
        qualified = f"batch-{self._batch_index + 1}-{view_id}"
        self._parent.set_view_payload(qualified, payload)

    def set_monitor_media(self, slot, payload, **details):
        if slot == "final_overlay" and hasattr(self._parent, "set_view_payload"):
            self._parent.set_view_payload(
                f"batch-{self._batch_index + 1}-final-overlay",
                payload,
            )
        self._parent.set_monitor_media(slot, payload, **details)

    def record_event(self, stage, action, reason, **details):
        for key in ("candidate_id", "supporting_candidate_id"):
            if details.get(key):
                details[key] = _offset_window_identity(details[key], self._window_offset)
        self._parent.record_event(stage, action, reason, **details)

    def __getattr__(self, name):
        return getattr(self._parent, name)


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
        self._request_metrics = {}
        self._reset_request_metrics()
        self.complete_workflow = CompleteFractureWorkflow(self)

    def detect(self, request, context, rendered):
        self._reset_request_metrics()
        windows = self._sliding_windows(
            request.depth_start,
            request.depth_end,
            request.sliding_window_m,
        )
        if len(windows) <= MAX_REVIEW_WINDOWS_PER_BATCH:
            return self._detect_window_group(
                request,
                context,
                rendered,
                windows=windows,
            )

        batches = [
            windows[index:index + MAX_REVIEW_WINDOWS_PER_BATCH]
            for index in range(0, len(windows), MAX_REVIEW_WINDOWS_PER_BATCH)
        ]
        batch_diagnostics = []
        batch_rendered_views = []
        all_annotations = []
        all_discards = []
        boundary_carry = []
        boundary_associations = []
        for batch_index, batch_windows in enumerate(batches):
            if context.cancelled:
                return []
            window_offset = batch_index * MAX_REVIEW_WINDOWS_PER_BATCH
            batch_start = float(batch_windows[0][0])
            batch_end = float(batch_windows[-1][1])
            context.update(
                "batch_rendering",
                0.02 + 0.87 * batch_index / len(batches),
                f"AI: preparing window batch {batch_index + 1}/{len(batches)}, "
                f"{batch_start:.3f}-{batch_end:.3f} m",
            )
            batch_rendered = self._render_window_batch(
                request,
                rendered,
                batch_start,
                batch_end,
                batch_index + 1,
            )
            batch_rendered_views.append(batch_rendered)
            batch_request = replace(
                request,
                depth_start=batch_start,
                depth_end=batch_end,
            )
            batch_context = _WindowBatchContext(
                context,
                batch_index,
                len(batches),
                window_offset,
                batch_diagnostics,
            )
            batch_annotations = self._detect_window_group(
                batch_request,
                batch_context,
                batch_rendered,
                windows=batch_windows,
                force_window_wrapper=True,
            )
            current_annotations = []
            for annotation in batch_annotations:
                current_annotations.append(self._remap_batch_annotation(
                    annotation,
                    window_offset,
                    batch_index + 1,
                ))
            combined = list(boundary_carry) + current_annotations
            if boundary_carry and current_annotations:
                combined, association_record, association_discards = (
                    self._associate_boundary_candidates(
                        request,
                        context,
                        rendered,
                        boundary_carry,
                        current_annotations,
                    )
                )
                boundary_associations.append({
                    "batch_index": batch_index + 1,
                    **association_record,
                })
                all_discards.extend(association_discards)

            if batch_index + 1 < len(batches):
                next_windows = batches[batch_index + 1]
                overlap_start = max(float(batch_windows[-1][0]), float(next_windows[0][0]))
                overlap_end = min(float(batch_windows[-1][1]), float(next_windows[0][1]))
                if overlap_end > overlap_start:
                    boundary_carry = [
                        item for item in combined
                        if self._candidate_intersects_depth_range(
                            item,
                            overlap_start,
                            overlap_end,
                        )
                    ]
                    carried_ids = {
                        str(item.get("candidate_id")) for item in boundary_carry
                    }
                    all_annotations.extend(
                        item for item in combined
                        if str(item.get("candidate_id")) not in carried_ids
                    )
                else:
                    all_annotations.extend(combined)
                    boundary_carry = []
            else:
                all_annotations.extend(combined)
                boundary_carry = []
            batch_record = batch_diagnostics[-1] if batch_diagnostics else None
            if batch_record is not None:
                batch_record["diagnostics"] = self._remap_batch_diagnostics(
                    batch_record.get("diagnostics") or {},
                    window_offset,
                )
                batch_record.update({
                    "depth_start": batch_start,
                    "depth_end": batch_end,
                    "source_window_indices": [
                        window_offset + index + 1
                        for index in range(len(batch_windows))
                    ],
                })
                diagnostics = batch_record.get("diagnostics") or {}
                all_discards.extend(
                    self._remap_batch_discard(item, 0, batch_index + 1)
                    for item in diagnostics.get("discarded") or []
                )

        reference_rendered = batch_rendered_views[0] if batch_rendered_views else rendered
        kept, cross_batch_duplicates = self.complete_workflow._non_maximum_suppression(
            all_annotations,
            reference_rendered,
        )
        all_discards.extend(cross_batch_duplicates)
        build_final_overlay = getattr(
            self.complete_workflow,
            "_build_batch_feedback_image",
            None,
        )
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
                    api_status="window_batches_completed",
                )
            if hasattr(context, "record_event"):
                context.record_event(
                    "staging",
                    "final_batch_summary_overlay_prepared",
                    "Prepared the full-depth summary overlay after bounded window-batch review",
                    status="accepted",
                    kept_count=len(kept),
                    batch_count=len(batches),
                )

        flattened_window_diagnostics = []
        context_only_candidates = []
        promoted_context_candidates = []
        for batch_record in batch_diagnostics:
            batch_result = batch_record.get("diagnostics") or {}
            flattened_window_diagnostics.extend(batch_result.get("window_diagnostics") or [])
            context_only_candidates.extend(batch_result.get("context_only_candidates") or [])
            promoted_context_candidates.extend(batch_result.get("promoted_context_candidates") or [])

        diagnostics = {
            "workflow_version": WORKFLOW_VERSION,
            "prompt_version": PROMPT_VERSION,
            "render_metadata": rendered.get("metadata") or {},
            "sliding_window_m": request.sliding_window_m,
            "sliding_window_overlap_fraction": 0.20,
            "max_review_windows_per_batch": MAX_REVIEW_WINDOWS_PER_BATCH,
            "sliding_windows": [
                {"index": index + 1, "depth_start": start, "depth_end": end}
                for index, (start, end) in enumerate(windows)
            ],
            "merged_observations": [],
            "window_diagnostics": flattened_window_diagnostics,
            "window_batches": batch_diagnostics,
            "cross_batch_duplicates": cross_batch_duplicates,
            "cross_batch_boundary_associations": boundary_associations,
            "global_batch_audit": {
                "audit_status": "performed_per_window_batch",
                "visual_global_audit_skipped": True,
            },
            "discarded": all_discards,
            "discarded_count": len(all_discards),
            "kept_candidate_ids": [item.get("candidate_id") for item in kept],
            "context_only_candidates": context_only_candidates,
            "promoted_context_candidates": promoted_context_candidates,
            "accepted_count": len(kept),
            "final_overlay_scope": "full_detection_depth_range_summary_only",
            "visual_requests": self.request_metrics_snapshot(),
        }
        context.set_diagnostics(diagnostics)
        if hasattr(context, "update_monitor"):
            context.update_monitor(
                candidate_count=len(kept) + len(all_discards),
                kept_count=len(kept),
                discarded_count=len(all_discards),
                current_candidate="",
                correction_round=0,
                api_status="ready_for_gui",
            )
        context.update(
            "staging",
            0.89,
            f"Prepared {len(kept)} candidate(s) from {len(windows)} windows in "
            f"{len(batches)} review batch(es)",
        )
        return kept

    def _detect_window_group(
        self,
        request,
        context,
        rendered,
        *,
        windows=None,
        force_window_wrapper=False,
    ):
        windows = list(windows or self._sliding_windows(
            request.depth_start,
            request.depth_end,
            request.sliding_window_m,
        ))
        if len(windows) == 1 and not force_window_wrapper:
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
                evidence_source_ids = list(item.get("source_candidate_ids") or [])
                if evidence_source_ids:
                    item["source_candidate_ids"] = [
                        str(source_id)
                        if str(source_id).startswith(("W", "G", "X-"))
                        else f"{prefix}-{source_id}"
                        for source_id in evidence_source_ids
                    ]
                item["sliding_window_index"] = pass_info.get("primary_index")
                item["merged_observation_group"] = pass_info.get("group_index")
                item["detection_pass_kind"] = pass_info["kind"]
                item["sliding_window_depth_range"] = [depth_start, depth_end]
                self._refresh_evidence_identity(item)
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
            "workflow_version": WORKFLOW_VERSION,
            "prompt_version": PROMPT_VERSION,
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
            "visual_requests": self.request_metrics_snapshot(),
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

    def _render_window_batch(
        self,
        request,
        rendered,
        depth_start,
        depth_end,
        batch_index,
    ):
        view_request = FractureAgentViewRequest(
            depth_start=float(depth_start),
            depth_end=float(depth_end),
            detail_level="overview",
            include_depth_track=True,
            scale=1.0,
        )
        if callable(self.agent_view_provider):
            return self.agent_view_provider(view_request)
        return self.view_renderer.render(
            rendered,
            request.target_image_track,
            view_request,
            view_id=f"window-batch-{batch_index}",
        )

    @staticmethod
    def _remap_batch_annotation(annotation, window_offset, batch_index):
        item = copy.deepcopy(annotation)
        for key in (
            "candidate_id",
            "matching_candidate_id",
            "supporting_candidate_id",
        ):
            if item.get(key):
                item[key] = _offset_window_identity(item[key], window_offset)
        for key in (
            "associated_candidate_ids",
            "ownership_support_candidate_ids",
            "associated_fragment_candidate_ids",
            "source_candidate_ids",
        ):
            if item.get(key):
                item[key] = [
                    _offset_window_identity(value, window_offset)
                    for value in item[key]
                ]
        for key in (
            "sliding_window_index",
            "ownership_fallback_source_window",
            "source_window_index",
        ):
            if item.get(key) is not None:
                item[key] = int(item[key]) + int(window_offset)
        if item.get("ownership_support_window_indices"):
            item["ownership_support_window_indices"] = [
                int(value) + int(window_offset)
                for value in item["ownership_support_window_indices"]
            ]
        metadata = dict(item.get("metadata") or {})
        if metadata.get("diagnostic_candidate_id"):
            metadata["diagnostic_candidate_id"] = _offset_window_identity(
                metadata["diagnostic_candidate_id"],
                window_offset,
            )
        if metadata:
            item["metadata"] = metadata
        item["processing_batch_index"] = int(batch_index)
        FractureVisionPipeline._refresh_evidence_identity(item)
        return item

    @staticmethod
    def _refresh_evidence_identity(annotation):
        source_ids = [
            str(value) for value in (
                annotation.get("source_candidate_ids")
                or annotation.get("associated_candidate_ids")
                or [annotation.get("candidate_id")]
            ) if value
        ]
        annotation["source_candidate_ids"] = sorted(set(source_ids))
        seed = "|".join(annotation["source_candidate_ids"])
        annotation["evidence_id"] = "EV-" + hashlib.sha256(
            seed.encode("utf-8")
        ).hexdigest()[:12]
        source_windows = []
        for value in (
            annotation.get("source_window_indices")
            or annotation.get("ownership_support_window_indices")
            or ([annotation.get("sliding_window_index")]
                if annotation.get("sliding_window_index") is not None else [])
        ):
            if value is not None:
                source_windows.append(int(value))
        annotation["source_window_indices"] = sorted(set(source_windows))
        return annotation

    @staticmethod
    def _candidate_intersects_depth_range(annotation, depth_start, depth_end):
        parameters = fracture_parameters(annotation)
        center = float(parameters["center_depth_m"])
        amplitude = abs(float(parameters["amplitude_m"]))
        return bool(
            center + amplitude >= float(depth_start)
            and center - amplitude <= float(depth_end)
        )

    def _associate_boundary_candidates(
        self,
        request,
        context,
        rendered,
        carried,
        current,
    ):
        input_candidates = list(carried) + list(current)
        associated, diagnostics = self.complete_workflow.associate_annotations_across_windows(
            request,
            context,
            rendered,
            input_candidates,
        )
        carried_ids = {str(item.get("candidate_id")) for item in carried}
        current_ids = {str(item.get("candidate_id")) for item in current}
        merged = []
        passthrough = []
        for annotation in associated:
            source_ids = {
                str(value) for value in annotation.get("associated_candidate_ids") or []
            }
            if source_ids & carried_ids and source_ids & current_ids:
                merged.append(annotation)
            else:
                passthrough.append(annotation)

        review_discards = []
        audited_merged = []
        if merged:
            reviewed, review_discards = self.complete_workflow.review_annotations_after_association(
                request,
                context,
                rendered,
                merged,
            )
            audit_result = self.complete_workflow._audit_staged_candidates(
                request,
                context,
                rendered,
                reviewed,
            )
            audited_merged = list(audit_result.get("kept") or [])
            review_discards = list(review_discards) + list(audit_result.get("discarded") or [])
        output = passthrough + audited_merged
        output.sort(key=lambda item: float(item.get("offset", 0.0)))
        record = {
            "input_carried_candidate_ids": sorted(carried_ids),
            "input_current_candidate_ids": sorted(current_ids),
            "merged_candidate_ids": [item.get("candidate_id") for item in audited_merged],
            "association": diagnostics,
            "review_discarded_count": len(review_discards),
        }
        return output, record, review_discards

    @staticmethod
    def _remap_batch_discard(discard, window_offset, batch_index):
        item = copy.deepcopy(discard)
        for key in (
            "candidate_id",
            "matching_candidate_id",
            "supporting_candidate_id",
        ):
            if item.get(key):
                item[key] = _offset_window_identity(item[key], window_offset)
        item["processing_batch_index"] = int(batch_index)
        return item

    @classmethod
    def _remap_batch_diagnostics(cls, diagnostics, window_offset):
        window_index_keys = {
            "primary_index",
            "sliding_window_index",
            "source_window_index",
            "ownership_fallback_source_window",
        }
        window_index_list_keys = {
            "ownership_support_window_indices",
            "source_window_indices",
        }

        def remap(value, key=None):
            if isinstance(value, dict):
                return {child_key: remap(child, child_key) for child_key, child in value.items()}
            if isinstance(value, list):
                if key in window_index_list_keys:
                    return [int(child) + int(window_offset) for child in value]
                return [remap(child) for child in value]
            if isinstance(value, tuple):
                return tuple(remap(child) for child in value)
            if isinstance(value, str):
                return _offset_window_identity(value, window_offset)
            if key in window_index_keys and value is not None:
                return int(value) + int(window_offset)
            return value

        return remap(copy.deepcopy(diagnostics or {}))

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
            "max_retries": 0,
        }
        if str(config.get("base_url") or "").strip():
            kwargs["base_url"] = config["base_url"]
        return openai.OpenAI(**kwargs)

    def _reset_request_metrics(self):
        self._request_metrics = {
            "visual_call_count": 0,
            "api_attempt_count": 0,
            "structured_output_fallback_count": 0,
            "calls": [],
        }

    def request_metrics_snapshot(self):
        return copy.deepcopy(self._request_metrics)

    @staticmethod
    def _message_image_hashes(messages):
        hashes = []
        for message in messages or []:
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "image_url":
                    continue
                value = item.get("image_url") or {}
                url = value.get("url") if isinstance(value, dict) else value
                raw = str(url or "").split(",", 1)[-1]
                try:
                    data = base64.b64decode(raw)
                except (TypeError, ValueError):
                    data = raw.encode("utf-8")
                hashes.append(hashlib.sha256(data).hexdigest())
        return hashes

    def _request(self, client, model, messages, response_schema=None):
        if response_schema is None:
            raise ValueError("A structured response schema is required")
        call_record = {
            "index": int(self._request_metrics["visual_call_count"]) + 1,
            "model": str(model),
            "schema": str(response_schema.get("name") or ""),
            "image_hashes": self._message_image_hashes(messages),
            "structured_output_supported": True,
        }
        self._request_metrics["visual_call_count"] += 1
        self._request_metrics["calls"].append(call_record)
        params = {
            "model": model,
            "messages": messages,
            "stream": False,
            "response_format": {
                "type": "json_schema",
                "json_schema": response_schema,
            },
        }

        def create():
            self._request_metrics["api_attempt_count"] += 1
            return client.chat.completions.create(**params)

        try:
            return create()
        except Exception as exc:
            message = str(exc).lower()
            if not any(term in message for term in (
                "response_format", "json_schema", "structured output",
            )):
                raise exc
            params["response_format"] = {"type": "json_object"}
            call_record["structured_output_supported"] = False
            self._request_metrics["structured_output_fallback_count"] += 1
            return create()

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
