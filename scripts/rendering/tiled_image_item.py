import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF, Signal, QObject
from PySide6.QtWidgets import QGraphicsItem, QGraphicsObject
from PySide6.QtGui import QPainter, QColor
import numpy as np
from ..utils.logger import logger

MAX_TILE_CACHE_BYTES_PER_TRACK = 128 * 1024 * 1024

class TiledImageItem(QGraphicsObject):
    """
    A container item that manages multiple ImageItem 'tiles' for handling 
    extremely long borehole images with high performance.
    """
    tile_requested = Signal(int, float, float) # tile_index, min_y, max_y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.tiles = {} # {index: pg.ImageItem}
        self.tile_meta = {} # {index: {"bytes": int, "last_used": float}}
        self._tile_cache_bytes = 0
        self.track = None # Back-reference to the owning track container
        self.px_height_per_tile = 1024 # Target visual height, but m_per_tile is now fixed
        self.m_per_tile = 15.0 # [FIXED] 15m per tile to ensure stable indexing and no flicker
        self._needed_indices = set()
        self._center_tile_idx = 0
        self._rect = QRectF(0, 0, 360, 10000) # Initial large bounding box
        self.setFlag(QGraphicsItem.ItemHasNoContents, True)

    def _estimate_tile_bytes(self, indexed_slice):
        if indexed_slice is None:
            return 0
        raw_bytes = getattr(indexed_slice, "nbytes", 0)
        shape = getattr(indexed_slice, "shape", ())
        if len(shape) >= 2:
            display_bytes = int(shape[0]) * int(shape[1]) * 4
        else:
            display_bytes = raw_bytes
        return int(raw_bytes + display_bytes)

    def _remove_tile(self, idx):
        item = self.tiles.pop(idx, None)
        meta = self.tile_meta.pop(idx, None)
        if meta:
            self._tile_cache_bytes = max(0, self._tile_cache_bytes - int(meta.get("bytes", 0)))
        if item is not None:
            item.setParentItem(None)
            if self.scene():
                self.scene().removeItem(item)

    def _prune_tile_cache(self):
        if self._tile_cache_bytes <= MAX_TILE_CACHE_BYTES_PER_TRACK:
            return

        candidates = [
            idx for idx in self.tiles
            if idx not in self._needed_indices
        ]
        candidates.sort(
            key=lambda idx: (
                -abs(idx - self._center_tile_idx),
                self.tile_meta.get(idx, {}).get("last_used", 0),
            )
        )

        for idx in candidates:
            if self._tile_cache_bytes <= MAX_TILE_CACHE_BYTES_PER_TRACK:
                break
            self._remove_tile(idx)

        if self._tile_cache_bytes > MAX_TILE_CACHE_BYTES_PER_TRACK:
            logger.debug(
                f"Image tile cache remains above limit because visible tiles are retained: "
                f"{self._tile_cache_bytes / (1024 * 1024):.1f} MB"
            )

    def set_depth_range(self, d_min, d_max):
        """Update the overall bounding box of the track (NaN safe)."""
        # [NEW] Ensure we have valid numbers for the scene bounding box
        if np.isnan(d_min) or np.isnan(d_max):
            d_min = 0 if np.isnan(d_min) else d_min
            d_max = d_min + 1000 if np.isnan(d_max) else d_max
            
        self.prepareGeometryChange()
        self._rect = QRectF(0, d_min, 360, d_max - d_min)
        self.update()

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget):
        # Container itself is invisible (ItemHasNoContents)
        pass

    def update_viewport(
        self,
        min_y,
        max_y,
        view_height_px,
        loading_indices=None,
        request_tiles=True,
        prune_tiles=True,
    ):
        """
        Calculates which tiles are needed for the current viewport (Fixed 15m mode).
        """
        if loading_indices is None: loading_indices = set()
        if self.m_per_tile <= 0: return

        # Indexing is now STABLE across zoom levels
        start_idx = int(np.floor(min_y / self.m_per_tile))
        end_idx = int(np.ceil(max_y / self.m_per_tile))
        
        # Keep the one-tile prefetch buffer inside the actual data extent.  In
        # particular, shallow wells starting in tile 0 must not request tile
        # -1: ``ImageSliceWorker`` historically used -1 as a non-tile sentinel,
        # and an out-of-range request can otherwise remain registered forever.
        data_start_idx = int(np.floor(self._rect.top() / self.m_per_tile))
        data_end_idx = int(np.ceil(self._rect.bottom() / self.m_per_tile)) - 1
        request_start_idx = max(start_idx - 1, data_start_idx)
        request_end_idx = min(end_idx, data_end_idx)
        needed_indices = (
            set(range(request_start_idx, request_end_idx + 1))
            if request_start_idx <= request_end_idx
            else set()
        )
        self._needed_indices = needed_indices
        self._center_tile_idx = (start_idx + end_idx) // 2
        now = time.monotonic()
        for idx in needed_indices:
            if idx in self.tile_meta:
                self.tile_meta[idx]["last_used"] = now
        
        # 1. Clear tiles far away (LRU replacement for simplicity).
        # During active scrollbar dragging we can skip pruning so the old image
        # remains visible until the user settles on a new depth range.
        if prune_tiles:
            visible_buffer = 2 # Keep 2 tiles above/below
            to_remove = []
            for idx in self.tiles:
                if idx < (start_idx - visible_buffer) or idx > (end_idx + visible_buffer):
                    to_remove.append(idx)
            
            for idx in to_remove:
                self._remove_tile(idx)

            self._prune_tile_cache()

        # 2. Identify missing tiles
        if request_tiles:
            for idx in needed_indices:
                # [ANTI-LOOP] Only emit signal if tile is NOT already loading
                if idx not in self.tiles and idx not in loading_indices:
                    t_min = idx * self.m_per_tile
                    t_max = t_min + self.m_per_tile
                    logger.debug(f"[DEBUG_TILE] Requesting tile {idx} (new and not loading)")
                    self.tile_requested.emit(idx, t_min, t_max)

    def set_tile_data(self, idx, indexed_slice, lut, actual_min, actual_max):
        """Apply rendered data to a specific tile."""
        if idx in self.tiles:
            item = self.tiles[idx]
            old_meta = self.tile_meta.get(idx)
            if old_meta:
                self._tile_cache_bytes = max(0, self._tile_cache_bytes - int(old_meta.get("bytes", 0)))
        else:
            item = pg.ImageItem(axisOrder='row-major')
            item.setParentItem(self)
            self.tiles[idx] = item
            
        item.setImage(indexed_slice, autoLevels=False, levels=[0, 255], lut=lut, reuse=True)
        item.setRect(QRectF(0, actual_min, 360, actual_max - actual_min))
        item.setZValue(-1) # Beneath other items but standard interactive items
        item.setVisible(True)
        tile_bytes = self._estimate_tile_bytes(indexed_slice)
        self.tile_meta[idx] = {"bytes": tile_bytes, "last_used": time.monotonic()}
        self._tile_cache_bytes += tile_bytes
        self._prune_tile_cache()
        # print(f"[RENDER] Tile Applied: idx={idx}, range={actual_min:.2f}-{actual_max:.2f}")

    def clear(self):
        """Full reset of all tiles."""
        for idx in list(self.tiles.keys()):
            self._remove_tile(idx)
        self.tile_meta = {}
        self._tile_cache_bytes = 0
        self._needed_indices = set()
