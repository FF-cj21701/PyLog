import pyqtgraph as pg
import numpy as np
import math
import time
from typing import Tuple, Optional, Any, Union, Dict, List
from PySide6.QtWidgets import (QWidget, QScrollArea, QPushButton, QComboBox, QHBoxLayout, 
                               QGraphicsOpacityEffect, QMenu, QSizePolicy, QGraphicsItem, QGraphicsBlurEffect)
from PySide6.QtCore import Qt, QRectF, QRect, QPointF, Signal, QEvent, QObject
from PySide6.QtGui import (QPainter, QPen, QFont, QColor, QBrush, QImage, QPainterPath, QPixmap, QLinearGradient, QPolygonF)
from ..utils.colormap_utils import get_standard_colormap
from ..utils.plot_style_utils import DEFAULT_IMAGE_CMAP
from .plot_constants import AXIS_WIDTH
from .image_manager import ImageTrackManager
from core.app_config import app_config

class HeaderWidget(QWidget):
    show_effects = True # Global toggle for frosted glass and other visual effects
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(40) # Default height
        self.items, self.is_image, self.highlighted_curves, self.default_range_visible = [], False, set(), True
        self.setAttribute(Qt.WA_StaticContents)
        self._bg_brush = QBrush(QColor(255, 255, 255, 150))
        self._border_pen = QPen(QColor(app_config.get_theme_color("text_main")), 1)
        self._separator_pen = QPen(QColor(app_config.get_theme_color("text_main")), 1)
        self._highlight_brush = QBrush(QColor(app_config.get_theme_color("item_selected")))
        self._image_name_color = QColor(app_config.get_theme_color("primary"))
        self._gray_border_pen = QPen(QColor(app_config.get_theme_color("border_light")), 0.5)
        self.is_auto_height, self.base_row_height, self.font_size_name, self.font_size_unit, self.font_size_scale = True, 70, 10, 8, 8
        self._blur_pixmap = None
        self._blur_effect = QGraphicsBlurEffect()
        self._blur_effect.setBlurRadius(10)
        self._blur_effect.setBlurHints(QGraphicsBlurEffect.PerformanceHint)
        self._updating_blur = False
        self._connected_vb = None
        
        # Transparent background by default
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, False) # It's a child widget
        self.update_theme()
        
    def update_theme(self):
        """Refresh internal pens and brushes from app_config."""
        self._bg_brush = QBrush(app_config.get_theme_qcolor("header_glass"))
        self._border_pen = QPen(app_config.get_theme_qcolor("text_main"), 1)
        self._separator_pen = QPen(app_config.get_theme_qcolor("text_main"), 1)
        self._highlight_brush = QBrush(app_config.get_theme_qcolor("accent_light"))
        self._image_name_color = app_config.get_theme_qcolor("primary")
        self._gray_border_pen = QPen(app_config.get_theme_qcolor("border_std"), 0.5)
        self.update()
        
    def add_curve_info(self, info):
        if info.get('is_image'): self.is_image = True
        self.items.append(info)
        
        # Connect once per owning ViewBox so repeated curve additions do not
        # stack duplicate header repaint callbacks during scrolling.
        parent = self.parent()
        if parent and hasattr(parent, 'plot_widget'):
            pw = parent.plot_widget
            vb = pw.plotItem.vb if hasattr(pw, 'plotItem') and pw.plotItem else None
            if vb and vb is not self._connected_vb:
                if self._connected_vb:
                    try:
                        self._connected_vb.sigYRangeChanged.disconnect(self.update)
                    except:
                        pass
                    try:
                        self._connected_vb.sigXRangeChanged.disconnect(self.update)
                    except:
                        pass
                try:
                    vb.sigYRangeChanged.connect(self.update)
                    vb.sigXRangeChanged.connect(self.update)
                    self._connected_vb = vb
                except:
                    pass
        
        self.adjust_height()
        self.update()
        
    def render_to(self, painter, rect, scale=1.0, scale_text=None, draw_border=True):
        painter.save()
        try:
            painter.translate(rect.topLeft())
            w, h = rect.width(), rect.height()
            if draw_border:
                painter.setPen(QPen(QColor(app_config.get_theme_color("text_main")), 1.2 * scale))
                # Offset top line to prevent clipping at the very top of the export
                p_w = 1.2 * scale
                offset = p_w / 2.0
                painter.drawLine(QPointF(0, offset), QPointF(w, offset))
                painter.drawLine(0, h-1, w, h-1)
            if not self.items:
                return
            n, row_height = len(self.items), self.base_row_height * scale
            for i, info in enumerate(self.items):
                y_top = h - (n - i) * row_height
                f_base, f_family = info.get('font_size', self.font_size_name), info.get('font_family', 'Arial')
                font_name = QFont(f_family)
                font_name.setPixelSize(int(f_base * 1.33 * scale))
                # [AESTHETIC] Always use bold for track names in headers for clarity
                font_name.setBold(True)
                
                font_unit = QFont(f_family)
                font_unit.setPixelSize(int(max(6, f_base - 2) * 1.33 * scale))
                
                font_scale = QFont(f_family)
                font_scale.setPixelSize(int(max(6, f_base - 2) * 1.33 * scale))
                painter.setFont(font_name)
                name_h = painter.fontMetrics().height()
                if info.get('is_image', False):
                    p_color = QColor(info.get('color', app_config.get_theme_color('text_main')))
                    painter.setPen(p_color)
                    display_name = info.get('title') or info.get('name', 'Image')
                    
                    # 1. Name Centered (Top)
                    # [ALIGN] name_rect top at 8.5px, ends at 30.5px. (70 - 30.5 = 39.5)
                    name_rect = QRectF(4 * scale, y_top + 8.5 * scale, w - 8 * scale, 22 * scale)
                    painter.drawText(name_rect, Qt.AlignCenter, display_name)
                    
                    # 2. Color Bar (Middle)
                    bar_y = y_top + row_height * 0.5
                    grad_rect = QRectF(5 * scale, bar_y - 4 * scale, w - 10 * scale, 8 * scale)
                    grad = self.get_gradient(info.get('cmap', DEFAULT_IMAGE_CMAP), invert=info.get('invert', False), 
                                             log_mode=info.get('log', False), min_v=info.get('min', 0), max_v=info.get('max', 100))
                    grad.setStart(grad_rect.left(), 0); grad.setFinalStop(grad_rect.right(), 0)
                    painter.fillRect(grad_rect, grad)
                    p_color = QColor(app_config.get_theme_color('text_main'))
                    painter.setPen(QPen(p_color, 0.5 * scale)); painter.drawRect(grad_rect)
                    
                    # 3. Bottom Row: [Min] [Unit] [Max]
                    painter.setFont(font_scale); painter.setPen(p_color)
                    bottom_rect = QRectF(5 * scale, bar_y + 8.5 * scale, w - 10 * scale, 18 * scale)
                    
                    v_min, v_max = info.get('min', 0), info.get('max', 100)
                    s_min, s_max = (f"{v_min:.2g}", f"{v_max:.2g}") if abs(v_min) < 0.01 or abs(v_max) > 1000 else (f"{v_min:.1f}", f"{v_max:.1f}")
                    
                    painter.drawText(bottom_rect, Qt.AlignLeft | Qt.AlignBottom, s_min)
                    painter.drawText(bottom_rect, Qt.AlignRight | Qt.AlignBottom, s_max)
                    
                    # Unit Centered
                    painter.setFont(font_unit)
                    painter.drawText(bottom_rect, Qt.AlignCenter | Qt.AlignBottom, info.get('unit', ''))
                    continue 
                
                # Plot Content Layout (Phase 11 Refactor)
                display_name = info.get('title') or info.get('name', '')
                is_depth = display_name.lower() == 'depth'
                
                # Use info color if it's not the default depth color, otherwise resolve from current theme
                if is_depth:
                    c = app_config.get_theme_qcolor('text_main')
                else:
                    c = QColor(info.get('color', app_config.get_theme_color('text_main')))
                painter.setPen(QPen(c, 1.5 * scale))
                
                # 1. Name Position
                painter.setFont(font_name)
                # [DEPTH] Move down to middle line position if it's the depth track
                # [ALIGN] normal name top at 8.5. 70 - (8.5 + 22) = 39.5.
                name_y_offset = (row_height * 0.5 - 11 * scale) if is_depth else 8.5 * scale
                name_rect = QRectF(4 * scale, y_top + name_y_offset, w - 8 * scale, 22 * scale)
                painter.drawText(name_rect, Qt.AlignCenter, display_name)
                
                if info.get('range_visible', True):
                    # [ALIGN] Consistent middle element position
                    bar_y = y_top + row_height * 0.5
                    painter.setPen(QPen(c, 1 * scale))
                    painter.drawLine(int(5 * scale), int(bar_y), int(w - 5 * scale), int(bar_y))
                    
                    # 3. Bottom Row: [Min] [Unit] [Max]
                    painter.setFont(font_scale)
                    painter.setPen(c)
                    bottom_rect = QRectF(5 * scale, bar_y + 8.5 * scale, w - 10 * scale, 18 * scale)
                    
                    # Range Values
                    s_min, s_max = f"{info.get('min', 0):.6g}", f"{info.get('max', 0):.6g}"
                    if info.get('invert_x', False): s_min, s_max = s_max, s_min
                    
                    painter.drawText(bottom_rect, Qt.AlignLeft | Qt.AlignBottom, s_min)
                    painter.drawText(bottom_rect, Qt.AlignRight | Qt.AlignBottom, s_max)
                    
                    # Unit Centered
                    painter.setFont(font_unit)
                    painter.drawText(bottom_rect, Qt.AlignCenter | Qt.AlignBottom, info.get('unit', ''))
                else:
                    # Case for Depth track where range is hidden
                    painter.setFont(font_unit)
                    painter.setPen(c)
                    unit_str = info.get('unit', '')
                    # [DEPTH] Add parentheses only for depth track
                    if is_depth and unit_str: unit_str = f"({unit_str})"
                    
                    # [DEPTH] Shift unit down if name was moved to middle
                    unit_y = row_height * 0.5 + 12 * scale if is_depth else row_height * 0.5
                    unit_rect = QRectF(4 * scale, y_top + unit_y, w - 8 * scale, 18 * scale)
                    painter.drawText(unit_rect, Qt.AlignCenter, unit_str)
            # if scale_text:
            #     f_scale = QFont("Arial"); f_scale.setPixelSize(int(10 * scale)); f_scale.setBold(True)
            #     painter.setFont(f_scale); painter.setPen(Qt.black)
            #     h_text = painter.fontMetrics().height()
            #     painter.drawText(QRectF(0, h - h_text - 5*scale, w, h_text), Qt.AlignCenter, scale_text)
        finally:
            painter.restore()

    def find_log_widget(self):
        p = self.parent()
        while p:
            if hasattr(p, 'sync_header_heights'): return p
            p = p.parent()
        return None

    def adjust_height(self):
        log_w = self.find_log_widget()
        if log_w: log_w.sync_header_heights()
        elif self.is_auto_height: self.setFixedHeight(max(40, len(self.items) * self.base_row_height))
        
    def remove_placeholder(self):
        self.items = [item for item in self.items if item.get('name') != "Loading..."]
        self.update()
        
    def clear_info(self):
        self.items, self.is_image = [], False
        self.adjust_height(); self.update()
        
    def set_title(self, title):
        if not self.items: self.items.append({'name': title, 'unit': '', 'min':0, 'max':0, 'color':app_config.get_theme_color('text_main'), 'range_visible': self.default_range_visible})
        else: self.items[0]['name'] = title
        self.adjust_height(); self.update()

    def set_range_visible(self, visible):
        self.default_range_visible = visible
        for item in self.items: item['range_visible'] = visible
        self.update()

    def set_unit(self, unit):
        if not self.items: self.items.append({'name': '', 'unit': unit, 'min':0, 'max':0, 'color':app_config.get_theme_color('text_main'), 'range_visible': self.default_range_visible})
        else: self.items[0]['unit'] = unit
        self.adjust_height(); self.update()

    def closeEvent(self, event):
        if self._connected_vb:
            try:
                self._connected_vb.sigYRangeChanged.disconnect(self.update)
            except:
                pass
            try:
                self._connected_vb.sigXRangeChanged.disconnect(self.update)
            except:
                pass
            self._connected_vb = None
        super().closeEvent(event)
        
    def paintEvent(self, event):
        log_widget = self.find_log_widget()
        if log_widget and getattr(log_widget, 'updating_scroll', False): return
        self._maybe_update_blur()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            if self.show_effects and self._blur_pixmap and not self._blur_pixmap.isNull():
                painter.drawPixmap(self.rect(), self._blur_pixmap)
            # Use themed brush, but make it solid if effects are off
            if self.show_effects:
                painter.fillRect(self.rect(), self._bg_brush)
            else:
                solid_color = QColor(self._bg_brush.color())
                solid_color.setAlpha(255)
                painter.fillRect(self.rect(), solid_color)
            painter.setPen(self._border_pen)
            w, h = self.width(), self.height()
            painter.drawLine(0, 0, w, 0); painter.drawLine(0, h-1, w, h-1)
            if not self.items: return
            n, row_height = len(self.items), self.base_row_height
            for i, info in enumerate(self.items):
                y_top = h - (n - i) * row_height
                rect = QRectF(0, y_top, w, row_height)
                if i in self.highlighted_curves: painter.fillRect(rect, self._highlight_brush)
                f_size, f_family = info.get('font_size', self.font_size_name), info.get('font_family', 'Arial')
                
                # [FIX] Use setPixelSize for consistent scaling across DPI levels
                font_name = QFont(f_family); font_name.setPixelSize(int(f_size * 1.33)); font_name.setBold(True)
                font_unit = QFont(f_family); font_unit.setPixelSize(int(max(6, f_size - 2) * 1.33))
                font_scale = QFont(f_family); font_scale.setPixelSize(int(max(6, f_size - 2) * 1.33))
                
                painter.setFont(font_name)
                name_h = painter.fontMetrics().height()
                if info.get('is_image', False):
                     display_name = info.get('title') or info.get('name', 'Image')
                     
                     # 1. Name Centered (Top)
                     painter.setPen(self._image_name_color)
                     name_rect = QRectF(4, y_top + 10, w - 8, 22)
                     painter.drawText(name_rect, Qt.AlignCenter, display_name)
                     
                     # 2. Color Bar (Middle)
                     bar_y = y_top + row_height * 0.5
                     grad_rect = QRectF(5, bar_y - 4, w - 10, 8)
                     grad = self.get_gradient(info.get('cmap', DEFAULT_IMAGE_CMAP), invert=info.get('invert', False), 
                                              log_mode=info.get('log', False), min_v=info.get('min', 0), max_v=info.get('max', 100))
                     grad.setStart(grad_rect.left(), 0); grad.setFinalStop(grad_rect.right(), 0)
                     painter.fillRect(grad_rect, grad)
                     painter.setPen(self._gray_border_pen)
                     painter.drawRect(grad_rect)
                     
                     # 3. Bottom Row: [Min] [Unit] [Max]
                     painter.setFont(font_scale); painter.setPen(Qt.black)
                     bottom_rect = QRectF(5, bar_y + 10, w - 10, 18)
                     
                     v_min, v_max = info.get('min', 0), info.get('max', 100)
                     s_min, s_max = (f"{v_min:.2g}", f"{v_max:.2g}") if abs(v_min) < 0.01 or abs(v_max) > 1000 else (f"{v_min:.1f}", f"{v_max:.1f}")
                     
                     painter.drawText(bottom_rect, Qt.AlignLeft | Qt.AlignBottom, s_min)
                     painter.drawText(bottom_rect, Qt.AlignRight | Qt.AlignBottom, s_max)
                     
                     # Unit Centered
                     painter.setFont(font_unit)
                     painter.drawText(bottom_rect, Qt.AlignCenter | Qt.AlignBottom, info.get('unit', ''))
                     continue 
                if i > 0: pass # [AESTHETIC] Internal separators removed by user request
                
                c = QColor(info['color'])
                painter.setPen(c)
                
                # 1. Name Position
                painter.setFont(font_name)
                display_name = info.get('title') or info.get('name', '')
                is_depth = display_name.lower() == 'depth'
                
                # [DEPTH] Move down to middle line position if it's the depth track
                # [ALIGN] name top at 8.5px if normal, 24px if depth.
                name_y_offset = (row_height * 0.5 - 11) if is_depth else 8.5
                name_rect = QRectF(4, y_top + name_y_offset, w - 8, 22)
                painter.drawText(name_rect, Qt.AlignCenter, display_name)
                
                if info.get('range_visible', True):
                    # [ALIGN] Consistent middle element position
                    bar_y = y_top + row_height * 0.5
                    painter.setPen(QPen(c, 1))
                    painter.drawLine(int(5), int(bar_y), int(w - 5), int(bar_y))
                    
                    # 3. Bottom Row: [Min] [Unit] [Max]
                    painter.setFont(font_scale)
                    painter.setPen(c)
                    # [ALIGN] bottom_rect from 43.5 to 61.5. Margin = 8.5.
                    bottom_rect = QRectF(5, bar_y + 8.5, w - 10, 18)
                    
                    # Range Values
                    s_min, s_max = f"{info['min']:.6g}", f"{info['max']:.6g}"
                    if info.get('invert_x', False): s_min, s_max = s_max, s_min
                    
                    painter.drawText(bottom_rect, Qt.AlignLeft | Qt.AlignBottom, s_min)
                    painter.drawText(bottom_rect, Qt.AlignRight | Qt.AlignBottom, s_max)
                    
                    # Unit Centered
                    painter.setFont(font_unit)
                    painter.drawText(bottom_rect, Qt.AlignCenter | Qt.AlignBottom, info['unit'])
                else:
                    # Case for Depth track where range is hidden
                    painter.setFont(font_unit)
                    painter.setPen(c)
                    unit_str = info.get('unit', '')
                    # [DEPTH] Add parentheses only for depth track
                    if is_depth and unit_str: unit_str = f"({unit_str})"
                    
                    # [DEPTH] Shift unit down if name was moved to middle
                    unit_y = (row_height * 0.5 + 12) if is_depth else row_height * 0.5
                    unit_rect = QRectF(4, y_top + unit_y, w - 8, 18)
                    painter.drawText(unit_rect, Qt.AlignCenter, unit_str)
        finally:
            painter.end()
            
    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            event.ignore(); return
        if not self.items: return
        n = len(self.items)
        idx = n - 1 - int((self.height() - event.position().y()) // self.base_row_height)
        if 0 <= idx < n:
            parent = self.parent()
            if hasattr(parent, 'select_curve'):
                parent.setFocus()
                append = bool(event.modifiers() & Qt.ControlModifier)
                parent.select_curve(idx, append=append)
                event.accept(); return
        super().mousePressEvent(event)
    
    def mouseDoubleClickEvent(self, event):
        if not self.items: return
        n = len(self.items)
        idx = n - 1 - int((self.height() - event.position().y()) // self.base_row_height)
        if 0 <= idx < n:
            parent = self.parent()
            if hasattr(parent, 'open_curve_settings'): parent.open_curve_settings(idx); event.accept(); return
        super().mouseDoubleClickEvent(event)

    def _maybe_update_blur(self):
        if not self.show_effects: return
        if getattr(self, '_updating_blur', False): return
        now = time.time()
        if hasattr(self, '_last_blur_time') and now - self._last_blur_time < 0.05: return
        self._last_blur_time = now
        self._updating_blur = True
        try:
            parent = self.parent()
            if not parent or not hasattr(parent, 'plot_widget'): return
            pw = parent.plot_widget
            if not pw or not pw.isVisible(): return
            h_rect = self.geometry()
            if h_rect.height() <= 0 or h_rect.width() <= 0: return
            target = pw.viewport() if hasattr(pw, 'viewport') and pw.viewport() else pw
            if not target: return
            v_rect = QRect(0, 0, h_rect.width(), h_rect.height())
            snap = target.grab(v_rect)
            if snap.isNull(): return
            p1 = snap.scaled(max(1, h_rect.width()//2), max(1, h_rect.height()//2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p2 = p1.scaled(max(1, p1.width()//2), max(1, p1.height()//2), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self._blur_pixmap = p2.scaled(h_rect.width(), h_rect.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        finally:
            self._updating_blur = False

    def get_gradient(self, cmap_name, invert=False, log_mode=False, min_v=0, max_v=100):
        pg_cmap, grad = get_standard_colormap(cmap_name, invert=invert)
        if not log_mode: return grad
        if min_v <= 0: min_v = 1e-4
        if max_v <= min_v: max_v = min_v * 10
        l_min, l_max = np.log10(min_v), np.log10(max_v)
        div = l_max - l_min or 1.0
        new_grad = QLinearGradient()
        for i in range(21):
            t = i / 20.0
            val = min_v + t * (max_v - min_v)
            norm = np.clip((np.log10(val) - l_min) / div, 0.0, 1.0)
            rgba = pg_cmap.map([norm], mode='byte')[0]
            new_grad.setColorAt(t, QColor(int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3])))
        return new_grad

class SelectionOverlay(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents); self.setAttribute(Qt.WA_NoSystemBackground)
        self.border_color, self.border_width, self.is_visible = None, 2, False
        self.update_theme()

    def update_theme(self):
        """Theme update placeholder for propagation."""
        self.update()

    def set_selection(self, visible, color=None):
        self.is_visible, self.border_color = visible, color
        self.update()

    def paintEvent(self, event):
        if not self.is_visible or not self.border_color: return
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()); c = QColor(self.border_color)
        painter.fillRect(rect, QColor(c.red(), c.green(), c.blue(), 12))
        painter.setPen(QPen(c, 1.5)); painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(0.75, 0.75, -0.75, -0.75))
        painter.fillRect(QRectF(0, 0, rect.width(), 4), c)
