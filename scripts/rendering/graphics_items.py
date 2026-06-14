import pyqtgraph as pg
import numpy as np
import math
from typing import Tuple, Optional, Any, Union, Dict, List
from PySide6.QtWidgets import (QWidget, QScrollArea, QPushButton, QComboBox, QHBoxLayout, 
                               QGraphicsOpacityEffect, QMenu, QSizePolicy, QGraphicsItem)
from PySide6.QtCore import Qt, QRectF, QRect, QPointF, QPoint, Signal, QEvent, QObject
from PySide6.QtGui import (QPainter, QPen, QFont, QColor, QBrush, QImage, QPainterPath, QPixmap, QLinearGradient, QPolygonF)
from ..utils.colormap_utils import get_standard_colormap
from .plot_constants import AXIS_WIDTH
from .image_manager import ImageTrackManager
from core.app_config import app_config

# =====================================================================
# 【全局核心算法】统一的物理深度网格步长计算 (Single Source of Truth)
# =====================================================================
def get_physical_grid_steps(view_span: float, height_px: int, scale: float = 1.0) -> Tuple[float, float]:
    """
    Calculates primary and secondary grid steps based on physical depth span and pixel height.
    Ensures consistent grid density across UI and high-res exports.
    """
    if view_span <= 0 or height_px <= 0:
        return 10.0, 1.0

    pixels_per_unit = height_px / view_span
    
    # 目标是每 80 个像素画一条主网格线。导出时乘以 scale 保证等比例放大
    target_step_px = 80.0 * scale
    ideal_step = target_step_px / pixels_per_unit

    exponent = math.floor(math.log10(ideal_step)) if ideal_step > 0 else 0
    mantissa = ideal_step / (10**exponent)

    # 强制将步长对齐到测井标准的 1, 2, 5 序列
    if mantissa <= 1.5:
        nice_mantissa = 1.0
    elif mantissa <= 3.5:
        nice_mantissa = 2.0
    elif mantissa <= 7.5:
        nice_mantissa = 5.0
    else:
        nice_mantissa = 10.0

    major_step = nice_mantissa * (10**exponent)

    # 副网格等分规则
    if nice_mantissa == 1.0:
        minor_step = major_step / 10.0  # 1 等分成 10 份 (0.1)
    elif nice_mantissa == 2.0:
        minor_step = major_step / 4.0   # 2 等分成 4 份 (0.5)
    else:
        minor_step = major_step / 5.0   # 5 等分成 5 份 (1.0)

    return major_step, minor_step


