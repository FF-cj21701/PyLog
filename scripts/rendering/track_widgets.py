import pyqtgraph as pg
import numpy as np
import math
from typing import Tuple, Optional, Any, Union, Dict, List
from PySide6.QtWidgets import (QWidget, QScrollArea, QPushButton, QComboBox, QHBoxLayout, 
                               QGraphicsOpacityEffect, QMenu, QSizePolicy, QGraphicsItem)
from PySide6.QtCore import Qt, QRectF, QRect, QPointF, Signal, QEvent, QObject
from PySide6.QtGui import (QPainter, QPen, QFont, QColor, QBrush, QImage, QPainterPath, QPixmap, QLinearGradient, QPolygonF)
from ..utils.colormap_utils import get_standard_colormap
from ..utils.plot_style_utils import DEFAULT_NULL_COLOR, normalize_fill_style
from .plot_constants import AXIS_WIDTH
from .image_manager import ImageTrackManager
from core.app_config import app_config

from .graphics_items import get_physical_grid_steps, VerticalLoggingCurveItem, CachedGridItem
from .fracture_annotations import sinusoidal_fracture_xy

class PainterDepthTrack(QWidget):
    """
    Manually drawn depth track using QPainter.
    【重构】屏幕刻度和导出刻度全部复用统一的物理算法。
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(60)
        self.vb = None 
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        
        self.curves, self.curve_viewboxes = [], []
        
        # 缓存变量
        self._cache_pixmap = None
        self._cache_min_y = 0
        self._cache_max_y = 0
        self._cache_major_step = 0
        self._cache_height_px = 0
        
        # [NEW] Font customization for depth labels
        self.label_font_family = "Arial"
        self.label_font_size = 0 # 0 for Auto
        self.label_mask_enabled = False
        self.label_mask_length = 2
        
        self.update_theme()
        
    def update_theme(self):
        """Refresh drawing pens and brushes from app_config."""
        self._bg_brush = QBrush(app_config.get_theme_qcolor("plot_bg"))
        self._pen_major = QPen(app_config.get_theme_qcolor("text_main"), 2)
        self._pen_minor = QPen(app_config.get_theme_qcolor("text_dim"), 1)
        self._font_bold_10 = QFont("Arial", 10, QFont.Bold)
        self._font_bold_8 = QFont("Arial", 8, QFont.Bold)
        # Invalidate the prerendered tick cache so theme-driven text colors refresh immediately.
        self._cache_pixmap = None
        self._cache_min_y = 0
        self._cache_max_y = 0
        self._cache_major_step = 0
        self._cache_height_px = 0
        self.update()
        
    # 💡 [新增] 吸收 PySide6 传来的多余参数
    def _on_view_changed(self, *args):
        # 缩放导致步长变化时，强制失效缓存
        self.update()

    def sync_with_plot(self, vb):
        if self.vb == vb: return
        if self.vb:
            try:
                # 💡 [修复] 对应断开拦截器
                self.vb.sigYRangeChanged.disconnect(self._on_view_changed)
                self.vb.sigTransformChanged.disconnect(self._on_view_changed)
            except: pass
        self.vb = vb
        if self.vb:
            # 💡 [修复] 连接到拦截器
            self.vb.sigYRangeChanged.connect(self._on_view_changed)
            self.vb.sigTransformChanged.connect(self._on_view_changed)
        self.update()

    def _draw_ticks(self, painter, rect, min_y, max_y, scale=1.0):
        w, h = rect.width(), rect.height()
        view_span = max_y - min_y
        if view_span <= 0: return

        major_step, minor_step = get_physical_grid_steps(view_span, h, scale=scale)
        start_tick = math.floor(min_y / major_step) * major_step
        
        # [NEW] Font point size: Use customized size if provided, else follow auto-logic
        if getattr(self, 'label_font_size', 0) > 0:
            font_size = self.label_font_size
        else:
            font_size = 10 if major_step < 1000 else 8
            
        font_family = getattr(self, 'label_font_family', "Arial")
        font = QFont(font_family, font_size, QFont.Bold)
        painter.setFont(font)
        fm = painter.fontMetrics()
        
        main_color = QColor(app_config.get_theme_color("text_main"))
        pen_maj = QPen(main_color, max(1.0, 2.0 * scale))
        pen_min = QPen(main_color, max(1.0, 1.0 * scale)) 
        pen_maj.setCosmetic(True)
        pen_min.setCosmetic(True)

        curr_major = start_tick
        while curr_major <= max_y + major_step:
            # 💡 [关键修复 2]：增加 1e-5 的容差，防止浮点数精度导致上下边缘的刻度被意外截断
            if min_y - 1e-5 <= curr_major <= max_y + 1e-5:
                y_p = (curr_major - min_y) / view_span * h
                painter.setPen(pen_maj)
                
                painter.drawLine(QPointF(0, y_p), QPointF(10 * scale, y_p))
                painter.drawLine(QPointF(w - 10 * scale, y_p), QPointF(w, y_p))
                
                label_val = int(round(curr_major)) if abs(curr_major - round(curr_major)) < 0.001 else curr_major
                text = f"{label_val:.1f}" if isinstance(label_val, float) else str(label_val)
                
                if getattr(self, 'label_mask_enabled', False):
                    m_len = getattr(self, 'label_mask_length', 2)
                    if len(text) > m_len:
                        text = "X" * m_len + text[m_len:]
                    else:
                        text = "X" * len(text)
                th = fm.height()
                # Center label vertically on the tick line (y_p), but clamp to [0, h] for borders
                top = y_p - th/2
                if top < 0: top = 0
                if top + th > h: top = h - th
                
                draw_rect = QRectF(0, top, w, th)
                painter.drawText(draw_rect, Qt.AlignCenter, text)

                curr_minor = curr_major + minor_step
                while curr_minor < curr_major + major_step - (minor_step * 0.1):
                    if min_y - 1e-5 <= curr_minor <= max_y + 1e-5:
                        y_p = (curr_minor - min_y) / view_span * h
                        painter.setPen(pen_min)
                        
                        # 💡 [关键修复 3]：适当加长副刻度 (原来是 5 -> 现改为 6)
                        # 确保在导出高分辨率大图时，副刻度也足够醒目
                        painter.drawLine(QPointF(0, y_p), QPointF(6 * scale, y_p))
                        painter.drawLine(QPointF(w - 6 * scale, y_p), QPointF(w, y_p))
                    curr_minor += minor_step
                
            curr_major += major_step

    def _update_tick_cache(self, min_y, max_y, h_px, major_step):
        """将刻度和文字预渲染到高清 QImage 中"""
        view_span = max_y - min_y
        if view_span <= 0: return
        pixels_per_unit = h_px / view_span
        
        # 获取设备像素比 (适配 4K 等高清屏)
        dpr = self.devicePixelRatioF()
        
        buffer_units = view_span 
        c_min = min_y - buffer_units
        c_max = max_y + buffer_units
        c_span = c_max - c_min
        c_h_px = int(c_span * pixels_per_unit)
        
        # 创建高清 QImage
        self._cache_pixmap = QImage(
            int(self.width() * dpr), 
            int(max(1, c_h_px) * dpr), 
            QImage.Format_ARGB32
        )
        self._cache_pixmap.setDevicePixelRatio(dpr)
        self._cache_pixmap.fill(Qt.transparent)
        
        p = QPainter(self._cache_pixmap)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        # 针对高清屏渲染
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # 复用核心绘制算法
        self._draw_ticks(p, QRectF(0, 0, self.width(), c_h_px), c_min, c_max, scale=1.0)
        p.end()
        
        self._cache_min_y = c_min
        self._cache_max_y = c_max
        self._cache_major_step = major_step
        self._cache_height_px = c_h_px

    def paintEvent(self, event):
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), self._bg_brush)
            if not self.vb: return
            try: (_, (min_y, max_y)) = self.vb.viewRange()
            except: return
            
            exact_h = self.vb.sceneBoundingRect().height()
            view_span = max_y - min_y
            if view_span <= 0: return
            
            major_step, _ = get_physical_grid_steps(view_span, exact_h, scale=1.0)
            
            # 校验缓存是否有效
            need_update = (self._cache_pixmap is None or 
                           abs(self._cache_major_step - major_step) > 1e-6 or
                           min_y < self._cache_min_y or 
                           max_y > self._cache_max_y or
                           abs(self._cache_height_px / (self._cache_max_y - self._cache_min_y) - exact_h / view_span) > 0.1)
            
            if need_update:
                self._update_tick_cache(min_y, max_y, exact_h, major_step)
            
            # Use the cache's own pixel density when positioning the prerendered
            # image. This avoids tiny scale mismatches versus the plot grid that
            # can accumulate into visible depth/grid drift.
            cache_span = self._cache_max_y - self._cache_min_y
            if cache_span <= 0:
                return
            cache_pixels_per_unit = self._cache_height_px / cache_span
            offset_y = (self._cache_min_y - min_y) * cache_pixels_per_unit
            
            painter.save()
            painter.translate(0, offset_y)
            painter.drawImage(0, 0, self._cache_pixmap)
            painter.restore()
            
        finally:
            painter.end()

    def render_to(self, painter, rect, min_y, max_y, scale=1.0, draw_border=True):
        painter.save()
        try:
            painter.translate(rect.topLeft())
            w, h = rect.width(), rect.height()
            painter.setClipRect(0, 0, w, h)
            painter.fillRect(0, 0, w, h, app_config.get_theme_qcolor("plot_bg"))
            
            if draw_border:
                painter.setPen(QPen(QColor(app_config.get_theme_color("track_divider")), 1.2 * scale))
                painter.drawRect(0, 0, w, h)
            
            self._draw_ticks(painter, QRectF(0, 0, w, h), min_y, max_y, scale=scale)
        finally:
            painter.restore()

    def set_grid_style(self, x, y): pass
    def mousePressEvent(self, event):
        if self.parent() and hasattr(self.parent(), 'select_track'):
            self.parent().setFocus()
            append = bool(event.modifiers() & Qt.ControlModifier)
            self.parent().select_track(append=append)
            event.accept()
            return
        super().mousePressEvent(event)

    def clear(self): pass
    def setFrameShape(self, *args): pass
    def setXRange(self, *args, **kwargs): pass
    def addItem(self, *args, **kwargs): pass
    def getViewBox(self): return None


class InteractivePlotWidget(pg.PlotWidget):
    """
    Base plot widget that supports overlaid ViewBoxes for multi-curve plotting.
    """
    # Signal to notify containers that the view has changed its pixel size
    viewResized = Signal(float, float) # min_y, max_y
    def __init__(self, parent=None):
        super().__init__(parent)

        # 💡 [修复 1] 强制移除 QGraphicsView 的默认 1px 边框，
        # 保证内部 ViewBox 高度与外部 Widget 高度 100% 一致！
        self.setStyleSheet("border: 0px; outline: none;")

        self.curves, self.curve_viewboxes = [], []
        self.is_log_scale = False
        self.setContentsMargins(0, 0, 0, 0)
        self.plotItem.vb.setContentsMargins(0, 0, 0, 0)
        self.plotItem.setContentsMargins(0, 0, 0, 0)
        self.plotItem.vb.setMouseEnabled(x=False, y=True)
        self.plotItem.vb.setMenuEnabled(False) 
        self.plotItem.hideButtons()
        self.invertY(True)
        
        left_axis = self.getPlotItem().getAxis('left')
        left_axis.setStyle(showValues=False)
        left_axis.setPen(None)
        # bottom_axis = self.getPlotItem().getAxis('bottom')
        # bottom_axis.setStyle(showValues=False, tickLength=0)
        # bottom_axis.setPen(None)
        # 彻底隐藏底部坐标轴和所有的数值、刻度
        self.getPlotItem().hideAxis('bottom')
        # 彻底隐藏左侧坐标轴（连同刻度线一起干掉）
        self.getPlotItem().hideAxis('left')
        self.getPlotItem().hideAxis('right')
        
        self.show_grid_x = True
        self.show_grid_y = True
        self.showGrid(x=False, y=False) 
        
        self.bg_grid = CachedGridItem(self.plotItem.vb)
        self.scene().addItem(self.bg_grid)
        self.plotItem.vb.sigResized.connect(self._sync_overlay_geometry)
        self.update_theme()
        
    def update_theme(self):
        """Update background color and grid colors from app_config."""
        theme_bg = app_config.get_theme_qcolor('plot_bg')
        bg_color = theme_bg
        
        # [NEW] Check if this is an image track and handle Null Color "Auto" (Theme)
        for c in self.curves:
            if c.get('is_image'):
                res = app_config.resolve_null_color(c['info'].get('null_color', DEFAULT_NULL_COLOR))
                if res == 'Theme':
                    bg_color = theme_bg
                elif res == 'White':
                    bg_color = QColor(Qt.white)
                elif res == 'Black':
                    bg_color = QColor(Qt.black)
                break # Primary image defines background
        
        self.setBackground(bg_color)
        if hasattr(self, 'bg_grid'):
            self.bg_grid.update_theme()
        self.update()
        
    def add_overlay_viewbox(self, info):
        vb = pg.ViewBox()
        vb.setBackgroundColor(None)
        vb.setMouseEnabled(x=False, y=True)
        vb.setMenuEnabled(False)
        vb.invertY(True)
        vb.setYLink(self.plotItem.vb)
        self.scene().addItem(vb)
        # [FIX] Apply Invert X flag correctly during initialization (Crucial for Templates)
        vb.invertX(info.get('invert_x', False))
        vb.setXRange(info.get('min', 0), info.get('max', 100), padding=0)
        entry = {'viewbox': vb, 'curve': None, 'info': info}
        self.curve_viewboxes.append(entry)
        self._sync_overlay_geometry()
        return vb
    
    def _sync_overlay_geometry(self):
        base_geom = self.plotItem.vb.sceneBoundingRect()
        for entry in self.curve_viewboxes:
            entry['viewbox'].setGeometry(base_geom)
        
        # [DECOUPLED] Just notify whoever is listening (usually the container or LogWidget)
        if base_geom.height() > 0:
            (min_y, max_y) = self.plotItem.vb.viewRange()[1]
            self.viewResized.emit(min_y, max_y)
    
    def remove_overlay_viewbox(self, index):
        if 0 <= index < len(self.curve_viewboxes):
            entry = self.curve_viewboxes.pop(index)
            vb = entry['viewbox']
            self.scene().removeItem(vb)
            # 💡 彻底销毁 C++ 对象，释放内存
            vb.deleteLater() 
    
    def clear_overlays(self):
        for entry in self.curve_viewboxes:
            vb = entry['viewbox']
            self.scene().removeItem(vb)
            # 💡 彻底销毁
            vb.deleteLater()
        self.curve_viewboxes.clear()
        
    def set_grid_style(self, x_grid, y_grid):
        self.show_grid_x = x_grid
        self.show_grid_y = y_grid
        if hasattr(self, 'bg_grid'):
            self.bg_grid.show_x, self.bg_grid.show_y = x_grid, y_grid
            self.bg_grid.update()
        self.update()
        
    def set_x_params(self, is_log, x_range):
        self.is_log_scale = is_log
        if hasattr(self, 'bg_grid'):
            self.bg_grid.log_x, self.bg_grid.x_range = is_log, x_range
            self.bg_grid._invalidate_cache() 
        # [CRITICAL] Force immediate redraw to reflect grid/scale changes
        self.update()
        
    def render_to(self, painter, rect, min_y, max_y, scale=1.0, draw_border=True):
        painter.save()
        try:
            painter.translate(rect.topLeft())
            w, h = rect.width(), rect.height()
            painter.setClipRect(0, 0, w, h)
            
            bg_color = app_config.get_theme_qcolor('plot_bg')
            for c in self.curves:
                if c.get('is_image') and c['info'].get('null_color') == 'Black':
                    bg_color = QColor(Qt.black); break
            painter.fillRect(0, 0, w, h, bg_color)
            if draw_border:
                painter.setPen(QPen(QColor(app_config.get_theme_color("track_divider")), 1.2 * scale))
                painter.drawRect(0, 0, w, h)
                
            grid_pen = QPen(QColor(app_config.get_theme_color("grid_major")), 0.5 * scale)
            minor_grid_pen = QPen(QColor(app_config.get_theme_color("grid_minor")), 0.3 * scale)

            # 【重构】导出高清图的 Y 轴网格，严格复用统一的物理深度逻辑
            if getattr(self, 'show_grid_y', True):
                view_span = max_y - min_y
                if view_span > 0:
                    # 💡 传入导出时的物理像素高度 h 和 scale
                    major_step, minor_step = get_physical_grid_steps(view_span, h, scale=scale)
                    curr_g = math.floor(min_y / major_step) * major_step
                    while curr_g <= max_y + major_step:
                        if min_y <= curr_g <= max_y:
                            painter.setPen(grid_pen)
                            y_p = (curr_g - min_y) / view_span * h
                            painter.drawLine(0, int(y_p), w, int(y_p))
                            
                        curr_m = curr_g + minor_step
                        while curr_m < curr_g + major_step - (minor_step * 0.1):
                            if min_y <= curr_m <= max_y:
                                painter.setPen(minor_grid_pen)
                                y_m = (curr_m - min_y) / view_span * h
                                painter.drawLine(0, int(y_m), w, int(y_m))
                            curr_m += minor_step
                        curr_g += major_step

            # X 轴网格导出逻辑
            if getattr(self, 'show_grid_x', True) and self.curves and not any(c.get('is_image') for c in self.curves):
                is_log = any(c['info'].get('log', False) for c in self.curves)
                if is_log:
                    info = self.curves[0]['info']
                    c_min, c_max = max(1e-10, info['min']), info['max']
                    log_min, log_max = math.floor(math.log10(c_min)), math.ceil(math.log10(c_max))
                    for exp in range(log_min, log_max + 1):
                        val = 10**exp
                        if c_min <= val <= c_max:
                            x_p = (math.log10(val) - math.log10(c_min)) / (math.log10(c_max) - math.log10(c_min)) * w
                            painter.setPen(grid_pen)
                            painter.drawLine(int(x_p), 0, int(x_p), h)
                        for m in range(2, 10):
                            m_val = m * (10**exp)
                            if c_min <= m_val <= c_max:
                                x_m = (math.log10(m_val) - math.log10(c_min)) / (math.log10(c_max) - math.log10(c_min)) * w
                                painter.setPen(minor_grid_pen)
                                painter.drawLine(int(x_m), 0, int(x_m), h)
                else:
                    for i in range(11):
                        x_p = (i / 10.0) * w
                        painter.setPen(grid_pen)
                        painter.drawLine(int(x_p), 0, int(x_p), h)
                        if i < 10:
                            for j in range(1, 10):
                                x_m = ((i + j/10.0) / 10.0) * w
                                painter.setPen(minor_grid_pen)
                                painter.drawLine(int(x_m), 0, int(x_m), h)

            # [NEW] PRE-PASS: Calculate pixel coordinates for all curves by INDEX (to support duplicate names)
            curve_pixel_data = {} # index -> (px_x, px_y)
            for idx, curve in enumerate(self.curves):
                if not curve.get('is_image'):
                    data, depth, info = curve.get('data'), curve.get('depth'), curve.get('info')
                    idx_start, idx_end = max(0, np.searchsorted(depth, min_y) - 1), min(len(depth), np.searchsorted(depth, max_y) + 1)
                    pts_x, pts_y = data[idx_start:idx_end], depth[idx_start:idx_end]
                    if len(pts_x) > 1:
                        c_min, c_max = info['min'], info['max']
                        if info.get('log', False):
                            c_min, c_max = max(1e-10, c_min), max(0.1, c_max)
                            l_min, l_max = np.log10(c_min), np.log10(c_max)
                            norm = (np.log10(np.clip(pts_x, c_min, c_max)) - l_min) / (l_max - l_min)
                        else:
                            # [FIX] Handle swapped Min/Max natively. (pts-min)/(max-min) is already inverted if min > max.
                            div = (c_max - c_min) if c_max != c_min else 1.0
                            norm = (pts_x - c_min) / div
                        
                        # [FIX] XOR with explicit Invert check to match UI behavior
                        if info.get('invert_x', False):
                            norm = 1.0 - norm
                            
                        px_x = norm * w
                        px_y = (pts_y - min_y) / (max_y - min_y) * h
                        # [FIX] Clamp Y to plot boundaries to prevent curves bleeding into header during export
                        px_y = np.clip(px_y, 0, h)
                        curve_pixel_data[idx] = (px_x, px_y)

            # RENDER PASS
            for idx, curve in enumerate(self.curves):
                if curve.get('is_image'):
                    ImageTrackManager.render_image_to_painter(painter, curve, min_y, max_y, w, h)
                else:
                    info = curve.get('info')
                    # Look up pre-calculated pixel data by INDEX
                    if idx in curve_pixel_data:
                        px_x, px_y = curve_pixel_data[idx]
                        
                        fill_mode = info.get('fill_mode', 'None')
                        target_pixels = None
                        
                        if fill_mode in ['Left', 'Right']:
                            if curve.get('_accum_fill_baseline') is not None:
                                c_min, c_max = info['min'], info['max']
                                baseline = curve['_accum_fill_baseline']
                                if info.get('log', False):
                                    c_min = max(1e-10, c_min)
                                    c_max = max(c_min * 10.0, c_max)
                                    l_min, l_max = np.log10(c_min), np.log10(c_max)
                                    div = (l_max - l_min) if l_max != l_min else 1.0
                                    norm = (np.log10(max(1e-10, baseline)) - l_min) / div
                                else:
                                    div = (c_max - c_min) if c_max != c_min else 1.0
                                    norm = (baseline - c_min) / div
                                if info.get('invert_x', False):
                                    norm = 1.0 - norm
                                bx = np.clip(norm, 0.0, 1.0) * w
                            else:
                                bx = 0 if fill_mode == 'Left' else w
                            target_pixels = (np.full_like(px_x, bx), px_y)
                        elif fill_mode != 'None':
                            # Prefer accumulative fill's internal target reference to support duplicate names.
                            target_idx = -1
                            accum_target = curve.get('_accum_fill_target_curve')
                            if accum_target in self.curves:
                                target_idx = self.curves.index(accum_target)
                            else:
                                # Fallback for standard "Fill to Curve" settings.
                                for i, other in enumerate(self.curves):
                                    if i != idx and other.get('info', {}).get('name') == fill_mode:
                                        target_idx = i
                                        break
                            if target_idx != -1:
                                target_pixels = curve_pixel_data.get(target_idx)

                        if target_pixels is not None:
                            tx, ty = target_pixels
                            
                            # [FIX] Robust mask to ensure same length for source and target within slice
                            mask_s = np.isfinite(px_x) & np.isfinite(px_y)
                            mask_t = np.isfinite(tx) & np.isfinite(ty)
                            common_mask = mask_s & mask_t
                            
                            # Only draw if there's enough valid data points for a polygon
                            if np.sum(common_mask) > 1:
                                xf, yf = px_x[common_mask], px_y[common_mask]
                                txf, tyf = tx[common_mask], ty[common_mask]
                                
                                fill_path = QPainterPath()
                                # Forward path along current curve
                                fill_path.moveTo(xf[0], yf[0])
                                for i in range(1, len(xf)):
                                    fill_path.lineTo(xf[i], yf[i])
                                # Backward path along target
                                for i in range(len(txf)-1, -1, -1):
                                    fill_path.lineTo(txf[i], tyf[i])
                                fill_path.closeSubpath()
                                fill_style = normalize_fill_style(info)
                                painter.fillPath(fill_path, QBrush(QColor(fill_style['fill_color'])))
                                
                        painter.setPen(QPen(QColor(info['color']), info['line_width'] * scale))
                        poly = QPolygonF()
                        for i in range(len(px_x)):
                            poly.append(QPointF(px_x[i], px_y[i]))
                        
                        path = QPainterPath()
                        path.addPolygon(poly)
                        painter.drawPath(path)

            for fracture in getattr(self, 'fracture_annotations', []):
                if fracture.get("type") != "sinusoidal_fracture":
                    continue
                fx, fy = sinusoidal_fracture_xy(fracture)
                if max_y == min_y:
                    continue
                px_x = np.clip(fx / 360.0, 0.0, 1.0) * w
                px_y = (fy - min_y) / (max_y - min_y) * h
                visible = (px_y >= -h * 0.25) & (px_y <= h * 1.25)
                if not np.any(visible):
                    continue
                painter.setPen(QPen(
                    QColor(fracture.get("color", "#00E5FF")),
                    float(fracture.get("line_width", 2.0)) * scale,
                ))
                path = QPainterPath()
                started = False
                for x_val, y_val, keep in zip(px_x, px_y, visible):
                    if not keep:
                        started = False
                        continue
                    if not started:
                        path.moveTo(float(x_val), float(y_val))
                        started = True
                    else:
                        path.lineTo(float(x_val), float(y_val))
                painter.drawPath(path)
        finally:
            painter.restore()
        
    def wheelEvent(self, event):
        # ... (业务事件原样保留) ...
        modifiers, delta = event.modifiers(), event.angleDelta().y()
        vb = self.plotItem.vb
        (min_y, max_y) = vb.viewRange()[1]
        y_range = max_y - min_y
        if modifiers & Qt.ControlModifier:
            scale_factor = 0.9 if delta > 0 else 1.11
            center = (min_y + max_y) / 2
            new_range = y_range * scale_factor
            new_min, new_max = center - new_range / 2, center + new_range / 2
        else:
            step = y_range * 0.1 
            if delta > 0: step = -step
            new_min, new_max = min_y + step, max_y + step
        log_w = self._find_log_widget()
        if log_w: log_w.apply_depth_range(new_min, new_max)
        else: vb.setYRange(new_min, new_max, padding=0)
        event.accept()
    
    def _find_log_widget(self):
        p = self.parent()
        while p:
            if p.__class__.__name__ == "LogWidget": return p
            p = p.parent()
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._mmb_zooming = True
            self._mmb_start_pos = event.position()
            self._mmb_start_range = self.plotItem.vb.viewRange()[1]
            event.accept(); return
        parent = self.parent()
        if parent and hasattr(parent, 'handle_fracture_pick_mouse'):
            if parent.handle_fracture_pick_mouse(event, self):
                event.accept()
                return
        if event.button() == Qt.LeftButton and parent and hasattr(parent, 'select_track'):
            parent.setFocus()
            append = bool(event.modifiers() & Qt.ControlModifier)
            parent.select_track(append=append)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        parent = self.parent()
        if parent and hasattr(parent, 'handle_fracture_pick_key'):
            if parent.handle_fracture_pick_key(event):
                event.accept()
                return
        super().keyPressEvent(event)

    def mouseMoveEvent(self, event):
        if getattr(self, '_mmb_zooming', False):
            dy = event.position().y() - self._mmb_start_pos.y()
            scale = 1.1 ** (dy / 50.0)
            min_y, max_y = self._mmb_start_range
            center = (min_y + max_y) / 2
            new_half_range = (max_y - min_y) * scale / 2
            new_min, new_max = center - new_half_range, center + new_half_range
            log_w = self._find_log_widget()
            if log_w: log_w.apply_depth_range(new_min, new_max)
            else: self.plotItem.vb.setYRange(new_min, new_max, padding=0)
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if getattr(self, '_mmb_zooming', False):
            self._mmb_zooming = False
            event.accept(); return
        super().mouseReleaseEvent(event)
