"""Well-discovery helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from scripts.utils.well_metadata import get_well_info_snapshot
from scripts.utils.well_queries import list_project_wells, resolve_optional_db_path_for_well, resolve_well_id


def list_wells(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve all wells from an explicit database or from the project scan."""
    return list_project_wells(db_path=db_path)


def get_well_info(well: Union[str, int], db_path: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve detailed metadata for a specific well."""
    db_path, resolution_error = resolve_optional_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    from scripts.data.db_manager import DBManager

    db = DBManager(db_path)
    well_id, error_info = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error_info}
    return get_well_info_snapshot(db, db_path, well_id)
