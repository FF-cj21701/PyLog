import json

from ..ai_core.config import AIConfig
from ..services.fracture_detection_service import (
    FRACTURE_TYPES,
    FractureDetectionRequest,
    get_fracture_detection_manager,
)
from ..services.fracture_vision_service import FractureVisionPipeline
from .base_tool import BaseTool
from .pylog_api_tool import _api_error, _run_executor_request, _wrap_api_result
from .registry import register_tool


def _plot_details(main_window, tool_executor, window_id):
    if tool_executor:
        result = _run_executor_request(tool_executor, "execute_get_plot_details", window_id)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Unable to inspect plot")
        return result.get("details") or {}
    if not main_window or not hasattr(main_window, "mdi_area"):
        raise RuntimeError("no main window")
    for sub in main_window.mdi_area.subWindowList():
        if sub.windowTitle() == window_id:
            widget = sub.widget()
            if hasattr(widget, "get_plot_details"):
                return widget.get_plot_details()
            raise RuntimeError(f"Window '{window_id}' is not a plot window")
    raise RuntimeError(f"Plot window with title '{window_id}' not found")


def _plot_widget(main_window, window_id):
    if not main_window or not hasattr(main_window, "mdi_area"):
        raise RuntimeError("no main window")
    for sub in main_window.mdi_area.subWindowList():
        if sub.windowTitle() in (window_id, f"Plot: {window_id}", f"Log Plot {window_id}"):
            return sub.widget()
    raise RuntimeError(f"Plot window with title '{window_id}' not found")


def _render_analysis_input(main_window, tool_executor, request):
    payload = {
        "window_id": request.window_id,
        "tracks": list(request.tracks),
        "depth_start": request.depth_start,
        "depth_end": request.depth_end,
        "width": 1600,
        "height": 1600,
        "include_depth_track": True,
        "preserve_aspect": True,
        "respect_current_vertical_scale": True,
    }
    if tool_executor:
        result = _run_executor_request(
            tool_executor,
            "execute_render_analysis_tracks",
            json.dumps(payload),
            timeout_ms=30000,
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Unable to render analysis tracks")
        return {"data_url": result["data_url"], "metadata": result["metadata"]}
    rendered = _plot_widget(main_window, request.window_id).render_analysis_tracks(
        request.tracks,
        request.depth_start,
        request.depth_end,
        width=1600,
        height=1600,
        include_depth_track=True,
        preserve_aspect=True,
        respect_current_vertical_scale=True,
    )
    import base64
    return {
        "data_url": "data:image/png;base64," + base64.b64encode(rendered["png_bytes"]).decode("ascii"),
        "metadata": rendered["metadata"],
    }


def _apply_detection_results(main_window, tool_executor, request, annotations, run_id):
    payload = {
        "window_id": request.window_id,
        "target_image_track": request.target_image_track,
        "annotations": annotations,
        "run_id": run_id,
    }
    if tool_executor:
        result = _run_executor_request(
            tool_executor,
            "execute_apply_fracture_detection_results",
            json.dumps(payload),
            timeout_ms=30000,
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "Unable to apply fracture results")
        return result
    widget = _plot_widget(main_window, request.window_id)
    if hasattr(widget, "start_ai_fracture_playback"):
        return widget.start_ai_fracture_playback(
            run_id,
            request.target_image_track,
            annotations,
        )
    applied = widget.apply_ai_fracture_results(request.target_image_track, annotations)
    return {"ok": True, "applied_count": len(applied), "completed_immediately": True}


def _track_aliases(details):
    aliases = {}
    for item in details.get("tracks", []):
        for alias in (item.get("name"), item.get("label")):
            if alias:
                aliases[str(alias)] = item
    return aliases


def _selected_plot_tracks(details, track_names):
    requested = list(dict.fromkeys(str(name).strip() for name in (track_names or []) if str(name).strip()))
    aliases = _track_aliases(details)
    missing = [name for name in requested if name not in aliases]
    if missing:
        raise ValueError(f"Plot track(s) not found: {', '.join(missing)}")
    selected_ids = {id(aliases[name]) for name in requested}
    return [track for track in details.get("tracks", []) if id(track) in selected_ids]


def _image_metadata(details, track_names=None):
    selected = _selected_plot_tracks(details, track_names) if track_names else details.get("tracks", [])
    image_tracks = []
    analysis_tracks = []
    for track in selected:
        image_curves = [curve for curve in track.get("curves", []) if curve.get("is_image")]
        analysis_tracks.append({
            "index": track.get("index"),
            "name": track.get("name"),
            "label": track.get("label") or track.get("name"),
            "is_image": bool(image_curves),
            "curves": track.get("curves", []),
        })
        if image_curves:
            image_tracks.append({**track, "curves": image_curves})
    return {
        "window_id": details.get("window_title"),
        "well_name": details.get("well_name"),
        "visible_depth_range": details.get("visible_depth_range"),
        "borehole_diameter_in": details.get("borehole_diameter_in", 8.0),
        "fracture_types": list(FRACTURE_TYPES),
        "existing_fracture_count": details.get("existing_fracture_count", 0),
        "analysis_tracks": analysis_tracks,
        "image_tracks": image_tracks,
        "pipeline_ready": get_fracture_detection_manager().pipeline_ready or AIConfig().is_vision_configured(),
    }


class _FractureTool(BaseTool):
    is_abstract = True

    def __init__(self, name, description, args_schema, main_window=None, tool_executor=None, metadata=None):
        super().__init__(name, description, args_schema, metadata=metadata)
        self.main_window = main_window
        self.tool_executor = tool_executor


@register_tool
class GetBoreholeImageMetadataTool(_FractureTool):
    is_abstract = False

    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "get_borehole_image_metadata",
            "Inspect image tracks and fracture-picking context in an open plot window.",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "tracks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional plot track names to inspect",
                    "nullable": True,
                },
            },
            main_window,
            tool_executor,
            metadata={
                "required_args": ["window_id"],
                "capability_tags": ["plot_inspection", "fracture_detection"],
                "domain_tags": ["geoscience", "pylog"],
                "keywords": ["borehole image", "fracture metadata", "image log"],
            },
        )

    def execute(self, window_id=None, tracks=None, track=None):
        if not window_id:
            return _api_error(self.name, "window_id is required")
        try:
            selected = tracks or ([track] if track else None)
            metadata = _image_metadata(_plot_details(self.main_window, self.tool_executor, window_id), selected)
            return _wrap_api_result(self.name, {"ok": True, "metadata": metadata}, "metadata")
        except Exception as exc:
            return _api_error(self.name, exc)


