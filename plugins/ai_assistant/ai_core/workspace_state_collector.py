from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


class WorkspaceStateCollector:
    """Collect lightweight context from the active PyLog workspace window."""

    def collect(self, main_window: Any) -> dict[str, Any] | None:
        if not main_window:
            return None

        subwindow = self._active_subwindow(main_window)
        if not subwindow:
            return None

        widget = self._subwindow_widget(subwindow)
        if not widget:
            return None

        title = self._window_title(subwindow, widget)
        window_type = self._infer_window_type(widget, title)
        state: dict[str, Any] = {
            "type": "plot_window_state",
            "active_window": {
                "title": title,
                "type": window_type,
            },
        }

        if window_type == "data_viewer":
            state.update(self._collect_data_viewer_state(widget))
        elif window_type == "plot":
            state.update(self._collect_plot_state(widget, title))
        else:
            return None

        return state

    def _active_subwindow(self, main_window: Any) -> Any:
        mdi_area = getattr(main_window, "mdi_area", None)
        if not mdi_area:
            return None
        active_subwindow = getattr(mdi_area, "activeSubWindow", None)
        if callable(active_subwindow):
            return self._safe_call(active_subwindow)
        return None

    def _subwindow_widget(self, subwindow: Any) -> Any:
        widget = getattr(subwindow, "widget", None)
        return self._safe_call(widget) if callable(widget) else widget

    def _window_title(self, subwindow: Any, widget: Any) -> str:
        return (
            self._safe_text(self._safe_call(getattr(subwindow, "windowTitle", None)))
            or self._safe_text(self._safe_call(getattr(widget, "windowTitle", None)))
            or self._safe_text(getattr(widget, "title", ""))
        )

    def _infer_window_type(self, widget: Any, title: str) -> str:
        class_name = widget.__class__.__name__.lower()
        text = f"{class_name} {title}".lower()
        if hasattr(widget, "_curve_entries") or "dataviewer" in text or "data viewer" in text:
            return "data_viewer"
        if hasattr(widget, "track_containers") or "logwidget" in text or "plot" in text:
            return "plot"
        return "unknown"

    def _collect_plot_state(self, widget: Any, title: str) -> dict[str, Any]:
        tracks = self._collect_tracks(widget)
        curve_names = [
            curve
            for track in tracks
            for curve in track.get("curves", [])
            if curve
        ]
        plot = {
            "title": title or self._first_attr(widget, "plot_title", "name"),
            "well": self._first_attr(widget, "well_name", "well", "current_well"),
            "db_path": self._first_attr(widget, "db_path", "database_path"),
            "depth_range": self._depth_range_from_attrs(widget),
            "track_count": len(tracks) if tracks else self._safe_len(getattr(widget, "track_containers", None)),
            "curve_count": len(curve_names),
            "selected_curves": curve_names,
            "tracks": tracks,
        }
        return {key: value for key, value in plot.items() if self._has_value(value)}

    def _collect_tracks(self, widget: Any) -> list[dict[str, Any]]:
        raw_tracks = getattr(widget, "track_containers", None) or getattr(widget, "tracks", None) or []
        tracks = []
        for index, track in enumerate(list(raw_tracks)[:8], start=1):
            track_name = self._first_attr(track, "track_name", "name") or f"Track {index}"
            curves = self._curve_names_from_track(track)
            track_state: dict[str, Any] = {"name": track_name}
            if curves:
                track_state["curves"] = curves
            depth_range = self._depth_range_from_attrs(track)
            if depth_range:
                track_state["depth_range"] = depth_range
            tracks.append(track_state)
        return tracks

    def _curve_names_from_track(self, track: Any) -> list[str]:
        plot_widget = getattr(track, "plot_widget", None)
        candidates = [
            getattr(track, "curve_names", None),
            getattr(track, "curves", None),
            getattr(plot_widget, "curve_names", None),
            getattr(plot_widget, "curves", None),
        ]
        names = []
        for candidate in candidates:
            for item in self._iter_items(candidate):
                name = self._curve_name(item)
                if name and name not in names:
                    names.append(name)
        return names

    def _collect_data_viewer_state(self, widget: Any) -> dict[str, Any]:
        entries = [entry for entry in self._iter_items(getattr(widget, "_curve_entries", None)) if isinstance(entry, Mapping)]
        curve_names = [self._curve_name(entry) for entry in entries]
        curve_names = [name for name in curve_names if name]

        model = getattr(widget, "model", None)
        table_state = {
            "row_count": self._safe_call(getattr(model, "rowCount", None)),
            "column_count": self._safe_call(getattr(model, "columnCount", None)),
            "visible_columns": self._column_names(model),
        }
        return {
            "active_window_type": "data_viewer",
            "depth_range": self._numeric_range(getattr(widget, "_depth_union", None)),
            "curve_count": len(curve_names),
            "selected_curves": curve_names,
            "table": {key: value for key, value in table_state.items() if self._has_value(value)},
        }

    def _column_names(self, model: Any) -> list[str]:
        columns = getattr(model, "columns", None) or getattr(model, "headers", None)
        names = []
        for column in self._iter_items(columns):
            name = self._curve_name(column) or self._safe_text(column)
            if name and name not in names:
                names.append(name)
        return names

    def _curve_name(self, item: Any) -> str:
        if isinstance(item, Mapping):
            for key in ("curve_name", "name", "label", "mnemonic", "display_name"):
                text = self._safe_text(item.get(key))
                if text:
                    return text
            return ""
        if isinstance(item, (list, tuple)) and item:
            return self._safe_text(item[1] if len(item) > 1 else item[0])
        for attr in ("curve_name", "name", "label", "mnemonic", "display_name"):
            text = self._safe_text(getattr(item, attr, ""))
            if text:
                return text
        return self._safe_text(item)

    def _depth_range_from_attrs(self, obj: Any) -> Any:
        for attr in ("depth_range", "view_depth_range"):
            value = getattr(obj, attr, None)
            if self._has_value(value):
                return value
        start = self._first_attr(obj, "depth_min", "min_depth", "custom_min_depth", "last_y_min")
        end = self._first_attr(obj, "depth_max", "max_depth", "custom_max_depth")
        if start is not None and end is not None:
            return {"min": start, "max": end}
        return None

    def _numeric_range(self, values: Any) -> dict[str, Any] | None:
        nums = []
        for item in self._iter_items(values):
            try:
                nums.append(float(item))
            except (TypeError, ValueError):
                continue
        if not nums:
            return None
        return {"min": min(nums), "max": max(nums)}

    def _first_attr(self, obj: Any, *attrs: str) -> Any:
        for attr in attrs:
            value = getattr(obj, attr, None)
            if value not in (None, ""):
                return value
        return None

    def _safe_len(self, value: Any) -> int:
        try:
            return len(value)
        except TypeError:
            return 0

    def _has_value(self, value: Any) -> bool:
        if value is None:
            return False
        try:
            if value == "":
                return False
        except Exception:
            pass
        if isinstance(value, (list, tuple, dict, set)):
            return bool(value)
        return True

    def _iter_items(self, value: Any) -> list[Any]:
        if value is None or isinstance(value, (str, bytes)):
            return []
        if isinstance(value, Mapping):
            return list(value.values())
        if isinstance(value, Iterable):
            try:
                return list(value)
            except TypeError:
                return []
        return []

    def _safe_call(self, fn: Any) -> Any:
        if not callable(fn):
            return None
        try:
            return fn()
        except TypeError:
            try:
                return fn(None)
            except Exception:
                return None
        except Exception:
            return None

    def _safe_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()