class CachedGridItem(QGraphicsItem):
    """
    Optimized background grid.
    - X Grid: Cached vertically (log/linear rules).
    - Y Grid: Strictly driven by physical depth logic (NO pixel tile cache needed, directly drawn for 100% accuracy).
    """
    def __init__(self, parent_vb):
        super().__init__()
        self.vb = parent_vb
        self.setZValue(-100)
        self.grid_pen = QPen(app_config.get_theme_qcolor("grid_major"), 1)
        self.grid_pen.setCosmetic(True)
        self.minor_grid_pen = QPen(app_config.get_theme_qcolor("grid_minor"), 1)
        self.minor_grid_pen.setCosmetic(True)
        
        self._x_pixmap = None
        self._y_pattern_pixmap = None
        self._y_pattern_major_step = 0
        self._y_pattern_height_px = 0
        
        self.show_x = True
        self.show_y = True
        self.log_x = False
        self.x_range = (0.1, 100.0)
        
        # 💡 [修复] 使用拦截器吸收 PySide6 传来的多余参数
        self.vb.sigYRangeChanged.connect(self._on_y_range_changed)
        self.vb.sigResized.connect(self._invalidate_cache)
        self.vb.sigTransformChanged.connect(self._on_transform_changed)
        
        self._rect = QRectF()
        self.sync_geometry()

    def update_theme(self):
        """Update grid pens from app_config tokens."""
        self.grid_pen = QPen(app_config.get_theme_qcolor("grid_major"), 1)
        self.grid_pen.setCosmetic(True)
        self.minor_grid_pen = QPen(app_config.get_theme_qcolor("grid_minor"), 1)
        self.minor_grid_pen.setCosmetic(True)
        self.update()
        
    def set_grid_visibility(self, x_grid, y_grid):
        self.show_x = x_grid
        self.show_y = y_grid
        self.update()

    # 💡 [新增] 吸收 (ViewBox, Tuple) 参数
    def _on_y_range_changed(self, vb, y_range):
        self.update()
        
    # 💡 [新增] 吸收任意数量的参数
    def _on_transform_changed(self, *args):
        self.sync_geometry()

    def sync_geometry(self):
        self.prepareGeometryChange()
        self._rect = self.vb.sceneBoundingRect()
        if not self._rect.isEmpty():
            self.setPos(self._rect.topLeft())
        self.update()

    def _invalidate_cache(self):
        self._x_pixmap = None
        self._y_pattern_pixmap = None
        self.sync_geometry()

    def boundingRect(self):
        return QRectF(0, 0, self._rect.width(), self._rect.height())

    def paint(self, painter, option, widget):
        if self._rect.isEmpty(): return
        # 💡 [修复 4] 去掉 int() 强转，保留高精度浮点数
        w, h = self._rect.width(), self._rect.height()

        # 1. 绘制 X 轴网格 (竖线，使用缓存)
        if self.show_x:
            if self._x_pixmap is None or self._x_pixmap.width() != w:
                self._x_pixmap = QPixmap(max(1, w), max(1, h))
                self._x_pixmap.fill(Qt.transparent)
                p = QPainter(self._x_pixmap)
                
                inv = getattr(self.vb, 'state', {}).get('xInverted', False)
                if self.log_x:
                    x_min, x_max = self.x_range
                    if x_min <= 0: x_min = 1e-10
                    log_min, log_max = math.floor(math.log10(x_min)), math.ceil(math.log10(x_max))
                    log_range = math.log10(x_max) - math.log10(x_min)
                    
                    if log_range > 0:
                        for exp in range(log_min, log_max + 1):
                            val = 10**exp
                            if x_min <= val <= x_max:
                                norm = (math.log10(val) - math.log10(x_min)) / log_range
                                x = (1.0 - norm) * w if inv else norm * w
                                p.setPen(self.grid_pen)
                                p.drawLine(QPointF(x, 0), QPointF(x, h))
                            
                            p.setPen(self.minor_grid_pen)
                            for m in range(2, 10):
                                m_val = m * (10**(exp-1))
                                if x_min <= m_val <= x_max:
                                    norm_m = (math.log10(m_val) - math.log10(x_min)) / log_range
                                    x_m = (1.0 - norm_m) * w if inv else norm_m * w
                                    p.drawLine(QPointF(x_m, 0), QPointF(x_m, h))
                else:
                    p.setPen(self.grid_pen)
                    for i in range(11):
                        norm = i / 10.0
                        x = (1.0 - norm) * w if inv else norm * w
                        p.drawLine(QPointF(x, 0), QPointF(x, h))
                p.end()
            painter.drawPixmap(0, 0, self._x_pixmap)

        # 2. 【优化】绘制 Y 轴网格 (横线，使用单周期平铺缓存)
        if self.show_y:
            y_min, y_max = self.vb.viewRange()[1]
            view_span = y_max - y_min
            if view_span <= 0: return
            
            # 1. 计算当前比例下的步长（像素级）
            major_step, minor_step = get_physical_grid_steps(view_span, h, scale=1.0)
            pixels_per_unit = h / view_span
            pattern_h = int(round(major_step * pixels_per_unit))
            
            # 2. 检查缓存是否有效 (步长或像素高度改变则失效)
            dpr = 1.0
            try: dpr = self.vb.window().devicePixelRatioF()
            except: pass
            
            if self._y_pattern_pixmap is None or \
               abs(self._y_pattern_major_step - major_step) > 1e-6 or \
               abs(self._y_pattern_height_px - pattern_h) > 0.5:
                
                self._y_pattern_major_step = major_step
                self._y_pattern_height_px = pattern_h
                
                # 创建高清 Pixmap 适配 HiDPI
                self._y_pattern_pixmap = QPixmap(int(max(1, w) * dpr), int(max(1, pattern_h) * dpr))
                self._y_pattern_pixmap.setDevicePixelRatio(dpr)
                self._y_pattern_pixmap.fill(Qt.transparent)
                
                p = QPainter(self._y_pattern_pixmap)
                # 高清渲染设置
                p.setRenderHint(QPainter.Antialiasing)
                # 画主横线（顶部 0 处）
                p.setPen(self.grid_pen)
                p.drawLine(QPointF(0, 0), QPointF(w, 0))
                
                # 画副横线
                p.setPen(self.minor_grid_pen)
                curr_m = minor_step
                while curr_m < major_step - (minor_step * 0.1):
                    y_p = curr_m * pixels_per_unit
                    p.drawLine(QPointF(0, y_p), QPointF(w, y_p))
                    curr_m += minor_step
                p.end()
            
            # 3. 绘制平铺图层
            # 计算第一个主刻度相对于视口顶部的像素偏移量
            # y_min 向上取整到最近的主刻度开始位置
            start_y_val = math.floor(y_min / major_step) * major_step
            offset_px = int(round((start_y_val - y_min) * pixels_per_unit))
            
            painter.save()
            # 从计算出的像素偏移开始平铺
            painter.drawTiledPixmap(QRectF(0, 0, w, h), self._y_pattern_pixmap, QPoint(0, -offset_px))
            painter.restore()


