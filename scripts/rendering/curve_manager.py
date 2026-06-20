import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QBrush
from ..utils.colormap_utils import get_standard_colormap
from ..utils.plot_style_utils import DEFAULT_IMAGE_CMAP, DEFAULT_NULL_COLOR, normalize_curve_plot_style, normalize_fill_style

class CurveManager:
    """
    Decouples curve logic from UI containers.
    Handles data processing, item creation, and style application.
    """
    
    @staticmethod
    def process_image_data(data, info):
        """Processes raw image data into indexed uint8 data and LUT."""
        info = normalize_curve_plot_style(info)
        # [OPTIMIZATION] Check for Proxy + Cached Min/Max to avoid full-scans
        if hasattr(data, 'min') and hasattr(data, 'max'):
            d_min_calc, d_max_calc = data.min(), data.max()
        else:
            invalid_mask_temp = ~np.isfinite(data)
            valid_mask = ~invalid_mask_temp
            if np.any(valid_mask):
                d_min_calc = float(np.min(data[valid_mask]))
                d_max_calc = float(np.max(data[valid_mask]))
            else:
                d_min_calc, d_max_calc = 0.0, 100.0
        
        d_min = info.get('min', d_min_calc)
        d_max = info.get('max', d_max_calc)
        if d_max == d_min: d_max += 1e-5
        
        info['min'], info['max'] = d_min, d_max
        info['null_color'] = info.get('null_color', DEFAULT_NULL_COLOR)

        # Re-calculate invalid mask (safe for Proxy via __array__)
        invalid_mask = ~np.isfinite(data)

        if info.get('log'):
             pos_mask = (data > 0)
             local_invalid_mask = invalid_mask | (~pos_mask)
             # Note: Full read triggered if it's a proxy, but this is unavoidable for global normalization
             log_data = np.copy(data) 
             log_data[~pos_mask] = 1e-4
             if d_min <= 0: d_min = 1e-4
             if d_max <= d_min: d_max = d_min * 10
             l_min, l_max = np.log10(d_min), np.log10(d_max)
             norm = np.clip((np.log10(log_data) - l_min) / (l_max - l_min) * 254, 0, 254)
             norm_filled = np.nan_to_num(norm, nan=255.0)
             indexed_data = norm_filled.astype(np.uint8)
             indexed_data[local_invalid_mask] = 255
        else:
             norm = np.clip((data - d_min) / (d_max - d_min) * 254, 0, 254)
             norm_filled = np.nan_to_num(norm, nan=255.0)
             indexed_data = norm_filled.astype(np.uint8)
             indexed_data[invalid_mask] = 255
        
        cmap_name = info.get('cmap', DEFAULT_IMAGE_CMAP).lower()
        invert_cmap = info.get('invert', False)
        pg_cmap, _ = get_standard_colormap(cmap_name, invert=invert_cmap)
        lut = pg_cmap.getLookupTable(0.0, 1.0, 255, alpha=True, mode='byte')
        transparent_color = np.array([[0, 0, 0, 0]], dtype=np.ubyte)
        full_lut = np.vstack([lut, transparent_color])
        
        return indexed_data, full_lut, info

    @staticmethod
    def create_image_item(indexed_data, full_lut, depth):
        """Creates a pg.ImageItem with proper geometry."""
        img = pg.ImageItem(axisOrder='row-major')
        img.setImage(indexed_data, levels=[0, 255], lut=full_lut)
        
        depth_min, depth_max = depth[0], depth[-1]
        if depth_min > depth_max: depth_min, depth_max = depth_max, depth_min
        img.setRect(QRectF(0, depth_min, 360, depth_max - depth_min))
        return img

    @staticmethod
    def update_image_on_item(item, data, info, settings):
        """Updates an existing ImageItem with new settings."""
        merged = info.copy()
        merged.update(settings)
        
        indexed_data, full_lut, merged = CurveManager.process_image_data(data, merged)
        item.setImage(indexed_data, levels=[0, 255], lut=full_lut)
        
        depth = merged.get('depth')
        if depth is not None and len(depth) > 0:
            depth_min, depth_max = depth[0], depth[-1]
            if depth_min > depth_max: depth_min, depth_max = depth_max, depth_min
            item.setRect(QRectF(0, depth_min, 360, depth_max - depth_min))
        
        return indexed_data, full_lut, merged

    @staticmethod
    def calculate_curve_range(data, info):
        """Calculates default min/max for 1D curves, or returns existing if present."""
        info = normalize_curve_plot_style(info)
        is_log = info.get('log', False)
        
        # If min/max are already in info (e.g. from template), respect them
        if 'min' in info and 'max' in info:
            info['log'] = is_log
            return info['min'], info['max'], is_log, info
            
        if is_log:
            # Handle Proxy
            if hasattr(data, 'min') and hasattr(data, 'max'):
                d_min, d_max = data.min(), data.max()
                if d_min <= 0: d_min = 0.2
            else:
                valid = data[data > 0]
                if len(valid) > 0:
                    d_min, d_max = float(np.min(valid)), float(np.max(valid))
                else:
                    d_min, d_max = 0.2, 2000
            info['log'] = True
        else:
            # Handle Proxy
            if hasattr(data, 'min') and hasattr(data, 'max'):
                d_min, d_max = data.min(), data.max()
            else:
                valid = data[np.isfinite(data)]
                if len(valid) > 0:
                    d_min, d_max = float(np.min(valid)), float(np.max(valid))
                    span = d_max - d_min
                    if span == 0: span = 1
                    d_min -= span * 0.05
                    d_max += span * 0.05
                else:
                    d_min, d_max = 0, 100
        
        info['min'], info['max'] = d_min, d_max
        return d_min, d_max, is_log, info

    @staticmethod
    def update_line_on_item(item, data, depth, info, settings):
        """Updates an existing PlotDataItem with new settings."""
        merged = info.copy()
        merged.update(settings)
        
        is_log = merged.get('log', False)
        # [OPTIMIZATION] Avoid full-disk-read Log Transform for H5Proxies at init.
        # [FIX] Do NOT perform eager log transform here. 
        # ScrollManager handles all scale-specific transformations during slicing 
        # to ensure consistency between H5Proxies and Numpy arrays.
        plot_data = data
            
        # Ensure data and depth have the same length to avoid shape mismatch errors
        # [REFINED] Use NaN padding instead of simple trimming to be more robust
        len_p = len(plot_data)
        len_d = len(depth)
        
        if len_p != len_d:
            max_len = max(len_p, len_d)
            if len_p < max_len:
                pad = np.full(max_len - len_p, np.nan)
                plot_data = np.concatenate([plot_data, pad])
            if len_d < max_len:
                # For depth, we pad with the last value + step if possible, or just np.nan
                last_val = depth[-1] if len_d > 0 else 0
                step = depth[1] - depth[0] if len_d > 1 else 0.1
                pad = np.linspace(last_val + step, last_val + step * (max_len - len_d), max_len - len_d)
                depth = np.concatenate([depth, pad])
        
        item.setData(plot_data, depth)
        CurveManager.apply_line_style(item, merged)
        
        return plot_data, depth, merged

    @staticmethod
    def apply_line_style(item, merged):
        """Apply visual style to an existing PlotDataItem without reloading its data."""
        is_log = merged.get('log', False)

        # Ensure line_style is stored as an integer for JSON serialization
        ls_default = Qt.SolidLine.value if hasattr(Qt.SolidLine, 'value') else 1
        line_style_raw = merged.get('line_style', ls_default)
        if hasattr(line_style_raw, 'value'):
            line_style = line_style_raw.value
        else:
            try:
                line_style = int(line_style_raw)
            except:
                line_style = ls_default
        merged['line_style'] = line_style

        pen = pg.mkPen(color=merged['color'], width=merged.get('line_width', 1.0), style=Qt.PenStyle(line_style))
        item.setPen(pen)

        fill_mode = merged.get('fill_mode', 'None')
        if fill_mode != 'None' and hasattr(item, 'curve') and hasattr(item.curve, 'setFillOptions'):
            fill_style = normalize_fill_style(merged)
            fill_color = QColor(fill_style['fill_color'])

            inv = merged.get('invert_x', False)
            if fill_mode == 'Left':
                val = merged.get('max', 100) if inv else merged.get('min', 0)
                level = np.log10(max(1e-10, val)) if is_log else val
            else:
                val = merged.get('min', 0) if inv else merged.get('max', 100)
                level = np.log10(max(1e-10, val)) if is_log else val

            item.curve.setFillOptions(level, QBrush(fill_color))
        elif hasattr(item, 'curve') and hasattr(item.curve, 'setFillOptions'):
            item.curve.setFillOptions(None, None)
        else:
            item.setBrush(None)

        item.setVisible(merged.get('visible', True))

    @staticmethod
    def create_curve_item(data, depth, info, is_log):
        """Creates a pg.PlotDataItem with proper transformation."""
        # Use our custom VerticalLoggingCurveItem for correct filling
        from .plot_components import VerticalLoggingCurveItem
        item = pg.PlotDataItem()
        
        # Replace internal PlotCurveItem with our VerticalLoggingCurveItem
        if hasattr(item, 'curve'):
            item.curve.setParentItem(None) # Remove old
        item.curve = VerticalLoggingCurveItem(autoDownsample=True, clipToView=True)
        item.curve.setParentItem(item) # Add new
        
        plot_data, depth, merged = CurveManager.update_line_on_item(item, data, depth, info, {})
        return item, plot_data, depth, merged
