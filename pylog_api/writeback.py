"""Writeback helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

import numpy as np

from scripts.utils.logger import logger
from scripts.utils.well_queries import get_active_db_path, resolve_folder_id, resolve_well_id


def save_curve(
    well: Union[str, int],
    curve_name: str,
    values: Any,
    unit: str = "",
    folder: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Save a curve into the well database."""
    db_path = db_path or get_active_db_path()
    if not db_path:
        return {"ok": False, "error": "No active database found."}

    try:
        from scripts.data.db_manager import DBManager

        db = DBManager(db_path)
        well_id, error_info = resolve_well_id(db, well)
        if well_id is None:
            return {"ok": False, **error_info}

        folder_id = resolve_folder_id(db, well_id, folder)
        data_arr = np.asarray(values)
        db.save_curve(well_id, curve_name, unit, data_arr, folder_id)

        return {
            "ok": True,
            "message": f"Successfully saved curve '{curve_name}' to well '{well}'.",
            "info": {
                "well": well,
                "curve": curve_name,
                "folder": folder or "Root",
                "length": len(data_arr),
            },
        }
    except Exception as exc:
        logger.error(f"Error in save_curve: {exc}")
        return {"ok": False, "error": str(exc)}
