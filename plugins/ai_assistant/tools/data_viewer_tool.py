try:
    from .base_tool import BaseTool
    from .registry import register_tool
except ImportError:
    from plugins.ai_assistant.tools.base_tool import BaseTool
    from plugins.ai_assistant.tools.registry import register_tool


@register_tool
class GetActiveDataViewerSelectionTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "get_active_data_viewer_selection",
            "Read the currently selected rows and columns from the active Data Viewer table.",
            {
                "max_rows": {
                    "type": "integer",
                    "description": "Maximum selected table rows to return. Defaults to 50.",
                },
                "include_stats": {
                    "type": "boolean",
                    "description": "Whether to include numeric stats for selected columns. Defaults to true.",
                },
            },
            metadata={
                "capability_tags": ["data_viewer", "data_inspection", "table_selection"],
                "domain_tags": ["geoscience", "pylog"],
                "keywords": [
                    "data viewer selection",
                    "selected table data",
                    "analyze selected rows",
                    "读取DataViewer选中数据",
                ],
                "usage_hint": "Use when the user asks to inspect or analyze selected Data Viewer cells.",
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, max_rows=50, include_stats=True):
        widget = self._active_data_viewer()
        if widget is None:
            return {"ok": False, "error": "No active Data Viewer window."}
        if not hasattr(widget, "get_selection_payload"):
            return {"ok": False, "error": "Active Data Viewer does not expose selection data."}
        try:
            return widget.get_selection_payload(max_rows=max_rows, include_stats=include_stats)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _active_data_viewer(self):
        mdi_area = getattr(self.main_window, "mdi_area", None)
        if mdi_area is None:
            return None
        active_subwindow = getattr(mdi_area, "activeSubWindow", None)
        subwindow = active_subwindow() if callable(active_subwindow) else None
        if subwindow is None:
            return None
        widget_fn = getattr(subwindow, "widget", None)
        widget = widget_fn() if callable(widget_fn) else widget_fn
        if widget is not None and widget.__class__.__name__ == "DataViewerWidget":
            return widget
        return widget if hasattr(widget, "get_selection_payload") else None
