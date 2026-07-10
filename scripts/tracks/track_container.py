import pyqtgraph as pg
import numpy as np
from typing import Optional, List, Dict, Any, Union, Type
from PySide6.QtWidgets import QFrame, QMenu, QStyleOption, QStyle, QSplitter, QApplication
from PySide6.QtCore import Qt, QRectF, QRect, QPointF, Signal, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QAction, QBrush
from core.app_config import app_config

from ..utils.colormap_utils import get_standard_colormap
from ..rendering.plot_constants import AXIS_WIDTH
from ..ui.plot_dialogs import UnifiedSettingsDialog
from ..rendering.plot_components import (InteractivePlotWidget, HeaderWidget, SelectionOverlay, PainterDepthTrack)
from ..rendering.image_manager import ImageTrackManager
from ..rendering.fill_manager import FillManager
from ..rendering.curve_manager import CurveManager
from ..rendering.fracture_annotations import (
    MIN_FRACTURE_PREVIEW_POINTS,
    MIN_FRACTURE_PICK_POINTS,
    build_fracture_annotation,
    sinusoidal_fracture_xy,
)
from ..utils.logger import logger
from ..utils.plot_style_utils import DEFAULT_IMAGE_CMAP, DEFAULT_NULL_COLOR, normalize_curve_plot_style
from .interaction_handler import TrackInteractionHandler

