import math
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import numpy as np


DEFAULT_FRACTURE_COLOR = "#FF2D2D"
DEFAULT_FRACTURE_WIDTH = 2.0
MIN_FRACTURE_PICK_POINTS = 3
MIN_FRACTURE_PREVIEW_POINTS = 2
FRACTURE_TYPE_STYLES = {
    "Conductive": {"color": "#0099CC", "label": "Conductive"},
    "Resistive": {"color": "#FF2D2D", "label": "Resistive"},
    "Bedding": {"color": "#16A951", "label": "Bedding"},
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


def fracture_parameters(annotation: Dict[str, Any]) -> Dict[str, float]:
    """Return the human-facing c, A, phase representation of a fitted fracture."""
    sin_coeff = float(annotation.get("sin_coeff", 0.0))
    cos_coeff = float(annotation.get("cos_coeff", 0.0))
    return {
        "center_depth_m": float(annotation.get("offset", annotation.get("center_depth", 0.0))),
        "amplitude_m": float(math.hypot(sin_coeff, cos_coeff)),
        "phase_deg": float(math.degrees(math.atan2(cos_coeff, sin_coeff)) % 360.0),
    }


def annotation_from_fracture_parameters(center_depth_m, amplitude_m, phase_deg) -> Dict[str, float]:
    center = float(center_depth_m)
    amplitude = abs(float(amplitude_m))
    phase = float(phase_deg) % 360.0
    radians = math.radians(phase)
    return {
        "offset": center,
        "sin_coeff": amplitude * math.cos(radians),
        "cos_coeff": amplitude * math.sin(radians),
        "amplitude": amplitude,
    }


def canonical_fracture_points(center_depth_m, amplitude_m, phase_deg) -> List[List[float]]:
    """Generate seam, extrema, and mid-slope points from absolute sine parameters."""
    fit = annotation_from_fracture_parameters(center_depth_m, amplitude_m, phase_deg)
    phase = float(phase_deg) % 360.0
    azimuths = {
        0.0,
        360.0,
        (-phase) % 360.0,
        (90.0 - phase) % 360.0,
        (180.0 - phase) % 360.0,
        (270.0 - phase) % 360.0,
    }
    points = []
    for azimuth in sorted(azimuths):
        radians = math.radians(azimuth)
        depth = fit["offset"] + fit["sin_coeff"] * math.sin(radians) + fit["cos_coeff"] * math.cos(radians)
        points.append([float(azimuth), float(depth)])
    return points


def enrich_fracture_interpretation(
    annotation: Dict[str, Any],
    *,
    borehole_diameter: float | None = None,
) -> Dict[str, Any]:
    """Add the core interpretation fields used by the fracture results table."""
    enriched = dict(annotation or {})
    center_depth = float(enriched.get("offset", 0.0))
    sin_coeff = float(enriched.get("sin_coeff", 0.0))
    cos_coeff = float(enriched.get("cos_coeff", 0.0))
    dip_height = float(enriched.get("amplitude", math.hypot(sin_coeff, cos_coeff)))
    image_azimuth = (math.degrees(math.atan2(sin_coeff, cos_coeff)) + 360.0) % 360.0

    apparent_dip = None
    diameter = borehole_diameter
    if diameter is None:
        diameter = enriched.get("borehole_diameter") or enriched.get("avg_caliper")
    try:
        diameter = float(diameter)
        if math.isfinite(diameter) and diameter > 0.0:
            apparent_dip = math.degrees(math.atan2(2.0 * dip_height, diameter))
    except Exception:
        apparent_dip = None

    enriched.update({
        "center_depth": center_depth,
        "dip_height": dip_height,
        "image_azimuth": image_azimuth,
        "apparent_dip": apparent_dip,
    })
    return enriched


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
    return enrich_fracture_interpretation(annotation)
