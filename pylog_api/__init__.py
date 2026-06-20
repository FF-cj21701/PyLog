"""Packaged public interface for the PyLog domain API."""

from __future__ import annotations

import sys
from types import ModuleType

from .api_reflection import inspect_api
from .analysis import analyze_curve
from .analysis import analyze_data
from .core import get_public_api_names
from .core import load_legacy_module
from .data_access import get_curve_data
from .data_access import get_curve_info
from .data_access import list_curves
from .depth import get_depth_data
from .plotting import plot
from .plotting import create_plot
from .plotting import update_plot
from .plotting import apply_curve_style
from .plotting import apply_track_style
from .plotting import add_curve_to_plot
from .plotting import remove_curve_from_plot
from .plotting import remove_track_from_plot
from .plotting import plot_from_db
from .plotting import plot_log_curves
from .plotting import plot_curves
from .well_info import get_well_info
from .well_info import list_wells
from .writeback import save_curve

_LEGACY_MODULE = load_legacy_module()
for _name in ("get_depth_data", "save_curve", "plot"):
    setattr(_LEGACY_MODULE, f"_original_{_name}", getattr(_LEGACY_MODULE, _name))
_LEGACY_MODULE._original__plot_from_db = _LEGACY_MODULE._plot_from_db
_LEGACY_MODULE._original__plot_log_curves = _LEGACY_MODULE._plot_log_curves
_LEGACY_MODULE.inspect_api = inspect_api
_LEGACY_MODULE.analyze_curve = analyze_curve
_LEGACY_MODULE.analyze_data = analyze_data
_LEGACY_MODULE.get_curve_data = get_curve_data
_LEGACY_MODULE.get_curve_info = get_curve_info
_LEGACY_MODULE.get_depth_data = get_depth_data
_LEGACY_MODULE.get_well_info = get_well_info
_LEGACY_MODULE.list_curves = list_curves
_LEGACY_MODULE.list_wells = list_wells
_LEGACY_MODULE.plot = plot
_LEGACY_MODULE.create_plot = create_plot
_LEGACY_MODULE.update_plot = update_plot
_LEGACY_MODULE.apply_curve_style = apply_curve_style
_LEGACY_MODULE.apply_track_style = apply_track_style
_LEGACY_MODULE.add_curve_to_plot = add_curve_to_plot
_LEGACY_MODULE.remove_curve_from_plot = remove_curve_from_plot
_LEGACY_MODULE.remove_track_from_plot = remove_track_from_plot
_LEGACY_MODULE.plot_from_db = plot_from_db
_LEGACY_MODULE.plot_log_curves = plot_log_curves
_LEGACY_MODULE.plot_curves = plot_curves
_LEGACY_MODULE.save_curve = save_curve
__all__ = sorted(
    set(get_public_api_names())
    | {
        "analyze_curve",
        "analyze_data",
        "add_curve_to_plot",
        "apply_curve_style",
        "apply_track_style",
        "create_plot",
        "get_curve_data",
        "get_curve_info",
        "get_depth_data",
        "get_well_info",
        "inspect_api",
        "list_curves",
        "list_wells",
        "plot",
        "plot_curves",
        "plot_from_db",
        "plot_log_curves",
        "remove_curve_from_plot",
        "remove_track_from_plot",
        "save_curve",
        "update_plot",
    }
)


class _PylogApiPackage(ModuleType):
    """Package module proxy that stays behaviorally compatible with the legacy module."""

    def __getattr__(self, name: str):
        try:
            return getattr(_LEGACY_MODULE, name)
        except AttributeError as exc:
            raise AttributeError(f"module 'pylog_api' has no attribute '{name}'") from exc

    def __setattr__(self, name: str, value):
        ModuleType.__setattr__(self, name, value)
        if name not in {"__class__", "__dict__", "__spec__", "__loader__", "__package__"}:
            setattr(_LEGACY_MODULE, name, value)

    def __dir__(self):
        return sorted(set(ModuleType.__dir__(self)) | set(dir(_LEGACY_MODULE)) | set(__all__))


sys.modules[__name__].__class__ = _PylogApiPackage
