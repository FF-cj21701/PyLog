import importlib
import json
import os

from PySide6.QtCore import QEventLoop, QTimer, Slot

try:
    from ..ai_core.tool_result import normalize_tool_result
except ImportError:
    try:
        from plugins.ai_assistant.ai_core.tool_result import normalize_tool_result
    except ImportError:
        normalize_tool_result = importlib.import_module("ai_core.tool_result").normalize_tool_result

try:
    from .base_tool import BaseTool
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool
        register_tool = importlib.import_module("registry").register_tool

import pylog_api


def _pick_primary_payload(result, *preferred_keys):
    if not isinstance(result, dict):
        return result
    for key in preferred_keys:
        if key in result:
            return result.get(key)
    if "data" in result:
        return result.get("data")
    return result


def _wrap_api_result(tool_name, result, *preferred_keys):
    normalized = normalize_tool_result(tool_name, result)
    payload = normalized.to_dict()
    if payload.get("data") is None:
        payload["data"] = _pick_primary_payload(result, *preferred_keys)
    if not payload.get("content") and isinstance(result, dict):
        message = result.get("message")
        if isinstance(message, str) and message.strip():
            payload["content"] = message.strip()
    return payload


def _api_error(tool_name, error):
    return _wrap_api_result(tool_name, {"ok": False, "error": str(error)})


def _run_executor_request(tool_executor, signal_name, payload, timeout_ms=10000):
    loop = QEventLoop()
    result = {"error": "execution failed"}

    @Slot(str)
    def on_tool_executed(result_str):
        nonlocal result
        try:
            result = json.loads(result_str)
        except Exception:
            result = {"ok": False, "error": result_str or "executor returned invalid JSON"}
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)

    try:
        tool_executor.tool_executed.connect(on_tool_executed)
        getattr(tool_executor, signal_name).emit(payload)
        timer.start(timeout_ms)
        loop.exec()
    finally:
        try:
            tool_executor.tool_executed.disconnect(on_tool_executed)
        except Exception:
            pass
        timer.stop()

    return result


