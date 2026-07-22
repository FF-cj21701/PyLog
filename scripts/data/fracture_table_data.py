import math

from scripts.data.db_manager import DBManager


FRACTURE_TABLE_TITLE = "Fracture Picks"
FRACTURE_TABLE_TYPE = "fracture_table"
FRACTURE_TABLE_HEADERS = [
    "Center Depth",
    "Type",
    "Dip Height",
    "Image Azimuth (deg)",
    "Apparent Dip (deg)",
    "Source",
]
AI_EVIDENCE_HEADERS = [
    "Evidence ID",
    "AI Status",
    "AI Confidence",
    "Source Windows",
    "Source Candidates",
    "Evidence Summary",
]


def format_fracture_table_value(value):
    try:
        number = float(value)
    except Exception:
        return ""
    return f"{number:.3f}" if math.isfinite(number) else ""


def _has_ai_evidence(annotation):
    return any(annotation.get(key) not in (None, "", [], {}) for key in (
        "evidence_id",
        "source_window_indices",
        "source_candidate_ids",
        "confidence",
        "ai_review_confidence",
        "needs_review",
        "decision_state",
        "cross_window_corroboration",
        "local_completeness",
    ))


def _format_sequence(values):
    if values in (None, ""):
        return ""
    if not isinstance(values, (list, tuple, set)):
        values = [values]
    clean = [str(value) for value in values if value not in (None, "")]
    return ", ".join(clean)


def _format_ai_status(annotation):
    if annotation.get("needs_review"):
        return "Needs review"
    state = str(annotation.get("decision_state") or "").strip()
    if state:
        return state.replace("_", " ").title()
    status = str(annotation.get("ai_alignment_status") or annotation.get("batch_audit_status") or "").strip()
    return status.replace("_", " ").title() if status else ""


def _format_ai_confidence(annotation):
    value = annotation.get("ai_review_confidence", annotation.get("confidence"))
    try:
        number = float(value)
    except Exception:
        return ""
    if not math.isfinite(number):
        return ""
    if 0.0 <= number <= 1.0:
        return f"{number:.2f}"
    return f"{number:.1f}"


def _format_evidence_summary(annotation):
    parts = []
    local = annotation.get("local_completeness") or {}
    if isinstance(local, dict) and local.get("available"):
        parts.append("local complete" if local.get("complete") else "local incomplete")
    corroboration = annotation.get("cross_window_corroboration") or {}
    if isinstance(corroboration, dict):
        try:
            support_count = int(corroboration.get("support_count", 0) or 0)
        except Exception:
            support_count = 0
        if support_count:
            fit_status = "fit ok" if corroboration.get("fit_acceptable") is True else "fit uncertain"
            parts.append(f"{support_count} window support; {fit_status}")
    reason = (
        annotation.get("ai_review_conflict_reason")
        or annotation.get("candidate_continuity_reason")
        or annotation.get("continuity_reason")
    )
    if reason:
        parts.append(str(reason))
    return " | ".join(parts)


def fracture_table_headers_for(annotations):
    depth_unit = ""
    for annotation in annotations or []:
        depth_unit = str(annotation.get("depth_unit") or "").strip()
        if depth_unit:
            break
    headers = list(FRACTURE_TABLE_HEADERS)
    if depth_unit:
        headers[0] = f"Center Depth ({depth_unit})"
        headers[2] = f"Dip Height ({depth_unit})"
    if any(_has_ai_evidence(annotation) for annotation in annotations or []):
        headers.extend(AI_EVIDENCE_HEADERS)
    return headers


def fracture_annotation_to_table_row(annotation, *, include_ai_evidence=False):
    row = [
        format_fracture_table_value(annotation.get("center_depth", annotation.get("offset"))),
        annotation.get("fracture_type", ""),
        format_fracture_table_value(annotation.get("dip_height", annotation.get("amplitude"))),
        format_fracture_table_value(annotation.get("image_azimuth")),
        format_fracture_table_value(annotation.get("apparent_dip")),
        annotation.get("source_curve_name") or annotation.get("source_track_label") or "",
    ]
    if include_ai_evidence:
        row.extend([
            annotation.get("evidence_id") or "",
            _format_ai_status(annotation),
            _format_ai_confidence(annotation),
            _format_sequence(annotation.get("source_window_indices")),
            _format_sequence(annotation.get("source_candidate_ids")),
            _format_evidence_summary(annotation),
        ])
    return row


def build_fracture_table_data(annotations):
    annotations = list(annotations or [])
    include_ai_evidence = any(_has_ai_evidence(annotation) for annotation in annotations)
    return fracture_table_headers_for(annotations), [
        fracture_annotation_to_table_row(annotation, include_ai_evidence=include_ai_evidence)
        for annotation in annotations
    ]


def load_fracture_table_data(db_path, well_id):
    annotations = DBManager(db_path).get_fracture_interpretations(well_id)
    headers, rows = build_fracture_table_data(annotations)
    return annotations, headers, rows


def fracture_table_metadata(db_path, well_id):
    return {
        "type": FRACTURE_TABLE_TYPE,
        "db_path": db_path,
        "well_id": int(well_id),
    }
