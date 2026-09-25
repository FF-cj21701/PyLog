from __future__ import annotations

import math
from typing import Any, Dict

import numpy as np

DEFAULT_FILL_ALPHA = 1.0
DEFAULT_FILL_COLOR = "#ff000000"
LEGACY_DEFAULT_FILL_COLOR = "#80000000"
AUTO_FILL_LIGHTEN_RATIO = 0.3
DEFAULT_IMAGE_CMAP = "thermal"
DEFAULT_NULL_COLOR = "Auto"
DEFAULT_IMAGE_AZIMUTH_START = 0.0


def is_resistivity_unit(unit: str) -> bool:
    unit_lower = str(unit or "").strip().lower()
    return "ohm" in unit_lower or ".m" in unit_lower


def resolve_default_log_mode(*, unit: str = "", is_image: bool = False, explicit_log: Any = None) -> bool:
    """Resolve plotting scale defaults consistently across API, tools, and UI."""
    if explicit_log is not None:
        return bool(explicit_log)
    if is_image:
        return False
    return is_resistivity_unit(unit)


def _coerce_fill_alpha(value: Any, default: float = DEFAULT_FILL_ALPHA) -> float:
    try:
        alpha = float(value)
    except (TypeError, ValueError):
        alpha = default
    if not math.isfinite(alpha):
        alpha = default
    return max(0.0, min(1.0, alpha))


def _coerce_finite_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    return result if math.isfinite(result) else default


def rotate_image_columns(values: Any, azimuth_start: Any = DEFAULT_IMAGE_AZIMUTH_START):
    """Circularly shift image columns so the left edge is ``azimuth_start`` degrees."""
    start = _coerce_finite_float(azimuth_start, DEFAULT_IMAGE_AZIMUTH_START)
    shape = getattr(values, "shape", ())
    if len(shape) < 2 or not shape[1]:
        return values
    shift = int(round((-start / 360.0) * int(shape[1]))) % int(shape[1])
    if shift == 0:
        return values
    return np.roll(values, shift, axis=1)


def _alpha_from_hex_color(color_name: str) -> float:
    if color_name.startswith("#") and len(color_name) == 9:
        try:
            return int(color_name[1:3], 16) / 255.0
        except ValueError:
            return DEFAULT_FILL_ALPHA
    return DEFAULT_FILL_ALPHA


def _with_alpha(color_name: Any, alpha: float) -> Any:
    if not isinstance(color_name, str) or not color_name.startswith("#"):
        return color_name
    alpha_hex = format(int(_coerce_fill_alpha(alpha) * 255), "02x")
    if len(color_name) == 7:
        return f"#{alpha_hex}{color_name[1:]}"
    if len(color_name) == 9:
        return f"#{alpha_hex}{color_name[3:]}"
    return color_name


def _lighten_hex_color(color_name: Any, ratio: float = AUTO_FILL_LIGHTEN_RATIO) -> Any:
    if not isinstance(color_name, str) or not color_name.startswith("#"):
        return color_name
    if len(color_name) == 7:
        rgb_hex = color_name[1:]
    elif len(color_name) == 9:
        rgb_hex = color_name[3:]
    else:
        return color_name
    try:
        r = int(rgb_hex[0:2], 16)
        g = int(rgb_hex[2:4], 16)
        b = int(rgb_hex[4:6], 16)
    except ValueError:
        return color_name
    ratio = max(0.0, min(1.0, float(ratio)))
    r = round(r + (255 - r) * ratio)
    g = round(g + (255 - g) * ratio)
    b = round(b + (255 - b) * ratio)
    return f"#{r:02x}{g:02x}{b:02x}"


def resolve_auto_fill_color(line_color: Any, alpha: float = DEFAULT_FILL_ALPHA) -> Any:
    """Return the automatic fill color: a lighter variant of the line color."""
    base_color = line_color or DEFAULT_FILL_COLOR
    return _with_alpha(_lighten_hex_color(base_color), alpha)


def normalize_fill_style(info: Dict[str, Any]) -> Dict[str, Any]:
    """Apply shared fill defaults and legacy default compatibility."""
    normalized = dict(info)
    fill_color = normalized.get("fill_color")
    fill_alpha = _coerce_fill_alpha(normalized.get("fill_alpha"))

    if normalized.get("fill_color_auto"):
        fill_color = None

    if not fill_color:
        line_color = normalized.get("color") or DEFAULT_FILL_COLOR
        normalized["fill_color"] = resolve_auto_fill_color(line_color, fill_alpha)
        normalized["fill_alpha"] = fill_alpha
        return normalized

    if str(fill_color).lower() == LEGACY_DEFAULT_FILL_COLOR:
        line_color = normalized.get("color") or DEFAULT_FILL_COLOR
        normalized["fill_color"] = resolve_auto_fill_color(line_color, DEFAULT_FILL_ALPHA)
        normalized["fill_alpha"] = DEFAULT_FILL_ALPHA
        return normalized

    if isinstance(fill_color, str) and fill_color.startswith("#"):
        if len(fill_color) == 7:
            alpha_hex = format(int(fill_alpha * 255), "02x")
            normalized["fill_color"] = f"#{alpha_hex}{fill_color[1:]}"
            normalized["fill_alpha"] = fill_alpha
            return normalized
        if len(fill_color) == 9:
            normalized["fill_color"] = fill_color
            normalized["fill_alpha"] = _alpha_from_hex_color(fill_color)
            return normalized

    normalized["fill_color"] = fill_color
    normalized["fill_alpha"] = fill_alpha
    return normalized


def normalize_curve_plot_style(info: Dict[str, Any]) -> Dict[str, Any]:
    """Apply shared plotting defaults to a curve info dict."""
    normalized = dict(info)
    is_image = bool(normalized.get("is_image", False))
    normalized["log"] = resolve_default_log_mode(
        unit=normalized.get("unit", ""),
        is_image=is_image,
        explicit_log=normalized.get("log"),
    )
    if is_image:
        normalized["cmap"] = str(normalized.get("cmap", DEFAULT_IMAGE_CMAP)).lower()
        normalized["invert"] = bool(normalized.get("invert", normalized.get("invert_x", False)))
        normalized["null_color"] = normalized.get("null_color", DEFAULT_NULL_COLOR)
        normalized["azimuth_start"] = _coerce_finite_float(
            normalized.get("azimuth_start", DEFAULT_IMAGE_AZIMUTH_START),
            DEFAULT_IMAGE_AZIMUTH_START,
        )
    else:
        normalized = normalize_fill_style(normalized)
    return normalized
