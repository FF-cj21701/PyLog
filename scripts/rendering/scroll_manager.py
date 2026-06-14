"""
ScrollManager — Extracted from LogWidget (plot_widget.py)
Handles depth synchronization, viewport scrollbar, hard slicing,
image slice caching, and scale management.
"""
import numpy as np
from PySide6.QtCore import Qt, QRectF, QTimer, QCoreApplication, QObject
from PySide6.QtWidgets import QMessageBox

from ..rendering.plot_components import InteractivePlotWidget, PainterDepthTrack
from ..utils.workers import ImageSliceWorker
from ..utils.logger import logger


class ScrollManager(QObject):
    """Manages all scroll/depth/viewport logic for a LogWidget."""

    def __init__(self, log_widget):
        super().__init__(log_widget)
        self.lw = log_widget
        
        # [NEW] Debounce for image tiling
        self._pending_tile_requests = {} # {track: {tile_index: (t_min, t_max)}}
        self._tile_request_debounce_ms = 50
        self._max_tile_dispatch_per_track = 4
        self._image_debounce_timer = QTimer(self)
        self._image_debounce_timer.setSingleShot(True)
        self._image_debounce_timer.timeout.connect(self._process_pending_tile_requests)

    # ─── Track X Cache ───────────────────────────────────────

    def _invalidate_track_x_cache(self):
        self.lw._track_x_cache_dirty = True

    def _refresh_track_x_cache(self):
        lw = self.lw
        if not getattr(lw, '_track_x_cache_dirty', True):
            return
        cache = {}
        try:
            base_x = lw.splitter.pos().x()
            for track in lw.track_containers:
                left = base_x + track.pos().x()
                cache[track] = (left, left + track.width())
        except Exception:
            cache = {}
        lw._track_x_cache = cache
        lw._track_x_cache_dirty = False

    def _on_splitter_moved(self, *args):
        self.lw._sync_container_width()
        self._invalidate_track_x_cache()

    # ─── Core Depth Sync ─────────────────────────────────────

    def apply_depth_range(
        self,
        min_y: float,
        max_y: float,
        update_scrollbar: bool = True,
        force_low_res: bool = False,
        force: bool = False,
        only_track = None
    ) -> None:
        """
        Unified Kernel for Depth Multi-track Sync + Hard Slicing.
        Updates all tracks and the scrollbar to the specified range.
        [OPTIMIZATION] Added only_track to prevent redundant refreshes of all tracks during single track resize.
        """
        lw = self.lw
        if getattr(lw, '_in_apply_depth_range', False):
            return
        lw._in_apply_depth_range = True
        lw.updating_scroll = True

        # [NEW] Enforce Depth Limits (Global or Custom)
        limit_min = lw.custom_min_depth if lw.custom_min_depth is not None else lw.global_min_depth
        limit_max = lw.custom_max_depth if lw.custom_max_depth is not None else lw.global_max_depth

        if limit_min is not None and limit_max is not None:
            # Ensure boundaries are correct (min < max)
            if limit_min > limit_max: limit_min, limit_max = limit_max, limit_min
            
            h = max_y - min_y
            total_h = limit_max - limit_min
            
            if h >= total_h:
                # Viewport larger than data: show full range
                min_y, max_y = limit_min, limit_max
            else:
                # Viewport smaller than data: clamp while preserving height
                if max_y > limit_max:
                    max_y = limit_max
                    min_y = max_y - h
                if min_y < limit_min:
                    min_y = limit_min
                    max_y = min_y + h
                
                # Double check absolute clamping
                min_y = max(limit_min, min_y)
                max_y = min(limit_max, max_y)

        # [OPTIMIZATION] If range hasn't changed and we have a specific track, only update that one.
        current_last_min = getattr(lw, 'last_y_min', -9999.0)
        range_changed = (abs(min_y - current_last_min) > 0.001) or force
        lw.last_y_min = min_y

        try:
            # [OPTIMIZATION] Calculate horizontal visible range for freezing
            sb_h = lw.scroll_area.horizontalScrollBar()
            view_left = sb_h.value()
            view_right = view_left + lw.scroll_area.viewport().width()

            # [NEW] Atomic Rendering: Disable updates during the sync loop
            lw.container.setUpdatesEnabled(False)
            try:
                self._refresh_track_x_cache()

                # 1. Update tracks (Selective or All)
                # [FIX] Prioritize 'only_track' even if 'force' is True, to prevent multi-track flicker.
                if only_track is not None:
                    tracks_to_update = [only_track]
                else:
                    tracks_to_update = lw.track_containers

                for track in tracks_to_update:
                    # [FREEZING LOGIC] Check if track is within horizontal viewport
                    if track in lw._track_x_cache:
                        track_left, track_right = lw._track_x_cache[track]
                    else:
                        base_x = lw.splitter.pos().x()
                        track_left = base_x + track.pos().x()
                        track_right = track_left + track.width()
                        lw._track_x_cache[track] = (track_left, track_right)

                    # Add a buffer (300 for balanced pre-fetch)
                    buffer = 300
                    is_visible = (track_right >= (view_left - buffer)) and (track_left <= (view_right + buffer))

                    # [SYNC] Forced Synchronous Coordinator Sync
                    track.sync_viewboxes(min_y, max_y)

                    # [CRITICAL] Skip heavy slicing/updates if NOT visible
                    if not is_visible:
                        continue

                    pw = track.plot_widget
                    if hasattr(pw, 'getViewBox'):
                        # Apply hard slicing (if enabled) for LINE CURVES
                        if lw.enable_hard_slicing and isinstance(pw, InteractivePlotWidget):
                            self._apply_hard_slicing(track, min_y, max_y, force=force)

                        # [FIX] Always check for image data cache updates
                        if isinstance(pw, InteractivePlotWidget) and hasattr(pw, 'image_data_cache'):
                            self._update_image_slice(track, min_y, max_y, force_low_res=force_low_res, force=force)

                        elif isinstance(pw, PainterDepthTrack):
                            pw.update()
            finally:
                # [NEW] Re-enable updates to push the atomic frame to screen
                lw.container.setUpdatesEnabled(True)

            # 2. Synchronize Scrollbar UI
            if update_scrollbar:
                self._update_scrollbar_range()

        finally:
            lw.updating_scroll = False
            lw._in_apply_depth_range = False

    def on_depth_range_changed(self, _, y_range):
        """Handle panning/zooming directly in any plot (master/slave)."""
        lw = self.lw
        if lw.updating_scroll:
            return
        min_y, max_y = y_range[1]

        # Trigger low-res immediately, and high-res after 200ms of inactivity
        self.apply_depth_range(min_y, max_y, update_scrollbar=True, force_low_res=True)
        lw.scroll_timer.start(200)

    def _on_scroll_settled(self):
        """Called when scrolling has stopped for 200ms. Triggers high-res update."""
        master_vb = self.lw.get_master_viewbox()
        if master_vb:
            (min_y, max_y) = master_vb.viewRange()[1]
            self.apply_depth_range(min_y, max_y, update_scrollbar=True, force_low_res=False)

    # ─── Scroll Events ───────────────────────────────────────

    def wheelEvent(self, event):
        lw = self.lw
        if not lw.track_containers:
            return
        target = None
        for t in lw.track_containers:
            if isinstance(t.plot_widget, InteractivePlotWidget):
                target = t.plot_widget
                break
        if target:
            target.wheelEvent(event)

    def on_horizontal_scroll(self, value):
        """Refresh tracks when horizontal scroll changes to unfreeze them."""
        master_vb = self.lw.get_master_viewbox()
        if master_vb:
            (min_y, max_y) = master_vb.viewRange()[1]
            self.apply_depth_range(min_y, max_y)

    def on_scrollbar_moved(self, value):
        lw = self.lw
        if lw.updating_scroll or not lw.track_containers:
            return
        new_min = value / lw.SCROLL_PRECISION
        master_vb = lw.get_master_viewbox()
        if not master_vb:
            return
        (min_y, max_y) = master_vb.viewRange()[1]
        height = max_y - min_y
        new_max = new_min + height
        # Use force_low_res during scrollbar movement
        self.apply_depth_range(new_min, new_max, update_scrollbar=False, force_low_res=True)
        lw.scroll_timer.start(200)

    def _update_scrollbar_range(self) -> None:
        """Synchronize the vertical scrollbar with current ViewBox limits and range."""
        lw = self.lw
        master_vb = lw.get_master_viewbox()
        if not master_vb:
            return
        try:
            (min_y, max_y) = master_vb.viewRange()[1]
        except:
            return

        lw.v_scrollbar.blockSignals(True)
        page_height = max_y - min_y

        # Determine current limits (custom or global)
        limit_min = lw.custom_min_depth if lw.custom_min_depth is not None else lw.global_min_depth
        limit_max = lw.custom_max_depth if lw.custom_max_depth is not None else lw.global_max_depth

        if limit_min is not None and limit_max is not None:
            # [FIX] Safety check for NaN to prevent crash (ValueError: cannot convert float NaN to integer)
            if np.isnan(limit_min) or np.isnan(limit_max) or np.isnan(page_height):
                logger.debug("Depth limits or page height contains NaN. Skipping scrollbar update.")
                lw.v_scrollbar.blockSignals(False)
                return

            scroll_min = int(limit_min * lw.SCROLL_PRECISION)
            scroll_max = int((limit_max - page_height) * lw.SCROLL_PRECISION)
            if scroll_max < scroll_min:
                scroll_max = scroll_min

            if lw.v_scrollbar.minimum() != scroll_min:
                lw.v_scrollbar.setMinimum(scroll_min)
            if lw.v_scrollbar.maximum() != scroll_max:
                lw.v_scrollbar.setMaximum(scroll_max)

            p_step = int(page_height * lw.SCROLL_PRECISION)
            if lw.v_scrollbar.pageStep() != p_step:
                lw.v_scrollbar.setPageStep(p_step)

        # [FIX] Safety check for min_y
        if not np.isnan(min_y):
            lw.v_scrollbar.setValue(int(min_y * lw.SCROLL_PRECISION))
        lw.v_scrollbar.blockSignals(False)

    # ─── Hard Slicing ────────────────────────────────────────

    def _apply_hard_slicing(self, track, min_y: float, max_y: float, force: bool = False) -> None:
        """Ultra-fast viewport slicing using numpy searchsorted."""
        if not hasattr(track.plot_widget, 'curves'):
            return

        for curve_obj in track.plot_widget.curves:
            if curve_obj.get('is_image'):
                continue

            item = curve_obj.get('item')
            if not item:
                continue

            full_depth = curve_obj.get('depth')
            full_plot_data = curve_obj.get('plot_data')
            if full_depth is None or full_plot_data is None:
                continue

            start_idx = np.searchsorted(full_depth, min_y)
            end_idx = np.searchsorted(full_depth, max_y)

            # [IMPROVEMENT: Slice Buffering]
            last_slice = curve_obj.get('_last_slice', None)

            view_pts = max(10, end_idx - start_idx)
            # Buffer is 1x the viewport size on each side, capped between 500 and 5000 points.
            buffer = max(500, min(view_pts, 5000))

            if not force and last_slice is not None:
                l_start, l_end = last_slice
                # Safe margin is 20% of the buffer
                safe_margin = int(buffer * 0.2)
                if (start_idx > l_start + safe_margin) and (end_idx < l_end - safe_margin):
                    continue  # Still within the safe inner bound of the current slice!

            # Fetch a new slice centered around the new view, including the buffer
            start = max(0, start_idx - buffer)
            end = min(len(full_depth), end_idx + buffer)

            # [OPTIMIZATION] Apply Log Transform on the slice, not the full array
            data_slice = full_plot_data[start:end]
            depth_slice = full_depth[start:end]

            if curve_obj.get('info', {}).get('log', False):
                # Ensure we have a numeric array for the log operation
                if not isinstance(data_slice, np.ndarray):
                    data_slice = np.array(data_slice)
                # Filter non-positives before log10 to avoid warnings
                data_slice = np.log10(np.clip(data_slice, 1e-10, None))

            item.setData(data_slice, depth_slice)
            curve_obj['_last_slice'] = (start, end)

    # ─── Image Slice Management ──────────────────────────────

    def _update_image_slice(self, track, min_y, max_y, force_low_res=False, force=False):
        """[TILED IMAGE OPTIMIZATION] Use TiledImageItem viewport management."""
        lw = self.lw
        pw = track.plot_widget
        cache = getattr(pw, 'image_data_cache', None)
        if not cache:
            return

        item = getattr(pw, 'image_item', None)
        if hasattr(item, 'update_viewport'):
            # [FIX] If force is set, we must clear existing tiles to avoid showing stale data 
            # with old Min/Max/Invert settings.
            if force and hasattr(item, 'clear'):
                item.clear()
                if 'tiles_loading' in cache:
                    cache['tiles_loading'].clear()
                cache['render_generation'] = cache.get('render_generation', 0) + 1

            # [ROBUST] Use manual flag to ensure unique connection across all PySide versions
            if not hasattr(item, '_is_connected_to_mgr'):
                item.tile_requested.connect(self._on_tile_requested)
                item._is_connected_to_mgr = True
            
            view_height_px = pw.height()
            # [FIX] If height is 0, wait until next layout cycle
            if view_height_px > 0:
                item.update_viewport(min_y, max_y, view_height_px, loading_indices=cache.get('tiles_loading'))
                self._prune_stale_tile_workers(track, cache, getattr(item, '_needed_indices', set()))

    def _prune_stale_tile_workers(self, track, cache, needed_indices):
        """Drop queued tile jobs that are no longer in the current viewport."""
        lw = self.lw
        if needed_indices is None:
            return

        stale_keys = []
        for worker_key, worker in list(lw.active_image_workers.items()):
            if not isinstance(worker_key, tuple) or len(worker_key) < 3:
                continue

            key_track_id, tier, tile_idx = worker_key[:3]
            if key_track_id != id(track) or tier != "tile":
                continue
            if tile_idx in needed_indices:
                continue

            try:
                removed = lw.thread_pool.tryTake(worker)
            except Exception:
                removed = False

            if removed:
                stale_keys.append(worker_key)
                cache.get('tiles_loading', set()).discard(tile_idx)

        for worker_key in stale_keys:
            lw.active_image_workers.pop(worker_key, None)

    def _on_tile_requested(self, idx, t_min, t_max):
        """Worker dispatcher for individual tiles (with Debounce)."""
        logger.debug(f"[DEBUG_SIGNAL] Tile Request Received for index {idx}")
        item = self.sender()
        if not item or not hasattr(item, 'track'): return
        track = item.track
        if not track: return
        
        if track not in self._pending_tile_requests:
            self._pending_tile_requests[track] = {}

        # Keep only latest request per tile index to avoid request storms while dragging.
        self._pending_tile_requests[track][idx] = (t_min, t_max)
        self._image_debounce_timer.start(self._tile_request_debounce_ms)

    def _process_pending_tile_requests(self):
        """Execute the buffered tile requests after scrolling slows down."""
        lw = self.lw
        logger.debug(f"[DEBUG_EXEC] Processing {sum(len(v) for v in self._pending_tile_requests.values())} pending tiles")
        next_pending = {}
        for track, requests in list(self._pending_tile_requests.items()):
            pw = track.plot_widget
            cache = getattr(pw, 'image_data_cache', None)
            if not cache:
                continue

            item = getattr(pw, 'image_item', None)
            needed_indices = getattr(item, '_needed_indices', set()) if item is not None else set()
            center_tile_idx = getattr(item, '_center_tile_idx', 0) if item is not None else 0

            candidates = []
            for idx, (t_min, t_max) in requests.items():
                # Drop stale requests that are already outside the current viewport window.
                if needed_indices and idx not in needed_indices:
                    continue
                if idx in cache['tiles_loading']:
                    continue

                candidates.append((idx, t_min, t_max))

            # Prioritize tiles near viewport center so perceived rendering is smoother.
            candidates.sort(key=lambda x: abs(x[0] - center_tile_idx))
            deferred = {}
            dispatched = 0

            for idx, t_min, t_max in candidates:
                if dispatched >= self._max_tile_dispatch_per_track:
                    deferred[idx] = (t_min, t_max)
                    continue

                cache['tiles_loading'].add(idx)
                generation = cache.get('render_generation', 0)
                worker_key = (id(track), "tile", idx, generation)
                
                if worker_key not in lw.active_image_workers:
                    track_w_px = track.width()
                    worker = ImageSliceWorker(track, t_min, t_max, 0, cache, v_step=1, track_w_px=track_w_px, tile_index=idx)
                    worker.signals.ready.connect(self.on_image_slice_ready)
                    worker.signals.error.connect(lambda e, wk=worker_key: self._on_image_worker_error(wk, e))
                    lw.active_image_workers[worker_key] = worker
                    lw.thread_pool.start(worker)
                    dispatched += 1

            if deferred:
                next_pending[track] = deferred
        
        self._pending_tile_requests = next_pending
        if self._pending_tile_requests:
            self._image_debounce_timer.start(self._tile_request_debounce_ms)

    def on_image_slice_ready(self, indexed_slice, lut, actual_min, actual_max, track, v_step, tile_index):
        """Main thread callback to apply the calculated image tile to TiledImageItem."""
        lw = self.lw
        track_id = id(track)

        # Check for tile or full slice
        is_tile = (tile_index >= 0)
        tier = "tile" if is_tile else ("high" if v_step == 1 else "low")
        worker_key = None
        for key, worker in list(lw.active_image_workers.items()):
            if is_tile:
                if (
                    isinstance(key, tuple)
                    and len(key) >= 3
                    and key[0] == track_id
                    and key[1] == tier
                    and key[2] == tile_index
                    and getattr(worker, 'signals', None) is self.sender()
                ):
                    worker_key = key
                    break
            elif key == (track_id, tier):
                worker_key = key
                break

        worker = lw.active_image_workers.get(worker_key) if worker_key is not None else None
        if worker_key in lw.active_image_workers:
            del lw.active_image_workers[worker_key]

        pw = track.plot_widget
        cache = getattr(pw, 'image_data_cache', None)
        if not cache:
            return

        if is_tile and worker is None:
            logger.debug(f"[DEBUG_UI] Dropping untracked tile data for index {tile_index}")
            self._check_loading_status()
            return
            
        current_generation = cache.get('render_generation', 0)
        is_stale_generation = worker is not None and getattr(worker, 'render_generation', 0) != current_generation
        if is_stale_generation:
            logger.debug(f"[DEBUG_UI] Dropping stale tile generation for index {tile_index}")
            self._check_loading_status()
            return
            
        if is_tile:
            cache['tiles_loading'].discard(tile_index)

        # [REFACTORED] Tiled image application (Legacy item check removed)
        item = getattr(pw, 'image_item', None)
        if hasattr(item, 'set_tile_data') and is_tile:
            needed_indices = getattr(item, '_needed_indices', set())
            if needed_indices and tile_index not in needed_indices:
                logger.debug(f"[DEBUG_UI] Dropping stale tile data for index {tile_index}")
                self._check_loading_status()
                return
            logger.debug(f"[DEBUG_UI] Applying tile data to index {tile_index}")
            item.set_tile_data(tile_index, indexed_slice, lut, actual_min, actual_max)

        self._check_loading_status()

    def _on_image_worker_error(self, worker_key, error):
        lw = self.lw
        if worker_key in lw.active_image_workers:
            del lw.active_image_workers[worker_key]
        logger.warning(f"Image Worker Error ({worker_key}): {error}")

    def _check_loading_status(self):
        if hasattr(self.lw, 'drop_controller'):
            self.lw.drop_controller._check_loading_status()

    # ─── Scale Management ────────────────────────────────────

    def set_horizontal_scale(self, factor):
        """Scale all track widths by a fixed factor."""
        lw = self.lw
        lw.current_h_scale = factor
        new_sizes = []
        for i in range(lw.splitter.count()):
            widget = lw.splitter.widget(i)
            if widget == lw.spacer:
                new_sizes.append(60)
            else:
                base_w = getattr(widget, 'base_width', 200)
                new_sizes.append(int(base_w * factor))

        lw.splitter.setSizes(new_sizes)
        lw._sync_container_width(new_sizes)

        master_vb = lw.get_master_viewbox()
        if master_vb:
            (min_y, max_y) = master_vb.viewRange()[1]
            self.apply_depth_range(min_y, max_y)

    def set_vertical_scale(self, scale_val):
        """[NEW] Programmatically set the vertical scale (e.g., 10 for 1:10)."""
        lw = self.lw
        if hasattr(lw, 'scale_control'):
            lw.scale_control.combo.setCurrentText(f"1:{scale_val}")

            def safe_update():
                if lw.track_containers and lw.track_containers[0].plot_widget.height() > 0:
                    lw.scale_control.update_scale()
                else:
                    # Retry once more if still not ready (layout still pending)
                    QTimer.singleShot(400, lw.scale_control.update_scale)

            QCoreApplication.processEvents()
            QTimer.singleShot(300, safe_update)

    def force_image_refresh(self):
        """Force refresh all image track caches with current buffer multiplier."""
        lw = self.lw
        master_vb = lw.get_master_viewbox()
        if not master_vb:
            return
        (min_y, max_y) = master_vb.viewRange()[1]

        # Invalidate all tiled or legacy loaded ranges for all image tracks
        for track in lw.track_containers:
            pw = track.plot_widget
            if hasattr(pw, 'image_data_cache'):
                cache = pw.image_data_cache
                if 'tiles_loading' in cache:
                    cache['tiles_loading'].clear()
                
                # If using TiledImageItem, clear its visual tiles
                item = getattr(pw, 'image_item', None)
                if hasattr(item, 'clear'):
                    item.clear()
                    cache['render_generation'] = cache.get('render_generation', 0) + 1
                
                # Legacy support
                cache['loaded_range'] = [-99999, -99999]

        # Trigger refresh
        self.apply_depth_range(min_y, max_y)

    # ─── Depth Limits ────────────────────────────────────────

    def update_depth_limits(self, depth):
        lw = self.lw
        # [FIX] Filter out NaN/Inf values before calculating limits 
        # (common in manually entered data with empty rows)
        finite_depth = depth[np.isfinite(depth)]
        if len(finite_depth) == 0:
            return

        d_min, d_max = float(finite_depth[0]), float(finite_depth[-1])
        if d_min > d_max:
            d_min, d_max = d_max, d_min

        if lw.global_min_depth is None or np.isnan(lw.global_min_depth):
            lw.global_min_depth = d_min
            lw.global_max_depth = d_max
        else:
            lw.global_min_depth = min(lw.global_min_depth, d_min)
            lw.global_max_depth = max(lw.global_max_depth, d_max)

        # [REFINED] Respect custom limits if they exist
        limit_min = lw.custom_min_depth if lw.custom_min_depth is not None else lw.global_min_depth
        limit_max = lw.custom_max_depth if lw.custom_max_depth is not None else lw.global_max_depth

        for t in lw.track_containers:
            pw = t.plot_widget
            if hasattr(pw, 'getViewBox'):
                vb = pw.getViewBox()
                if vb:
                    vb.setLimits(yMin=limit_min, yMax=limit_max)
            # [FIX] Also apply limits to overlay viewboxes to prevent over-scroll desync
            if hasattr(pw, 'curve_viewboxes'):
                for entry in pw.curve_viewboxes:
                    vb_sub = entry.get('viewbox')
                    if vb_sub:
                        vb_sub.setLimits(yMin=limit_min, yMax=limit_max)

        if lw.global_min_depth is not None:
            lw.v_scrollbar.setMinimum(int(limit_min * lw.SCROLL_PRECISION))

    def set_custom_depth_limits(self, d_start: float, d_end: float) -> None:
        """
        Manually restrict the viewable depth range.
        If d_start/d_end match global range, effectively 'unlocks' the restriction.
        """
        lw = self.lw
        # Close enough to global range? Reset to None
        is_global = False
        if lw.global_min_depth is not None and lw.global_max_depth is not None:
            if abs(d_start - lw.global_min_depth) < 1e-3 and abs(d_end - lw.global_max_depth) < 1e-3:
                is_global = True

        if is_global:
            lw.custom_min_depth = None
            lw.custom_max_depth = None
        else:
            lw.custom_min_depth = d_start
            lw.custom_max_depth = d_end

        limit_min = lw.custom_min_depth if lw.custom_min_depth is not None else lw.global_min_depth
        limit_max = lw.custom_max_depth if lw.custom_max_depth is not None else lw.global_max_depth

        # Apply limits to all viewboxes
        for t in lw.track_containers:
            pw = t.plot_widget
            if hasattr(pw, 'getViewBox'):
                vb = pw.getViewBox()
                if vb:
                    vb.setLimits(yMin=limit_min, yMax=limit_max)
            # [FIX] Also apply limits to overlay viewboxes to prevent over-scroll desync
            if hasattr(pw, 'curve_viewboxes'):
                for entry in pw.curve_viewboxes:
                    vb_sub = entry.get('viewbox')
                    if vb_sub:
                        vb_sub.setLimits(yMin=limit_min, yMax=limit_max)

        # [FIX] Viewport Persistence
        vb_master = lw.get_master_viewbox()
        needs_jump = True
        if vb_master:
            (v_min, v_max) = vb_master.viewRange()[1]
            # If current view is substantially inside new limits, don't jump
            if v_min >= limit_min - 0.1 and v_max <= limit_max + 0.1:
                needs_jump = False

        if needs_jump:
            self.apply_depth_range(d_start, d_end)
        else:
            # Just refresh scrollbar range to reflect new limit visibility
            self._update_scrollbar_range()
