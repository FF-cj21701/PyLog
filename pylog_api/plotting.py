"""Plotting helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import numpy as np
from PySide6.QtCore import Qt

from .core import get_legacy_public_callable
from .depth import get_depth_data
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

    return plot_log_curves(
        data_list=built["data_list"],
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
