"""Legacy plotting bridge that keeps old entry points thin."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from pylog_api.compat_shims import legacy_resolve_optional_db_path_for_well
from scripts.utils.well_queries import resolve_well_context


def legacy_plot_from_db(
    render_plot_log_curves,
    *,
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
) -> Dict[str, Any]:
    """Legacy-compatible DB plotting bridge that reuses packaged plot building."""
    current_curves = curves or curve_names
    if not current_curves:
        return {"ok": False, "error": "Parameter 'curves' or 'curve_names' is required."}

    resolved_db_path, resolution_error = legacy_resolve_optional_db_path_for_well(well, db_path=db_path)
    if resolution_error:
        return resolution_error

    well_context, context_error = resolve_well_context(well, db_path=resolved_db_path)
    if context_error:
        return context_error

    from pylog_api.plotting import _build_plot_data_list_from_db

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

    return render_plot_log_curves(
        built["data_list"],
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
