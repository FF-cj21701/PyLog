import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
from mcp.server.fastmcp import FastMCP


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pylog_api.analysis import analyze_data as packaged_analyze_data
from pylog_api import apply_curve_style as packaged_apply_curve_style
from pylog_api import apply_track_style as packaged_apply_track_style
from pylog_api import add_curve_to_plot as packaged_add_curve_to_plot
from pylog_api import create_plot as packaged_create_plot
from pylog_api.data_access import get_curve_info as packaged_get_curve_info
from pylog_api.data_access import list_curves as packaged_list_curves
from pylog_api import remove_curve_from_plot as packaged_remove_curve_from_plot
from pylog_api import remove_track_from_plot as packaged_remove_track_from_plot
from pylog_api import update_plot as packaged_update_plot
from pylog_api.well_info import get_well_info as packaged_get_well_info
from scripts.data.db_manager import DBManager
from scripts.utils.curve_resolution import resolve_curve_row
from scripts.utils.well_queries import (
    build_folder_map,
    list_project_wells,
    resolve_optional_db_path_for_well,
    resolve_well_id,
)


API_METADATA = {
    "list_databases": "List all project databases under data/.",
    "list_wells": "List wells in one database, or across all project databases if db_path is omitted.",
    "get_well_info": "Return folders and curves for one well.",
    "list_curves": "List curve metadata for a well.",
    "get_curve_info": "Get metadata for one curve, supports folder-qualified names like FRAME0/GR.",
    "get_curve_samples": "Read a bounded slice of curve values; intended for MCP-safe payloads.",
    "analyze_curve": "Compute summary statistics for a curve.",
    "analyze_values": "Compute summary statistics for an input list of numeric values.",
    "create_plot": "Create a plot window from a normalized plot spec.",
    "update_plot": "Apply plot update commands such as curve style or track style updates.",
    "apply_curve_style": "Apply style settings to one curve in a plot window.",
    "apply_track_style": "Apply settings to one track in a plot window.",
    "add_curve_to_plot": "Add one curve to an existing track or create a new track in a plot window.",
    "remove_curve_from_plot": "Remove one curve from a plot window.",
    "remove_track_from_plot": "Remove one track from a plot window.",
}


mcp = FastMCP(
    name="PyLog MCP",
    instructions=(
        "MCP server for PyLog well databases. "
        "Use it to discover databases, inspect wells and curves, "
        "read bounded curve samples, and run basic statistical analysis."
    ),
)


def _project_data_dir() -> Path:
    return ROOT_DIR / "data"


def _resolve_db_path(db_path: str | None) -> str | None:
    if not db_path:
        return None
    path = Path(db_path)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return str(path.resolve())


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return value

def _get_db(db_path: str) -> DBManager:
    return DBManager(db_path)


def _list_db_files() -> list[Path]:
    data_dir = _project_data_dir()
    if not data_dir.exists():
        return []
    return sorted(data_dir.glob("*.db"))


def _resolve_db_path_for_well(well: str | int, db_path: str | None = None) -> tuple[str | None, dict[str, Any] | None]:
    resolved = _resolve_db_path(db_path)
    if resolved:
        return resolved, None
    return resolve_optional_db_path_for_well(well, data_dir=_project_data_dir())


def _analyze_array(values: Any, force_full: bool = False) -> dict[str, Any]:
    result = packaged_analyze_data(values, force_full=force_full)
    if not result.get("ok", True):
        return result

    normalized = dict(result)
    if "shape" in normalized and not isinstance(normalized["shape"], list):
        normalized["shape"] = list(normalized["shape"])
    if "finite" in normalized and "finite_count" not in normalized:
        normalized["finite_count"] = normalized["finite"]
    return normalized


def _bounded_curve_slice(values: Any, offset: int = 0, limit: int = 200) -> dict[str, Any]:
    total = int(values.shape[0]) if hasattr(values, "shape") and values.shape else int(len(values))
    start = max(0, int(offset))
    size = max(1, min(int(limit), 5000))
    end = min(total, start + size)
    sliced = np.asarray(values[start:end])

    result: dict[str, Any] = {
        "ok": True,
        "shape": list(getattr(values, "shape", sliced.shape)),
        "dtype": str(getattr(values, "dtype", sliced.dtype)),
        "total_points": total,
        "offset": start,
        "limit": size,
        "returned_points": int(sliced.shape[0]) if sliced.ndim > 0 else int(sliced.size),
        "values": _json_safe(sliced),
    }

    if hasattr(values, "min") and hasattr(values, "max"):
        result["min"] = float(values.min())
        result["max"] = float(values.max())
    elif sliced.size > 0 and np.issubdtype(sliced.dtype, np.number):
        result["min"] = float(np.nanmin(sliced))
        result["max"] = float(np.nanmax(sliced))

    return result


@mcp.tool()
def ping() -> dict[str, Any]:
    return {"ok": True, "server": "PyLog MCP"}


@mcp.tool()
def list_databases() -> dict[str, Any]:
    databases = []
    for db_file in _list_db_files():
        h5_file = db_file.with_suffix(".h5")
        databases.append(
            {
                "name": db_file.name,
                "db_path": str(db_file.resolve()),
                "h5_exists": h5_file.exists(),
                "h5_path": str(h5_file.resolve()) if h5_file.exists() else None,
            }
        )
    return {"ok": True, "databases": databases}