@register_tool
class ListWellsTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__(
            "list_wells",
            "List all wells available in the current project database",
            {
                "db_path": {
                    "type": "string",
                    "description": "Optional database file path",
                    "nullable": True,
                }
            },
            metadata={
                "required_args": [],
                "capability_tags": ["well_lookup"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window

    def execute(self, db_path=None):
        try:
            result = pylog_api.list_wells(db_path=db_path)
            return _wrap_api_result("list_wells", result, "wells")
        except Exception as e:
            return _api_error("list_wells", e)


class BaseWellTool(BaseTool):
    """Common base for tools requiring well lookup."""

    is_abstract = True

    def __init__(self, name, description, parameters, main_window=None, tool_executor=None):
        super().__init__(name, description, parameters)
        self.main_window = main_window
        self.tool_executor = tool_executor


@register_tool
class GetWellInfoTool(BaseWellTool):
    def __init__(self, main_window=None):
        super().__init__(
            "get_well_info",
            "Get detailed information about a specific well",
            {
                "well": {"type": "string", "description": "Well name or ID"},
                "db_path": {
                    "type": "string",
                    "description": "Optional database file path",
                    "nullable": True,
                },
            },
            main_window=main_window,
        )
        self.metadata["required_args"] = ["well"]
        self.metadata["capability_tags"] = ["well_lookup"]
        self.metadata["domain_tags"] = ["geoscience", "pylog"]

    def execute(self, well=None, db_path=None):
        if well is None:
            return _api_error("get_well_info", "well is required")

        try:
            result = pylog_api.get_well_info(well, db_path=db_path)
            return _wrap_api_result("get_well_info", result, "well", "info", "data")
        except Exception as e:
            return _api_error("get_well_info", e)


@register_tool
class ListCurvesTool(BaseWellTool):
    def __init__(self, main_window=None):
        super().__init__(
            "list_curves",
            "List all curves for a specific well",
            {
                "well": {"type": "string", "description": "Well name or ID"},
                "db_path": {
                    "type": "string",
                    "description": "Optional database file path",
                    "nullable": True,
                },
            },
            main_window=main_window,
        )
        self.metadata["required_args"] = ["well"]
        self.metadata["capability_tags"] = ["curve_lookup"]
        self.metadata["domain_tags"] = ["geoscience", "pylog"]

    def execute(self, well=None, db_path=None):
        if well is None:
            return _api_error("list_curves", "well is required")

        try:
            result = pylog_api.list_curves(well, db_path=db_path)
            return _wrap_api_result("list_curves", result, "curves")
        except Exception as e:
            return _api_error("list_curves", e)


@register_tool
class GetCurveInfoTool(BaseWellTool):
    def __init__(self, main_window=None):
        super().__init__(
            "get_curve_info",
            "Get metadata for a specific curve",
            {
                "well": {"type": "string", "description": "Well name or ID"},
                "curve_name": {"type": "string", "description": "Name of the curve"},
                "db_path": {
                    "type": "string",
                    "description": "Optional database file path",
                    "nullable": True,
                },
            },
            main_window=main_window,
        )
        self.metadata["required_args"] = ["well", "curve_name"]
        self.metadata["capability_tags"] = ["curve_lookup", "metadata_lookup"]
        self.metadata["domain_tags"] = ["geoscience", "pylog"]

    def execute(self, well=None, curve_name=None, db_path=None):
        if well is None or curve_name is None:
            return _api_error("get_curve_info", "well and curve_name are required")

        try:
            result = pylog_api.get_curve_info(well, curve_name, db_path=db_path)
            return _wrap_api_result("get_curve_info", result, "curve", "info", "data")
        except Exception as e:
            return _api_error("get_curve_info", e)


# GetDepthDataTool remains available as pylog_api.get_depth_data() for scripting,
# but is intentionally excluded from chat tools to avoid flooding raw numeric data.


@register_tool
class SaveCurveTool(BaseWellTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "save_curve",
            "Save a calculated curve back into the well database",
            {
                "well": {"type": "string", "description": "Well name or ID"},
                "curve_name": {"type": "string", "description": "Name for the new curve"},
                "values": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Numeric data values",
                },
                "unit": {"type": "string", "description": "Unit", "nullable": True},
                "folder": {"type": "string", "description": "Folder name", "nullable": True},
                "db_path": {
                    "type": "string",
                    "description": "Database path",
                    "nullable": True,
                },
            },
            main_window=main_window,
            tool_executor=tool_executor,
        )
        self.metadata["required_args"] = ["well", "curve_name", "values"]
        self.metadata["capability_tags"] = ["curve_write"]
        self.metadata["domain_tags"] = ["geoscience", "pylog"]

    def execute(self, well=None, curve_name=None, values=None, unit="", folder=None, db_path=None):
        if not well or not curve_name or values is None:
            return _api_error("save_curve", "well, curve_name and values are required")

        try:
            if self.tool_executor:
                payload = json.dumps(
                    {
                        "well": well,
                        "curve_name": curve_name,
                        "values": values,
                        "unit": unit,
                        "folder": folder,
                        "db_path": db_path,
                    }
                )
                result = _run_executor_request(self.tool_executor, "execute_save_curve", payload)
                return _wrap_api_result("save_curve", result, "curve_id", "data")

            result = pylog_api.save_curve(well, curve_name, values, unit, folder, db_path)
            return _wrap_api_result("save_curve", result, "curve_id", "data")
        except Exception as e:
            return _api_error("save_curve", e)


@register_tool
class AnalyzeDataTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__(
            "analyze_data",
            "Analyze numerical data and return statistics",
            {
                "values": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Numerical values to analyze",
                }
            },
            metadata={
                "required_args": ["values"],
                "capability_tags": ["numeric_analysis"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window

    def execute(self, values=None):
        if values is None:
            return _api_error("analyze_data", "values is required")

        try:
            result = pylog_api.analyze_data(values)
            return _wrap_api_result("analyze_data", {"ok": True, "analysis": result}, "analysis")
        except Exception as e:
            return _api_error("analyze_data", e)


@register_tool
class AnalyzeCurveTool(BaseWellTool):
    def __init__(self, main_window=None):
        super().__init__(
            "analyze_curve",
            "Analyze a curve and return statistics",
            {
                "well": {"type": "string", "description": "Well name or ID"},
                "curve_name": {"type": "string", "description": "Name of the curve to analyze"},
                "db_path": {
                    "type": "string",
                    "description": "Optional database file path",
                    "nullable": True,
                },
            },
            main_window=main_window,
        )
        self.metadata["required_args"] = ["well", "curve_name"]
        self.metadata["capability_tags"] = ["curve_analysis"]
        self.metadata["domain_tags"] = ["geoscience", "pylog"]

    def execute(self, well=None, curve_name=None, db_path=None):
        if well is None or curve_name is None:
            return _api_error("analyze_curve", "well and curve_name are required")

        try:
            result = pylog_api.analyze_curve(well, curve_name, db_path=db_path)
            return _wrap_api_result("analyze_curve", result, "analysis", "data")
        except Exception as e:
            return _api_error("analyze_curve", e)


@register_tool
class PlotTool(BaseWellTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "plot",
            "Unified plotting tool. Mode A: well plus curves. Mode B: data_list for in-memory plotting.",
            {
                "well": {
                    "type": "string",
                    "description": "Well name or ID",
                    "nullable": True,
                },
                "curves": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Database curve names to plot",
                    "nullable": True,
                },
                "data_list": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": "In-memory curve payloads",
                    "nullable": True,
                },
                "title": {"type": "string", "description": "Plot window title", "nullable": True},
                "accum_fill": {
                    "type": "boolean",
                    "description": "Enable cumulative fill",
                    "nullable": True,
                },
                "db_path": {"type": "string", "description": "Optional DB path", "nullable": True},
            },
            main_window=main_window,
            tool_executor=tool_executor,
        )
        self.metadata["argument_rules"] = [
            {"type": "at_least_one_of", "fields": ["curves", "data_list"]},
            {"type": "requires_when", "arg": "curves", "equals": "__non_empty__", "requires": "well"},
        ]
        self.metadata["capability_tags"] = ["plotting", "curve_visualization"]
        self.metadata["domain_tags"] = ["geoscience", "pylog"]
        self.metadata["usage_hint"] = (
            "Provide data_list for in-memory plotting, or provide well plus curves for database-backed plotting."
        )

    def execute(self, well=None, curves=None, data_list=None, title=None, db_path=None, **kwargs):
        try:
            if self.tool_executor:
                params = {
                    "well": well,
                    "curves": curves,
                    "data_list": data_list,
                    "title": title,
                    "db_path": db_path,
                }
                params.update(kwargs)
                result = _run_executor_request(self.tool_executor, "execute_plot", json.dumps(params))
                return _wrap_api_result("plot", result, "plot", "data")

            result = pylog_api.plot(
                well=well,
                curves=curves,
                data_list=data_list,
                title=title,
                db_path=db_path,
                **kwargs,
            )
            return _wrap_api_result("plot", result, "plot", "data")
        except Exception as e:
            return _api_error("plot", e)


@register_tool
class CreatePlotTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "create_plot",
            "Create a plot window from a normalized plot spec",
            {
                "plot_spec": {"type": "object", "description": "Normalized plot spec"},
            },
            metadata={
                "required_args": ["plot_spec"],
                "capability_tags": ["plotting", "plot_spec"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, plot_spec=None):
        if not plot_spec:
            return _api_error("create_plot", "plot_spec is required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_create_plot",
                    json.dumps({"plot_spec": plot_spec}),
                )
                return _wrap_api_result("create_plot", result, "title", "data")
            result = pylog_api.create_plot(plot_spec)
            return _wrap_api_result("create_plot", result, "title", "data")
        except Exception as e:
            return _api_error("create_plot", e)


@register_tool
class UpdatePlotTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "update_plot",
            "Apply plot commands such as curve style or track style updates",
            {
                "window_id": {"type": "string", "description": "Plot window title", "nullable": True},
                "commands": {"type": "array", "items": {"type": "object"}, "description": "Plot update commands"},
            },
            metadata={
                "required_args": ["commands"],
                "capability_tags": ["plotting", "plot_update"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, window_id=None, commands=None):
        if not commands:
            return _api_error("update_plot", "commands is required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_update_plot",
                    json.dumps({"window_id": window_id, "commands": commands}),
                )
                return _wrap_api_result("update_plot", result, "applied", "data")
            result = pylog_api.update_plot(window_id=window_id, commands=commands)
            return _wrap_api_result("update_plot", result, "applied", "data")
        except Exception as e:
            return _api_error("update_plot", e)


@register_tool
class ApplyCurveStyleTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "apply_curve_style",
            "Apply curve style settings to a plot curve",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "track": {"type": ["string", "number"], "description": "Track name or index"},
                "curve": {"type": ["string", "number"], "description": "Curve name/title or index"},
                "settings": {"type": "object", "description": "Curve style settings"},
            },
            metadata={
                "required_args": ["window_id", "track", "curve", "settings"],
                "capability_tags": ["plot_style", "curve_style"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, window_id=None, track=None, curve=None, settings=None):
        if window_id is None or track is None or curve is None or settings is None:
            return _api_error("apply_curve_style", "window_id, track, curve and settings are required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_apply_curve_style",
                    json.dumps({
                        "window_id": window_id,
                        "track": track,
                        "curve": curve,
                        "settings": settings,
                    }),
                )
                return _wrap_api_result("apply_curve_style", result, "applied", "data")
            result = pylog_api.apply_curve_style(window_id, track, curve, settings)
            return _wrap_api_result("apply_curve_style", result, "applied", "data")
        except Exception as e:
            return _api_error("apply_curve_style", e)


@register_tool
class ApplyTrackStyleTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "apply_track_style",
            "Apply track settings to a plot track",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "track": {"type": ["string", "number"], "description": "Track name or index"},
                "settings": {"type": "object", "description": "Track settings"},
            },
            metadata={
                "required_args": ["window_id", "track", "settings"],
                "capability_tags": ["plot_style", "track_style"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, window_id=None, track=None, settings=None):
        if window_id is None or track is None or settings is None:
            return _api_error("apply_track_style", "window_id, track and settings are required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_apply_track_style",
                    json.dumps({
                        "window_id": window_id,
                        "track": track,
                        "settings": settings,
                    }),
                )
                return _wrap_api_result("apply_track_style", result, "applied", "data")
            result = pylog_api.apply_track_style(window_id, track, settings)
            return _wrap_api_result("apply_track_style", result, "applied", "data")
        except Exception as e:
            return _api_error("apply_track_style", e)


@register_tool
class AddCurveToPlotTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "add_curve_to_plot",
            "Add a curve to an existing plot track or create a new track in the plot",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "well_id": {"type": "number", "description": "Well ID"},
                "curve_id": {"type": "number", "description": "Curve ID"},
                "track": {"type": ["string", "number"], "description": "Track name or index", "nullable": True},
                "db_path": {"type": "string", "description": "Database path", "nullable": True},
                "curve_settings": {"type": "object", "description": "Curve style settings", "nullable": True},
                "track_name": {"type": "string", "description": "New track name", "nullable": True},
                "track_width": {"type": "number", "description": "New track width", "nullable": True},
                "header_visible": {"type": "boolean", "description": "Whether header is visible", "nullable": True},
                "track_settings": {"type": "object", "description": "Track settings", "nullable": True},
            },
            metadata={
                "required_args": ["window_id", "well_id", "curve_id"],
                "capability_tags": ["plotting", "plot_update"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, window_id=None, well_id=None, curve_id=None, track=None, db_path=None, curve_settings=None, track_name=None, track_width=200, header_visible=True, track_settings=None):
        if window_id is None or well_id is None or curve_id is None:
            return _api_error("add_curve_to_plot", "window_id, well_id and curve_id are required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_update_plot",
                    json.dumps({
                        "window_id": window_id,
                        "commands": [{
                            "action": "add_curve",
                            "track": track,
                            "well_id": int(well_id),
                            "curve_id": int(curve_id),
                            "db_path": db_path,
                            "curve_settings": curve_settings or {},
                            "track_name": track_name,
                            "track_width": int(track_width or 200),
                            "header_visible": bool(header_visible),
                            "track_settings": track_settings or {},
                        }],
                    }),
                )
                return _wrap_api_result("add_curve_to_plot", result, "applied", "data")
            result = pylog_api.add_curve_to_plot(
                window_id,
                well_id=int(well_id),
                curve_id=int(curve_id),
                track=track,
                db_path=db_path,
                curve_settings=curve_settings or {},
                track_name=track_name,
                track_width=int(track_width or 200),
                header_visible=bool(header_visible),
                track_settings=track_settings or {},
            )
            return _wrap_api_result("add_curve_to_plot", result, "applied", "data")
        except Exception as e:
            return _api_error("add_curve_to_plot", e)


@register_tool
class RemoveCurveFromPlotTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "remove_curve_from_plot",
            "Remove a curve from a plot track",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "track": {"type": ["string", "number"], "description": "Track name or index"},
                "curve": {"type": ["string", "number"], "description": "Curve name/title or index"},
            },
            metadata={
                "required_args": ["window_id", "track", "curve"],
                "capability_tags": ["plotting", "plot_update"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, window_id=None, track=None, curve=None):
        if window_id is None or track is None or curve is None:
            return _api_error("remove_curve_from_plot", "window_id, track and curve are required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_update_plot",
                    json.dumps({
                        "window_id": window_id,
                        "commands": [{
                            "action": "remove_curve",
                            "track": track,
                            "curve": curve,
                        }],
                    }),
                )
                return _wrap_api_result("remove_curve_from_plot", result, "applied", "data")
            result = pylog_api.remove_curve_from_plot(window_id, track, curve)
            return _wrap_api_result("remove_curve_from_plot", result, "applied", "data")
        except Exception as e:
            return _api_error("remove_curve_from_plot", e)


@register_tool
class RemoveTrackFromPlotTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "remove_track_from_plot",
            "Remove a track from a plot",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "track": {"type": ["string", "number"], "description": "Track name or index"},
            },
            metadata={
                "required_args": ["window_id", "track"],
                "capability_tags": ["plotting", "plot_update"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, window_id=None, track=None):
        if window_id is None or track is None:
            return _api_error("remove_track_from_plot", "window_id and track are required")
        try:
            if self.tool_executor:
                result = _run_executor_request(
                    self.tool_executor,
                    "execute_update_plot",
                    json.dumps({
                        "window_id": window_id,
                        "commands": [{
                            "action": "remove_track",
                            "track": track,
                        }],
                    }),
                )
                return _wrap_api_result("remove_track_from_plot", result, "applied", "data")
            result = pylog_api.remove_track_from_plot(window_id, track)
            return _wrap_api_result("remove_track_from_plot", result, "applied", "data")
        except Exception as e:
            return _api_error("remove_track_from_plot", e)


@register_tool
class GetPlotDetailsTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "get_plot_details",
            "Get detailed information about a specific plot window including tracks and curves",
            {
                "title": {
                    "type": "string",
                    "description": "The title of the plot window to query",
                }
            },
            metadata={
                "required_args": ["title"],
                "capability_tags": ["plot_inspection"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, title=None):
        if not self.main_window:
            return _api_error("get_plot_details", "no main window")
        if not title:
            return _api_error("get_plot_details", "title is required")

        try:
            if self.tool_executor:
                result = _run_executor_request(self.tool_executor, "execute_get_plot_details", title)
                return _wrap_api_result("get_plot_details", result, "details")

            found = False
            for sub in self.main_window.mdi_area.subWindowList():
                if sub.windowTitle() != title:
                    continue
                widget = sub.widget()
                if hasattr(widget, "get_plot_details"):
                    return _wrap_api_result(
                        "get_plot_details",
                        {"ok": True, "details": widget.get_plot_details()},
                        "details",
                    )
                found = True
                break

            if not found:
                return _api_error("get_plot_details", f"Plot window with title '{title}' not found")
            return _api_error("get_plot_details", f"Window '{title}' is not a valid plot window")
        except Exception as e:
            return _api_error("get_plot_details", e)


@register_tool
class InspectApiTool(BaseTool):
    """
    Inspect the machine-readable signature and examples for a specific PyLog API function.
    """

    def __init__(self, main_window=None):
        super().__init__(
            "inspect_api",
            "Return the formal signature, parameter schema, and examples for a PyLog API function.",
            {
                "function_name": {
                    "type": "string",
                    "description": "The API function to inspect, for example plot or analyze_curve",
                }
            },
            metadata={
                "required_args": ["function_name"],
                "capability_tags": ["api_inspection"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )
        self.mw = main_window

    def execute(self, function_name: str):
        try:
            result = pylog_api.inspect_api(function_name)
            return _wrap_api_result("inspect_api", result, "parameters", "data")
        except Exception as e:
            return _api_error("inspect_api", e)
