"""Stable API metadata registry for the packaged ``pylog_api`` surface."""

from __future__ import annotations

from typing import Any, Dict


API_METADATA: Dict[str, Dict[str, Any]] = {
    "plot": {
        "name": "plot",
        "signature": "plot(well=None, curves=None, data_list=None, db_path=None, title='Log Plot 1', ...)",
        "description": "Unified plotting API. Mode A (DB): well + curves. Mode B (Memory): data_list. Smart-depth enabled.",
        "parameters": {
            "well": {"type": "str/int", "description": "Well Name/ID. Optional if data_list has depth."},
            "curves": {"type": "List[str]", "description": "Names of curves in DB to plot."},
            "data_list": {"type": "List[Dict]", "description": "Memory curves: [{'values':[], 'depth':[], 'name':''}, ...]"},
            "db_path": {"type": "str", "optional": True},
            "accum_fill": {"type": "bool", "default": False},
        },
    },
    "save_curve": {
        "name": "save_curve",
        "signature": "save_curve(well, curve_name, values, unit='', folder=None, db_path=None)",
        "description": "Saves a calculated curve into the well database (HDF5 + Metadata).",
        "parameters": {
            "well": {"type": "str/int", "required": True},
            "curve_name": {"type": "str", "required": True},
            "values": {"type": "array-like", "required": True},
            "unit": {"type": "str", "default": "''"},
            "folder": {"type": "str", "optional": True, "description": "e.g. 'FRAME0'"},
            "db_path": {"type": "str", "required": False},
        },
    },
    "get_depth_data": {
        "name": "get_depth_data",
        "signature": "get_depth_data(well, folder=None, db_path=None)",
        "description": "Automatically finds and returns the best depth curve for a well or specific folder.",
        "parameters": {
            "well": {"type": "str/int", "required": True},
            "folder": {"type": "str", "optional": True},
            "db_path": {"type": "str", "required": False},
        },
    },
    "get_well_info": {
        "name": "get_well_info",
        "signature": "get_well_info(well, db_path=None)",
        "description": "Get detailed metadata, folders, and curves for a well.",
        "parameters": {
            "well": {"type": "Union[str, int]", "required": True},
            "db_path": {"type": "str", "required": False},
        },
        "returns": "Dict with 'ok', 'id', 'name', 'folders', 'curves' or 'error/suggestions'.",
    },
    "analyze_data": {
        "name": "analyze_data",
        "signature": "analyze_data(values)",
        "description": "Analyze numerical values and return statistics.",
        "parameters": {"values": {"type": "array-like"}},
    },
    "analyze_curve": {
        "name": "analyze_curve",
        "signature": "analyze_curve(well, curve_name, db_path=None)",
        "description": "High-level API to fetch curve data and perform statistical analysis in one call.",
        "parameters": {
            "well": {"type": "Union[str, int]", "required": True},
            "curve_name": {"type": "str", "required": True},
            "db_path": {"type": "str", "required": False},
        },
        "returns": "Analysis result dict (with 'ok', 'total_points', 'analysis').",
    },
    "list_wells": {
        "name": "list_wells",
        "signature": "list_wells(db_path=None)",
        "description": "Retrieve all wells in a database.",
        "parameters": {"db_path": {"type": "str", "required": False, "default": "None (auto-resolve)"}},
        "returns": "Dict with 'ok', 'wells' (List[Tuple[int, str]]), or 'error'.",
    },
    "list_curves": {
        "name": "list_curves",
        "signature": "list_curves(well, db_path=None)",
        "description": "List all curves metadata (id, name, unit, folder, range) for a specific well.",
        "parameters": {
            "well": {"type": "Union[str, int]", "required": True},
            "db_path": {"type": "str", "required": False},
        },
        "returns": "Dict with 'ok', 'curves' (list of metadata dicts including 'folder' name) or 'error'.",
    },
    "get_curve_info": {
        "name": "get_curve_info",
        "signature": "get_curve_info(well, curve_name, db_path=None)",
        "description": "Get metadata (unit, folder, range, shape) for a specific curve.",
        "parameters": {
            "well": {"type": "Union[str, int]", "required": True},
            "curve_name": {"type": "str", "required": True},
            "db_path": {"type": "str", "required": False},
        },
        "returns": "Dict with 'ok', 'id', 'name', 'folder', 'unit', 'shape', 'min', 'max' or 'error'.",
    },
    "get_curve_data": {
        "name": "get_curve_data",
        "signature": "get_curve_data(well, curve_name, db_path=None)",
        "description": "Retrieve raw numeric data for a specific curve. Use for analysis or custom plotting.",
        "parameters": {
            "well": {"type": "Union[str, int]", "required": True},
            "curve_name": {"type": "str", "required": True},
            "db_path": {"type": "str", "required": False},
        },
        "returns": "numpy.ndarray on success, or structured error Dict (with 'ok': False).",
    },
    "analyze": {
        "name": "analyze",
        "signature": "analyze(values, force_full=False)",
        "description": "Statistical analysis (min, max, mean, std, percentiles) for arrays.",
        "parameters": {
            "values": {"type": "array", "required": True},
            "force_full": {"type": "bool", "default": "False"},
        },
    },
}

