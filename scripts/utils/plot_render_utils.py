from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from scripts.rendering.plot_components import PainterDepthTrack

from .plot_payload_utils import prepare_curve_payload_for_render
from .plot_track_utils import ensure_track_container


def ensure_depth_track_present(log_plot) -> None:
    """Ensure the target plot has a depth track before adding curves."""
    has_depth = any(isinstance(track.plot_widget, PainterDepthTrack) for track in log_plot.track_containers)
    if not has_depth:
        log_plot.add_depth_track()


def precreate_named_tracks(
    log_plot,
    data_list: List[Dict[str, Any]],
    *,
    accum_fill: bool,
) -> tuple[Dict[Optional[str], Any], Set[Any]]:
    """Precreate only explicitly named tracks so overlays land in the same container."""
    track_map: Dict[Optional[str], Any] = {}
    affected_tracks: Set[Any] = set()

    for curve in data_list:
        track_id = curve.get("track")
        if track_id is None:
            continue

        is_image = any(
            candidate.get("type", "").upper() == "2D" or candidate.get("is_image", False)
            for candidate in data_list
            if candidate.get("track") == track_id
        )
        container = ensure_track_container(
            log_plot,
            track_map,
            track_id=track_id,
            accum_fill=accum_fill,
            is_image=is_image,
        )
        affected_tracks.add(container)

    return track_map, affected_tracks


def render_curve_batch(
    log_plot,
    data_list: List[Dict[str, Any]],
    *,
    accum_fill: bool,
    fill_to: Optional[List[str]] = None,
    fill_colors: Optional[List[str]] = None,
    fill_alphas: Optional[List[float]] = None,
    titles: Optional[List[str]] = None,
) -> Set[Any]:
    """Render a normalized batch of curves into the target plot and return touched tracks."""
    ensure_depth_track_present(log_plot)
    track_map, affected_tracks = precreate_named_tracks(
        log_plot,
        data_list,
        accum_fill=accum_fill,
    )

    for idx, curve in enumerate(data_list):
        prepared = prepare_curve_payload_for_render(
            curve,
            idx,
            accum_fill=accum_fill,
            fill_to=fill_to,
            fill_colors=fill_colors,
            fill_alphas=fill_alphas,
            titles=titles,
        )
        container = track_map.get(prepared["track_id"])
        if container is None:
            container = ensure_track_container(
                log_plot,
                track_map,
                track_id=None,
                accum_fill=accum_fill,
                is_image=prepared["is_image"],
            )
            affected_tracks.add(container)

        container.add_curve(prepared["values"], prepared["depth"], prepared["info"])
        log_plot.update_depth_limits(prepared["depth"])

    return affected_tracks


def refresh_accumulative_fills(tracks: Set[Any]) -> None:
    """Refresh accumulative fill visuals for affected tracks when supported."""
    for track in tracks:
        if hasattr(track, "_update_accumulative_fills"):
            track._update_accumulative_fills()
