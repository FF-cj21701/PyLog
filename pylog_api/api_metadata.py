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
    "inspect_api": {
        "name": "inspect_api",
        "signature": "inspect_api(name)",
        "description": "Return machine-readable signature and parameter metadata for a public pylog_api function.",
        "parameters": {"name": {"type": "str", "required": True}},
        "returns": "Dict containing name, signature, description, parameters, and optional returns/examples.",
    },
    "create_plot": {
        "name": "create_plot",
        "signature": "create_plot(plot_spec)",
        "description": "Create a PyLog plot window from a normalized plot specification.",
        "parameters": {"plot_spec": {"type": "dict", "required": True}},
        "returns": "Dict with ok, title, and created_tracks on success.",
    },
    "update_plot": {
        "name": "update_plot",
        "signature": "update_plot(window_id=None, commands=None)",
        "description": "Apply one or more plot update commands to an existing plot window.",
        "parameters": {
            "window_id": {"type": "str", "required": False, "description": "Plot window title/id. Defaults to Log Plot 1."},
            "commands": {"type": "List[Dict]", "required": True},
        },
        "returns": "Dict with ok and update result details.",
    },
    "apply_curve_style": {
        "name": "apply_curve_style",
        "signature": "apply_curve_style(window_id, track, curve, settings)",
        "description": "Apply curve or image display style settings to a curve in a plot.",
        "parameters": {
            "window_id": {"type": "str", "required": True},
            "track": {"type": "str/int", "required": True},
            "curve": {"type": "str/int", "required": True},
            "settings": {"type": "dict", "required": True, "description": "Style settings such as color, line_width, cmap, min, max, invert, null_color."},
        },
    },
    "apply_track_style": {
        "name": "apply_track_style",
        "signature": "apply_track_style(window_id, track, settings)",
        "description": "Apply display settings to a plot track.",
        "parameters": {
            "window_id": {"type": "str", "required": True},
            "track": {"type": "str/int", "required": True},
            "settings": {"type": "dict", "required": True},
        },
    },
    "add_curve_to_plot": {
        "name": "add_curve_to_plot",
        "signature": "add_curve_to_plot(window_id, *, well_id, curve_id, track=None, db_path=None, curve_settings=None, track_name=None, track_width=200, header_visible=True, track_settings=None)",
        "description": "Add a database curve to an existing plot track, or create a new track in the plot.",
        "parameters": {
            "window_id": {"type": "str", "required": True},
            "well_id": {"type": "int", "required": True},
            "curve_id": {"type": "int", "required": True},
            "track": {"type": "str/int", "required": False},
            "db_path": {"type": "str", "required": False},
            "curve_settings": {"type": "dict", "required": False},
            "track_name": {"type": "str", "required": False},
            "track_width": {"type": "int", "default": 200},
            "header_visible": {"type": "bool", "default": True},
            "track_settings": {"type": "dict", "required": False},
        },
    },
    "remove_curve_from_plot": {
        "name": "remove_curve_from_plot",
        "signature": "remove_curve_from_plot(window_id, track, curve)",
        "description": "Remove a curve from a plot track.",
        "parameters": {
            "window_id": {"type": "str", "required": True},
            "track": {"type": "str/int", "required": True},
            "curve": {"type": "str/int", "required": True},
        },
    },
    "remove_track_from_plot": {
        "name": "remove_track_from_plot",
        "signature": "remove_track_from_plot(window_id, track)",
        "description": "Remove a track from a plot.",
        "parameters": {
            "window_id": {"type": "str", "required": True},
            "track": {"type": "str/int", "required": True},
        },
    },
    "plot_from_db": {
        "name": "plot_from_db",
        "signature": "plot_from_db(well, curves=None, db_path=None, curve_names=None, title='Log Plot 1', ...)",
        "description": "Plot curves directly from a database-backed well using packaged PyLog orchestration.",
        "parameters": {
            "well": {"type": "str/int", "required": True},
            "curves": {"type": "List[str]", "required": False},
            "curve_names": {"type": "List[str]", "required": False, "description": "Legacy alias for curves."},
            "db_path": {"type": "str", "required": False},
            "title": {"type": "str", "default": "Log Plot 1"},
        },
    },
    "plot_log_curves": {
        "name": "plot_log_curves",
        "signature": "plot_log_curves(data_list, title='Log Plot 1', accum_fill=False, ...)",
        "description": "Plot in-memory curve payloads into the PyLog UI.",
        "parameters": {
            "data_list": {"type": "List[Dict]", "required": True},
            "title": {"type": "str", "default": "Log Plot 1"},
            "accum_fill": {"type": "bool", "default": False},
        },
    },
    "plot_curves": {
        "name": "plot_curves",
        "signature": "plot_curves(*args, **kwargs)",
        "description": "Compatibility alias for curve plotting; prefer plot or plot_from_db for new scripts.",
        "parameters": {
            "args": {"type": "tuple", "required": False},
            "kwargs": {"type": "dict", "required": False},
        },
    },
}

