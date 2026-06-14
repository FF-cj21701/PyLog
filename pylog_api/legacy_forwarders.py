"""Thin forwarding helpers kept for the legacy module surface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import numpy as np

from .api_metadata import API_METADATA


def inspect_api(name: str) -> Dict[str, Any]:
    """Return machine-readable signature and documentation for a specific API."""
    return API_METADATA.get(name, {"error": f"API function '{name}' not found in registry."})


def list_wells(db_path: Optional[str] = None) -> Dict[str, Any]:
    from pylog_api.well_info import list_wells as packaged_list_wells

    return packaged_list_wells(db_path=db_path)


def get_well_info(well: Union[str, int], db_path: Optional[str] = None) -> Dict[str, Any]:
    from pylog_api.well_info import get_well_info as packaged_get_well_info

    return packaged_get_well_info(well=well, db_path=db_path)


def list_curves(well: Union[str, int], db_path: Optional[str] = None) -> Dict[str, Any]:
    from pylog_api.data_access import list_curves as packaged_list_curves

    return packaged_list_curves(well=well, db_path=db_path)


def get_curve_info(
    well: Union[str, int],
    curve_name: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    from pylog_api.data_access import get_curve_info as packaged_get_curve_info

    return packaged_get_curve_info(well=well, curve_name=curve_name, db_path=db_path)


def get_curve_data(
    well: Union[str, int],
    curve_name: str,
    db_path: Optional[str] = None,
) -> Union[np.ndarray, Dict[str, Any]]:
    from pylog_api.data_access import get_curve_data as packaged_get_curve_data

    return packaged_get_curve_data(well=well, curve_name=curve_name, db_path=db_path)


def analyze_curve(well: Union[str, int], curve_name: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    from pylog_api.analysis import analyze_curve as packaged_analyze_curve

    return packaged_analyze_curve(well=well, curve_name=curve_name, db_path=db_path)


def analyze_data(values: Union[List[Any], np.ndarray], force_full: bool = False) -> Dict[str, Any]:
    from pylog_api.analysis import analyze_data as packaged_analyze_data

    return packaged_analyze_data(values=values, force_full=force_full)


def get_depth_data(
    well: Union[str, int],
    folder: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Union[np.ndarray, Dict[str, Any]]:
    from pylog_api.depth import get_depth_data as packaged_get_depth_data

    return packaged_get_depth_data(well=well, folder=folder, db_path=db_path)


def save_curve(
    well: Union[str, int],
    curve_name: str,
    values: Any,
    unit: str = "",
    folder: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    from pylog_api.writeback import save_curve as packaged_save_curve

    return packaged_save_curve(
        well=well,
        curve_name=curve_name,
        values=values,
        unit=unit,
        folder=folder,
        db_path=db_path,
    )


def plot(
    well: Optional[Union[str, int]] = None,
    curves: Optional[List[str]] = None,
    data_list: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
    title: str = "Log Plot 1",
    **kwargs,
) -> Dict[str, Any]:
    from pylog_api.plotting import plot as packaged_plot

    return packaged_plot(
        well=well,
        curves=curves,
        data_list=data_list,
        db_path=db_path,
        title=title,
        **kwargs,
    )
