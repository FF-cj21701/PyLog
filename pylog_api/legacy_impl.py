import numpy as np
from typing import List, Dict, Optional, Union, Any, Tuple
from PySide6.QtCore import Qt
from pylog_api.compat_shims import legacy_compute_auto_display_range as _compute_auto_display_range
from pylog_api.compat_shims import legacy_curve_row_to_dict as _curve_row_to_dict
from pylog_api.compat_shims import legacy_resolve_optional_db_path_for_well as _resolve_optional_db_path_for_well
from pylog_api.compat_shims import legacy_resolve_well_id as _resolve_well_id
from pylog_api.legacy_forwarders import analyze_curve
from pylog_api.legacy_forwarders import analyze_data
from pylog_api.legacy_forwarders import get_curve_data
from pylog_api.legacy_forwarders import get_curve_info
from pylog_api.legacy_forwarders import get_depth_data
from pylog_api.legacy_forwarders import get_well_info
from pylog_api.legacy_forwarders import inspect_api
from pylog_api.legacy_forwarders import list_curves
from pylog_api.legacy_forwarders import list_wells
from pylog_api.legacy_forwarders import plot
from pylog_api.legacy_plot_bridge import legacy_plot_from_db
from pylog_api.legacy_forwarders import save_curve
from scripts.utils.plot_finalize_utils import schedule_plot_finalize
from scripts.utils.plot_render_utils import refresh_accumulative_fills
from scripts.utils.plot_render_utils import render_curve_batch
from scripts.utils.plot_window_utils import get_or_create_plot_window

def _plot_log_curves(
    data_list: List[Dict[str, Any]], 
    title: str = "Log Plot 1", 
    show_ai_chat: bool = False, 
    show_scripts: bool = False, 
    block: bool = True,
    accum_fill: bool = False,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None
) -> None:
    """
    Plots well log curves into ALIVE track systems.
    
    This is the primary high-level API for visualizing log data. It supports both
    1D curves and 2D image data.

    Args:
        data_list: A list of dictionaries, where each dict represents a curve:
            - 'values' (np.ndarray): The data values.
            - 'depth' (np.ndarray): Corresponding depth values. (Required)
            - 'name' (str): Display name.
            - 'unit' (str, optional): Unit of measurement.
            - 'track' (str, optional): Target track ID for overlays.
            - 'type' (str, optional): '1D' or '2D'.
            - 'color' (str, optional): Hex color for 1D curves.
            - 'cmap' (str, optional): Colormap for 2D images.
        title: The title of the plot window. If a window with this title already exists (e.g., 'Log Plot 1'), new curves will be added to it. Otherwise, a new window is created.
        show_ai_chat: Whether to automatically show the AI Assistant panel.
        show_scripts: Whether to show the script editor panel.
        block: If True, blocks execution until the window is closed.
    """

    _app, mw, log_plot, target_sub = get_or_create_plot_window(
        title,
        show_ai_chat=show_ai_chat,
        show_scripts=show_scripts,
    )

    if data_list:
        affected_tracks = render_curve_batch(
            log_plot,
            data_list,
            accum_fill=accum_fill,
            fill_to=fill_to,
            fill_colors=fill_colors,
            fill_alphas=fill_alphas,
            titles=titles,
        )
        if accum_fill:
            refresh_accumulative_fills(affected_tracks)
        schedule_plot_finalize(mw, log_plot, target_sub)

    return {"ok": True, "message": f"Successfully plotted {len(data_list)} curves in window '{title}'."}

def _plot_from_db(
    well: Union[str, int], 
    curves: Optional[List[str]] = None,
    db_path: Optional[str] = None, 
    curve_names: Optional[List[str]] = None, # Alias for backward compatibility
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
    titles: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Compatibility DB plotting entry that delegates to the legacy plotting bridge."""
    return legacy_plot_from_db(
        _plot_log_curves,
        well=well,
        curves=curves,
        db_path=db_path,
        curve_names=curve_names,
        title=title,
        show_ai_chat=show_ai_chat,
        show_scripts=show_scripts,
        block=block,
        track=track,
        colors=colors,
        line_widths=line_widths,
        line_styles=line_styles,
        v_mins=v_mins,
        v_maxs=v_maxs,
        colormap=colormap,
        invert_colormap=invert_colormap,
        accum_fill=accum_fill,
        fill_to=fill_to,
        fill_colors=fill_colors,
        fill_alphas=fill_alphas,
        titles=titles,
    )