class BaseTrackContainer(QFrame):
    """Base class for all track containers. Handles UI layout, selection, and interactions."""
    selectionChanged = Signal()
    
    def __init__(self, parent=None, plot_widget_class=InteractivePlotWidget):
        super().__init__(parent)
        self.layout = None
        
        self.plot_widget = plot_widget_class(self)
        self.header = HeaderWidget(self)
        self.header.raise_()
        self.selection_overlay = SelectionOverlay(self)
        self.selection_overlay.raise_()
        
        try:
            self.plot_widget.setFrameShape(QFrame.NoFrame)
        except:
            pass
        
        if hasattr(self.plot_widget, 'is_log_scale'):
            self.plot_widget.is_log_scale = False
        if hasattr(self.plot_widget, 'curves'):
            self.plot_widget.curves = [] 
        
        self.log_widget = self.find_log_widget()
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
        
        self.setMinimumWidth(30)
        self.is_selected = False
        self.selected_curve_indices = set()
        self.track_name = None
        self.is_accum_fill = False
        self.interaction_handler = TrackInteractionHandler(self)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoFillBackground(True)
        
    def get_viewbox(self):
        """[HELPER] Consistent way to access the ViewBox across all track types."""
        if hasattr(self.plot_widget, 'getViewBox'):
            return self.plot_widget.getViewBox()
        return None

    @staticmethod
    def _safe_x_range(d_min, d_max, is_log):
        """
        Return a finite drawable axis range and its display-space coordinates.
        Prevents ViewBox crashes like: Cannot set range [nan, nan].
        """
        def _to_float(v):
            try:
                return float(v)
            except Exception:
                return np.nan

        d_min = _to_float(d_min)
        d_max = _to_float(d_max)

        min_ok = np.isfinite(d_min)
        max_ok = np.isfinite(d_max)

        if is_log:
            if not min_ok and not max_ok:
                d_min, d_max = 0.2, 2000.0
            elif not min_ok and max_ok:
                d_min = max(1e-4, d_max / 10.0) if d_max > 0 else 0.2
            elif min_ok and not max_ok:
                d_max = max(d_min * 10.0, 2.0) if d_min > 0 else 2000.0

            if d_min <= 0:
                d_min = 1e-4
            if d_max <= d_min:
                d_max = d_min * 10.0

            x_min = np.log10(d_min)
            x_max = np.log10(d_max)
        else:
            if not min_ok and not max_ok:
                d_min, d_max = 0.0, 100.0
            elif not min_ok and max_ok:
                d_min = d_max - 1.0
            elif min_ok and not max_ok:
                d_max = d_min + 1.0

            if d_max < d_min:
                d_min, d_max = d_max, d_min
            if abs(d_max - d_min) < 1e-12:
                d_max = d_min + 1.0

            x_min, x_max = d_min, d_max

        return d_min, d_max, x_min, x_max

    @property
    def selected_curve_idx(self):
        return list(self.selected_curve_indices)[0] if self.selected_curve_indices else -1

    def update_theme(self):
        """Propagate theme changes to header and plot widget."""
        bg = app_config.get_theme_color('plot_bg')
        self.setStyleSheet(f"background-color: {bg}; border: none;")
        
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor(bg))
        self.setPalette(palette)
        
        if hasattr(self, 'header') and hasattr(self.header, 'update_theme'):
            self.header.update_theme()
        if hasattr(self, 'plot_widget') and hasattr(self.plot_widget, 'update_theme'):
            self.plot_widget.update_theme()
        self.update()

    @selected_curve_idx.setter
    def selected_curve_idx(self, val):
        if val < 0:
            self.selected_curve_indices.clear()
        else:
            self.selected_curve_indices = {val}

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        if hasattr(self, 'plot_widget') and self.plot_widget:
            self.plot_widget.setGeometry(0, 0, w, h)
        header_h = self.header.height() if hasattr(self, 'header') and self.header and self.header.isVisible() else 0
        if hasattr(self, 'header') and self.header:
            self.header.setGeometry(0, 0, w, header_h)
        if hasattr(self, 'selection_overlay') and self.selection_overlay:
            self.selection_overlay.setGeometry(0, 0, w, h)
            self.selection_overlay.raise_()
    
    def show_context_menu(self, pos):
        menu = QMenu(self)
        del_act = QAction("Delete Track", self)
        del_act.triggered.connect(self.delete_me)
        menu.addAction(del_act)
        menu.addSeparator()
        
        if hasattr(self.plot_widget, 'curves') and len(self.plot_widget.curves) > 0:
            rem_menu = menu.addMenu("Remove Curve")
            for i, c in enumerate(self.plot_widget.curves):
                act = QAction(c['info']['name'], self)
                act.triggered.connect(lambda checked=False, idx=i: self.remove_curve_at(idx))
                rem_menu.addAction(act)
            menu.addSeparator()

        add_depth_act = QAction("Add Depth Track", self)
        add_empty_act = QAction("Add Empty Track", self)
        lw = self.find_log_widget()
        if lw:
            add_depth_act.triggered.connect(lambda: lw.add_depth_track())
            add_empty_act.triggered.connect(lambda: lw.add_empty_track())
        menu.addAction(add_depth_act)
        menu.addAction(add_empty_act)
        
        settings_act = QAction("Properties...", self)
        settings_act.triggered.connect(self.open_settings)
        menu.addAction(settings_act)
        menu.exec(self.mapToGlobal(pos))
    
    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        p.setPen(QPen(app_config.get_theme_qcolor("border_std"), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
    
    def mousePressEvent(self, event):
        self.interaction_handler.handle_mouse_press(event)
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        self.interaction_handler.handle_mouse_double_click(event)
        super().mouseDoubleClickEvent(event)
    
    def sync_viewboxes(self, min_y: float, max_y: float) -> None:
        pw = self.plot_widget
        if not hasattr(pw, 'getViewBox'): return
        vb_main = pw.getViewBox()
        if vb_main:
            (v_min, v_max) = vb_main.viewRange()[1]
            if abs(v_min - min_y) > 1e-7 or abs(v_max - max_y) > 1e-7:
                vb_main.setYRange(min_y, max_y, padding=0)

    def select_curve(self, idx, append=False):
        self.interaction_handler.select_curve(idx, append)
    
    def closeEvent(self, event):
        self.log_widget = None
        super().closeEvent(event)
    
    def select_track(self, append=False):
        self.interaction_handler.select_track(append)
    
    def update_selection_style(self):
        try:
            if not getattr(self, 'plot_widget', None): return
        except RuntimeError: return  
            
        if self.is_selected:
            self.selection_overlay.set_selection(True, QColor(app_config.get_theme_color("accent")))
        else:
            self.selection_overlay.set_selection(False)
            
        if hasattr(self.header, 'highlighted_curves'):
            self.header.highlighted_curves = set(self.selected_curve_indices)
        else:
            self.header.highlighted_curve = list(self.selected_curve_indices)[0] if self.selected_curve_indices else -1
        self.header.update()
    
    def keyPressEvent(self, event):
        if not self.interaction_handler.handle_key_press(event):
            super().keyPressEvent(event)
    
    def select_previous_curve(self): self.interaction_handler.select_previous_curve()
    def select_next_curve(self): self.interaction_handler.select_next_curve()
    def move_curve_in_header(self, direction): self.interaction_handler.move_curve_in_header(direction)
    def move_curve_to_adjacent_track(self, direction): self.interaction_handler.move_curve_to_adjacent_track(direction)
    def move_track_left(self): self.interaction_handler.move_track_left()
    def move_track_right(self): self.interaction_handler.move_track_right()
    def move_curve_to_track(self, curve_idx, target_track): self.interaction_handler.move_curve_to_track(curve_idx, target_track)
    def delete_me(self): self.interaction_handler.delete_me()
            
    def render_to(self, painter, rect, min_y, max_y, scale=1.0, scale_text=None, draw_border=True, header_h_override=None):
        header_h = int(self.header.height() * scale)
        actual_header_h = header_h_override if header_h_override is not None else header_h
        
        if len(self.header.items) > 0:
            header_rect = QRect(rect.x(), rect.y(), rect.width(), actual_header_h)
            self.header.render_to(painter, header_rect, scale=scale, scale_text=scale_text, draw_border=draw_border)
        
        plot_y = rect.y() + actual_header_h
        plot_h = rect.height() - actual_header_h
        plot_rect = QRect(rect.x(), plot_y, rect.width(), plot_h)
        self.plot_widget.render_to(painter, plot_rect, min_y, max_y, scale=scale, draw_border=draw_border)

    def find_log_widget(self):
        from ..rendering.plot_widget import LogWidget
        p = self.parent()
        while p:
            if isinstance(p, LogWidget): return p
            p = p.parent()
        return None

    def cleanup(self):
        """Explicitly detach heavy plot resources before the container is deleted."""
        try:
            pw = getattr(self, 'plot_widget', None)
            if pw is not None:
                if hasattr(pw, 'clear_overlays'):
                    pw.clear_overlays()

                if hasattr(pw, 'curves'):
                    for curve in list(pw.curves):
                        item = curve.get('item') or curve.get('curve')
                        vb = curve.get('viewbox')
                        try:
                            if vb and item:
                                vb.removeItem(item)
                            elif item:
                                pw.removeItem(item)
                        except Exception:
                            pass
                    pw.curves.clear()

                if hasattr(pw, 'image_data_cache') or getattr(pw, 'image_item', None):
                    try:
                        ImageTrackManager.cleanup_image_track(pw)
                    except Exception:
                        pass

                if hasattr(pw, 'curve_viewboxes'):
                    pw.curve_viewboxes.clear()

                try:
                    pw.clear()
                except Exception:
                    pass

            if hasattr(self, 'header') and hasattr(self.header, 'items'):
                self.header.items.clear()
        except Exception:
            pass

    def open_settings(self):
        def apply_cb(s): self.apply_track_settings(s)
        log_w = self.log_widget or self.find_log_widget()
        if log_w and log_w.current_settings_dialog:
            dlg = log_w.current_settings_dialog
            dlg.load_for_track(self, apply_callback=apply_cb)
            try: dlg.accepted.disconnect()
            except RuntimeError: pass
            dlg.accepted.connect(lambda: apply_cb(dlg.get_settings()))
            dlg.raise_()
            dlg.activateWindow()
            return
        
        dlg = UnifiedSettingsDialog(self)
        dlg.accepted.connect(lambda: apply_cb(dlg.get_settings()))
        if log_w:
            log_w.open_dialog(dlg)
            dlg.load_for_track(self, apply_callback=apply_cb)
        else:
            dlg.load_for_track(self, apply_callback=apply_cb)
            dlg.exec()

    def apply_track_settings(self, s):
        if "name" in s:
            self.track_name = s["name"] if s["name"].strip() else None
            
        if s["width"] != self.width():
            splitter = self.parent()
            if isinstance(splitter, QSplitter):
                sizes = splitter.sizes()
                idx = splitter.indexOf(self)
                if idx >= 0:
                    delta = s["width"] - sizes[idx]
                    sizes[idx] = s["width"]
                    # Absorb width change from the TrackSpacer (always last),
                    # keeping total sum constant so QSplitter won't scale other tracks.
                    if len(sizes) > 1:
                        sizes[-1] = max(0, sizes[-1] - delta)
                    splitter.setSizes(sizes)
        
        if self.log_widget and "depth_start" in s and "depth_end" in s:
            current_d1 = getattr(self.log_widget, 'custom_min_depth', None) or self.log_widget.global_min_depth
            current_d2 = getattr(self.log_widget, 'custom_max_depth', None) or self.log_widget.global_max_depth
            if abs(s["depth_start"] - current_d1) > 1e-3 or abs(s["depth_end"] - current_d2) > 1e-3:
                self.log_widget.set_custom_depth_limits(s["depth_start"], s["depth_end"])

        if hasattr(self.plot_widget, 'set_grid_style') and ('grid_x' in s or 'grid_y' in s):
            grid_x = s.get('grid_x', getattr(self.plot_widget, 'show_grid_x', False))
            grid_y = s.get('grid_y', getattr(self.plot_widget, 'show_grid_y', True))
            self.plot_widget.set_grid_style(grid_x, grid_y)
            self.plot_widget.show_grid_x = grid_x
            self.plot_widget.show_grid_y = grid_y
        
        if 'log' in s and hasattr(self.plot_widget, 'is_log_scale') and self.plot_widget.is_log_scale != s['log']:
            self.plot_widget.is_log_scale = s['log']
            pi = getattr(self.plot_widget, 'getPlotItem', lambda: None)()
            if pi: pi.setLogMode(x=s['log'], y=False)

        self._update_track_settings_specific(s)
        self.plot_widget.update()
        self.header.update()
        lw = self.log_widget or self.find_log_widget()
        if lw and hasattr(lw, "refresh_fracture_target_tracks"):
            lw.refresh_fracture_target_tracks()

    def _update_track_settings_specific(self, s):
        pass # Override in subclasses

    def get_state(self):
        state = {
            "name": self.track_name,
            "width": self.width(),
            "base_width": getattr(self, 'base_width', 200),
            "header_visible": self.header.isVisible() if hasattr(self, 'header') else True,
            "is_accum_fill": self.is_accum_fill,
            "curves": []
        }
        return state

    def open_curve_settings(self, idx):
        if not hasattr(self.plot_widget, 'curves'): return
        curve_entry = None
        if idx < len(self.plot_widget.curves):
            curve_entry = self.plot_widget.curves[idx]
        if not curve_entry and idx < len(self.header.items):
            info = self.header.items[idx]
            curve_entry = {'viewbox': None, 'curve': None, 'info': info}
        if not curve_entry: return
        
        def apply_cb(settings): self.apply_curve_settings(idx, settings)
        
        log_w = self.log_widget or self.find_log_widget()
        if log_w and log_w.current_settings_dialog:
            dlg = log_w.current_settings_dialog
            dlg.load_for_curve(self, idx, apply_callback=apply_cb)
            try: dlg.accepted.disconnect()
            except RuntimeError: pass
            dlg.accepted.connect(lambda: apply_cb(dlg.get_settings()))
            dlg.raise_()
            dlg.activateWindow()
            return

        dlg = UnifiedSettingsDialog(self)
        dlg.accepted.connect(lambda: apply_cb(dlg.get_settings()))
        if log_w:
            log_w.open_dialog(dlg)
            dlg.load_for_curve(self, idx, apply_callback=apply_cb)
        else:
            dlg.load_for_curve(self, idx, apply_callback=apply_cb)
            dlg.exec()

    # Virtual methods to be implemented by DataTrack/ImageTrack
    def add_curve(self, data, depth, info, rgb_full_bg=None): pass
    def add_curve_at_index(self, data, depth, info, index, rgb_full_bg=None): pass
    def remove_curve_at(self, idx): pass
    def apply_curve_settings(self, idx, settings, trigger_others=True, reload_data=True): pass
    def _refresh_z_orders(self): pass
    def _update_grid_visibility(self): pass

class DepthTrackContainer(BaseTrackContainer):
    """Specialized track container for rendering depth axis."""
    def __init__(self, parent=None):
        super().__init__(parent, plot_widget_class=PainterDepthTrack)
        self.setMinimumWidth(60)

    def open_curve_settings(self, idx):
        """For depth tracks, header double-click should open track properties."""
        self.open_settings()

    def show_depth_axis(self, show: bool):
        left_axis = self.plot_widget.getPlotItem().getAxis('left')
        axis_color = app_config.get_theme_qcolor("text_main")
        if show:
            left_axis.setStyle(showValues=True, tickLength=5)
            left_axis.setPen(pg.mkPen(axis_color, width=1))
            left_axis.setTextPen(axis_color)
            left_axis.setTickPen(axis_color)
            self.plot_widget.plotItem.getAxis('left').setWidth(50) 
        else:
            left_axis.setStyle(showValues=False) 
            left_axis.setPen(None)
            left_axis.setTextPen(None)
            left_axis.setTickPen(QColor(0,0,0,0)) 
            self.plot_widget.plotItem.getAxis('left').setWidth(0)
        self.plot_widget.update()

    def update_theme(self):
        """Specially refresh depth header colors when theme changes."""
        super().update_theme()
        if hasattr(self, 'header') and self.header.items:
            for item in self.header.items:
                if item.get('name', '').lower() == 'depth' or not item.get('range_visible', True):
                    item['color'] = app_config.get_theme_color('text_main')
            self.header.update()

    def get_state(self):
        state = super().get_state()
        state["type"] = "depth"
        # [NEW] Persist Depth Label font and masking settings
        state["label_font_family"] = getattr(self.plot_widget, 'label_font_family', 'Arial')
        state["label_font_size"] = getattr(self.plot_widget, 'label_font_size', 0)
        state["label_mask_enabled"] = getattr(self.plot_widget, 'label_mask_enabled', False)
        state["label_mask_length"] = getattr(self.plot_widget, 'label_mask_length', 2)
        return state

    def apply_track_settings(self, s):
        """Specially handle Depth track header attributes (Title, Unit, Font)."""
        super().apply_track_settings(s)
        
        if "name" in s:
            self.header.set_title(s["name"])
        if "unit" in s:
            self.header.set_unit(s["unit"])
            
        if "font_family" in s or "font_size" in s:
            if not self.header.items:
                self.header.add_curve_info({
                    'name': self.track_name or "Depth", 
                    'unit': s.get('unit', 'm'), 
                    'color': app_config.get_theme_color('text_main'),
                    'range_visible': False
                })
            
            info = self.header.items[0]
            if "font_family" in s: info['font_family'] = s["font_family"]
            if "font_size" in s: info['font_size'] = s["font_size"]
            
        # [NEW] Apply Depth Label font settings to plot_widget (PainterDepthTrack)
        if "label_font_family" in s:
            self.plot_widget.label_font_family = s["label_font_family"]
            self.plot_widget._cache_pixmap = None 
        if "label_font_size" in s:
            self.plot_widget.label_font_size = s["label_font_size"]
            self.plot_widget._cache_pixmap = None 
            
        # [NEW] Apply Depth Masking settings
        if "label_mask_enabled" in s:
            self.plot_widget.label_mask_enabled = s["label_mask_enabled"]
            self.plot_widget._cache_pixmap = None
        if "label_mask_length" in s:
            self.plot_widget.label_mask_length = s["label_mask_length"]
            self.plot_widget._cache_pixmap = None
            
        self.header.update()
        self.plot_widget.update()

class CurveTrackContainer(BaseTrackContainer):
    """Standard track container for 1D log curves."""
    def __init__(self, parent=None):
        super().__init__(parent, plot_widget_class=InteractivePlotWidget)

    def add_curve(self, data: np.ndarray, depth: np.ndarray, info: Dict[str, Any], rgb_full_bg: Optional[QColor] = None) -> None:
        is_image_data = (data is not None and data.ndim > 1) or info.get('is_image', False)
        if is_image_data:
            info['is_image'] = True
            ImageTrackManager.setup_image_track(self, data, depth, info)
            self._refresh_z_orders()
            return

        self._update_grid_visibility()
        d_min, d_max, is_log, info = CurveManager.calculate_curve_range(data, info)
        d_min, d_max, x_min, x_max = self._safe_x_range(d_min, d_max, is_log)
        info['min'], info['max'] = d_min, d_max
        info['line_width'] = info.get('line_width', 1.0)
        info['line_style'] = info.get('line_style', Qt.SolidLine)
        info['visible'] = True

        lw = self.log_widget or self.find_log_widget()
        if lw: lw.update_depth_limits(depth)

        if len(self.plot_widget.curves) == 0:
            self.plot_widget.is_log_scale = is_log
            self.plot_widget.getPlotItem().setLogMode(x=False, y=False)
            self.plot_widget.setXRange(x_min, x_max, 0)
            self.plot_widget.getPlotItem().vb.invertX(info.get('invert_x', False))
            if hasattr(self.plot_widget, 'set_x_params'):
                self.plot_widget.set_x_params(is_log, (d_min, d_max))
        
        vb = self.plot_widget.add_overlay_viewbox(info)
        curve_item, plot_data, depth, info = CurveManager.create_curve_item(data, depth, info, is_log)
        vb.addItem(curve_item)
        curve_item.setClipToView(False)
        skip = self.log_widget.skip_finite_check if getattr(self, 'log_widget', None) else True
        curve_item.setSkipFiniteCheck(skip)
        vb.setXRange(x_min, x_max, padding=0)
        
        lw = self.log_widget or self.find_log_widget()
        if lw:
            l_min = lw.custom_min_depth if lw.custom_min_depth is not None else lw.global_min_depth
            l_max = lw.custom_max_depth if lw.custom_max_depth is not None else lw.global_max_depth
            if l_min is not None and l_max is not None:
                vb.setLimits(yMin=l_min, yMax=l_max)
        
        vb_record = self.plot_widget.curve_viewboxes[-1]
        vb_record.update({'curve': curve_item, 'data': data, 'plot_data': plot_data, 'depth': depth})
        
        curve_obj = {
            'item': curve_item, 'data': data, 'plot_data': plot_data, 
            'depth': depth, 'info': info, 'viewbox': vb
        }
        if 'title' not in info: info['title'] = info.get('name', '')
            
        self.plot_widget.curves.append(curve_obj)
        self.header.add_curve_info(info)
        self._refresh_z_orders()
        self._update_grid_visibility()

    def add_curve_at_index(self, data, depth, info, index, rgb_full_bg=None):
        self.add_curve(data, depth, info, rgb_full_bg=rgb_full_bg)
        if index < len(self.plot_widget.curves) - 1 and len(self.plot_widget.curves) > 1:
            curve_obj = self.plot_widget.curves.pop()
            header_item = self.header.items.pop()
            self.plot_widget.curves.insert(index, curve_obj)
            self.header.items.insert(index, header_item)
            if not curve_obj.get('is_image', False) and len(self.plot_widget.curve_viewboxes) > 0:
                vb_entry = self.plot_widget.curve_viewboxes.pop()
                self.plot_widget.curve_viewboxes.insert(index, vb_entry)
            self.header.update()
            self._update_grid_visibility()

    def _update_accumulative_fills(self):
        FillManager.update_accumulative_fills(self, self.is_accum_fill)

    def apply_track_settings(self, s):
        super().apply_track_settings(s)
        if 'is_accum_fill' in s:
            new_state = s.get('is_accum_fill', False)
            if self.is_accum_fill != new_state:
                self.is_accum_fill = new_state
                FillManager.update_accumulative_fills(self, self.is_accum_fill)
                self.plot_widget.update()

    def remove_curve_at(self, idx):
        if idx >= len(self.plot_widget.curves): return
        c = self.plot_widget.curves.pop(idx)
        if 'viewbox' in c and c['viewbox']:
            c['viewbox'].removeItem(c['item'])
            self.plot_widget.scene().removeItem(c['viewbox'])
        else:
            self.plot_widget.removeItem(c['item'])
        if idx < len(self.plot_widget.curve_viewboxes): self.plot_widget.curve_viewboxes.pop(idx)
        if idx < len(self.header.items):
            self.header.items.pop(idx)
            self.header.adjust_height()
        self._refresh_z_orders()
        self._update_grid_visibility() 
        self.header.update()

    def apply_curve_settings(
        self,
        idx: int,
        settings: Dict[str, Any],
        trigger_others: bool = True,
        reload_data: bool = True,
    ) -> None:
        if idx >= len(self.plot_widget.curves): return
        curve_entry = self.plot_widget.curves[idx]
        info, vb = curve_entry['info'], curve_entry.get('viewbox')
        if not vb: return
        
        item, data, depth = curve_entry.get('item', curve_entry.get('curve')), curve_entry.get('data'), curve_entry.get('depth')
        if reload_data:
            plot_data, depth, merged = CurveManager.update_line_on_item(item, data, depth, info, settings)
        else:
            merged = info.copy()
            merged.update(settings)
            plot_data = curve_entry.get('plot_data', data)
            CurveManager.apply_line_style(item, merged)
        if 'title' in settings: merged['title'] = settings['title']
        
        curve_entry.update({'info': merged, 'plot_data': plot_data, 'depth': depth})
        is_log, c_min, c_max = merged.get('log', False), merged.get('min', 0), merged.get('max', 100)
        c_min, c_max, x_start, x_end = self._safe_x_range(c_min, c_max, is_log)
        merged['min'], merged['max'] = c_min, c_max
        vb.invertX(merged.get('invert_x', False))
        vb.setXRange(x_start, x_end, padding=0)
        if not reload_data:
            curve_entry.pop('_last_slice', None)
        
        lw = self.log_widget or self.find_log_widget()
        if lw and hasattr(lw, 'apply_depth_range'):
            master_vb = lw.get_master_viewbox()
            if master_vb:
                y_min, y_max = master_vb.viewRange()[1]
                lw.apply_depth_range(y_min, y_max, force=True, only_track=self)
        
        FillManager.apply_cross_fill(self, idx)
        if trigger_others:
            for i, other in enumerate(self.plot_widget.curves):
                if i != idx and other.get('info', {}).get('fill_mode') == info.get('name'):
                    self.apply_curve_settings(i, other['info'], trigger_others=False)
        
        if idx < len(self.header.items): self.header.items[idx].update(merged)
        if 'null_color' in merged:
            res = app_config.resolve_null_color(merged['null_color'])
            bg_color = app_config.get_theme_qcolor('plot_bg') if res == 'Theme' else (QColor(Qt.white) if res == 'White' else QColor(Qt.black))
            self.plot_widget.setBackground(bg_color)
        self.header.update()

    def _update_track_settings_specific(self, s):
        ax_min, ax_max = s.get('axis_min'), s.get('axis_max')
        if ax_min is not None and ax_max is not None and hasattr(self.plot_widget, 'set_x_params'):
            self.plot_widget.set_x_params(s.get('log', False), (ax_min, ax_max))
        elif self.plot_widget.curves and hasattr(self.plot_widget, 'set_x_params'):
            c0 = self.plot_widget.curves[0]['info']
            self.plot_widget.set_x_params(s.get('log', False), (c0.get('min', 0.1), c0.get('max', 100.0)))

    def _refresh_z_orders(self):
        n = len(self.plot_widget.curves)
        for i, c in enumerate(self.plot_widget.curves):
            z_val = n - i
            if 'viewbox' in c and c['viewbox']: c['viewbox'].setZValue(z_val)
        if hasattr(self.plot_widget, 'plotItem') and self.plot_widget.plotItem.vb:
            self.plot_widget.plotItem.vb.setZValue(0)

    def _update_grid_visibility(self):
        if hasattr(self.plot_widget, 'set_grid_style'):
            self.plot_widget.set_grid_style(getattr(self.plot_widget, 'show_grid_x', False), getattr(self.plot_widget, 'show_grid_y', True))

    def get_state(self):
        state = super().get_state()
        state["type"] = "data"
        for curve in self.plot_widget.curves:
            info = curve.get('info', {}).copy()
            state["curves"].append(info)
        return state

class AccumulativeTrackContainer(CurveTrackContainer):
    """Specialized track container for accumulative solid fills."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_accum_fill = False

    def apply_track_settings(self, s):
        super().apply_track_settings(s)
            
    def add_curve_at_index(self, data, depth, info, index, rgb_full_bg=None):
        super().add_curve_at_index(data, depth, info, index, rgb_full_bg)
        if self.is_accum_fill: self._update_accumulative_fills()

    def remove_curve_at(self, idx):
        super().remove_curve_at(idx)
        if self.is_accum_fill: self._update_accumulative_fills()

    def move_curve_in_header(self, direction):
        super().move_curve_in_header(direction)
        if self.is_accum_fill: self._update_accumulative_fills()

class ImageTrackContainer(BaseTrackContainer):
    """Specialized track container for 2D image slices/matrices."""
    def __init__(self, parent=None):
        super().__init__(parent, plot_widget_class=InteractivePlotWidget)
        self.fracture_annotations = []
        self._fracture_items = []
        self._fracture_pick_active = False
        self._fracture_pick_points = []
        self._fracture_preview_item = None
        self._fracture_pick_scatter = None
        self.plot_widget.fracture_annotations = self.fracture_annotations
        
    def add_curve(self, data: np.ndarray, depth: np.ndarray, info: Dict[str, Any], rgb_full_bg: Optional[QColor] = None) -> None:
        is_image_data = (data is not None and data.ndim > 1) or info.get('is_image', False)
        lw = self.log_widget or self.find_log_widget()
        if lw: lw.update_depth_limits(depth)

        if is_image_data:
            info['is_image'] = True
            info = normalize_curve_plot_style(info)
            ImageTrackManager.setup_image_track(self, data, depth, info)
            self._refresh_z_orders()
            if lw and hasattr(lw, "refresh_fracture_target_tracks"):
                lw.refresh_fracture_target_tracks()
            return
        else:
            info['is_image'] = False
            d_min, d_max, is_log, info = CurveManager.calculate_curve_range(data, info)
            d_min, d_max, x_min, x_max = self._safe_x_range(d_min, d_max, is_log)
            info['min'], info['max'] = d_min, d_max
            vb = self.plot_widget.add_overlay_viewbox(info)
            curve_item, plot_data, depth, info = CurveManager.create_curve_item(data, depth, info, is_log)
            vb.addItem(curve_item)
            vb.setXRange(x_min, x_max, padding=0)
            self.plot_widget.curves.append({'item': curve_item, 'viewbox': vb, 'is_image': False, 'data': data, 'depth': depth, 'info': info})
            
        self.header.add_curve_info(info)
        self._refresh_z_orders()
        
        master_range = None
        if getattr(self, 'log_widget', None):
            for track in self.log_widget.track_containers:
                if track != self and isinstance(track.plot_widget, InteractivePlotWidget):
                    vb = track.plot_widget.getViewBox()
                    if vb:
                        master_range = vb.viewRange()[1]
                        break
        
        if self.log_widget:
            if master_range: self.log_widget.apply_depth_range(master_range[0], master_range[1])
            else:
                d_min, d_max = (depth[0], depth[-1]) if depth[0] < depth[-1] else (depth[-1], depth[0])
                self.plot_widget.setYRange(d_min, d_min + 10, 0)
                if hasattr(self.log_widget, 'scale_control'): QTimer.singleShot(50, self.log_widget.scale_control.update_scale)
                else: self.log_widget.apply_depth_range(d_min, d_min + 10)

    def add_curve_at_index(self, data, depth, info, index, rgb_full_bg=None):
        self.add_curve(data, depth, info, rgb_full_bg=rgb_full_bg)
        if index < len(self.plot_widget.curves) - 1 and len(self.plot_widget.curves) > 1:
            curve_obj = self.plot_widget.curves.pop()
            header_item = self.header.items.pop()
            self.plot_widget.curves.insert(index, curve_obj)
            self.header.items.insert(index, header_item)
            if not curve_obj.get('is_image') and len(self.plot_widget.curve_viewboxes) > 0:
                vb_entry = self.plot_widget.curve_viewboxes.pop()
                self.plot_widget.curve_viewboxes.insert(index, vb_entry)
            self.header.update()
            self._refresh_z_orders()

    def remove_curve_at(self, idx):
        if idx >= len(self.plot_widget.curves): return
        curve_obj = self.plot_widget.curves.pop(idx)
        if curve_obj.get('is_image', False): ImageTrackManager.cleanup_image_track(self.plot_widget)
        else:
            vb = curve_obj.get('viewbox')
            if vb:
                vb.removeItem(curve_obj['item'])
                self.plot_widget.scene().removeItem(vb)
                for i, entry in enumerate(self.plot_widget.curve_viewboxes):
                    if entry['viewbox'] == vb:
                        self.plot_widget.curve_viewboxes.pop(i)
                        break
            else: self.plot_widget.removeItem(curve_obj['item'])
        if idx < len(self.header.items):
            self.header.items.pop(idx)
            self.header.adjust_height()
        self._refresh_z_orders()
        self.header.update()

    def apply_curve_settings(
        self,
        idx: int,
        settings: Dict[str, Any],
        trigger_others: bool = True,
        reload_data: bool = True,
    ) -> None:
        if idx >= len(self.plot_widget.curves): return
        curve_entry = self.plot_widget.curves[idx]
        old_info = curve_entry['info']
        old_state = self._image_render_state(old_info)
        
        merged = old_info.copy()
        merged.update(settings)
        merged['is_image'] = True
        merged = normalize_curve_plot_style(merged)
        curve_entry['info'] = merged
        
        null_color = merged.get('null_color', DEFAULT_NULL_COLOR)
        res = app_config.resolve_null_color(null_color)
        bg_color = app_config.get_theme_qcolor('plot_bg') if res == 'Theme' else (QColor(Qt.white) if res == 'White' else QColor(Qt.black))
        self.plot_widget.setBackground(bg_color)
        if hasattr(self.plot_widget, 'getViewBox') and self.plot_widget.getViewBox():
             self.plot_widget.getViewBox().setBackgroundColor(bg_color)
        
        # [FIX] Only refresh image tiles when image-relevant properties actually changed
        if old_state != self._image_render_state(merged):
            self._refresh_image_tiles()
        
        if idx < len(self.header.items): self.header.items[idx].update(merged)
        self.header.update()

    @staticmethod
    def _image_render_state(info):
        return (
            str(info.get('cmap', DEFAULT_IMAGE_CMAP)).lower(),
            bool(info.get('invert', False)),
            bool(info.get('log', False)),
            info.get('min'),
            info.get('max'),
            info.get('null_color', DEFAULT_NULL_COLOR),
        )

    def _refresh_image_tiles(self):
        if not getattr(self, 'log_widget', None):
            return
        vb = self.get_viewbox()
        if not vb:
            return
        min_y, max_y = vb.viewRange()[1]
        self.log_widget.scroll_mgr.apply_depth_range(min_y, max_y, force=True, only_track=self)

    def _update_track_settings_specific(self, s):
        null_color = s.get('null_color', DEFAULT_NULL_COLOR)
        res = app_config.resolve_null_color(null_color)
        bg_color = app_config.get_theme_qcolor('plot_bg') if res == 'Theme' else (QColor(Qt.white) if res == 'White' else QColor(Qt.black))
        self.plot_widget.setBackground(bg_color)
        if hasattr(self.plot_widget, 'getViewBox') and self.plot_widget.getViewBox():
             self.plot_widget.getViewBox().setBackgroundColor(bg_color)
        has_image_changed = False
        for c in self.plot_widget.curves:
            if c.get('is_image'):
                info = c['info']
                old_state = self._image_render_state(info)
                info['null_color'] = s.get('null_color', info.get('null_color', DEFAULT_NULL_COLOR))
                info['cmap'] = s.get('cmap', info.get('cmap', DEFAULT_IMAGE_CMAP)).lower()
                info['invert'] = s.get('invert', info.get('invert'))
                info['log'] = s.get('log', info.get('log', False))
                if 'img_min' in s: info['min'] = s['img_min']
                elif 'min' in s and 'cmap' in s: info['min'] = s['min']
                if 'img_max' in s: info['max'] = s['img_max']
                elif 'max' in s and 'cmap' in s: info['max'] = s['max']
                if old_state != self._image_render_state(info): has_image_changed = True
        if has_image_changed:
            self._refresh_image_tiles()

        if "fractures" in s:
            self.load_fracture_annotations(s.get("fractures") or [])

    def _refresh_z_orders(self):
        for i, c in enumerate(self.plot_widget.curves):
            z_val = 0 if c.get('is_image', False) else i + 10
            target = c.get('viewbox') or c.get('item')
            if target: target.setZValue(z_val)
        if hasattr(self.plot_widget, 'plotItem') and self.plot_widget.plotItem.vb:
            self.plot_widget.plotItem.vb.setZValue(0)

    def _show_fracture_status(self, message):
        lw = self.log_widget or self.find_log_widget()
        try:
            window = lw.window() if lw else None
            status_bar = window.statusBar() if window and hasattr(window, "statusBar") else None
            if status_bar:
                status_bar.showMessage(message, 5000)
        except Exception:
            pass

    def set_fracture_pick_enabled(self, enabled):
        self._fracture_pick_active = bool(enabled)
        if not enabled:
            self._fracture_pick_points = []
            self._clear_fracture_preview()

    def start_fracture_pick(self):
        self.set_fracture_pick_enabled(True)
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self.setFocus()
        self._show_fracture_status("Fracture pick: left-click at least 3 points, Space/Enter to finish, Esc to cancel.")

    def cancel_fracture_pick(self, show_message=True):
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        if show_message:
            self._show_fracture_status("Current fracture pick canceled.")

    def finish_fracture_pick(self, continue_picking=False):
        if len(self._fracture_pick_points) < MIN_FRACTURE_PICK_POINTS:
            self.cancel_fracture_pick(show_message=False)
            self._show_fracture_status("Not enough points for a fracture. Current pick canceled.")
            return False
        style = self._current_fracture_style()
        lw = self.log_widget or self.find_log_widget()
        target_track = lw.get_fracture_display_track(fallback=self) if lw and hasattr(lw, "get_fracture_display_track") else self
        if target_track is None:
            target_track = self
        annotation = build_fracture_annotation(
            self._fracture_pick_points,
            fracture_type=style["fracture_type"],
            color=style["color"],
            line_width=style["line_width"],
            name=f"Fracture {len(getattr(target_track, 'fracture_annotations', [])) + 1}",
        )
        image_curve = next((c for c in self.plot_widget.curves if c.get('is_image')), None)
        if image_curve:
            info = image_curve.get("info", {})
            annotation["source_curve_id"] = info.get("curve_id", info.get("id"))
            annotation["source_curve_name"] = info.get("name")
        annotation["source_track_id"] = id(self)
        target_track.add_fracture_annotation(annotation)
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self.plot_widget.update()
        if not continue_picking:
            self._fracture_pick_active = False
        target_name = lw._fracture_track_label(target_track) if lw and hasattr(lw, "_fracture_track_label") else "target track"
        self._show_fracture_status(f"Fracture pick added on {target_name}. Continue picking or disable Fracture mode.")
        return True

    def undo_fracture_pick_point(self):
        if not self._fracture_pick_points:
            return
        self._fracture_pick_points.pop()
        self._update_fracture_preview()

    def clear_fracture_annotations(self):
        for item in list(self._fracture_items):
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self._fracture_items.clear()
        self.fracture_annotations.clear()
        self.plot_widget.fracture_annotations = self.fracture_annotations
        self.plot_widget.update()

    def add_fracture_annotation(self, annotation):
        if not isinstance(annotation, dict):
            return None
        clean = annotation.copy()
        if "name" not in clean:
            clean["name"] = f"Fracture {len(self.fracture_annotations) + 1}"
        self.fracture_annotations.append(clean)
        item = self._add_fracture_item(clean)
        self.plot_widget.fracture_annotations = self.fracture_annotations
        self.plot_widget.update()
        return item

    def load_fracture_annotations(self, annotations):
        self.clear_fracture_annotations()
        for annotation in annotations:
            if not isinstance(annotation, dict):
                continue
            if annotation.get("type") != "sinusoidal_fracture":
                continue
            self.add_fracture_annotation(annotation)
        self.plot_widget.fracture_annotations = self.fracture_annotations

    def handle_fracture_pick_mouse(self, event, plot_widget):
        lw = self.log_widget or self.find_log_widget()
        if not getattr(lw, "fracture_picking_enabled", False):
            return False
        if event.button() == Qt.RightButton:
            return False
        if event.button() != Qt.LeftButton:
            return False
        if not self._fracture_pick_active:
            self._fracture_pick_active = True
        if lw and hasattr(lw, "set_active_fracture_track"):
            lw.set_active_fracture_track(self)
        vb = plot_widget.getViewBox()
        if not vb:
            return True
        scene_pos = plot_widget.mapToScene(event.position().toPoint())
        view_pos = vb.mapSceneToView(scene_pos)
        x = max(0.0, min(360.0, float(view_pos.x())))
        y = float(view_pos.y())
        if not np.isfinite(y):
            return True
        self._fracture_pick_points.append([x, y])
        self._update_fracture_preview()
        return True

    def handle_fracture_pick_key(self, event):
        lw = self.log_widget or self.find_log_widget()
        if not getattr(lw, "fracture_picking_enabled", False):
            return False
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.finish_fracture_pick(continue_picking=True)
            return True
        if event.key() == Qt.Key_Escape:
            self.cancel_fracture_pick()
            if lw and getattr(lw, "active_fracture_track", None) is self:
                lw.active_fracture_track = None
            return True
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            self.undo_fracture_pick_point()
            return True
        return False

    def _current_fracture_style(self):
        lw = self.log_widget or self.find_log_widget()
        if lw and hasattr(lw, "get_fracture_pick_style"):
            return lw.get_fracture_pick_style()
        return {"fracture_type": "Conductive", "color": "#00E5FF", "line_width": 2.0}

    def refresh_fracture_preview_style(self):
        if self._fracture_pick_points:
            self._update_fracture_preview()

    def _add_fracture_item(self, annotation):
        x, y = sinusoidal_fracture_xy(annotation)
        pen = pg.mkPen(
            QColor(annotation.get("color", "#00E5FF")),
            width=float(annotation.get("line_width", 2.0)),
        )
        item = pg.PlotDataItem(x, y, pen=pen)
        item.setZValue(50)
        self.plot_widget.addItem(item)
        self._fracture_items.append(item)
        return item

    def _update_fracture_preview(self):
        self._clear_fracture_preview()
        points = self._fracture_pick_points
        if not points:
            return
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self._fracture_pick_scatter = pg.ScatterPlotItem(
            xs,
            ys,
            size=7,
            pen=pg.mkPen(QColor("#FFFFFF"), width=1),
            brush=pg.mkBrush(QColor(self._current_fracture_style()["color"])),
        )
        self._fracture_pick_scatter.setZValue(60)
        self.plot_widget.addItem(self._fracture_pick_scatter)
        if len(points) >= MIN_FRACTURE_PREVIEW_POINTS:
            try:
                annotation = build_fracture_annotation(
                    points,
                    name="Preview",
                    min_points=MIN_FRACTURE_PREVIEW_POINTS,
                )
                x, y = sinusoidal_fracture_xy(annotation)
                self._fracture_preview_item = pg.PlotDataItem(
                    x,
                    y,
                    pen=pg.mkPen(QColor(self._current_fracture_style()["color"]), width=2, style=Qt.DashLine),
                )
                self._fracture_preview_item.setZValue(55)
                self.plot_widget.addItem(self._fracture_preview_item)
            except Exception:
                pass

    def _clear_fracture_preview(self):
        for attr in ("_fracture_preview_item", "_fracture_pick_scatter"):
            item = getattr(self, attr, None)
            if item is not None:
                try:
                    self.plot_widget.removeItem(item)
                except Exception:
                    pass
                setattr(self, attr, None)

    def keyPressEvent(self, event):
        if self.handle_fracture_pick_key(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def get_state(self):
        state = super().get_state()
        state["type"] = "data"
        state["fractures"] = [
            {key: value for key, value in fracture.items() if key != "item"}
            for fracture in self.fracture_annotations
        ]
        for curve in self.plot_widget.curves:
            info = curve.get('info', {}).copy()
            state["curves"].append(info)
        return state

LogTrackContainer = CurveTrackContainer
