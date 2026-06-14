import numpy as np


INVALID_VALUE_SENTINELS = (-99999, -9999, -32767, -999.25)
DEFAULT_DISPLAY_RANGE = (0.0, 100.0)


def sample_plot_values(values, *, is_image: bool = False):
    """Down-sample large 2D image arrays before computing display statistics."""
    arr = np.asarray(values)
    if is_image and arr.ndim >= 2:
        row_step = max(1, int(arr.shape[0] // 2000))
        col_step = max(1, int(arr.shape[1] // 360))
        return arr[::row_step, ::col_step]
    return arr


def build_invalid_value_mask(values, *, is_log: bool = False):
    """Return a boolean mask for non-finite and configured null-sentinel values."""
    arr = np.asarray(values)
    invalid_mask = ~np.isfinite(arr)
    invalid_mask |= np.isin(arr, INVALID_VALUE_SENTINELS)
    if is_log:
        invalid_mask |= ~(arr > 0)
    return invalid_mask


def is_invalid_plot_value(value, *, is_log: bool = False):
    """Scalar-friendly invalid-value check for tables and single-point formatting."""
    try:
        invalid = bool(build_invalid_value_mask(np.asarray([value]), is_log=is_log)[0])
    except Exception:
        return True
    return invalid


def sanitize_invalid_plot_values(values, *, is_log: bool = False):
    """Replace invalid plotting values with NaN for float-like arrays/scalars."""
    arr = np.asarray(values)
    if arr.ndim == 0:
        scalar = arr.item()
        return np.nan if is_invalid_plot_value(scalar, is_log=is_log) else scalar

    if not np.issubdtype(arr.dtype, np.floating):
        return arr

    invalid_mask = build_invalid_value_mask(arr, is_log=is_log)
    if not np.any(invalid_mask):
        return arr

    if not getattr(arr, "flags", None) or not arr.flags.writeable:
        arr = arr.copy()
    arr[invalid_mask] = np.nan
    return arr


def extract_valid_plot_values(values, *, is_image: bool = False, is_log: bool = False):
    """Return only values that should participate in plotting/auto-range decisions."""
    sampled = sample_plot_values(values, is_image=is_image)
    if sampled.size == 0:
        return np.asarray([], dtype=float)
    invalid_mask = build_invalid_value_mask(sampled, is_log=is_log)
    return np.asarray(sampled[~invalid_mask], dtype=float)


def compute_auto_display_range(values, *, is_image: bool = False, is_log: bool = False):
    """Compute a finite display range consistent across API tools and manual plotting."""
    valid = extract_valid_plot_values(values, is_image=is_image, is_log=is_log)
    if valid.size == 0:
        return DEFAULT_DISPLAY_RANGE

    d_min = float(np.min(valid))
    d_max = float(np.max(valid))
    if d_min == d_max:
        d_max += 1e-5
    return d_min, d_max