class VerticalLoggingCurveItem(pg.PlotCurveItem):
    """
    Optimized Curve Item for vertical logging tracks.
    Correctly handles horizontal filling to a value (Left/Right fill)
    """
    # ... (此部分业务逻辑完美，无需修改，保留您原本的代码) ...
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._custom_fill_level = None
        self._custom_fill_brush = None
        self._target_data = None
        self._fill_path_cache = None
        self._cache_dirty = True
        self._last_view_range = None
        self._cached_path_range = (1e15, -1e15)
        self._fill_buffer_n = 0.5 # Default buffer factor (0.5 = 1/2 screen above/below)

    def invalidateFillCache(self):
        self._fill_path_cache = None # [NEW] Now stores QPolygonF
        self._cache_dirty = True
        self.update()

    def setFillOptions(self, level, brush):
        if self._custom_fill_level == level and self._custom_fill_brush == brush: return
        self._custom_fill_level = level
        self._custom_fill_brush = brush
        self._target_data = None 
        self.opts['fillLevel'] = None
        self.opts['fillBrush'] = None
        self._cache_dirty = True
        self.prepareGeometryChange()
        self.invalidateFillCache()

    def boundingRect(self):
        """
        [FIX] Expand bounding rect to include potential fill area.
        Standard CurveItem only bounds the points, which causes clipping when 
        the line is off-screen but the fill should still be visible.
        """
        rect = super().boundingRect()
        if self._custom_fill_level is not None:
            # Union with fill level line
            rect = rect.united(QRectF(self._custom_fill_level, rect.top(), 0, rect.height()))
        elif self._target_data is not None:
            # For cross-fills, we bound the horizontal space excessively to ensure 
            # common track area (0-200 etc) is always considered 'visible' 
            # if the depth range matches.
            rect.setLeft(min(rect.left(), -1000))
            rect.setRight(max(rect.right(), 1000))
        return rect

    def setFillTargetData(self, brush, x_target, y_target, t_min, t_max, t_log, t_inv, s_min, s_max, s_log, s_inv):
        self._custom_fill_brush = brush
        self._target_data = {
            'x': x_target, 'y': y_target, 
            't_min': t_min, 't_max': t_max, 't_log': t_log, 't_inv': t_inv,
            's_min': s_min, 's_max': s_max, 's_log': s_log, 's_inv': s_inv
        }
        self._custom_fill_level = None 
        self.opts['fillLevel'] = None
        self.opts['fillBrush'] = None
        self._cache_dirty = True
        self.prepareGeometryChange()
        self.invalidateFillCache()

    def paint(self, painter, option, widget=None):
        if self.xData is None or self.yData is None or len(self.xData) < 2:
            return
        
        # [NEW] Check viewport clipping
        vb = self.getViewBox()
        if vb:
            vr = vb.viewRange()[1]
            if self._cache_dirty or self._fill_path_cache is None or \
               vr[0] < self._cached_path_range[0] or \
               vr[1] > self._cached_path_range[1]:
                self._cache_dirty = True
        
        if self._cache_dirty or self._fill_path_cache is None:
            self._updateFillPath()
        
        if self._fill_path_cache:
            painter.save()
            # [FIX] Use viewRect() which is available on ViewBox
            v_rect = vb.viewRect().adjusted(0, -10, 0, 10) 
            painter.setClipRect(v_rect)
            
            painter.setPen(Qt.NoPen)
            painter.setBrush(self._custom_fill_brush)
            # [AESTHETIC] Antialiasing left enabled for smooth high-res fills
            
            if isinstance(self._fill_path_cache, list):
                for poly in self._fill_path_cache:
                    painter.drawPolygon(poly)
            else:
                painter.drawPolygon(self._fill_path_cache)
            painter.restore()
        super().paint(painter, option, widget)

    def _updateFillPath(self):
        self._fill_path_cache = QPolygonF()
        self._cache_dirty = False
        
        x_self, y_self = self.xData, self.yData
        if x_self is None or y_self is None or len(x_self) <= 1: return
        
        vb = self.getViewBox()
        if not vb: return
        vr = vb.viewRange()[1]
        v_min, v_max = vr
        
        # [NEW] Default 0.5 buffer factor for smooth scrolling experience
        v_span = v_max - v_min
        buf = v_span * self._fill_buffer_n
        v_min -= buf
        v_max += buf
        self._cached_path_range = (v_min, v_max)
        
        # [OPTIMIZATION] Slice self curve before mask to avoid unnecessary processing
        start_i = max(0, np.searchsorted(y_self, v_min) - 1)
        end_i = min(len(y_self), np.searchsorted(y_self, v_max) + 1)
        xs_slice = x_self[start_i:end_i]
        ys_slice = y_self[start_i:end_i]

        mask_s = np.isfinite(xs_slice) & np.isfinite(ys_slice)
        if not np.any(mask_s):
            return
        xs_v, ys_v = xs_slice[mask_s], ys_slice[mask_s]
        if len(xs_v) <= 1:
            return

        idx_s = np.argsort(ys_v)
        ys_sorted, xs_sorted = ys_v[idx_s], xs_v[idx_s]

        if self._custom_fill_level is not None:
            xf, yf = xs_sorted, ys_sorted
            # [PERF] Downsample if too many points per screen
            if len(xf) > 2000:
                step = max(1, len(xf) // 1000)
                xf, yf = xf[::step], yf[::step]

            poly = QPolygonF()
            poly.append(QPointF(self._custom_fill_level, yf[0]))
            for i in range(len(xf)):
                poly.append(QPointF(xf[i], yf[i]))
            poly.append(QPointF(self._custom_fill_level, yf[-1]))
            self._fill_path_cache = poly
            return

        target = self._target_data
        if target is None:
            return

        # [OPTIMIZATION] Slice target curve before mask
        start_it = max(0, np.searchsorted(target['y'], v_min) - 1)
        end_it = min(len(target['y']), np.searchsorted(target['y'], v_max) + 1)
        xt_v = target['x'][start_it:end_it]
        yt_v = target['y'][start_it:end_it]

        mask_t = np.isfinite(xt_v) & np.isfinite(yt_v)
        if not np.any(mask_t):
            return

        xt_v, yt_v = xt_v[mask_t], yt_v[mask_t]
        if len(xt_v) <= 1:
            return

        idx_t = np.argsort(yt_v)
        yt_sorted, xt_sorted = yt_v[idx_t], xt_v[idx_t]

        # [OPT] Check alignment
        is_aligned = False
        if len(ys_sorted) == len(yt_sorted) and len(ys_sorted) > 1:
            if abs(ys_sorted[0] - yt_sorted[0]) < 1e-6 and abs(ys_sorted[-1] - yt_sorted[-1]) < 1e-6:
                is_aligned = True

        d_start, d_end = max(ys_sorted[0], yt_sorted[0]), min(ys_sorted[-1], yt_sorted[-1])
        if d_start >= d_end:
            return

        if is_aligned:
            d_grid, x_s_interp, x_t_raw = ys_sorted, xs_sorted, xt_sorted
        else:
            # [PERF] Balanced density: use viewport height as point cap
            n_pts = max(2, min(1500, int(vb.height())))
            d_grid = np.linspace(d_start, d_end, n_pts)
            x_s_interp = np.interp(d_grid, ys_sorted, xs_sorted)
            x_t_raw = np.interp(d_grid, yt_sorted, xt_sorted)

        t_min_p, t_max_p = target['t_min'], target['t_max']
        s_min_p, s_max_p = target['s_min'], target['s_max']

        if not target['t_log'] and not target['s_log'] and \
           target['t_log'] == target['s_log'] and \
           target.get('t_inv') == target.get('s_inv') and \
           abs(t_min_p - s_min_p) < 1e-6 and abs(t_max_p - s_max_p) < 1e-6:
            x_t_mapped = x_t_raw
        else:
            xt_proc = x_t_raw
            if target['t_log']:
                t_min_v, t_max_v = np.log10(max(1e-10, t_min_p)), np.log10(max(1e-10, t_max_p))
                xt_proc = np.log10(np.clip(x_t_raw, 1e-10, None))
            else:
                t_min_v, t_max_v = t_min_p, t_max_p

            norm_t = (xt_proc - t_min_v) / (t_max_v - t_min_v) if t_max_v != t_min_v else xt_proc * 0
            if target.get('t_inv'):
                norm_t = 1.0 - norm_t
            norm_s = 1.0 - norm_t if target.get('s_inv') else norm_t

            if target['s_log']:
                s_min_v, s_max_v = np.log10(max(1e-10, s_min_p)), np.log10(max(1e-10, s_max_p))
            else:
                s_min_v, s_max_v = s_min_p, s_max_p
            x_t_mapped = norm_s * (s_max_v - s_min_v) + s_min_v

        poly = QPolygonF()
        for i in range(len(d_grid)):
            poly.append(QPointF(x_s_interp[i], d_grid[i]))
        for i in range(len(d_grid) - 1, -1, -1):
            poly.append(QPointF(x_t_mapped[i], d_grid[i]))
        self._fill_path_cache = poly

    def setData(self, *args, **kwargs):
        super().setData(*args, **kwargs)
        self.invalidateFillCache()


