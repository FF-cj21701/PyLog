import pyqtgraph as pg
import numpy as np
from typing import Optional, List, Dict, Any, Union, Type
from PySide6.QtWidgets import QFrame, QMenu, QStyleOption, QStyle, QSplitter, QApplication
from PySide6.QtCore import Qt, QRectF, QRect, QPointF, Signal, QTimer
from PySide6.QtGui import QPainter, QPen, QColor, QAction, QBrush, QFont
from core.app_config import app_config

from ..utils.colormap_utils import get_standard_colormap
from ..rendering.plot_constants import AXIS_WIDTH
from ..ui.plot_dialogs import UnifiedSettingsDialog
from ..rendering.plot_components import (InteractivePlotWidget, HeaderWidget, SelectionOverlay, PainterDepthTrack)
from ..rendering.track_widgets import TadpoleTrackWidget
from ..rendering.image_manager import ImageTrackManager
from ..rendering.fill_manager import FillManager
from ..rendering.curve_manager import CurveManager
from ..rendering.fracture_annotations import (
    annotation_from_fracture_parameters,
    canonical_fracture_points,
    FRACTURE_TYPE_STYLES,
    MIN_FRACTURE_PREVIEW_POINTS,
    MIN_FRACTURE_PICK_POINTS,
    build_fracture_annotation,
    enrich_fracture_interpretation,
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
        add_tadpole_act = QAction("Add Tadpole Track", self)
        lw = self.find_log_widget()
        if lw:
            add_depth_act.triggered.connect(lambda: lw.add_depth_track())
            add_empty_act.triggered.connect(lambda: lw.add_empty_track())
            add_tadpole_act.triggered.connect(lambda: lw.show_tadpole_track() if hasattr(lw, "show_tadpole_track") else None)
        menu.addAction(add_depth_act)
        menu.addAction(add_empty_act)
        menu.addAction(add_tadpole_act)

        fracture_act = QAction("Fracture Picking", self)
        fracture_act.triggered.connect(self.enter_fracture_picking_mode)
        menu.addAction(fracture_act)
        
        settings_act = QAction("Properties...", self)
        settings_act.triggered.connect(self.open_settings)
        menu.addAction(settings_act)
        menu.exec(self.mapToGlobal(pos))

    def enter_fracture_picking_mode(self):
        lw = self.log_widget or self.find_log_widget()
        if not lw or not hasattr(lw, "set_fracture_picking_enabled"):
            return
        if hasattr(self, "fracture_annotations") and hasattr(lw, "_image_tracks_for_fracture_display"):
            tracks = lw._image_tracks_for_fracture_display()
            if self in tracks:
                lw.fracture_target_track = self
        lw.set_fracture_picking_enabled(True)
        if hasattr(lw, "refresh_fracture_target_tracks"):
            lw.refresh_fracture_target_tracks()
    
    def paintEvent(self, event):
        opt = QStyleOption()
        opt.initFrom(self)
        p = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, opt, p, self)
        p.setPen(QPen(app_config.get_theme_qcolor("border_std"), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
    
    def mousePressEvent(self, event):
        log_widget = self.find_log_widget()
        if (
            event.button() == Qt.LeftButton
            and log_widget
            and getattr(log_widget, "fracture_picking_enabled", False)
            and not hasattr(self, "fracture_annotations")
            and hasattr(log_widget, "clear_fracture_interaction")
        ):
            log_widget.clear_fracture_interaction()
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


class TadpoleLegendHeader(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = [{"name": "Tadpole"}]
        self.fracture_types = []
        self.is_auto_height = False
        self.base_row_height = 122
        self.setFixedHeight(122)
        self.update_theme()

    def update_theme(self):
        self._bg = app_config.get_theme_qcolor("header_glass")
        self._border = app_config.get_theme_qcolor("text_main")
        self._text = app_config.get_theme_qcolor("text_main")
        self._muted = app_config.get_theme_qcolor("text_dim")
        self.update()

    def set_title(self, title):
        self.items[0]["name"] = title
        self.update()

    def set_unit(self, unit):
        self.items[0]["unit"] = unit
        self.update()

    def set_range_visible(self, visible):
        self.items[0]["range_visible"] = bool(visible)
        self.update()

    def set_fracture_types(self, fracture_types):
        ordered = []
        for key in ("Conductive", "Bedding", "Resistive"):
            if key in fracture_types:
                ordered.append(key)
        for key in fracture_types:
            if key not in ordered:
                ordered.append(key)
        if ordered != self.fracture_types:
            self.fracture_types = ordered
            self.update()

    def adjust_height(self):
        log_w = self.find_log_widget()
        if log_w:
            log_w.sync_header_heights()

    def find_log_widget(self):
        p = self.parent()
        while p:
            if hasattr(p, "sync_header_heights"):
                return p
            p = p.parent()
        return None

    def _draw_sample(self, painter, x, y, color, scale=1.0):
        c = QColor(color)
        pen = QPen(c, max(1.4, 1.8 * scale))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QBrush(c))
        painter.drawLine(QPointF(x, y), QPointF(x + 8 * scale, y - 11 * scale))
        painter.drawEllipse(QPointF(x, y), 3.5 * scale, 3.5 * scale)

    def _draw(self, painter, rect, scale=1.0, draw_border=True):
        painter.save()
        painter.translate(rect.topLeft())
        w, h = rect.width(), rect.height()
        painter.fillRect(0, 0, w, h, self._bg)
        if draw_border:
            painter.setPen(QPen(self._border, max(1.0, 1.0 * scale)))
            painter.drawLine(QPointF(0, 0), QPointF(w, 0))
            painter.drawLine(QPointF(0, h - 1), QPointF(w, h - 1))

        font = QFont("Arial")
        font.setPixelSize(int(11 * scale))
        painter.setFont(font)
        label_map = {
            "Conductive": "Conductive fracture",
            "Bedding": "Bedding",
            "Resistive": "Resistive fracture",
        }
        labels = [(label_map.get(key, key), key) for key in self.fracture_types]
        row_step = 27 * scale
        y = h - 50 * scale
        for label, key in reversed(labels):
            color = FRACTURE_TYPE_STYLES.get(key, {}).get("color", app_config.get_theme_color("accent"))
            self._draw_sample(painter, 12 * scale, y, color, scale=scale)
            painter.setPen(QPen(QColor(color), max(1.0, 1.0 * scale)))
            painter.drawText(QRectF(31 * scale, y - 12 * scale, w - 35 * scale, 20 * scale), Qt.AlignLeft | Qt.AlignVCenter, label)
            y -= row_step

        painter.setPen(QPen(QColor("#ff2d2d"), max(1.0, 1.0 * scale)))
        title_font = QFont("Arial")
        title_font.setPixelSize(int(12 * scale))
        painter.setFont(title_font)
        title_rect = QRectF(0, h - 35 * scale, w, 14 * scale)
        painter.drawText(title_rect, Qt.AlignCenter, "Dip/deg")

        scale_font = QFont("Arial")
        scale_font.setPixelSize(int(10 * scale))
        painter.setFont(scale_font)
        plot_w = max(1.0, w - 1.0)
        label_y = h - 19 * scale
        label_w = 24 * scale
        for dip in (0, 30, 60, 90):
            x = dip / 90.0 * plot_w
            if dip == 0:
                x += 2.0 * scale + label_w / 2.0
            elif dip == 90:
                x -= 2.0 * scale + label_w / 2.0
            painter.drawText(
                QRectF(x - label_w / 2.0, label_y, label_w, 16 * scale),
                Qt.AlignHCenter | Qt.AlignBottom,
                str(dip),
            )
        painter.restore()

    def paintEvent(self, event):
        painter = QPainter(self)
        self._draw(painter, self.rect())
        painter.end()

    def render_to(self, painter, rect, scale=1.0, scale_text=None, draw_border=True):
        self._draw(painter, rect, scale=scale, draw_border=draw_border)


class TadpoleTrackContainer(BaseTrackContainer):
    """Track container for fracture tadpole interpretation display."""
    def __init__(self, parent=None):
        super().__init__(parent, plot_widget_class=TadpoleTrackWidget)
        old_header = self.header
        old_header.hide()
        old_header.deleteLater()
        self.header = TadpoleLegendHeader(self)
        self.header.raise_()
        self.track_name = "Tadpole"
        self.setMinimumWidth(90)

    def set_annotations(self, annotations):
        self.plot_widget.set_annotations(annotations)
        types = []
        for annotation in annotations or []:
            fracture_type = annotation.get("fracture_type")
            if fracture_type and fracture_type not in types:
                types.append(fracture_type)
        if hasattr(self.header, "set_fracture_types"):
            self.header.set_fracture_types(types)

    def refresh_from_fractures(self):
        lw = self.log_widget or self.find_log_widget()
        annotations = lw.collect_fracture_annotations() if lw and hasattr(lw, "collect_fracture_annotations") else []
        self.set_annotations(annotations)

    def get_state(self):
        state = super().get_state()
        state["type"] = "tadpole"
        return state

    def add_curve(self, data, depth, info, rgb_full_bg=None):
        pass

    def add_curve_at_index(self, data, depth, info, index, rgb_full_bg=None):
        pass

    def remove_curve_at(self, idx):
        pass

    def apply_curve_settings(self, idx, settings, trigger_others=True, reload_data=True):
        pass

    def _refresh_z_orders(self):
        pass

    def _update_grid_visibility(self):
        pass

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
        self._selected_fracture_indexes = set()
        self._fracture_pick_active = False
        self._fracture_pick_points = []
        self._fracture_preview_item = None
        self._fracture_pick_scatter = None
        self._fracture_drag_state = None
        self._programmatic_fracture_session = None
        self._ai_staged_fracture_annotations = []
        self._ai_staged_fracture_items = []
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
            info.get('azimuth_start', 0.0),
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
                info['azimuth_start'] = s.get('azimuth_start', info.get('azimuth_start', 0.0))
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
            self.cancel_programmatic_fracture_pick()
            self._fracture_pick_points = []
            self._clear_fracture_preview()

    def start_fracture_pick(self):
        self.set_fracture_pick_enabled(True)
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self.setFocus()
        self._show_fracture_status("Fracture pick: left-click at least 3 points, Space/Enter to finish, Esc to cancel.")

    def cancel_fracture_pick(self, show_message=True):
        if self._programmatic_fracture_session is not None:
            return False
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        if show_message:
            self._show_fracture_status("Current fracture pick canceled.")

    def finish_fracture_pick(self, continue_picking=False):
        if self._programmatic_fracture_session is not None:
            return False
        if len(self._fracture_pick_points) < MIN_FRACTURE_PICK_POINTS:
            self.cancel_fracture_pick(show_message=False)
            self._show_fracture_status("Not enough points for a fracture. Current pick canceled.")
            return False
        style = self._current_fracture_style()
        lw = self.log_widget or self.find_log_widget()
        target_track = lw.get_fracture_display_track(fallback=self) if lw and hasattr(lw, "get_fracture_display_track") else self
        if target_track is None:
            target_track = self
        annotation = self._commit_fracture_points(
            self._fracture_pick_points,
            style=style,
            target_track=target_track,
        )
        if lw:
            for track in getattr(lw, "track_containers", []):
                if isinstance(track, TadpoleTrackContainer):
                    track.refresh_from_fractures()
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self.plot_widget.update()
        if not continue_picking:
            self._fracture_pick_active = False
        target_name = lw._fracture_track_label(target_track) if lw and hasattr(lw, "_fracture_track_label") else "target track"
        self._show_fracture_status(f"Fracture pick added on {target_name}. Continue picking or disable Fracture mode.")
        return True

    def _append_fracture_pick_point(self, azimuth_deg, depth):
        try:
            x = max(0.0, min(360.0, float(azimuth_deg)))
            y = float(depth)
        except (TypeError, ValueError):
            return False
        if not np.isfinite(x) or not np.isfinite(y):
            return False
        self._fracture_pick_points.append([x, y])
        self._update_fracture_preview()
        return True

    def _commit_fracture_points(self, points, *, style, target_track=None, metadata=None):
        target_track = target_track or self
        annotation = build_fracture_annotation(
            points,
            fracture_type=style["fracture_type"],
            color=style["color"],
            line_width=style["line_width"],
            name=f"Fracture {len(getattr(target_track, 'fracture_annotations', [])) + 1}",
        )
        image_curve = next((c for c in self.plot_widget.curves if c.get('is_image')), None)
        if image_curve:
            info = image_curve.get("info", {})
            annotation["source_curve_id"] = info.get("curve_id", info.get("id"))
            annotation["source_curve_name"] = info.get("title") or info.get("name")
        annotation["source_track_id"] = id(self)
        annotation.update(dict(metadata or {}))
        annotation = enrich_fracture_interpretation(
            annotation,
            borehole_diameter=(metadata or {}).get("borehole_diameter_in"),
        )
        target_track.add_fracture_annotation(annotation)
        return annotation

    def begin_programmatic_fracture_pick(self, session_id, fracture_type, metadata=None):
        if not session_id or fracture_type not in FRACTURE_TYPE_STYLES:
            return False
        style = FRACTURE_TYPE_STYLES[fracture_type]
        metadata = dict(metadata or {})
        self._programmatic_fracture_session = {
            "session_id": str(session_id),
            "fracture_type": fracture_type,
            "style": {
                "fracture_type": fracture_type,
                "color": str(metadata.get("color") or style["color"]),
                "line_width": float(metadata.get("line_width", 2.0)),
            },
            "metadata": metadata,
        }
        self._fracture_pick_active = True
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        return True

    def append_programmatic_fracture_point(self, session_id, azimuth_deg, depth):
        session = self._programmatic_fracture_session
        if not session or session["session_id"] != str(session_id):
            return False
        return self._append_fracture_pick_point(azimuth_deg, depth)

    def replace_programmatic_fracture_points(self, session_id, points):
        session = self._programmatic_fracture_session
        if not session or session["session_id"] != str(session_id):
            return False
        clean = []
        for point in points or []:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            try:
                x = max(0.0, min(360.0, float(point[0])))
                y = float(point[1])
            except (TypeError, ValueError):
                continue
            if np.isfinite(x) and np.isfinite(y):
                clean.append([x, y])
        self._fracture_pick_points = clean
        self._update_fracture_preview()
        return True

    def replace_programmatic_fracture_parameters(
        self,
        session_id,
        center_depth_m,
        amplitude_m,
        phase_deg,
    ):
        session = self._programmatic_fracture_session
        if not session or session["session_id"] != str(session_id):
            return False
        try:
            points = canonical_fracture_points(center_depth_m, amplitude_m, phase_deg)
            parameters = annotation_from_fracture_parameters(center_depth_m, amplitude_m, phase_deg)
        except (TypeError, ValueError):
            return False
        session["metadata"]["ai_final_parameters"] = {
            "center_depth_m": float(parameters["offset"]),
            "amplitude_m": float(parameters["amplitude"]),
            "phase_deg": float(phase_deg) % 360.0,
        }
        return self.replace_programmatic_fracture_points(session_id, points)

    def update_programmatic_fracture_metadata(self, session_id, metadata):
        session = self._programmatic_fracture_session
        if not session or session["session_id"] != str(session_id):
            return False
        session["metadata"].update(dict(metadata or {}))
        return True

    def commit_programmatic_fracture_pick(self, session_id):
        session = self._programmatic_fracture_session
        if not session or session["session_id"] != str(session_id):
            return None
        if len(self._fracture_pick_points) < MIN_FRACTURE_PICK_POINTS:
            self.cancel_programmatic_fracture_pick(session_id)
            return None
        metadata = dict(session["metadata"])
        metadata["final_points"] = [list(point) for point in self._fracture_pick_points]
        annotation = self._commit_fracture_points(
            self._fracture_pick_points,
            style=session["style"],
            target_track=self,
            metadata=metadata,
        )
        self._programmatic_fracture_session = None
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self.plot_widget.update()
        self._refresh_tadpole_tracks()
        return annotation

    def stage_programmatic_fracture_pick(self, session_id):
        session = self._programmatic_fracture_session
        if not session or session["session_id"] != str(session_id):
            return None
        if len(self._fracture_pick_points) < MIN_FRACTURE_PICK_POINTS:
            self.cancel_programmatic_fracture_pick(session_id)
            return None
        metadata = dict(session["metadata"])
        metadata["final_points"] = [list(point) for point in self._fracture_pick_points]
        annotation = build_fracture_annotation(
            self._fracture_pick_points,
            fracture_type=session["style"]["fracture_type"],
            color=session["style"]["color"],
            line_width=session["style"]["line_width"],
            name=f"AI staged {len(self._ai_staged_fracture_annotations) + 1}",
        )
        annotation.update(metadata)
        annotation = enrich_fracture_interpretation(
            annotation,
            borehole_diameter=metadata.get("borehole_diameter_in"),
        )
        self._programmatic_fracture_session = None
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self._ai_staged_fracture_annotations.append(annotation)
        self._ai_staged_fracture_items.append(self._add_ai_staged_fracture_item(annotation))
        self.plot_widget.update()
        return annotation

    def set_ai_staged_fractures(self, annotations):
        self.clear_ai_staged_fractures()
        for annotation in annotations or []:
            if not isinstance(annotation, dict) or annotation.get("type") != "sinusoidal_fracture":
                continue
            clean = dict(annotation)
            self._ai_staged_fracture_annotations.append(clean)
            self._ai_staged_fracture_items.append(self._add_ai_staged_fracture_item(clean))
        self.plot_widget.update()
        return list(self._ai_staged_fracture_annotations)

    def clear_ai_staged_fractures(self):
        for item in list(self._ai_staged_fracture_items):
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self._ai_staged_fracture_items.clear()
        self._ai_staged_fracture_annotations.clear()
        self.plot_widget.update()

    def commit_ai_staged_fractures(self, annotations=None):
        selected = list(annotations) if annotations is not None else list(self._ai_staged_fracture_annotations)
        self.clear_ai_staged_fractures()
        committed = []
        for annotation in selected:
            clean = {
                key: value for key, value in dict(annotation).items()
                if not str(key).startswith("_") and key != "item"
            }
            clean["name"] = f"Fracture {len(self.fracture_annotations) + 1}"
            self.add_fracture_annotation(clean)
            committed.append(clean)
        if committed:
            self._refresh_tadpole_tracks()
        return committed

    def cancel_programmatic_fracture_pick(self, session_id=None):
        session = self._programmatic_fracture_session
        if session_id is not None and session and session["session_id"] != str(session_id):
            return False
        self._programmatic_fracture_session = None
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        return True

    def undo_fracture_pick_point(self):
        if self._programmatic_fracture_session is not None:
            return
        if not self._fracture_pick_points:
            return
        self._fracture_pick_points.pop()
        self._update_fracture_preview()

    def clear_fracture_annotations(self):
        self.clear_ai_staged_fractures()
        for item in list(self._fracture_items):
            try:
                self.plot_widget.removeItem(item)
            except Exception:
                pass
        self._fracture_items.clear()
        self._selected_fracture_indexes.clear()
        self.fracture_annotations.clear()
        self.plot_widget.fracture_annotations = self.fracture_annotations
        self.plot_widget.update()

    def clear_fracture_selection(self):
        if not self._selected_fracture_indexes:
            return
        self._selected_fracture_indexes.clear()
        self._refresh_fracture_item_styles()

    def selected_fracture_count(self):
        return len(self._selected_fracture_indexes)

    def delete_selected_fractures(self):
        selected = sorted(self._selected_fracture_indexes, reverse=True)
        if not selected:
            return 0
        removed = 0
        for index in selected:
            if not (0 <= index < len(self.fracture_annotations)):
                continue
            item = self._fracture_items[index] if index < len(self._fracture_items) else None
            if item is not None:
                try:
                    self.plot_widget.removeItem(item)
                except Exception:
                    pass
            del self.fracture_annotations[index]
            if index < len(self._fracture_items):
                del self._fracture_items[index]
            removed += 1
        self._selected_fracture_indexes.clear()
        self.plot_widget.fracture_annotations = self.fracture_annotations
        self._refresh_fracture_names()
        self._refresh_fracture_item_styles()
        self.plot_widget.update()
        return removed

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
        if self._programmatic_fracture_session is not None:
            return True
        if event.button() == Qt.RightButton:
            return False
        if event.button() != Qt.LeftButton:
            return False
        hit_index = self._fracture_index_at_event(event, plot_widget)
        if hit_index is not None:
            append = bool(event.modifiers() & Qt.ControlModifier)
            already_selected = hit_index in self._selected_fracture_indexes
            if lw and not append and not already_selected and hasattr(lw, "clear_fracture_selection"):
                lw.clear_fracture_selection()
            if append or not already_selected:
                self._toggle_fracture_selection(
                    hit_index,
                    append=append,
                )
            else:
                self._fracture_pick_points = []
                self._clear_fracture_preview()
                self._refresh_fracture_item_styles()
            if lw and hasattr(lw, "set_active_fracture_track"):
                lw.set_active_fracture_track(self)
            if hit_index in self._selected_fracture_indexes and not append:
                start_depth = self._event_depth(event, plot_widget)
                if start_depth is not None:
                    self._fracture_drag_state = {
                        "start_depth": start_depth,
                        "indexes": sorted(self._selected_fracture_indexes),
                        "start_offsets": {
                            i: float(self.fracture_annotations[i].get("offset", 0.0))
                            for i in self._selected_fracture_indexes
                            if 0 <= i < len(self.fracture_annotations)
                        },
                        "start_points": {
                            i: [
                                [float(point[0]), float(point[1])]
                                for point in self.fracture_annotations[i].get("points", [])
                                if len(point) >= 2
                            ]
                            for i in self._selected_fracture_indexes
                            if 0 <= i < len(self.fracture_annotations)
                        },
                    }
            return True
        if lw and hasattr(lw, "clear_fracture_selection"):
            lw.clear_fracture_selection()
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
        self._append_fracture_pick_point(x, y)
        return True

    def handle_fracture_pick_mouse_move(self, event, plot_widget):
        if not self._fracture_drag_state:
            return False
        current_depth = self._event_depth(event, plot_widget)
        if current_depth is None:
            return True
        delta = current_depth - self._fracture_drag_state["start_depth"]
        for index in self._fracture_drag_state["indexes"]:
            if not (0 <= index < len(self.fracture_annotations)):
                continue
            annotation = self.fracture_annotations[index]
            start_offset = self._fracture_drag_state["start_offsets"].get(index)
            if start_offset is None:
                continue
            annotation["offset"] = start_offset + delta
            annotation["center_depth"] = annotation["offset"]
            if index in self._fracture_drag_state["start_points"]:
                annotation["points"] = [
                    [point[0], point[1] + delta]
                    for point in self._fracture_drag_state["start_points"][index]
                ]
            self._update_fracture_item(index)
        self.plot_widget.update()
        self._refresh_tadpole_tracks()
        return True

    def handle_fracture_pick_mouse_release(self, event, plot_widget):
        if not self._fracture_drag_state:
            return False
        self._fracture_drag_state = None
        self._refresh_tadpole_tracks()
        return True

    def handle_fracture_pick_key(self, event):
        lw = self.log_widget or self.find_log_widget()
        if not getattr(lw, "fracture_picking_enabled", False):
            return False
        if self._programmatic_fracture_session is not None:
            return True
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.finish_fracture_pick(continue_picking=True)
            return True
        if event.key() == Qt.Key_Escape:
            self.cancel_fracture_pick()
            self.clear_fracture_selection()
            if lw and getattr(lw, "active_fracture_track", None) is self:
                lw.active_fracture_track = None
            return True
        if event.key() in (Qt.Key_Backspace, Qt.Key_Delete):
            if self._selected_fracture_indexes:
                removed = self.delete_selected_fractures()
                if removed:
                    self._show_fracture_status(f"Deleted {removed} selected fracture(s).")
                return True
            self.undo_fracture_pick_point()
            return True
        return False

    def _current_fracture_style(self):
        if self._programmatic_fracture_session is not None:
            return self._programmatic_fracture_session["style"]
        lw = self.log_widget or self.find_log_widget()
        if lw and hasattr(lw, "get_fracture_pick_style"):
            return lw.get_fracture_pick_style()
        return {"fracture_type": "Conductive", "color": "#00E5FF", "line_width": 2.0}

    def _event_depth(self, event, plot_widget):
        vb = plot_widget.getViewBox()
        if not vb:
            return None
        scene_pos = plot_widget.mapToScene(event.position().toPoint())
        view_pos = vb.mapSceneToView(scene_pos)
        y = float(view_pos.y())
        return y if np.isfinite(y) else None

    def _refresh_tadpole_tracks(self):
        lw = self.log_widget or self.find_log_widget()
        if not lw:
            return
        for track in getattr(lw, "track_containers", []):
            if isinstance(track, TadpoleTrackContainer):
                track.refresh_from_fractures()

    def refresh_fracture_preview_style(self):
        if self._fracture_pick_points:
            self._update_fracture_preview()

    def _add_fracture_item(self, annotation):
        x, y = sinusoidal_fracture_xy(annotation)
        pen = self._fracture_pen(annotation, selected=False)
        item = pg.PlotDataItem(x, y, pen=pen)
        item.setZValue(50)
        self.plot_widget.addItem(item)
        self._fracture_items.append(item)
        return item

    def _add_ai_staged_fracture_item(self, annotation):
        x, y = sinusoidal_fracture_xy(annotation)
        color = QColor(annotation.get("color", "#00E5FF"))
        item = pg.PlotDataItem(
            x,
            y,
            pen=pg.mkPen(color, width=float(annotation.get("line_width", 2.0)), style=Qt.DashLine),
        )
        item.setZValue(52)
        self.plot_widget.addItem(item)
        return item

    def _update_fracture_item(self, index):
        if not (0 <= index < len(self.fracture_annotations)):
            return
        if not (0 <= index < len(self._fracture_items)):
            return
        item = self._fracture_items[index]
        if item is None:
            return
        x, y = sinusoidal_fracture_xy(self.fracture_annotations[index])
        try:
            item.setData(x, y)
        except Exception:
            pass

    def _fracture_pen(self, annotation, selected=False):
        width = float(annotation.get("line_width", 2.0))
        color = QColor(annotation.get("color", "#00E5FF"))
        if selected:
            return pg.mkPen(color, width=max(width + 2.0, 4.0), style=Qt.DashLine)
        return pg.mkPen(color, width=width)

    def _refresh_fracture_item_styles(self):
        for index, item in enumerate(self._fracture_items):
            if item is None or index >= len(self.fracture_annotations):
                continue
            try:
                item.setPen(self._fracture_pen(
                    self.fracture_annotations[index],
                    selected=index in self._selected_fracture_indexes,
                ))
            except Exception:
                pass

    def _refresh_fracture_names(self):
        for index, annotation in enumerate(self.fracture_annotations, start=1):
            annotation["name"] = f"Fracture {index}"

    def _toggle_fracture_selection(self, index, append=False):
        if not (0 <= index < len(self.fracture_annotations)):
            return
        if append:
            if index in self._selected_fracture_indexes:
                self._selected_fracture_indexes.remove(index)
            else:
                self._selected_fracture_indexes.add(index)
        else:
            self._selected_fracture_indexes = {index}
        self._fracture_pick_points = []
        self._clear_fracture_preview()
        self._refresh_fracture_item_styles()
        count = len(self._selected_fracture_indexes)
        self._show_fracture_status(f"Selected {count} fracture(s).")

    def _fracture_index_at_event(self, event, plot_widget):
        if not self.fracture_annotations:
            return None
        vb = plot_widget.getViewBox()
        if not vb:
            return None
        scene_pos = plot_widget.mapToScene(event.position().toPoint())
        threshold = 8.0
        best_index = None
        best_distance = threshold
        for index, annotation in enumerate(self.fracture_annotations):
            try:
                x_values, y_values = sinusoidal_fracture_xy(annotation, samples=181)
            except Exception:
                continue
            for x_val, y_val in zip(x_values, y_values):
                point = vb.mapViewToScene(QPointF(float(x_val), float(y_val)))
                distance = ((point.x() - scene_pos.x()) ** 2 + (point.y() - scene_pos.y()) ** 2) ** 0.5
                if distance <= best_distance:
                    best_distance = distance
                    best_index = index
        return best_index

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
