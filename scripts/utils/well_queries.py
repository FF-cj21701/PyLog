import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
from PySide6.QtWidgets import QApplication

from ..data.db_manager import DBManager


DEPTH_MNEMONICS = ("DEPT", "TDEP", "DEPTH", "MDEPT")


def get_active_db_path() -> Optional[str]:
    """Best-effort lookup of the currently active database in the running app."""
    app = QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            if hasattr(widget, "db_path") and widget.db_path:
                return widget.db_path

            if hasattr(widget, "db") and widget.db and hasattr(widget.db, "db_path"):
                return widget.db.db_path

            if hasattr(widget, "get_active_db"):
                try:
                    db = widget.get_active_db()
                    if db and hasattr(db, "db_path"):
                        return db.db_path
                except Exception:
                    pass
    return None


def list_project_db_files(data_dir: Optional[Union[str, Path]] = None) -> List[str]:
    """Return candidate project database files under the standard data directory."""
    base_dir = Path(data_dir) if data_dir is not None else Path("data")
    if not base_dir.exists():
        return []
    return [str(path.resolve()) for path in sorted(base_dir.glob("*.db"))]


def list_project_wells(
    db_path: Optional[str] = None,
    data_dir: Optional[Union[str, Path]] = None,
):
    if db_path:
        db = DBManager(db_path)
        return {"ok": True, "wells": [(wid, name, db_path) for (wid, name) in db.get_wells()]}

    all_wells = []
    app = QApplication.instance()
    if app:
        for widget in app.topLevelWidgets():
            if hasattr(widget, "get_all_well_info"):
                try:
                    wells_data = widget.get_all_well_info()
                    for item in wells_data:
                        all_wells.append((item["id"], item["name"], item["db_path"]))
                except Exception:
                    pass

    if not all_wells:
        for path in list_project_db_files(data_dir=data_dir):
            try:
                temp_db = DBManager(path)
                for wid, wname in temp_db.get_wells():
                    all_wells.append((wid, wname, path))
            except Exception:
                continue

    if not all_wells:
        return {"ok": False, "error": "No databases found in the data/ folder."}
    return {"ok": True, "wells": all_wells}


