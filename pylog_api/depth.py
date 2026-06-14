"""Depth helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

import numpy as np

from scripts.utils.well_queries import get_depth_data_for_well, resolve_optional_db_path_for_well, resolve_well_id


def get_depth_data(well: Union[str, int], folder: Optional[str] = None, db_path: Optional[str] = None) -> Union[np.ndarray, Dict[str, Any]]:
    """Return the best available depth curve for a well or folder."""
    db_path, resolution_error = resolve_optional_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    from scripts.data.db_manager import DBManager

    db = DBManager(db_path)
    well_id, error_info = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error_info}

    depth_res = get_depth_data_for_well(db, well_id, folder=folder)
    if not depth_res.get("ok"):
        return {
            "ok": False,
            "error": depth_res.get("error", f"No depth curve (DEPT/DEPTH) found in well {well}."),
        }
    return depth_res["data"]