@register_tool
class StartFractureDetectionTool(_FractureTool):
    is_abstract = False

    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "start_fracture_detection",
            "Start background fracture detection from one or more rendered plot tracks.",
            {
                "window_id": {"type": "string", "description": "Plot window title"},
                "tracks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "One or more plot tracks to render together, including curves or image tracks",
                },
                "target_image_track": {
                    "type": "string",
                    "description": "Selected image track that receives detected fracture coordinates",
                    "nullable": True,
                },
                "depth_start": {"type": "number", "description": "Top depth"},
                "depth_end": {"type": "number", "description": "Bottom depth"},
                "fracture_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FRACTURE_TYPES)},
                    "description": "One or more fracture types",
                },
                "borehole_diameter_in": {"type": "number", "description": "Borehole diameter in inches", "default": 8.0},
                "min_confidence": {"type": "number", "description": "Minimum confidence from 0 to 1", "default": 0.60},
            },
            main_window,
            tool_executor,
            metadata={
                "required_args": ["window_id", "tracks", "depth_start", "depth_end", "fracture_types"],
                "capability_tags": ["fracture_detection", "image_analysis"],
                "domain_tags": ["geoscience", "pylog"],
                "side_effect_level": "state",
                "risk_level": "low",
            },
        )

    def execute(self, **kwargs):
        try:
            window_id = kwargs.get("window_id")
            details = _plot_details(self.main_window, self.tool_executor, window_id)
            requested = kwargs.get("tracks") or ([kwargs.get("track")] if kwargs.get("track") else [])
            selected = _selected_plot_tracks(details, requested)
            image_tracks = [
                track for track in selected
                if any(curve.get("is_image") for curve in track.get("curves", []))
            ]
            target_name = str(kwargs.get("target_image_track") or "").strip()
            if target_name:
                aliases = _track_aliases(details)
                target = aliases.get(target_name)
                if target not in selected or target not in image_tracks:
                    return _api_error(self.name, "target_image_track must be an image track included in tracks")
            elif len(image_tracks) == 1:
                target = image_tracks[0]
            elif not image_tracks:
                return _api_error(self.name, "tracks must include an image track")
            else:
                return _api_error(self.name, "target_image_track is required when multiple image tracks are selected")

            kwargs["tracks"] = [track.get("label") or track.get("name") for track in selected]
            kwargs["target_image_track"] = target.get("label") or target.get("name")
            kwargs.pop("track", None)
            request = FractureDetectionRequest.build(**kwargs)
            rendered = _render_analysis_input(self.main_window, self.tool_executor, request)
            pipeline = FractureVisionPipeline()

            def worker(run_request, context, input_payload):
                annotations = pipeline.detect(run_request, context, input_payload)
                if context.cancelled:
                    return []
                context.defer_completion()
                context.update("playback", 0.90, "Preparing final candidate playback")
                apply_result = _apply_detection_results(
                    self.main_window,
                    self.tool_executor,
                    run_request,
                    annotations,
                    context.run_id,
                )
                if apply_result.get("completed_immediately"):
                    get_fracture_detection_manager().complete(
                        context.run_id,
                        apply_result.get("applied_count", len(annotations)),
                    )
                return annotations

            run = get_fracture_detection_manager().start(
                request,
                input_payload=rendered,
                worker=worker,
            )
            return _wrap_api_result(self.name, {"ok": True, "run": run}, "run")
        except Exception as exc:
            return _api_error(self.name, exc)


