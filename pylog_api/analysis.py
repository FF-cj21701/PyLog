"""Analysis helpers for the packaged ``pylog_api`` interface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import numpy as np

from .data_access import get_curve_data


def analyze_curve(well: Union[str, int], curve_name: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """Load a curve and immediately run statistical analysis on it."""
    try:
        data = get_curve_data(well, curve_name, db_path=db_path)
        if isinstance(data, dict) and not data.get("ok", True):
            return data
        return analyze_data(data)
    except Exception as e:
        return {"ok": False, "error": str(e)}


def analyze_data(values: Union[List[Any], np.ndarray], force_full: bool = False) -> Dict[str, Any]:
    """Perform memory-safe statistical analysis on numerical data."""
    if hasattr(values, "min") and hasattr(values, "max") and not force_full:
        return {
            "ok": True,
            "shape": getattr(values, "shape", (len(values),)),
            "ndim": getattr(values, "ndim", 1),
            "count": len(values),
            "min": float(values.min()),
            "max": float(values.max()),
            "is_lazy": True,
            "message": "Lazy analysis (Metadata-based). Use force_full=True for deep stats (Mean/Std).",
        }

    arr = np.asarray(values)
    if arr.dtype == object:
        try:
            arr = arr.astype(float)
        except Exception:
            flat = []
            for row in values:
                if hasattr(row, "__iter__"):
                    flat.extend(row)
                else:
                    flat.append(row)
            arr = np.asarray(flat, dtype=float)

    shape = arr.shape
    ndim = arr.ndim

    try:
        flat_arr = arr.ravel()
    except Exception:
        flat_arr = arr

    if flat_arr.size > 0:
        if not np.issubdtype(flat_arr.dtype, np.number):
            try:
                flat_arr = flat_arr.astype(float)
                arr = flat_arr
            except Exception:
                return {
                    "shape": shape,
                    "ndim": ndim,
                    "count": int(flat_arr.size),
                    "dtype": str(flat_arr.dtype),
                    "error": "Non-numeric data",
                }

    is_image_data = False
    if ndim == 2 and np.min(flat_arr) >= 0 and np.max(flat_arr) <= 255:
        is_image_data = True

    finite = np.isfinite(flat_arr)
    count = int(flat_arr.size)
    finite_count = int(np.sum(finite))
    non_finite = count - finite_count

    if finite_count > 0:
        vals = flat_arr[finite]
        vmin = float(np.min(vals))
        vmax = float(np.max(vals))
        mean = float(np.mean(vals))
        median = float(np.median(vals))
        std = float(np.std(vals))
        p10 = float(np.percentile(vals, 10))
        p90 = float(np.percentile(vals, 90))
    else:
        vmin = vmax = mean = median = std = p10 = p90 = None

    result = {
        "shape": shape,
        "ndim": ndim,
        "count": count,
        "finite": finite_count,
        "non_finite": non_finite,
        "min": vmin,
        "max": vmax,
        "mean": mean,
        "median": median,
        "std": std,
        "p10": p10,
        "p90": p90,
    }

    if is_image_data:
        result["is_image_data"] = True
        result["image_info"] = {
            "width": shape[1],
            "height": shape[0],
            "pixel_range": [vmin, vmax],
        }

    return result
