from __future__ import annotations

import importlib
import os
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .db_manager import DBManager
from ..utils.well_metadata import get_well_export_snapshot
from ..utils.well_queries import DEPTH_MNEMONICS, find_depth_curve_row


ROOT_FRAME_NAME = "ROOT"
UNIT_ALIASES = {
    "API": "dAPI",
    "GAPI": "gAPI",
    "NAPI": "nAPI",
    "OHM.M": "ohm",
    "OHM-M": "ohm",
    "OHMM": "ohm",
    "G/CM3": "g",
    "G/CC": "g",
    "G_CM3": "g",
    "US/FT": "us",
    "US/F": "us",
    "US/M": "us",
}


def export_well_to_dlis(
    well_context: dict,
    selected_curves: Sequence[dict],
    output_path: str,
    dliswriter_module=None,
    progress_callback=None,
) -> Dict[str, Any]:
    """Export selected curves from a well snapshot into a DLIS file."""
    if not well_context:
        return {"ok": False, "error": "Missing well export context."}
    if not selected_curves:
        return {"ok": False, "error": "No curves selected for export."}
    if not output_path:
        return {"ok": False, "error": "Missing output path."}

    writer_module = _load_dliswriter_module() if dliswriter_module is None else dliswriter_module
    if writer_module is None:
        return {
            "ok": False,
            "error": "DLIS export dependency 'dliswriter' is not installed.",
            "action_hint": "Install 'dliswriter' to enable DLIS export.",
        }

    db_path = well_context.get("db_path")
    well_id = well_context.get("well_id")
    well_name = well_context.get("well_name") or "Unknown"
    snapshot = well_context.get("snapshot")
    if not snapshot:
        db = DBManager(db_path)
        snapshot = get_well_export_snapshot(db, db_path, well_id)

    curves_by_id = {curve["id"]: curve for curve in snapshot.get("curves", [])}
    selected_ids = {curve["id"] for curve in selected_curves if curve.get("id") in curves_by_id}
    if not selected_ids:
        return {"ok": False, "error": "Selected curves could not be resolved in the target well."}

    selected_rows = [curves_by_id[curve_id] for curve_id in selected_ids]
    rows_by_frame = defaultdict(list)
    for row in selected_rows:
        rows_by_frame[row.get("folder") or ROOT_FRAME_NAME].append(row)

    auto_added_depth_ids: set[int] = set()
    curve_rows = snapshot.get("curve_rows", [])
    folder_map = snapshot.get("folder_map", {})
    for frame_name in list(rows_by_frame.keys()):
        frame_rows = rows_by_frame[frame_name]
        if any(_is_depth_curve(row.get("name")) for row in frame_rows):
            continue

        source_folder = None if frame_name == ROOT_FRAME_NAME else frame_name
        depth_row = find_depth_curve_row(curve_rows, folder_map=folder_map, folder=source_folder)
        if depth_row and depth_row[0] not in selected_ids:
            depth_curve = curves_by_id.get(depth_row[0])
            if depth_curve:
                rows_by_frame[frame_name].insert(0, depth_curve)
                auto_added_depth_ids.add(depth_curve["id"])

    writer = _create_writer(writer_module)
    if hasattr(writer, "progress_callback"):
        writer.progress_callback = progress_callback
    _set_well_name(writer, well_name)

    exported_count = 0
    skipped_multidim: List[str] = []
    unit_warnings: List[str] = []
    exported_curve_labels: List[str] = []

    total_candidates = sum(len(rows) for rows in rows_by_frame.values())
    processed_candidates = 0

    for frame_name in sorted(rows_by_frame.keys(), key=lambda value: (value != ROOT_FRAME_NAME, value.upper())):
        original_frame_rows = rows_by_frame[frame_name]
        exportable_rows = []
        pending_depth_rows = []
        for row in original_frame_rows:
            data = row.get("data")
            if data is None:
                continue
            array = np.asarray(data)
            if array.ndim < 1 or array.ndim > 2:
                skipped_multidim.append(_curve_path_label(row))
                continue
            if row.get("id") in auto_added_depth_ids:
                pending_depth_rows.append(row)
            else:
                exportable_rows.append(row)

        if exportable_rows and pending_depth_rows:
            exportable_rows = pending_depth_rows + exportable_rows

        if not exportable_rows:
            continue

        frame_handle = _add_frame(writer, frame_name)
        for row in exportable_rows:
            processed_candidates += 1
            array = np.asarray(row.get("data"))
            curve_label = _curve_path_label(row)
            if progress_callback:
                progress_callback(
                    {
                        "current": processed_candidates,
                        "total": total_candidates,
                        "curve": curve_label,
                        "frame": frame_name,
                        "phase": "preparing_curve",
                    }
                )
            _add_curve(
                frame_handle,
                row.get("name"),
                array,
                unit=_normalize_unit(row.get("unit"), writer_module, unit_warnings, row),
                is_index=_is_depth_curve(row.get("name")),
            )
            exported_count += 1
            exported_curve_labels.append(curve_label)

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    if progress_callback:
        progress_callback(
            {
                "current": 0,
                "total": 0,
                "curve": os.path.basename(output_path),
                "frame": None,
                "phase": "writing_file",
            }
        )
    _write_file(writer, output_path)

    result = {
        "ok": True,
        "exported_curve_count": exported_count,
        "exported_curves": exported_curve_labels,
        "auto_added_depth_ids": sorted(auto_added_depth_ids),
        "skipped_multidim": skipped_multidim,
        "output_path": output_path,
    }
    if skipped_multidim:
        result["warning"] = (
            "Some curves were skipped because the configured DLIS writer adapter currently supports only 1D and 2D curves."
        )
    if unit_warnings:
        unit_warning = "Some curve units were normalized or omitted for DLIS compatibility."
        result["unit_warnings"] = unit_warnings
        result["warning"] = f"{result.get('warning', '')}\n{unit_warning}".strip()
    return result


