"""Plotting helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Union

import numpy as np
from PySide6.QtCore import Qt

from .depth import get_depth_data
from scripts.services.plot_spec_service import build_plot_spec_from_manual_items, open_plot_from_spec, update_plot_from_commands
from scripts.utils.curve_loading import load_curve_bundle_for_plot
from scripts.utils.curve_resolution import resolve_curve_row
from scripts.utils.plot_style_utils import normalize_curve_plot_style, resolve_default_log_mode
from scripts.utils.plot_value_utils import compute_auto_display_range
from scripts.utils.well_queries import build_folder_map, resolve_well_context


DEFAULT_COLORS = [
    "#0078D7",
    "#E81123",
    "#107C10",
    "#FF8C00",
    "#8B00FF",
    "#00BFFF",
    "#FF1493",
    "#32CD32",
]


def create_plot(plot_spec: Dict[str, Any]) -> Dict[str, Any]:
    from scripts.utils.plot_window_utils import get_or_create_main_window

    title = plot_spec.get("title") or "Log Plot 1"
    _app, mw = get_or_create_main_window(show_ai_chat=False, show_scripts=False)
    widget, created_tracks = open_plot_from_spec(mw, plot_spec)
    if not widget:
        return {"ok": False, "error": "Failed to create plot from spec."}
    return {"ok": True, "title": title, "created_tracks": created_tracks}


def update_plot(window_id: Optional[str] = None, commands: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    from scripts.utils.plot_window_utils import get_or_create_plot_window

    if not commands:
        return {"ok": False, "error": "commands is required"}

    title = window_id or "Log Plot 1"
    _app, _mw, log_plot, _target_sub = get_or_create_plot_window(title, show_ai_chat=False, show_scripts=False)
    return update_plot_from_commands(log_plot, commands)


def apply_curve_style(window_id: str, track: Union[str, int], curve: Union[str, int], settings: Dict[str, Any]) -> Dict[str, Any]:
    return update_plot(window_id, [{
        "action": "apply_curve_style",
        "track": track,
        "curve": curve,
        "settings": settings,
    }])


def apply_track_style(window_id: str, track: Union[str, int], settings: Dict[str, Any]) -> Dict[str, Any]:
    return update_plot(window_id, [{
        "action": "apply_track_style",
        "track": track,
        "settings": settings,
    }])


def add_curve_to_plot(
    window_id: str,
    *,
    well_id: int,
    curve_id: int,
    track: Optional[Union[str, int]] = None,
    db_path: Optional[str] = None,
    curve_settings: Optional[Dict[str, Any]] = None,
    track_name: Optional[str] = None,
    track_width: int = 200,
    header_visible: bool = True,
    track_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return update_plot(window_id, [{
        "action": "add_curve",
        "track": track,
        "well_id": well_id,
        "curve_id": curve_id,
        "db_path": db_path,
        "curve_settings": curve_settings or {},
        "track_name": track_name,
        "track_width": track_width,
        "header_visible": header_visible,
        "track_settings": track_settings or {},
    }])


def remove_curve_from_plot(window_id: str, track: Union[str, int], curve: Union[str, int]) -> Dict[str, Any]:
    return update_plot(window_id, [{
        "action": "remove_curve",
        "track": track,
        "curve": curve,
    }])


def remove_track_from_plot(window_id: str, track: Union[str, int]) -> Dict[str, Any]:
    return update_plot(window_id, [{
        "action": "remove_track",
        "track": track,
    }])


def _build_plot_spec_from_db_curves(
    well_context: Dict[str, Any],
    current_curves: List[str],
    *,
    title: str,
    track: Optional[str] = None,
    colors: Optional[List[str]] = None,
    line_widths: Optional[List[float]] = None,
    line_styles: Optional[List[str]] = None,
    v_mins: Optional[List[float]] = None,
    v_maxs: Optional[List[float]] = None,
    colormap: str = "thermal",
    invert_colormap: bool = False,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None,
    track_settings_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    db = well_context["db"]
    well_id = well_context["resolved_well_id"]
    db_path = well_context["resolved_db_path"]
    well_name = well_context["well_name"]
    curves_meta = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)

    items_data: List[Dict[str, Any]] = []
    curve_settings_by_curve_id: Dict[int, Dict[str, Any]] = {}

    for idx, raw_name in enumerate(current_curves):
        name = str(raw_name)
        resolved = resolve_curve_row(name, curves_meta, folder_map)
        if not resolved.get("ok"):
            if resolved.get("error_code") == "curve_ambiguous":
                resolved["error"] = f"Curve '{name}' is ambiguous (multiple folders)."
                resolved["action_hint"] = "Please specify path like 'FRAME0/GR'."
            elif resolved.get("error_code") == "curve_not_found":
                resolved["error"] = f"Curve '{name}' not found in well '{well_name}'."
                resolved["action_hint"] = f"Did you mean one of these? Or use list_curves('{well_name}') to see all curves."
            return resolved

        target_meta = resolved["row"]
        if not target_meta:
            return {"ok": False, "error": f"Curve '{name}' could not be resolved."}

        curve_id = target_meta[0]
        unit = target_meta[2] if len(target_meta) > 2 else ""
        loaded = load_curve_bundle_for_plot(
            db_path,
            well_id,
            curve_id,
            preferences={"cmap": colormap, "null_color": "Auto"},
            db=db,
        )
        if not loaded.get("ok"):
            return {
                "ok": False,
                "error": f"Could not load curve '{name}' for well '{well_name}': {loaded.get('error')}",
            }

        vals = loaded["data"]
        base_info = loaded["info"]
        is_image = base_info.get("is_image", getattr(vals, "ndim", 1) > 1)
        color = colors[idx] if colors and idx < len(colors) else DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
        line_width = float(line_widths[idx]) if line_widths and idx < len(line_widths) else 1.0
        line_style = _resolve_line_style(line_styles, idx)

        curve_info: Dict[str, Any] = {
            "name": name,
            "unit": base_info.get("unit", unit or ""),
            "color": color,
            "line_width": line_width,
            "line_style": line_style,
            "is_image": is_image,
            "title": titles[idx] if titles and idx < len(titles) else None,
            "well_id": base_info.get("well_id"),
            "curve_id": base_info.get("curve_id"),
            "db_path": base_info.get("db_path"),
            "well_name": base_info.get("well_name"),
        }

        if fill_to and idx < len(fill_to):
            curve_info["fill_mode"] = fill_to[idx]
        if fill_colors and idx < len(fill_colors):
            curve_info["fill_color"] = fill_colors[idx]
        if fill_alphas and idx < len(fill_alphas):
            curve_info["fill_alpha"] = fill_alphas[idx]

        curve_info["log"] = resolve_default_log_mode(
            unit=curve_info["unit"],
            is_image=is_image,
            explicit_log=curve_info.get("log"),
        )

        if v_mins and idx < len(v_mins) and v_mins[idx] is not None:
            curve_info["min"] = float(v_mins[idx])
        if v_maxs and idx < len(v_maxs) and v_maxs[idx] is not None:
            curve_info["max"] = float(v_maxs[idx])

        if "min" not in curve_info or not np.isfinite(curve_info.get("min")):
            curve_info["min"] = base_info.get("min")
        if "max" not in curve_info or not np.isfinite(curve_info.get("max")):
            curve_info["max"] = base_info.get("max")
        if not np.isfinite(curve_info.get("min")) or not np.isfinite(curve_info.get("max")):
            auto_min, auto_max = compute_auto_display_range(vals, is_image=is_image, is_log=False)
            curve_info["min"] = auto_min
            curve_info["max"] = auto_max

        if is_image:
            curve_info["cmap"] = base_info.get("cmap", colormap)
            curve_info["invert"] = invert_colormap
            curve_info["null_color"] = base_info.get("null_color", "Auto")

        curve_info = normalize_curve_plot_style(curve_info)
        items_data.append({
            "type": "curve",
            "id": curve_id,
            "well_id": well_id,
            "db_path": db_path,
            "name": name,
        })
        curve_settings_by_curve_id[curve_id] = curve_info

    if not items_data:
        return {"ok": False, "error": f"No data could be extracted for the requested curves in well '{well_name}'."}

    plot_spec = build_plot_spec_from_manual_items(items_data, title=title)
    for idx, track_spec in enumerate(plot_spec.get("tracks", [])):
        track_name = track if track else track_spec.get("name")
        if track:
            track_spec["name"] = track
        if track_settings_map and track_name in track_settings_map:
            track_spec["track_settings"] = dict(track_settings_map[track_name])

        for curve_spec in track_spec.get("curves", []):
            curve_id = curve_spec.get("curve_id")
            curve_spec["curve_settings"] = dict(curve_settings_by_curve_id.get(curve_id, {}))

    return {"ok": True, "plot_spec": plot_spec}


def _resolve_line_style(line_styles: Optional[List[str]], idx: int):
    line_style = Qt.SolidLine
    if line_styles and idx < len(line_styles):
        style_str = str(line_styles[idx]).lower()
        if style_str == "dash":
            line_style = Qt.DashLine
        elif style_str == "dot":
            line_style = Qt.DotLine
        elif style_str == "dash_dot":
            line_style = Qt.DashDotLine
    return line_style


def _build_plot_data_list_from_db(
    well_context: Dict[str, Any],
    current_curves: List[str],
    *,
    track: Optional[str] = None,
    colors: Optional[List[str]] = None,
    line_widths: Optional[List[float]] = None,
    line_styles: Optional[List[str]] = None,
    v_mins: Optional[List[float]] = None,
    v_maxs: Optional[List[float]] = None,
    colormap: str = "thermal",
    invert_colormap: bool = False,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    db = well_context["db"]
    well_id = well_context["resolved_well_id"]
    db_path = well_context["resolved_db_path"]
    well_name = well_context["well_name"]

    curves_meta = db.get_curves(well_id)
    folder_map = build_folder_map(db, well_id)
    data_list: List[Dict[str, Any]] = []

    for idx, raw_name in enumerate(current_curves):
        name = str(raw_name)
        resolved = resolve_curve_row(name, curves_meta, folder_map)
        if not resolved.get("ok"):
            if resolved.get("error_code") == "curve_ambiguous":
                resolved["error"] = f"Curve '{name}' is ambiguous (multiple folders)."
                resolved["action_hint"] = "Please specify path like 'FRAME0/GR'."
            elif resolved.get("error_code") == "curve_not_found":
                resolved["error"] = f"Curve '{name}' not found in well '{well_name}'."
                resolved["action_hint"] = f"Did you mean one of these? Or use list_curves('{well_name}') to see all curves."
            return resolved

        target_meta = resolved["row"]
        if not target_meta:
            return {"ok": False, "error": f"Curve '{name}' could not be resolved."}

        curve_id = target_meta[0]
        unit = target_meta[2] if len(target_meta) > 2 else ""
        loaded = load_curve_bundle_for_plot(
            db_path,
            well_id,
            curve_id,
            preferences={"cmap": colormap, "null_color": "Auto"},
            db=db,
        )
        if not loaded.get("ok"):
            return {
                "ok": False,
                "error": f"Could not load curve '{name}' for well '{well_name}': {loaded.get('error')}",
            }

        vals = loaded["data"]
        depth = loaded["depth"]
        base_info = loaded["info"]
        is_image = base_info.get("is_image", getattr(vals, "ndim", 1) > 1)

        color = colors[idx] if colors and idx < len(colors) else DEFAULT_COLORS[idx % len(DEFAULT_COLORS)]
        line_width = float(line_widths[idx]) if line_widths and idx < len(line_widths) else 1.0
        line_style = _resolve_line_style(line_styles, idx)

        curve_info: Dict[str, Any] = {
            "name": name,
            "depth": depth,
            "values": vals,
            "track": track,
            "unit": base_info.get("unit", unit or ""),
            "color": color,
            "line_width": line_width,
            "line_style": line_style,
            "is_image": is_image,
            "title": titles[idx] if titles and idx < len(titles) else None,
            "well_id": base_info.get("well_id"),
            "curve_id": base_info.get("curve_id"),
            "db_path": base_info.get("db_path"),
            "well_name": base_info.get("well_name"),
        }

        if fill_to and idx < len(fill_to):
            curve_info["fill_to"] = fill_to[idx]
        if fill_colors and idx < len(fill_colors):
            curve_info["fill_color"] = fill_colors[idx]
        if fill_alphas and idx < len(fill_alphas):
            curve_info["fill_alpha"] = fill_alphas[idx]

        curve_info["log"] = resolve_default_log_mode(
            unit=curve_info["unit"],
            is_image=is_image,
            explicit_log=curve_info.get("log"),
        )

        if v_mins and idx < len(v_mins) and v_mins[idx] is not None:
            curve_info["min"] = float(v_mins[idx])
        if v_maxs and idx < len(v_maxs) and v_maxs[idx] is not None:
            curve_info["max"] = float(v_maxs[idx])

        if "min" not in curve_info or not np.isfinite(curve_info.get("min")):
            curve_info["min"] = base_info.get("min")
        if "max" not in curve_info or not np.isfinite(curve_info.get("max")):
            curve_info["max"] = base_info.get("max")
        if not np.isfinite(curve_info.get("min")) or not np.isfinite(curve_info.get("max")):
            auto_min, auto_max = compute_auto_display_range(vals, is_image=is_image, is_log=False)
            curve_info["min"] = auto_min
            curve_info["max"] = auto_max

        if is_image:
            curve_info["cmap"] = base_info.get("cmap", colormap)
            curve_info["invert"] = invert_colormap
            curve_info["null_color"] = base_info.get("null_color", "Auto")

        data_list.append(normalize_curve_plot_style(curve_info))

    if not data_list:
        return {"ok": False, "error": f"No data could be extracted for the requested curves in well '{well_name}'."}
    return {"ok": True, "data_list": data_list}


def plot(
    well: Optional[Union[str, int]] = None,
    curves: Optional[List[str]] = None,
    data_list: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
    title: str = "Log Plot 1",
    **kwargs,
) -> Dict[str, Any]:
    """Unified plotting API for database-backed or in-memory curves."""
    current_curves = curves or kwargs.get("curve_names")
    if well is not None and current_curves is not None:
        return plot_from_db(
            well=well,
            curves=curves,
            db_path=db_path,
            curve_names=kwargs.pop("curve_names", None),
            title=title,
            **kwargs,
        )

    if data_list is not None:
        if well is not None:
            depth_data = get_depth_data(well, db_path=db_path)
            if isinstance(depth_data, np.ndarray):
                for item in data_list:
                    if "depth" not in item or item["depth"] is None:
                        item["depth"] = depth_data

        plot_log_curves(data_list=data_list, title=title, **kwargs)
        return {"ok": True, "message": f"Plotting {len(data_list)} memory curves."}

    return {"ok": False, "error": "Insufficient parameters. Provide (well, curves) or (data_list)."}


def plot_from_db(
    well: Union[str, int],
    curves: Optional[List[str]] = None,
    db_path: Optional[str] = None,
    curve_names: Optional[List[str]] = None,
    title: str = "Log Plot 1",
    show_ai_chat: bool = False,
    show_scripts: bool = False,
    block: bool = True,
    track: Optional[str] = None,
    colors: Optional[List[str]] = None,
    line_widths: Optional[List[float]] = None,
    line_styles: Optional[List[str]] = None,
    v_mins: Optional[List[float]] = None,
    v_maxs: Optional[List[float]] = None,
    colormap: str = "thermal",
    invert_colormap: bool = False,
    accum_fill: bool = False,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None,
    **_kwargs,
) -> Dict[str, Any]:
    """Plot curves directly from the database using packaged orchestration."""
    current_curves = curves or curve_names
    if not current_curves:
        return {"ok": False, "error": "Parameter 'curves' or 'curve_names' is required."}

    well_context, resolution_error = resolve_well_context(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    built = _build_plot_data_list_from_db(
        well_context,
        current_curves,
        track=track,
        colors=colors,
        line_widths=line_widths,
        line_styles=line_styles,
        v_mins=v_mins,
        v_maxs=v_maxs,
        colormap=colormap,
        invert_colormap=invert_colormap,
        fill_to=fill_to,
        fill_colors=fill_colors,
        fill_alphas=fill_alphas,
        titles=titles,
    )
    if not built.get("ok"):
        return built

    spec_built = _build_plot_spec_from_db_curves(
        well_context,
        current_curves,
        title=title,
        track=track,
        colors=colors,
        line_widths=line_widths,
        line_styles=line_styles,
        v_mins=v_mins,
        v_maxs=v_maxs,
        colormap=colormap,
        invert_colormap=invert_colormap,
        fill_to=fill_to,
        fill_colors=fill_colors,
        fill_alphas=fill_alphas,
        titles=titles,
    )
    if not spec_built.get("ok"):
        return spec_built
    result = create_plot(spec_built["plot_spec"])
    if result.get("ok"):
        result["message"] = f"Successfully plotted {len(current_curves)} curves in window '{title}'."
    return result


def plot_log_curves(
    data_list: List[Dict[str, Any]],
    title: str = "Log Plot 1",
    show_ai_chat: bool = False,
    show_scripts: bool = False,
    block: bool = True,
    accum_fill: bool = False,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Plot in-memory curves into the PyLog UI."""
    from .core import get_legacy_public_callable

    return get_legacy_public_callable("_plot_log_curves")(
        data_list=data_list,
        title=title,
        show_ai_chat=show_ai_chat,
        show_scripts=show_scripts,
        block=block,
        accum_fill=accum_fill,
        fill_to=fill_to,
        fill_colors=fill_colors,
        fill_alphas=fill_alphas,
        titles=titles,
    )


