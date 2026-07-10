from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QTimer

from scripts.rendering.plot_widget import LogWidget
from scripts.utils.curve_loading import clear_depth_cache
from scripts.utils.workers import clear_lut_cache


PlotSpec = Dict[str, Any]
TrackSpec = Dict[str, Any]
CurveSpec = Dict[str, Any]

TEMPLATE_CURVE_SETTINGS_MODE = "full"
TEMPLATE_LIGHT_CURVE_KEYS = (
    "title",
    "color",
    "line_width",
    "line_style",
)
TEMPLATE_INCLUDE_DEPTH_TRACK = True
TEMPLATE_APPLY_TRACK_SETTINGS = True


def _clone_dict(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return deepcopy(data) if isinstance(data, dict) else {}


def _normalize_curve_spec(curve: Dict[str, Any], fallback_db_path: Optional[str], fallback_well_id: Optional[int]) -> CurveSpec:
    curve_settings = _clone_dict(curve.get("curve_settings"))
    if not curve_settings and any(k in curve for k in (
        "title", "color", "line_width", "line_style", "log", "invert_x",
        "fill_mode", "fill_color", "visible", "min", "max", "cmap", "null_color",
    )):
        curve_settings = {
            key: curve.get(key)
            for key in (
                "title", "color", "line_width", "line_style", "log", "invert_x",
                "fill_mode", "fill_color", "visible", "min", "max", "cmap", "null_color",
            )
            if key in curve and curve.get(key) is not None
        }

    return {
        "curve_id": curve.get("curve_id", curve.get("id")),
        "well_id": curve.get("well_id", fallback_well_id),
        "db_path": curve.get("db_path", fallback_db_path),
        "curve_settings": curve_settings,
    }


def _normalize_track_spec(track: Dict[str, Any], fallback_db_path: Optional[str], fallback_well_id: Optional[int]) -> TrackSpec:
    curves = [
        _normalize_curve_spec(curve, fallback_db_path, fallback_well_id)
        for curve in track.get("curves", [])
        if curve.get("curve_id", curve.get("id")) is not None
    ]
    return {
        "name": track.get("name") or "Track",
        "type": track.get("type", "data"),
        "width": int(track.get("width", track.get("base_width", 200))),
        "header_visible": bool(track.get("header_visible", True)),
        "track_settings": _clone_dict(track.get("track_settings")),
        "curves": curves,
    }


def normalize_plot_spec(plot_spec: PlotSpec) -> PlotSpec:
    db_path = plot_spec.get("db_path")
    well_id = plot_spec.get("well_id")
    tracks = [
        _normalize_track_spec(track, db_path, well_id)
        for track in plot_spec.get("tracks", [])
    ]
    return {
        "db_path": db_path,
        "well_id": well_id,
        "title": plot_spec.get("title"),
        "tracks": tracks,
    }


def build_plot_spec_from_manual_items(items_data: Iterable[Dict[str, Any]], *, title: Optional[str] = None) -> PlotSpec:
    curves = [item for item in items_data if item.get("type") == "curve"]
    if not curves:
        return {"db_path": None, "well_id": None, "title": title, "tracks": []}

    first = curves[0]
    db_path = first.get("db_path")
    well_id = first.get("well_id")
    tracks: List[TrackSpec] = []

    for idx, curve in enumerate(curves):
        if curve.get("db_path") != db_path or curve.get("well_id") != well_id:
            continue
        tracks.append({
            "name": f"Track {idx + 1}",
            "type": "data",
            "width": 200,
            "header_visible": True,
            "track_settings": {},
            "curves": [{
                "curve_id": curve.get("id"),
                "well_id": well_id,
                "db_path": db_path,
                "curve_settings": {},
            }],
        })

    return normalize_plot_spec({
        "db_path": db_path,
        "well_id": well_id,
        "title": title,
        "tracks": tracks,
    })


def build_plot_spec_from_template(template_state: Dict[str, Any], db, well_id: Optional[int], resolve_curve_fn) -> PlotSpec:
    db_path = getattr(db, "db_path", None)
    resolved_tracks: List[TrackSpec] = []
    fallback_well_id = well_id

    for track_state in template_state.get("tracks", []):
        track_type = track_state.get("type", "data")
        if track_type == "depth":
            if not TEMPLATE_INCLUDE_DEPTH_TRACK:
                continue
            depth_track_settings = {}
            if TEMPLATE_APPLY_TRACK_SETTINGS:
                depth_track_settings = {
                    key: track_state.get(key)
                    for key in (
                        "name", "width", "grid_x", "grid_y", "depth_start", "depth_end",
                        "is_accum_fill", "label_font_family", "label_font_size",
                        "label_mask_enabled", "label_mask_length", "fractures",
                    )
                    if key in track_state and track_state.get(key) is not None
                }
            resolved_tracks.append({
                "name": track_state.get("name", "Depth"),
                "type": "depth",
                "width": int(track_state.get("base_width", track_state.get("width", 60))),
                "header_visible": bool(track_state.get("header_visible", True)),
                "track_settings": depth_track_settings,
                "curves": [],
            })
            continue

        resolved_curves: List[CurveSpec] = []
        for curve_cfg in track_state.get("curves", []):
            resolved = resolve_curve_fn(db, curve_cfg, well_id=fallback_well_id)
            if not resolved:
                continue
            resolved_well_id, curve_id = resolved
            if fallback_well_id is None:
                fallback_well_id = resolved_well_id
            curve_setting_keys = TEMPLATE_LIGHT_CURVE_KEYS
            if TEMPLATE_CURVE_SETTINGS_MODE == "none":
                curve_setting_keys = ()
            elif TEMPLATE_CURVE_SETTINGS_MODE != "light":
                curve_setting_keys = (
                    "title", "color", "line_width", "line_style", "log", "invert_x",
                    "fill_mode", "fill_color", "fill_alpha", "visible", "min", "max",
                    "cmap", "null_color",
                )
            curve_settings = {
                key: curve_cfg.get(key)
                for key in curve_setting_keys
                if key in curve_cfg and curve_cfg.get(key) is not None
            }
            resolved_curves.append({
                "curve_id": curve_id,
                "well_id": resolved_well_id,
                "db_path": db_path,
                "curve_settings": curve_settings,
            })

        if resolved_curves:
            track_settings = {}
            if TEMPLATE_APPLY_TRACK_SETTINGS:
                track_settings = {
                    key: track_state.get(key)
                    for key in (
                        "name", "width", "grid_x", "grid_y", "depth_start", "depth_end",
                        "is_accum_fill", "label_font_family", "label_font_size",
                        "label_mask_enabled", "label_mask_length", "fractures",
                    )
                    if key in track_state and track_state.get(key) is not None
                }
            resolved_tracks.append({
                "name": track_state.get("name") or f"Track {len(resolved_tracks) + 1}",
                "type": track_type,
                "width": int(track_state.get("base_width", track_state.get("width", 200))),
                "header_visible": bool(track_state.get("header_visible", True)),
                "track_settings": track_settings,
                "curves": resolved_curves,
            })

    return normalize_plot_spec({
        "db_path": db_path,
        "well_id": fallback_well_id,
        "title": template_state.get("title"),
        "tracks": resolved_tracks,
    })


def _clear_plot_runtime_state(log_widget: LogWidget) -> None:
    clear_depth_cache()
    clear_lut_cache()
    try:
        if hasattr(log_widget, "thread_pool"):
            log_widget.thread_pool.clear()
    except Exception:
        pass
    try:
        if hasattr(log_widget, "active_image_workers"):
            log_widget.active_image_workers.clear()
    except Exception:
        pass


def _apply_track_settings_batch(track_settings_pairs: List[Tuple[Any, Dict[str, Any]]]) -> None:
    for track, track_settings in track_settings_pairs:
        if not track or not track_settings:
            continue
        try:
            track.apply_track_settings(track_settings)
        except Exception:
            pass


def _schedule_deferred_track_settings(log_widget: LogWidget, track_settings_pairs: List[Tuple[Any, Dict[str, Any]]]) -> None:
    if not track_settings_pairs:
        return

    def _apply_once():
        try:
            log_widget.loadingFinished.disconnect(_apply_once)
        except Exception:
            pass
        _apply_track_settings_batch(track_settings_pairs)

    has_pending_loads = bool(getattr(log_widget, "pending_loads", 0))
    if has_pending_loads:
        log_widget.loadingFinished.connect(_apply_once)
        return

    QTimer.singleShot(0, _apply_once)


def open_plot_from_spec(main_window, plot_spec: PlotSpec):
    spec = normalize_plot_spec(plot_spec)
    if not spec.get("tracks"):
        return None, 0

    active_sub = main_window.mdi_area.activeSubWindow() if hasattr(main_window, "mdi_area") else None
    if active_sub:
        active_widget = active_sub.widget()
        if isinstance(active_widget, LogWidget):
            _clear_plot_runtime_state(active_widget)

    widget = main_window.new_plot_window()
    if not isinstance(widget, LogWidget):
        return None, 0

    widget.set_db_source(spec.get("db_path"))
    _clear_plot_runtime_state(widget)

    created_tracks = 0
    deferred_track_settings: List[Tuple[Any, Dict[str, Any]]] = []
    for track_spec in spec.get("tracks", []):
        if track_spec.get("type") == "depth":
            widget.add_depth_track()
            depth_track = next((track for track in widget.track_containers if getattr(track, "track_name", None) == "Depth"), None)
            if depth_track and track_spec.get("track_settings"):
                deferred_track_settings.append((depth_track, track_spec["track_settings"]))
            continue

        container = None
        curves = track_spec.get("curves", [])
        if not curves:
            continue

        for idx, curve_spec in enumerate(curves):
            curve_settings = _clone_dict(curve_spec.get("curve_settings"))
            if idx == 0:
                container = widget.create_new_track(
                    curve_spec.get("well_id"),
                    curve_spec.get("curve_id"),
                    db_path=curve_spec.get("db_path", spec.get("db_path")),
                    curve_settings=curve_settings,
                    track_name=track_spec.get("name"),
                    track_width=track_spec.get("width", 200),
                    header_visible=track_spec.get("header_visible", True),
                )
                created_tracks += 1
            elif container is not None:
                widget.add_curve_to_track(
                    container,
                    curve_spec.get("well_id"),
                    curve_spec.get("curve_id"),
                    db_path=curve_spec.get("db_path", spec.get("db_path")),
                    curve_settings=curve_settings,
                )

        if container and track_spec.get("track_settings"):
            deferred_track_settings.append((container, track_spec["track_settings"]))

    _schedule_deferred_track_settings(widget, deferred_track_settings)

    if spec.get("title"):
        active_sub = main_window.mdi_area.activeSubWindow()
        if active_sub:
            active_sub.setWindowTitle(spec["title"])
    return widget, created_tracks


def _resolve_track_ref(log_widget: LogWidget, track_ref: Any):
    if isinstance(track_ref, int):
        data_tracks = [track for track in log_widget.track_containers if getattr(track, "track_name", None) != "Depth"]
        return data_tracks[track_ref] if 0 <= track_ref < len(data_tracks) else None
    for track in log_widget.track_containers:
        if getattr(track, "track_name", None) == track_ref:
            return track
    return None


def _resolve_curve_index(track, curve_ref: Any) -> Optional[int]:
    curves = getattr(track.plot_widget, "curves", [])
    if isinstance(curve_ref, int):
        return curve_ref if 0 <= curve_ref < len(curves) else None
    for idx, curve in enumerate(curves):
        info = curve.get("info", {})
        if info.get("name") == curve_ref or info.get("title") == curve_ref:
            return idx
    return None


def _resolve_window_title(log_widget: LogWidget) -> str:
    window = log_widget.window()
    try:
        return window.windowTitle()
    except Exception:
        return ""


def update_plot_from_commands(log_widget: LogWidget, commands: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    applied = 0
    errors: List[str] = []

    for command in commands:
        action = command.get("action")
        if action == "apply_curve_style":
            track = _resolve_track_ref(log_widget, command.get("track"))
            if track is None:
                errors.append(f"Track not found: {command.get('track')}")
                continue
            curve_idx = _resolve_curve_index(track, command.get("curve"))
            if curve_idx is None:
                errors.append(f"Curve not found: {command.get('curve')}")
                continue
            track.apply_curve_settings(curve_idx, _clone_dict(command.get("settings")), reload_data=False)
            applied += 1
        elif action == "apply_track_style":
            track = _resolve_track_ref(log_widget, command.get("track"))
            if track is None:
                errors.append(f"Track not found: {command.get('track')}")
                continue
            track.apply_track_settings(_clone_dict(command.get("settings")))
            applied += 1
        elif action == "add_curve":
            track_ref = command.get("track")
            curve_settings = _clone_dict(command.get("curve_settings"))
            well_id = command.get("well_id")
            curve_id = command.get("curve_id")
            db_path = command.get("db_path", log_widget.db_path)
            if well_id is None or curve_id is None:
                errors.append("add_curve requires well_id and curve_id")
                continue

            if track_ref is None:
                created = log_widget.create_new_track(
                    well_id,
                    curve_id,
                    db_path=db_path,
                    curve_settings=curve_settings,
                    track_name=command.get("track_name"),
                    track_width=command.get("track_width", 200),
                    header_visible=command.get("header_visible", True),
                )
                if created and command.get("track_settings"):
                    created.apply_track_settings(_clone_dict(command.get("track_settings")))
                applied += 1
                continue

            track = _resolve_track_ref(log_widget, track_ref)
            if track is None:
                errors.append(f"Track not found: {track_ref}")
                continue
            log_widget.add_curve_to_track(
                track,
                well_id,
                curve_id,
                db_path=db_path,
                curve_settings=curve_settings,
            )
            applied += 1
        elif action == "remove_curve":
            track = _resolve_track_ref(log_widget, command.get("track"))
            if track is None:
                errors.append(f"Track not found: {command.get('track')}")
                continue
            curve_idx = _resolve_curve_index(track, command.get("curve"))
            if curve_idx is None:
                errors.append(f"Curve not found: {command.get('curve')}")
                continue
            track.remove_curve_at(curve_idx)
            if not getattr(track.plot_widget, "curves", []):
                log_widget.remove_track(track)
            applied += 1
        elif action == "remove_track":
            track = _resolve_track_ref(log_widget, command.get("track"))
            if track is None:
                errors.append(f"Track not found: {command.get('track')}")
                continue
            log_widget.remove_track(track)
            applied += 1
        elif action == "set_depth_range":
            depth_range = command.get("depth_range")
            if not isinstance(depth_range, (list, tuple)) or len(depth_range) != 2:
                errors.append("set_depth_range requires depth_range [min, max]")
                continue
            try:
                log_widget.apply_depth_range(float(depth_range[0]), float(depth_range[1]), force=True)
                applied += 1
            except Exception as exc:
                errors.append(f"Failed to set depth range: {exc}")
        elif action == "select_curve":
            track = _resolve_track_ref(log_widget, command.get("track"))
            if track is None:
                errors.append(f"Track not found: {command.get('track')}")
                continue
            curve_idx = _resolve_curve_index(track, command.get("curve"))
            if curve_idx is None:
                errors.append(f"Curve not found: {command.get('curve')}")
                continue
            track.select_curve(curve_idx)
            applied += 1
        else:
            errors.append(f"Unsupported action: {action}")

    return {
        "ok": not errors,
        "applied": applied,
        "errors": errors,
        "window_id": _resolve_window_title(log_widget),
    }
