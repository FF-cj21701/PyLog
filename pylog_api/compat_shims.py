"""Thin compatibility shims kept for legacy entry points."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

from scripts.utils.curve_resolution import curve_row_to_dict as shared_curve_row_to_dict
from scripts.utils.plot_value_utils import compute_auto_display_range as shared_compute_auto_display_range
from scripts.utils.well_queries import (
    resolve_optional_db_path_for_well as shared_resolve_optional_db_path_for_well,
    resolve_well_id as shared_resolve_well_id,
)

if TYPE_CHECKING:
    from scripts.data.db_manager import DBManager


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def legacy_resolve_optional_db_path_for_well(
    well: Union[str, int],
    db_path: Optional[str] = None,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Legacy-compatible db-path resolution using the packaged project data dir."""
    return shared_resolve_optional_db_path_for_well(well, db_path=db_path, data_dir=DATA_DIR)


def legacy_compute_auto_display_range(values, *, is_image: bool = False, is_log: bool = False):
    """Legacy-compatible wrapper around the shared plotting range helper."""
    return shared_compute_auto_display_range(values, is_image=is_image, is_log=is_log)


def legacy_curve_row_to_dict(row: tuple, folder_map: Optional[Dict[int, str]] = None) -> Dict[str, Any]:
    """Legacy-compatible wrapper around the shared curve-row serializer."""
    return shared_curve_row_to_dict(row, folder_map)


def legacy_resolve_well_id(
    db: "DBManager",
    well: Union[str, int],
) -> Tuple[Optional[int], Dict[str, Any]]:
    """Legacy-compatible wrapper around the shared well-resolution helper."""
    return shared_resolve_well_id(db, well)