def plot_curves(
    well: Union[str, int],
    curves: List[str],
    db_path: Optional[str] = None,
    title: str = "Log Plot 1",
    curve_settings_map: Optional[Dict[str, Dict[str, Any]]] = None,
    track_settings_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    well_context, resolution_error = resolve_well_context(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    db = well_context["db"]
    resolved_items: List[Dict[str, Any]] = []
    curves_meta = db.get_curves(well_context["resolved_well_id"])
    folder_map = build_folder_map(db, well_context["resolved_well_id"])

    for curve_name in curves:
        resolved = resolve_curve_row(str(curve_name), curves_meta, folder_map)
        if not resolved.get("ok"):
            return resolved
        row = resolved["row"]
        resolved_items.append({
            "type": "curve",
            "id": row[0],
            "well_id": well_context["resolved_well_id"],
            "db_path": well_context["resolved_db_path"],
            "name": curve_name,
        })

    plot_spec = build_plot_spec_from_manual_items(resolved_items, title=title)
    for track in plot_spec.get("tracks", []):
        track_name = track.get("name")
        if track_settings_map and track_name in track_settings_map:
            track["track_settings"] = dict(track_settings_map[track_name])
        for curve in track.get("curves", []):
            curve_settings = curve.get("curve_settings", {})
            curve_name = next((item.get("name") for item in resolved_items if item.get("id") == curve.get("curve_id")), None)
            if curve_name and curve_settings_map and curve_name in curve_settings_map:
                curve_settings.update(curve_settings_map[curve_name])
            curve["curve_settings"] = curve_settings

    return create_plot(plot_spec)
