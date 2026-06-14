"""Data-access helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

import numpy as np

from scripts.utils.curve_resolution import curve_row_to_dict, resolve_curve_row
from scripts.utils.well_queries import build_folder_map, resolve_optional_db_path_for_well, resolve_well_id


def list_curves(well: Union[str, int], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve the list of curves available in a specific well."""
    db_path, resolution_error = resolve_optional_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    from scripts.data.db_manager import DBManager

    db = DBManager(db_path)
    well_id, error_info = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error_info}

    curves = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)

    return {
        "ok": True,
        "curves": [curve_row_to_dict(row, folder_map) for row in curves],
    }


def get_curve_info(
    well: Union[str, int],
    curve_name: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve metadata for a specific curve, supporting folder-path disambiguation."""
    db_path, resolution_error = resolve_optional_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    from scripts.data.db_manager import DBManager

    db = DBManager(db_path)
    well_id, error_info = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error_info}

    curves = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)

    resolved = resolve_curve_row(curve_name, curves, folder_map)
    if resolved.get("ok"):
        return curve_row_to_dict(resolved["row"], folder_map)

    if resolved.get("error_code") == "curve_not_found":
        resolved["action_hint"] = f"Did you mean one of these? Or use get_well_info('{well}') to see folder hierarchy."
    return resolved


def get_curve_data(
    well: Union[str, int],
    curve_name: str,
    db_path: Optional[str] = None,
) -> Union[np.ndarray, Dict[str, Any]]:
    """Retrieve numeric data for a curve, including folder-path disambiguation."""
    db_path, resolution_error = resolve_optional_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    from scripts.data.db_manager import DBManager

    db = DBManager(db_path)
    well_id, error_info = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error_info}

    curves = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)

    resolved = resolve_curve_row(curve_name, curves, folder_map)
    if resolved.get("ok"):
        target_cid = resolved["row"][0]
        data = db.get_curve_data(target_cid)
        if data is None:
            return {"ok": False, "error": f"Failed to load data for ID {target_cid}"}
        return data
    if resolved.get("error_code") == "curve_ambiguous":
        resolved["error"] = f"Curve '{curve_name}' is ambiguous."
        resolved["action_hint"] = "Please use folder path like 'FRAME0/GR'."
    return resolved