@mcp.tool()
def inspect_api(name: str | None = None) -> dict[str, Any]:
    if not name:
        return {"ok": True, "apis": API_METADATA}
    description = API_METADATA.get(name)
    if not description:
        return {"ok": False, "error": f"Unknown API '{name}'.", "apis": sorted(API_METADATA)}
    return {"ok": True, "name": name, "description": description}


@mcp.tool()
def list_wells(db_path: str | None = None) -> dict[str, Any]:
    resolved = _resolve_db_path(db_path)
    if resolved:
        db = _get_db(resolved)
        return {"ok": True, "wells": [(wid, name, resolved) for wid, name in db.get_wells()]}
    return list_project_wells(data_dir=_project_data_dir())


@mcp.tool()
def get_well_info(well: str, db_path: str | None = None) -> dict[str, Any]:
    resolved, resolution_error = _resolve_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error
    return packaged_get_well_info(well, db_path=resolved)


@mcp.tool()
def list_curves(well: str, db_path: str | None = None) -> dict[str, Any]:
    resolved, resolution_error = _resolve_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error
    return packaged_list_curves(well, db_path=resolved)


@mcp.tool()
def get_curve_info(well: str, curve_name: str, db_path: str | None = None) -> dict[str, Any]:
    resolved, resolution_error = _resolve_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error
    return packaged_get_curve_info(well, curve_name, db_path=resolved)


@mcp.tool()
def get_curve_samples(
    well: str,
    curve_name: str,
    db_path: str,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    resolved = _resolve_db_path(db_path)
    if not resolved:
        return {"ok": False, "error": "db_path is required."}

    db = _get_db(resolved)
    well_id, error = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error}

    curves = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)
    resolved_curve = resolve_curve_row(curve_name, curves, folder_map)
    if not resolved_curve.get("ok"):
        return resolved_curve

    values = db.get_curve_data(resolved_curve["row"][0])
    if values is None:
        return {"ok": False, "error": f"Failed to load curve data for '{curve_name}'."}
    return _bounded_curve_slice(values, offset=offset, limit=limit)


@mcp.tool()
def analyze_curve(well: str, curve_name: str, db_path: str | None = None, force_full: bool = False) -> dict[str, Any]:
    resolved, resolution_error = _resolve_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    db = _get_db(resolved)
    well_id, error = resolve_well_id(db, well)
    if well_id is None:
        return {"ok": False, **error}

    curves = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)
    resolved_curve = resolve_curve_row(curve_name, curves, folder_map)
    if not resolved_curve.get("ok"):
        return resolved_curve

    values = db.get_curve_data(resolved_curve["row"][0])
    if values is None:
        return {"ok": False, "error": f"Failed to load curve data for '{curve_name}'."}
    result = _analyze_array(values, force_full=force_full)
    result["curve_name"] = curve_name
    result["well"] = well
    result["db_path"] = resolved
    return result


@mcp.tool()
def analyze_values(values: list[float], force_full: bool = False) -> dict[str, Any]:
    return _analyze_array(values, force_full=force_full)


@mcp.tool()
def create_plot(plot_spec: dict[str, Any]) -> dict[str, Any]:
    return packaged_create_plot(_json_safe(plot_spec))


@mcp.tool()
def update_plot(window_id: str | None = None, commands: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return packaged_update_plot(window_id=window_id, commands=_json_safe(commands or []))


@mcp.tool()
def apply_curve_style(window_id: str, track: str | int, curve: str | int, settings: dict[str, Any]) -> dict[str, Any]:
    return packaged_apply_curve_style(window_id, track, curve, _json_safe(settings))


@mcp.tool()
def apply_track_style(window_id: str, track: str | int, settings: dict[str, Any]) -> dict[str, Any]:
    return packaged_apply_track_style(window_id, track, _json_safe(settings))


@mcp.tool()
def add_curve_to_plot(
    window_id: str,
    well_id: int,
    curve_id: int,
    track: str | int | None = None,
    db_path: str | None = None,
    curve_settings: dict[str, Any] | None = None,
    track_name: str | None = None,
    track_width: int = 200,
    header_visible: bool = True,
    track_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return packaged_add_curve_to_plot(
        window_id,
        well_id=well_id,
        curve_id=curve_id,
        track=track,
        db_path=db_path,
        curve_settings=_json_safe(curve_settings or {}),
        track_name=track_name,
        track_width=track_width,
        header_visible=header_visible,
        track_settings=_json_safe(track_settings or {}),
    )


@mcp.tool()
def remove_curve_from_plot(window_id: str, track: str | int, curve: str | int) -> dict[str, Any]:
    return packaged_remove_curve_from_plot(window_id, track, curve)


@mcp.tool()
def remove_track_from_plot(window_id: str, track: str | int) -> dict[str, Any]:
    return packaged_remove_track_from_plot(window_id, track)


if __name__ == "__main__":
    os.chdir(ROOT_DIR)
    mcp.run(transport="stdio")