@register_tool
class GetFractureDetectionStatusTool(BaseTool):
    def __init__(self):
        super().__init__(
            "get_fracture_detection_status",
            "Get progress and status for a fracture detection run.",
            {"run_id": {"type": "string", "description": "Detection run ID"}},
            metadata={
                "required_args": ["run_id"],
                "capability_tags": ["fracture_detection", "job_status"],
                "domain_tags": ["geoscience", "pylog"],
            },
        )

    def execute(self, run_id=None):
        try:
            run = get_fracture_detection_manager().get_status(run_id)
            return _wrap_api_result(self.name, {"ok": True, "run": run}, "run")
        except Exception as exc:
            return _api_error(self.name, exc)


@register_tool
class ExportFractureDetectionDebugTool(BaseTool):
    def __init__(self):
        super().__init__(
            "export_fracture_detection_debug",
            "Export the exact analysis PNG, render metadata, raw model points, and fitted fracture diagnostics for a run.",
            {"run_id": {"type": "string", "description": "Detection run ID"}},
            metadata={
                "required_args": ["run_id"],
                "capability_tags": ["fracture_detection", "debug_export"],
                "domain_tags": ["geoscience", "pylog"],
                "side_effect_level": "write",
                "risk_level": "low",
            },
        )

    def execute(self, run_id=None):
        try:
            bundle = get_fracture_detection_manager().export_debug_bundle(run_id)
            return _wrap_api_result(self.name, {"ok": True, "bundle": bundle}, "bundle")
        except Exception as exc:
            return _api_error(self.name, exc)


@register_tool
class CancelFractureDetectionTool(BaseTool):
    def __init__(self):
        super().__init__(
            "cancel_fracture_detection",
            "Request cancellation of a running fracture detection job.",
            {"run_id": {"type": "string", "description": "Detection run ID"}},
            metadata={
                "required_args": ["run_id"],
                "capability_tags": ["fracture_detection", "job_control"],
                "domain_tags": ["geoscience", "pylog"],
                "side_effect_level": "state",
                "risk_level": "low",
            },
        )

    def execute(self, run_id=None):
        try:
            run = get_fracture_detection_manager().cancel(run_id)
            return _wrap_api_result(self.name, {"ok": True, "run": run}, "run")
        except Exception as exc:
            return _api_error(self.name, exc)