def _curve_path_label(row: dict) -> str:
    folder = row.get("folder")
    if folder:
        return f"{folder}/{row.get('name')}"
    return str(row.get("name"))


def _normalize_unit(unit: Optional[str], writer_module, unit_warnings: List[str], row: dict) -> Optional[str]:
    raw = str(unit or "").strip()
    if not raw:
        return None

    allowed_units = _get_allowed_units(writer_module)
    if raw in allowed_units:
        return raw

    normalized_key = raw.upper().replace(" ", "")
    alias = UNIT_ALIASES.get(normalized_key)
    if alias and alias in allowed_units:
        unit_warnings.append(f"{_curve_path_label(row)}: '{raw}' -> '{alias}'")
        return alias

    compact = raw.replace(" ", "")
    if compact in allowed_units:
        unit_warnings.append(f"{_curve_path_label(row)}: '{raw}' -> '{compact}'")
        return compact

    unit_warnings.append(f"{_curve_path_label(row)}: dropped unsupported unit '{raw}'")
    return None


def _get_allowed_units(writer_module) -> set[str]:
    try:
        unit_enum = getattr(getattr(writer_module, "utils"), "enums").Unit
    except Exception:
        try:
            unit_enum = writer_module.enums.Unit
        except Exception:
            return set()

    allowed = set()
    for name in dir(unit_enum):
        if name.startswith("_"):
            continue
        try:
            value = getattr(unit_enum, name)
            enum_value = getattr(value, "value", None)
            if isinstance(enum_value, str):
                allowed.add(enum_value)
        except Exception:
            continue
    return allowed


def _is_depth_curve(name: Optional[str]) -> bool:
    if not name:
        return False
    upper = str(name).upper()
    return upper in DEPTH_MNEMONICS or "DEPT" in upper


def _load_dliswriter_module():
    try:
        return importlib.import_module("dliswriter")
    except Exception:
        return None


def _create_writer(module):
    if hasattr(module, "DLISFile"):
        writer = module.DLISFile()
        if hasattr(writer, "add_logical_file") and not hasattr(writer, "add_frame"):
            return _DlisWriterV1Adapter(module, writer)
        return writer
    if hasattr(module, "dlis") and hasattr(module.dlis, "DLISFile"):
        return module.dlis.DLISFile()
    raise RuntimeError("Unsupported dliswriter module: missing DLISFile.")


def _set_well_name(writer, well_name: str):
    candidates: Sequence[Tuple[str, Any]] = (
        ("set_well_name", lambda target: target.set_well_name(well_name)),
        ("set_origin", lambda target: target.set_origin({"well_name": well_name})),
    )
    for attr_name, action in candidates:
        if hasattr(writer, attr_name):
            try:
                action(writer)
                return
            except Exception:
                pass

    for attr_name in ("well_name", "name"):
        if hasattr(writer, attr_name):
            try:
                setattr(writer, attr_name, well_name)
                return
            except Exception:
                pass


def _add_frame(writer, frame_name: str):
    if hasattr(writer, "add_frame"):
        return writer.add_frame(frame_name)
    if hasattr(writer, "new_frame"):
        return writer.new_frame(frame_name)
    if hasattr(writer, "create_frame"):
        return writer.create_frame(frame_name)
    raise RuntimeError("Unsupported dliswriter module: missing frame creation API.")


