"""
ImageManager — Extracted from LogTrackContainer and InteractivePlotWidget
Handles the setup, caching, cleanup, and rendering (to QImage via numpy)
of 2D image data (like Acoustic Waveforms or Borehole Image Logs).
"""
import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QColor

from ..utils.colormap_utils import get_standard_colormap
from ..utils.plot_style_utils import (
    DEFAULT_IMAGE_CMAP,
    DEFAULT_NULL_COLOR,
    normalize_curve_plot_style,
    rotate_image_columns,
)
from ..utils.plot_value_utils import build_invalid_value_mask, compute_auto_display_range
from .tiled_image_item import TiledImageItem
from ..utils.logger import logger

class ImageTrackManager:
    """Static utility class to handle 2D image data rendering and lifecycle."""

    @staticmethod
    def setup_image_track(track, data, depth, info):
        """
        Calculates extremes, initializes pyqtgraph ImageItem, 
        sets up the background and caching dictionary for multi-layer rendering.
        
        'track' is the TrackContainer (parent of PlotWidget).
        """
        info = normalize_curve_plot_style(info)
        plot_widget = track.plot_widget
        # Default grid to off for new image-only tracks
        if len(plot_widget.curves) == 0:
            plot_widget.show_grid_x = False
            plot_widget.show_grid_y = False
        
        # Auto-calculate min/max if absent
        if 'min' not in info or 'max' not in info:
            d_min_calc, d_max_calc = compute_auto_display_range(
                data,
                is_image=True,
                is_log=info.get('log', False),
            )
            info['min'] = d_min_calc
            info['max'] = d_max_calc
        
        if 'null_color' not in info:
            info['null_color'] = DEFAULT_NULL_COLOR

        # [NEW] Use TiledImageItem instead of a single ImageItem
        tiled_item = TiledImageItem()
        tiled_item.track = track # [CRITICAL] Back-reference for ScrollManager
        
        # Set track background color based on null_color preference
        from core.app_config import app_config
        res = app_config.resolve_null_color(info.get('null_color', DEFAULT_NULL_COLOR))
        if res == 'Theme':
            bg_color = app_config.get_theme_qcolor('plot_bg')
        else:
            bg_color = QColor(Qt.white) if res == 'White' else QColor(Qt.black)
        plot_widget.setBackground(bg_color)
        if hasattr(plot_widget, 'getViewBox'):
            vb = plot_widget.getViewBox()
            if vb: 
                vb.setBackgroundColor(bg_color)
        
        # Add TiledImageItem directly to plot widget
        plot_widget.addItem(tiled_item)
        plot_widget.image_item = tiled_item
        
        # Configure layout behavior for images
        plot_widget.setXRange(0, 360, padding=0)
        plot_widget.show_grid_x = False
        plot_widget.show_grid_y = False
        plot_widget.set_grid_style(False, False)
        
        # Calculate total depth range for the tiling container
        # Fix: Use nanmin/nanmax to prevent the image track from disappearing when depth[0] is NaN
        depth_min, depth_max = (np.nanmin(depth), np.nanmax(depth)) if len(depth) > 0 else (0, 1000)
        tiled_item.set_depth_range(depth_min, depth_max)
        
        # Initialize Cache
        plot_widget.image_data_cache = {
            'data': data,
            'depth': depth,
            'full_depth_range': [depth_min, depth_max],
            'tiles_loading': set(), # Track indices currently being fetched
            'render_generation': 0,
        }
        
        image_obj = {
            'item': tiled_item,
            'is_image': True, 
            'data': data, 
            'depth': depth, 
            'info': info, 
            'is_buffered': True,
            'is_tiled': True
        }
        
        # [NEW] Mandatory Registration for ScrollManager visibility
        if not hasattr(plot_widget, 'curves'):
            plot_widget.curves = []
        if image_obj not in plot_widget.curves:
            plot_widget.curves.append(image_obj)
            
        track.header.add_curve_info(info)
        
        # [NEW] Cold Start: Trigger first viewport refresh immediately
        lw = track.log_widget if hasattr(track, 'log_widget') else None
        if not lw and hasattr(track, 'find_log_widget'):
            lw = track.find_log_widget()
            
        if lw and hasattr(lw, 'scroll_mgr'):
            (v_min, v_max) = plot_widget.getViewBox().viewRange()[1]
            logger.debug(f"[IMAGE_DEBUG] Starting cold-start refresh for depth range {depth_min}-{depth_max}")
            lw.scroll_mgr._update_image_slice(track, v_min, v_max, force=True)
            
        return image_obj

    @staticmethod
    def cleanup_image_track(plot_widget):
        """Removes the ImageItems and clears the data cache."""
        for attr in ['image_item', 'image_item_med', 'image_item_low']:
            item = getattr(plot_widget, attr, None)
            if item:
                plot_widget.removeItem(item)
                setattr(plot_widget, attr, None)
        
        if hasattr(plot_widget, 'image_data_cache'):
            del plot_widget.image_data_cache

    @staticmethod
    def render_image_to_painter(painter, curve, min_y, max_y, w, h):
        """
        Numpy heavy-lifting -> Color Mapping -> QImage export.
        Called directly by InteractivePlotWidget.render_to during JPG/PDF export.
        """
        img_data, depth, info = curve.get('data'), curve.get('depth'), curve.get('info')
        idx_start, idx_end = np.searchsorted(depth, min_y), np.searchsorted(depth, max_y)
        slice_data, slice_depth = img_data[idx_start:idx_end], depth[idx_start:idx_end]
        slice_data = rotate_image_columns(slice_data, info.get('azimuth_start', 0.0))
        
        if len(slice_data) == 0:
            return
            
        d_min, d_max = info['min'], info['max']
        is_log = info.get('log', False)
        
        if is_log:
            pos_mask = (slice_data > 0)
            safe_data = slice_data.copy()
            safe_data[~pos_mask] = 1e-4 
            temp_min, temp_max = max(1e-4, d_min), max(max(1e-4, d_min) * 10, d_max)
            l_min, l_max = np.log10(temp_min), np.log10(temp_max)
            norm = np.clip((np.log10(safe_data) - l_min) / (l_max - l_min), 0, 1)
        else:
            norm = np.clip((slice_data - d_min) / (d_max - d_min), 0, 1)
            
        pg_cmap, _ = get_standard_colormap(info.get('cmap', DEFAULT_IMAGE_CMAP).lower(), invert=info.get('invert', False))
        rgb = pg_cmap.map(np.nan_to_num(norm, nan=0.0), mode='byte')
        
        invalid = build_invalid_value_mask(slice_data, is_log=is_log)
        rgb[invalid] = [0, 0, 0, 0] # Make invalid points transparent
        
        qimg = QImage(rgb.data, rgb.shape[1], rgb.shape[0], QImage.Format_RGBA8888)
        
        y_start_p = (slice_depth[0] - min_y) / (max_y - min_y) * h
        y_end_p = (slice_depth[-1] - min_y) / (max_y - min_y) * h
        
        painter.drawImage(QRectF(0, y_start_p, w, y_end_p - y_start_p), qimg)
