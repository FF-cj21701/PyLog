import threading
from collections import OrderedDict
from typing import Optional

import numpy as np
from PySide6.QtGui import QColor

from core.app_config import app_config
from ..data.db_manager import DBManager
from .logger import logger
from .plot_style_utils import DEFAULT_IMAGE_CMAP, DEFAULT_NULL_COLOR, normalize_curve_plot_style
from .well_queries import build_folder_map, get_depth_data_for_well


MAX_DEPTH_CACHE_ITEMS = 32
DEPTH_CACHE = OrderedDict()
DEPTH_LOCK = threading.Lock()


def clear_depth_cache():
    """Clear the shared depth cache used across plot loads."""
    with DEPTH_LOCK:
        DEPTH_CACHE.clear()


def _find_curve_row(curves, curve_id):
    for row in curves:
        if row[0] == curve_id:
            return row
    return None


def _resolve_depth_for_curve(local_db, well_id, curve_id, curves, target_len):
    source_curve = _find_curve_row(curves, curve_id)
    source_folder_id = source_curve[4] if source_curve and len(source_curve) > 4 else None
    folder_map = build_folder_map(local_db, well_id)
    source_folder = folder_map.get(source_folder_id)

    depth_res = get_depth_data_for_well(local_db, well_id, folder=source_folder)
    if not depth_res.get("ok"):
        return None, None, depth_res.get("error")
    depth_data = depth_res["data"]
    best_match = depth_res["row"]

    if len(depth_data) != target_len:
        depth_candidates = [
            row for row in curves
            if str(row[1]).upper() in ("DEPT", "TDEP", "DEPTH", "MDEPT")
        ]
        in_folder_candidates = [row for row in depth_candidates if row[4] == source_folder_id]
        other_candidates = [row for row in depth_candidates if row[4] != source_folder_id]
        sorted_candidates = in_folder_candidates + other_candidates
        for candidate in sorted_candidates:
            temp_depth = local_db.get_curve_data(candidate[0])
            if temp_depth is not None and len(temp_depth) == target_len:
                depth_data = temp_depth
                best_match = candidate
                break

    if depth_data is None:
        return None, None, "Could not load depth data from candidate curve."

    cache_key = (local_db.db_path, best_match[0])
    with DEPTH_LOCK:
        if cache_key in DEPTH_CACHE:
            depth_data = DEPTH_CACHE[cache_key]
            DEPTH_CACHE.move_to_end(cache_key)
        else:
            if not isinstance(depth_data, np.ndarray):
                depth_data = np.array(depth_data)
            DEPTH_CACHE[cache_key] = depth_data
            while len(DEPTH_CACHE) > MAX_DEPTH_CACHE_ITEMS:
                evicted_key, _ = DEPTH_CACHE.popitem(last=False)
                logger.debug(f"Evicted depth cache entry: {evicted_key}")

    return depth_data, best_match, None


def _resolve_well_name(local_db, well_id):
    for candidate_id, name in local_db.get_wells():
        if candidate_id == well_id:
            return name
    return "Unknown"


def load_curve_bundle_for_plot(
    db_path,
    well_id,
    curve_id,
    *,
    preferences=None,
    db: Optional[DBManager] = None,
):
    """Load data/depth/info for plotting using the same rules as manual drag/drop."""
    local_db = db or DBManager(db_path, ensure_schema=False)
    prefs = preferences or {}

    curves = local_db.get_curves(well_id)
    curve_data = local_db.get_curve_data(curve_id)
    if curve_data is None:
        return {"ok": False, "error": f"Failed to load curve data for ID: {curve_id}"}

    depth_data, depth_row, error = _resolve_depth_for_curve(
        local_db,
        well_id,
        curve_id,
        curves,
        len(curve_data),
    )
    if error:
        return {"ok": False, "error": error}

    if len(curve_data) != len(depth_data):
        min_len = min(len(curve_data), len(depth_data))
        logger.warning(f"Data/Depth length mismatch ({len(curve_data)} vs {len(depth_data)}). Aligning to {min_len} for {curve_id}")
        curve_data = curve_data[:min_len]
        depth_data = depth_data[:min_len]

    curve_row = _find_curve_row(curves, curve_id)
    curve_name = curve_row[1] if curve_row else "Unknown"
    curve_unit = curve_row[2] if curve_row else ""
    depth_unit = depth_row[2] if depth_row and len(depth_row) > 2 else ""
    val_min = curve_row[5] if curve_row and len(curve_row) > 5 and curve_row[5] is not None else 0.0
    val_max = curve_row[6] if curve_row and len(curve_row) > 6 and curve_row[6] is not None else 100.0
    is_image = getattr(curve_data, "ndim", 1) > 1

    color = app_config.get_theme_color("text_main")
    if not is_image:
        color = QColor.fromHsv(np.random.randint(0, 360), 255, 150).name()

    info = normalize_curve_plot_style(
        {
            "well_id": well_id,
            "curve_id": curve_id,
            "name": curve_name,
            "unit": curve_unit,
            "depth_unit": depth_unit,
            "is_image": is_image,
            "color": color,
            "line_width": 1.0,
            "null_color": prefs.get("null_color", DEFAULT_NULL_COLOR),
            "cmap": prefs.get("cmap", DEFAULT_IMAGE_CMAP),
            "db_path": db_path,
            "well_name": _resolve_well_name(local_db, well_id),
            "min": val_min,
            "max": val_max,
        }
    )

    return {
        "ok": True,
        "data": curve_data,
        "depth": depth_data,
        "info": info,
        "rgb_full": None,
    }
