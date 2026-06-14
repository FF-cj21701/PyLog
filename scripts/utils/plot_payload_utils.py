from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from .plot_style_utils import DEFAULT_IMAGE_CMAP, normalize_curve_plot_style
from .plot_value_utils import compute_auto_display_range


def prepare_curve_payload_for_render(
    curve: Dict[str, Any],
    idx: int,
    *,
    accum_fill: bool = False,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Normalize one curve payload before it is injected into a UI track."""
    track_id = curve.get("track")
    title = curve.get("title")
    if titles and idx < len(titles):
        title = titles[idx]

    vals = curve["values"]
    depth_vals = curve["depth"]

    if not hasattr(vals, "__len__") and not hasattr(vals, "shape"):
        vals = np.asarray(vals)
    if not hasattr(depth_vals, "__len__") and not hasattr(depth_vals, "shape"):
        depth_vals = np.asarray(depth_vals)

    c_type = str(curve.get("type", "1D")).upper()
    is_image = c_type == "2D"
    if not is_image:
        is_image = curve.get("is_image", getattr(vals, "ndim", 1) > 1)

    min_len = min(len(vals), len(depth_vals))
    vals = vals[:min_len]
    depth = depth_vals[:min_len]

    v_min = curve.get("min")
    v_max = curve.get("max")
    if v_min is None or v_max is None or not np.isfinite(v_min) or not np.isfinite(v_max):
        auto_min, auto_max = compute_auto_display_range(
            vals,
            is_image=is_image,
            is_log=curve.get("log", False),
        )
        if v_min is None or not np.isfinite(v_min):
            v_min = auto_min
        if v_max is None or not np.isfinite(v_max):
            v_max = auto_max

    color = curve.get("color", "#0078D7")
    fill_color = curve.get("fill_color")
    if fill_color is None and fill_colors and idx < len(fill_colors):
        fill_color = fill_colors[idx]
    fill_alpha = curve.get("fill_alpha")
    if fill_alpha is None and fill_alphas and idx < len(fill_alphas):
        fill_alpha = fill_alphas[idx]
    if fill_alpha is None:
        fill_alpha = 1.0

    fill_mode = curve.get("fill_to")
    if fill_mode is None and fill_to and idx < len(fill_to):
        fill_mode = fill_to[idx]
    if fill_mode is None:
        fill_mode = curve.get("fill_mode", "None")

    info = {
        "name": curve.get("name", "Curve"),
        "title": title,
        "unit": curve.get("unit", ""),
        "color": color,
        "min": v_min,
        "max": v_max,
        "is_image": is_image,
        "cmap": curve.get("cmap", DEFAULT_IMAGE_CMAP),
        "line_width": curve.get("line_width", 1.0),
        "line_style": curve.get("line_style", 1),
        "fill_mode": fill_mode,
        "fill_color": fill_color,
        "fill_alpha": fill_alpha,
        "log": curve.get("log", False),
    }
    info = normalize_curve_plot_style(info)

    return {
        "track_id": track_id,
        "is_image": is_image,
        "values": vals,
        "depth": depth,
        "info": info,
    }