def resolve_optional_db_path_for_well(
    well: Union[str, int],
    db_path: Optional[str] = None,
    data_dir: Optional[Union[str, Path]] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Resolve db_path for a well via active project first, then project db scan."""
    if db_path:
        return db_path, None

    active_db_path = get_active_db_path()

    if active_db_path:
        try:
            active_db = DBManager(active_db_path)
            well_id, _error_info = resolve_well_id(active_db, well)
            if well_id is not None:
                return active_db_path, None
        except Exception:
            pass

    matches = []
    candidate_db_paths = list_project_db_files(data_dir=data_dir)
    for candidate in candidate_db_paths:
        try:
            db = DBManager(candidate)
            well_id, _error_info = resolve_well_id(db, well)
            if well_id is not None:
                matches.append(candidate)
        except Exception:
            continue

    if len(matches) == 1:
        return matches[0], None

    if len(matches) > 1:
        return None, {
            "ok": False,
            "error": (
                f"Well '{well}' exists in multiple databases. "
                "Please provide db_path explicitly."
            ),
            "candidate_db_paths": matches,
        }

    return None, {
        "ok": False,
        "error": (
            "No active project, and no unique database match was found for "
            f"well '{well}'. Please provide db_path explicitly."
        ),
        "candidate_db_paths": candidate_db_paths,
    }


def resolve_well_context(
    well: Union[str, int],
    db_path: Optional[str] = None,
    data_dir: Optional[Union[str, Path]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Resolve a well once into a stable execution context."""
    resolved_db_path, resolution_error = resolve_optional_db_path_for_well(
        well,
        db_path=db_path,
        data_dir=data_dir,
    )
    if resolution_error:
        return None, resolution_error

    db = DBManager(resolved_db_path)
    resolved_well_id, error_info = resolve_well_id(db, well)
    if resolved_well_id is None:
        return None, {"ok": False, **error_info}

    normalized_well_name = str(well)
    for candidate_id, candidate_name in db.get_wells():
        if candidate_id == resolved_well_id:
            normalized_well_name = str(candidate_name)
            break

    return {
        "resolved_db_path": resolved_db_path,
        "resolved_well_id": resolved_well_id,
        "well_name": normalized_well_name,
        "db": db,
    }, None


def build_folder_map(db: DBManager, well_id: int) -> Dict[int, str]:
    return {fid: fname for fid, fname, _fpid in db.get_folders(well_id)}


def resolve_folder_id(db: DBManager, well_id: int, folder: Optional[str]) -> Optional[int]:
    if not folder:
        return None

    folder_str = str(folder)
    folder_upper = folder_str.upper()
    for folder_id, folder_name, _parent_id in db.get_folders(well_id):
        if str(folder_name) == folder_str:
            return folder_id
    for folder_id, folder_name, _parent_id in db.get_folders(well_id):
        if str(folder_name).upper() == folder_upper:
            return folder_id
    return None


def resolve_well_id(db: DBManager, well: Union[str, int]) -> Tuple[Optional[int], Dict[str, str]]:
    if db is None:
        return None, {"error": "Database manager not initialized.", "action_hint": "Check your db_path."}

    wells = db.get_wells()
    if isinstance(well, int):
        for wid, _wname in wells:
            if wid == well:
                return wid, {}
        return None, {
            "error": f"Well ID {well} not found in current DB.",
            "suggestions": [str(wid) for (wid, _wname) in wells[:3]],
            "action_hint": "Use list_wells() to inspect available well IDs.",
        }

    well_str = str(well)
    for wid, wname in wells:
        if str(wname) == well_str:
            return wid, {}
    for wid, wname in wells:
        if str(wname).upper() == well_str.upper():
            return wid, {}

    import difflib
    well_names = [str(wname) for _wid, wname in wells]
    suggestions = difflib.get_close_matches(well_str, well_names, n=3, cutoff=0.5)
    return None, {
        "error": f"Well '{well}' not found.",
        "suggestions": suggestions,
        "action_hint": "Use list_wells() to inspect available well names.",
    }


def find_depth_curve_row(curves_rows, folder_map: Optional[Dict[int, str]] = None, folder: Optional[str] = None):
    folder_rows = curves_rows
    if folder:
        folder_upper = str(folder).upper()
        folder_rows = [row for row in curves_rows if str((folder_map or {}).get(row[4], "")).upper() == folder_upper]
        if folder_rows:
            preferred = _find_depth_curve_in_rows(folder_rows)
            if preferred is not None:
                return preferred
    return _find_depth_curve_in_rows(curves_rows)


def get_depth_data_for_well(db: DBManager, well_id: int, folder: Optional[str] = None):
    curves_rows = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)
    depth_row = find_depth_curve_row(curves_rows, folder_map=folder_map, folder=folder)
    if depth_row is None:
        return {
            "ok": False,
            "error": f"No depth curve (DEPT/DEPTH) found in well {well_id}.",
        }
    depth_data = db.get_curve_data(depth_row[0])
    if depth_data is None:
        return {"ok": False, "error": f"Failed to load depth data for curve ID {depth_row[0]}."}
    return {"ok": True, "data": depth_data, "row": depth_row, "folder_map": folder_map}


def _find_depth_curve_in_rows(curves_rows):
    for row in curves_rows:
        cid, name, _unit, _shape, _folder_id = row[:5]
        if str(name).upper() in DEPTH_MNEMONICS:
            return row
    for row in curves_rows:
        cid, name, _unit, _shape, _folder_id = row[:5]
        if "DEPT" in str(name).upper():
            return row
    return None
