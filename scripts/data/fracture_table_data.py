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


def format_fracture_table_value(value):
    try:
        number = float(value)
    except Exception:
        return ""
    return f"{number:.3f}" if math.isfinite(number) else ""


def fracture_table_headers_for(annotations):
    depth_unit = ""
    for annotation in annotations or []:
        depth_unit = str(annotation.get("depth_unit") or "").strip()
        if depth_unit:
            break
    if not depth_unit:
        return list(FRACTURE_TABLE_HEADERS)
    headers = list(FRACTURE_TABLE_HEADERS)
    headers[0] = f"Center Depth ({depth_unit})"
    headers[2] = f"Dip Height ({depth_unit})"
    return headers


def fracture_annotation_to_table_row(annotation):
    return [
        format_fracture_table_value(annotation.get("center_depth", annotation.get("offset"))),
        annotation.get("fracture_type", ""),
        format_fracture_table_value(annotation.get("dip_height", annotation.get("amplitude"))),
        format_fracture_table_value(annotation.get("image_azimuth")),
        format_fracture_table_value(annotation.get("apparent_dip")),
        annotation.get("source_curve_name") or annotation.get("source_track_label") or "",
    ]


def build_fracture_table_data(annotations):
    annotations = list(annotations or [])
    return fracture_table_headers_for(annotations), [
        fracture_annotation_to_table_row(annotation)
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
