from __future__ import annotations

from typing import Any, Dict, Optional


def ensure_track_container(
    log_plot,
    track_map: Dict[Optional[str], Any],
    *,
    track_id: Optional[str],
    accum_fill: bool,
    is_image: bool,
):
    """Find or create the appropriate track container for one curve payload."""
    container = track_map.get(track_id) if track_id is not None else None
    if container is None and track_id is not None:
        for candidate in log_plot.track_containers:
            if getattr(candidate, "_api_track_id", None) == track_id or getattr(candidate, "track_name", None) == track_id:
                container = candidate
                track_map[track_id] = candidate
                break

    if container is None:
        from scripts.rendering.plot_components import InteractivePlotWidget
        from scripts.tracks.track_container import AccumulativeTrackContainer, CurveTrackContainer, ImageTrackContainer

        if accum_fill:
            container = AccumulativeTrackContainer(log_plot)
        elif is_image:
            container = ImageTrackContainer(log_plot)
        else:
            container = CurveTrackContainer(log_plot)

        track_count = sum(1 for track in log_plot.track_containers if isinstance(track.plot_widget, InteractivePlotWidget))
        container.track_name = track_id if track_id else f"Track {track_count + 1}"
        log_plot._add_track_to_layout(container, width=204)
        if track_id:
            container._api_track_id = track_id
            track_map[track_id] = container

    if accum_fill and not container.is_accum_fill:
        container.is_accum_fill = True
    return container
