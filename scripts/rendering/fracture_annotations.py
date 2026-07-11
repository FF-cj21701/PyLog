import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np


DEFAULT_FRACTURE_COLOR = "#00E5FF"
DEFAULT_FRACTURE_WIDTH = 2.0
MIN_FRACTURE_PICK_POINTS = 3
MIN_FRACTURE_PREVIEW_POINTS = 2
FRACTURE_TYPE_STYLES = {
    "Conductive": {"color": "#00E5FF", "label": "Conductive"},
    "Resistive": {"color": "#FF2D2D", "label": "Resistive"},
    "Bedding": {"color": "#52D273", "label": "Bedding"},
}


def _finite_points(points: Iterable[Sequence[float]]) -> List[Tuple[float, float]]:
    clean = []
    for point in points or []:
        if len(point) < 2:
            continue
        try:
            x = float(point[0])
            y = float(point[1])
        except Exception:
            continue
        if math.isfinite(x) and math.isfinite(y):
            clean.append((max(0.0, min(360.0, x)), y))
    return clean


def fit_sinusoidal_fracture(
    points: Iterable[Sequence[float]],
    *,
    min_points: int = MIN_FRACTURE_PICK_POINTS,
) -> Dict[str, Any]:
    """
    Fit an unfolded borehole-image fracture trace with a fixed 360 degree period.

    Model: depth = offset + sin_coeff * sin(azimuth) + cos_coeff * cos(azimuth)
    """
    clean = _finite_points(points)
    if len(clean) < min_points:
        raise ValueError(f"At least {min_points} fracture pick points are required.")

    azimuth = np.asarray([p[0] for p in clean], dtype=float)
    depth = np.asarray([p[1] for p in clean], dtype=float)
    radians = np.deg2rad(azimuth)
    design = np.column_stack([np.ones_like(radians), np.sin(radians), np.cos(radians)])
    coeffs, *_ = np.linalg.lstsq(design, depth, rcond=None)
    offset, sin_coeff, cos_coeff = [float(v) for v in coeffs]
    amplitude = float(math.hypot(sin_coeff, cos_coeff))

    return {
        "points": [[float(x), float(y)] for x, y in clean],
        "offset": offset,
        "sin_coeff": sin_coeff,
        "cos_coeff": cos_coeff,
        "amplitude": amplitude,
    }


def sinusoidal_fracture_xy(annotation: Dict[str, Any], samples: int = 361) -> Tuple[np.ndarray, np.ndarray]:
    x = np.linspace(0.0, 360.0, max(2, int(samples)))
    radians = np.deg2rad(x)
    y = (
        float(annotation.get("offset", 0.0))
        + float(annotation.get("sin_coeff", 0.0)) * np.sin(radians)
        + float(annotation.get("cos_coeff", 0.0)) * np.cos(radians)
    )
    return x, y


def build_fracture_annotation(
    points: Iterable[Sequence[float]],
    *,
    fracture_type: str = "Conductive",
    color: str = DEFAULT_FRACTURE_COLOR,
    line_width: float = DEFAULT_FRACTURE_WIDTH,
    name: str = "Fracture",
    min_points: int = MIN_FRACTURE_PICK_POINTS,
) -> Dict[str, Any]:
    annotation = fit_sinusoidal_fracture(points, min_points=min_points)
    annotation.update({
        "type": "sinusoidal_fracture",
        "fracture_type": fracture_type,
        "name": name,
        "color": color,
        "line_width": float(line_width),
    })
    return annotation
