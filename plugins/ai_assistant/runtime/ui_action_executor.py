from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional


class UiActionExecutor:
    """Execute whitelisted PyLog UI actions on the main thread."""

    MAX_ACTIONS = 20
    MAX_ACTION_BYTES = 64_000
    SUPPORTED_TYPES = {
        "create_plot",
        "update_plot",
        "open_data_viewer",
        "set_depth_range",
        "select_curve",
        "highlight_curve",
        "export_plot",
        "focus_window",
    }

    def __init__(self, main_window=None):
        self.main_window = main_window

    def execute_many(self, actions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized = list(actions or [])
        results: List[Dict[str, Any]] = []
        for index, action in enumerate(normalized[: self.MAX_ACTIONS]):
            result = self.execute(action)
            result.setdefault("action_index", index)
            if not result.get("ok"):
                result.setdefault("failed_action_index", index)
            results.append(result)
        for index, action in enumerate(normalized[self.MAX_ACTIONS :], start=self.MAX_ACTIONS):
            results.append({
                "ok": False,
                "type": action.get("type") if isinstance(action, dict) else "invalid",
                "action_index": index,
                "failed_action_index": index,
                "retryable": False,
                "error": f"UI action limit exceeded ({self.MAX_ACTIONS})",
            })
        return results

    def execute(self, action: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(action, dict):
            return self._error("invalid", "UI action must be an object", retryable=False)

        action_type = str(action.get("type") or "").strip()
        payload_error = self._validate_payload_size(action)
        if payload_error:
            return self._error(action_type or "unknown", payload_error, retryable=False)
        if action_type not in self.SUPPORTED_TYPES:
            return self._error(action_type or "unknown", f"Unsupported UI action type: {action_type or 'unknown'}")

        if action_type == "create_plot":
            return self._create_plot(action)
        if action_type == "update_plot":
            return self._update_plot(action)
        if action_type == "open_data_viewer":
            return self._open_data_viewer(action)
        if action_type == "highlight_curve":
            return self._highlight_curve(action)
        if action_type == "set_depth_range":
            return self._update_plot(action | {"commands": [{"action": "set_depth_range", "depth_range": action.get("depth_range")}]})
        if action_type == "select_curve":
            return self._update_plot(action | {"commands": [{"action": "select_curve", "track": action.get("track"), "curve": action.get("curve")}]})
        if action_type == "focus_window":
            return self._focus_window(action)
        return self._error("export_plot", "export_plot UI action is recognized but not implemented yet", retryable=False)

    def _create_plot(self, action: Dict[str, Any]) -> Dict[str, Any]:
        plot_spec = action.get("plot_spec")
        if not isinstance(plot_spec, dict):
            return self._error("create_plot", "plot_spec is required")

        from pylog_api import create_plot

        result = create_plot(plot_spec)
        return self._wrap_result("create_plot", result)

    def _update_plot(self, action: Dict[str, Any]) -> Dict[str, Any]:
        commands = action.get("commands")
        if not isinstance(commands, list) or not commands:
            return self._error("update_plot", "commands is required")

        from pylog_api import update_plot

        result = update_plot(window_id=action.get("window_id"), commands=commands)
        return self._wrap_result("update_plot", result)

    def _open_data_viewer(self, action: Dict[str, Any]) -> Dict[str, Any]:
        window = self.main_window
        if window is None or not hasattr(window, "new_data_viewer_window"):
            return self._error("open_data_viewer", "main window does not support Data Viewer actions")

        items = self._data_viewer_items_from_action(action)
        if not items:
            active = self._active_data_viewer()
            if active and hasattr(active, "get_workspace_state"):
                state = active.get_workspace_state()
                return {
                    "ok": True,
                    "type": "open_data_viewer",
                    "window_id": self._window_title_for_widget(active),
                    "active_window_type": "data_viewer",
                    "workspace_state": state,
                    "summary": "Using active Data Viewer selection",
                }
            return self._error("open_data_viewer", "open_data_viewer requires curve_ids, curves, or an active Data Viewer")

        if hasattr(window, "handle_open_data_viewer"):
            window.handle_open_data_viewer(items)
            viewer = self._active_data_viewer()
        else:
            viewer = window.new_data_viewer_window()
            for item in items:
                viewer.add_curve_request(
                    item.get("well_id"),
                    item.get("id"),
                    item.get("db_path"),
                    well_name=item.get("well_name"),
                    curve_name=item.get("name"),
                )

        state = viewer.get_workspace_state() if viewer and hasattr(viewer, "get_workspace_state") else {}
        return {
            "ok": True,
            "type": "open_data_viewer",
            "window_id": self._window_title_for_widget(viewer),
            "active_window_type": "data_viewer",
            "curve_count": state.get("curve_count", len(items)),
            "row_count": (state.get("table") or {}).get("row_count"),
            "column_count": (state.get("table") or {}).get("column_count"),
            "selection": action.get("selection") or {},
            "workspace_state": state,
            "summary": f"Opened Data Viewer with {len(items)} curve(s)",
        }

    def _highlight_curve(self, action: Dict[str, Any]) -> Dict[str, Any]:
        settings = dict(action.get("style") or action.get("settings") or {})
        if not settings:
            settings = {"line_width": 2}
        return self._update_plot({
            "type": "update_plot",
            "window_id": action.get("window_id"),
            "commands": [{
                "action": "apply_curve_style",
                "track": action.get("track"),
                "curve": action.get("curve"),
                "settings": settings,
            }],
        })

    def _focus_window(self, action: Dict[str, Any]) -> Dict[str, Any]:
        window_id = action.get("window_id")
        sub = self._find_subwindow(window_id)
        if not sub:
            return self._error("focus_window", f"Window not found: {window_id}")
        mdi = getattr(self.main_window, "mdi_area", None)
        if mdi and hasattr(mdi, "setActiveSubWindow"):
            mdi.setActiveSubWindow(sub)
        try:
            sub.show()
            sub.raise_()
        except Exception:
            pass
        return {"ok": True, "type": "focus_window", "window_id": window_id, "summary": f"Focused window {window_id}"}

    def _data_viewer_items_from_action(self, action: Dict[str, Any]) -> List[Dict[str, Any]]:
        well_id = action.get("well_id")
        db_path = action.get("db_path")
        well_name = action.get("well_name")
        items = []
        for curve_id in action.get("curve_ids") or []:
            items.append({
                "type": "curve",
                "id": curve_id,
                "well_id": well_id,
                "db_path": db_path,
                "name": str(curve_id),
                "well_name": well_name,
            })
        if items:
            return items

        curves = action.get("curves") or []
        if not curves:
            return []
        return self._resolve_curve_names_for_data_viewer(action, curves)

    def _resolve_curve_names_for_data_viewer(self, action: Dict[str, Any], curves: List[Any]) -> List[Dict[str, Any]]:
        from scripts.utils.curve_resolution import resolve_curve_row
        from scripts.utils.well_queries import build_folder_map, resolve_well_context

        well = action.get("well") or action.get("well_name") or action.get("well_id")
        context, error = resolve_well_context(well, db_path=action.get("db_path"))
        if error or not context:
            return []
        db = context["db"]
        well_id = context["resolved_well_id"]
        curves_meta = db.get_curves(well_id)
        folder_map = build_folder_map(db, well_id)
        items = []
        for raw_name in curves:
            resolved = resolve_curve_row(str(raw_name), curves_meta, folder_map)
            if not resolved.get("ok"):
                continue
            row = resolved.get("row")
            if not row:
                continue
            items.append({
                "type": "curve",
                "id": row[0],
                "well_id": well_id,
                "db_path": context["resolved_db_path"],
                "name": str(raw_name),
                "well_name": context.get("well_name"),
            })
        return items

    def _active_data_viewer(self):
        mdi = getattr(self.main_window, "mdi_area", None)
        if not mdi or not hasattr(mdi, "activeSubWindow"):
            return None
        sub = mdi.activeSubWindow()
        widget = sub.widget() if sub and hasattr(sub, "widget") else None
        if widget and widget.__class__.__name__ == "DataViewerWidget":
            return widget
        try:
            for candidate in reversed(mdi.subWindowList()):
                widget = candidate.widget()
                if widget.__class__.__name__ == "DataViewerWidget":
                    return widget
        except Exception:
            return None
        return None

    def _find_subwindow(self, window_id: Optional[str]):
        mdi = getattr(self.main_window, "mdi_area", None)
        if not mdi or not window_id:
            return None
        for sub in mdi.subWindowList():
            try:
                if sub.windowTitle() == window_id:
                    return sub
            except Exception:
                continue
        return None

    @staticmethod
    def _window_title_for_widget(widget) -> str:
        if not widget:
            return ""
        try:
            return widget.window().windowTitle()
        except Exception:
            return ""

    def _validate_payload_size(self, action: Dict[str, Any]) -> Optional[str]:
        try:
            size = len(json.dumps(action, ensure_ascii=False))
        except Exception:
            return "UI action payload must be JSON serializable"
        if size > self.MAX_ACTION_BYTES:
            return f"UI action payload is too large ({size} bytes > {self.MAX_ACTION_BYTES})"
        return None

    @staticmethod
    def _error(action_type: str, error: str, *, retryable: bool = True) -> Dict[str, Any]:
        return {
            "ok": False,
            "type": action_type,
            "error": error,
            "summary": error,
            "retryable": retryable,
            "recommended_next_tool": "get_script_job" if retryable else None,
        }

    @staticmethod
    def _wrap_result(action_type: str, result: Any) -> Dict[str, Any]:
        if isinstance(result, dict):
            payload = dict(result)
        else:
            payload = {"ok": bool(result), "data": result}
        payload.setdefault("ok", not bool(payload.get("error")))
        payload["type"] = action_type
        payload.setdefault("summary", payload.get("message") or payload.get("error") or f"{action_type} completed")
        return payload