def _add_curve(frame_handle, name: str, data: np.ndarray, unit: str = "", is_index: bool = False):
    array = np.asarray(data)
    curve_kwargs = {"unit": unit} if unit is not None else {}

    candidate_calls = [
        lambda target: target.add_channel(name, array, **curve_kwargs),
        lambda target: target.add_curve(name, array, unit=unit),
        lambda target: target.add_curve(name=name, values=array, unit=unit),
        lambda target: target.add_channel(name=name, values=array, unit=unit),
    ]

    for call in candidate_calls:
        try:
            result = call(frame_handle)
            _mark_index_curve(frame_handle, result, name, is_index=is_index)
            return result
        except TypeError:
            continue
        except AttributeError:
            continue

    raise RuntimeError(f"Unsupported dliswriter frame API for curve '{name}'.")


def _mark_index_curve(frame_handle, channel_handle, name: str, is_index: bool = False):
    if not is_index:
        return
    for attr_name in ("set_index_curve", "set_index_channel"):
        if hasattr(frame_handle, attr_name):
            try:
                getattr(frame_handle, attr_name)(channel_handle or name)
                return
            except Exception:
                pass
    for attr_name in ("index_curve", "index_channel"):
        if hasattr(frame_handle, attr_name):
            try:
                setattr(frame_handle, attr_name, channel_handle or name)
                return
            except Exception:
                pass


def _write_file(writer, output_path: str):
    for attr_name in ("write", "save"):
        if hasattr(writer, attr_name):
            getattr(writer, attr_name)(output_path)
            return
    raise RuntimeError("Unsupported dliswriter module: missing write/save API.")


class _DlisWriterV1Adapter:
    """Compatibility adapter for dliswriter 1.x structured API."""

    def __init__(self, module, writer):
        self.module = module
        self.writer = writer
        self.logical_file = writer.add_logical_file()
        self.origin = None
        self.frames = []
        self.progress_callback = None

    def set_well_name(self, well_name: str):
        if self.origin is None:
            self.origin = self.logical_file.add_origin(
                name=f"{well_name}_ORIGIN",
                well_name=well_name,
                well_id=well_name,
                file_type="DLIS",
                product="PyLog",
                company="PyLog",
            )
        else:
            self.origin.well_name.value = well_name
            self.origin.well_id.value = well_name

    def add_frame(self, frame_name: str):
        frame = _DlisFrameV1Adapter(self.logical_file, frame_name)
        self.frames.append(frame)
        return frame

    def write(self, output_path: str):
        for frame in self.frames:
            frame.finalize()
        with _patch_dliswriter_progress(self.progress_callback):
            self.writer.write(output_path, output_chunk_size=8192)


class _DlisFrameV1Adapter:
    def __init__(self, logical_file, frame_name: str):
        self.logical_file = logical_file
        self.frame_name = frame_name
        self.channels = []
        self.index_channel = None

    def add_channel(self, name: str, values: np.ndarray, unit: str = ""):
        channel = self.logical_file.add_channel(
            name=name,
            data=np.asarray(values),
            units=unit or None,
        )
        self.channels.append(channel)
        return channel

    def set_index_curve(self, channel_handle):
        self.index_channel = channel_handle

    def set_index_channel(self, channel_handle):
        self.index_channel = channel_handle

    @property
    def index_curve(self):
        return self.index_channel

    @index_curve.setter
    def index_curve(self, value):
        self.index_channel = value

    @property
    def index_channel(self):
        return self._index_channel if hasattr(self, "_index_channel") else None

    @index_channel.setter
    def index_channel(self, value):
        self._index_channel = value

    def finalize(self):
        if not self.channels or getattr(self, "_finalized", False):
            return
        index_type = "BOREHOLE-DEPTH" if self._index_channel is not None else None
        self.logical_file.add_frame(
            name=self.frame_name,
            channels=self.channels,
            index_type=index_type,
        )
        self._finalized = True


@contextmanager
def _patch_dliswriter_progress(progress_callback):
    if progress_callback is None:
        yield
        return

    try:
        writer_module = importlib.import_module("dliswriter.file.writer")
    except Exception:
        yield
        return

    original_progressbar = getattr(writer_module, "progressbar", None)
    if original_progressbar is None:
        yield
        return

    def callback_progressbar(iterable, max_value=None, *args, **kwargs):
        total = max_value
        if total is None:
            try:
                total = len(iterable)
            except Exception:
                total = 0

        inner_iterable = original_progressbar(iterable, max_value=max_value, *args, **kwargs)
        for index, item in enumerate(inner_iterable, start=1):
            progress_callback(
                {
                    "current": index,
                    "total": total,
                    "curve": None,
                    "frame": None,
                    "phase": "writing_records",
                }
            )
            yield item

    writer_module.progressbar = callback_progressbar
    try:
        yield
    finally:
        writer_module.progressbar = original_progressbar
