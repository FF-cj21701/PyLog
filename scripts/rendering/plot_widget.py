import pyqtgraph as pg
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QMessageBox, 
                               QLabel, QFrame, QDialog, QFormLayout, QSpinBox, 
                               QDoubleSpinBox, QComboBox, QDialogButtonBox, QPushButton, 
                               QColorDialog, QScrollArea, QMenu, QApplication, QSlider, QScrollBar, QCheckBox,
                               QSplitter, QSizePolicy, QLineEdit, QFontComboBox, QGraphicsOpacityEffect, QFileDialog, QGroupBox)
from PySide6.QtCore import Qt, QMimeData, QPoint, QRectF, Signal, QRect, QPointF, QTimer, QEvent, QObject, QThread, QRunnable, QThreadPool, QMarginsF, QSizeF, QCoreApplication
from PySide6.QtGui import QDrag, QAction, QCursor, QPainter, QPen, QFont, QColor, QBrush, QImage, QPdfWriter, QPageLayout, QPageSize, QPainterPath, QLinearGradient
import numpy as np
import math
from typing import Optional, Union, Tuple, Any, Dict, List
from ..data.db_manager import DBManager
from ..utils.workers import DataFetchWorker, ImageSliceWorker
from ..rendering.plot_constants import AXIS_WIDTH, NULL_MNEMONICS
from core.app_config import app_config
from ..ui.plot_dialogs import (UnifiedSettingsDialog, WellSelectionDialog, UnitEditDialog)
from ..rendering.plot_components import (InteractivePlotWidget, HeaderWidget, SelectionOverlay, PainterDepthTrack, CachedGridItem)
from ..ui.ui_components import (FloatingScaleControl, FloatingHeaderToggle, FracturePickingPanel, QuickAddZone, TrackSpacer, CustomScrollArea)
from ..rendering.fracture_annotations import FRACTURE_TYPE_STYLES, enrich_fracture_interpretation
from ..data.export_manager import LogExporter
from ..tracks.track_container import BaseTrackContainer, DepthTrackContainer, CurveTrackContainer, ImageTrackContainer
from ..rendering.scroll_manager import ScrollManager

# --- Main Widget ---

# --- UI Components moved to plot_components.py ---

# --- Main Widget ---
class LogWidget(QWidget):
    loadingFinished = Signal() # Emitted when all async data and image renders are done
    selectionChanged = Signal(list) # [NEW] Emitted when tracks or curves are selected (multi-selection support)
    
    def __init__(self, db_or_path, parent=None):
        super().__init__(parent)
        self.db = None
        self.db_path = None
        self.set_db_source(db_or_path)
        self.track_containers = []
        self.skip_finite_check = True  # Optimized default
        self.current_settings_dialog = None # Track active non-blocking dialog
        self.current_h_scale = 1.0 # Global horizontal scale factor
        self.active_image_workers = {} # {track_id: (worker, timestamp)} tracking for throttling
        self.pending_loads = 0
        self.last_y_min = None # [NEW] Track last position for directional prefetch
        self._track_x_cache = {}
        self._track_x_cache_dirty = True
        self.custom_min_depth = None # [NEW] Restrictive viewport min
        self.custom_max_depth = None # [NEW] Restrictive viewport max
        self._pending_initial_scale_update = False
        self._initial_scale_update_applied = False
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Scroll Area for tracks
        self.scroll_area = CustomScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.layout.addWidget(self.scroll_area)
        
        # New: Quick Add Zone (Floating Over Right Edge)
        self.quick_add = QuickAddZone(self, self)
        self.quick_add.show()
        self.quick_add.raise_()
        
        # Floating Control Panel (Independent Overlay)
        self.scale_control = FloatingScaleControl(self)
        self.header_toggle = FloatingHeaderToggle(self)
        self.header_toggle.toggled.connect(self.toggle_headers)
        self.fracture_panel = FracturePickingPanel(self)
        self.fracture_panel.hide()
        
        self.scale_control.raise_()
        self.header_toggle.raise_()
        self.fracture_panel.raise_()
        
        self.container = QWidget()
        self.scroll_area.setWidget(self.container)
        
        # Apply floating scrollbar to horizontal scroll area
        from scripts.ui.floating_scrollbar import FloatingScrollbarManager
        self.h_sb_mgr = FloatingScrollbarManager(self.scroll_area)
        
        # Move initial theme application to the end of __init__
        
        self.container_layout = QHBoxLayout(self.container)
        self.container_layout.setContentsMargins(10, 0, 0, 0)
        self.container_layout.setSpacing(0)
        
        # [MODULE] ScrollManager handles all depth/scroll/viewport logic
        self.scroll_mgr = ScrollManager(self)
        from .drop_controller import DataDropController
        from .selection_controller import TrackSelectionController
        self.drop_controller = DataDropController(self)
        self.selection_controller = TrackSelectionController(self)
        
        # [OPTIMIZATION] Connect horizontal scroll to refresh viewport freezing
        self.scroll_area.horizontalScrollBar().valueChanged.connect(self.scroll_mgr.on_horizontal_scroll)

        # Left Divider Line (at the edge of the 30px margin)
        self.left_divider = QFrame()
        self.left_divider.setFrameShape(QFrame.VLine)
        self.left_divider.setFrameShadow(QFrame.Plain)
        self.left_divider.setFixedWidth(2)
        self.left_divider.setStyleSheet(f"background-color: {app_config.get_theme_color('track_divider')}; border: none;")
        self.left_divider.hide() # Initial hidden
        self.container_layout.addWidget(self.left_divider)
        
        # QSplitter - Seamless layout
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(2)  # Remove gap between tracks
        self.splitter.setChildrenCollapsible(False) 
        self.splitter.splitterMoved.connect(self.scroll_mgr._on_splitter_moved)
        splitter_color = app_config.get_theme_color("track_divider")
        accent_color = app_config.get_theme_color("accent")
        self.splitter.setStyleSheet(f"""
            QSplitter::handle {{
                background-color: {splitter_color}; /* 明显的对比色分割线 */
                width: 2px;
            }}
            QSplitter::handle:hover {{
                background-color: {accent_color}; /* 鼠标悬停时变色，提示可拖动 */
            }}
        """)
        self.container_layout.addWidget(self.splitter)
        
        # Spacer for empty space (To prevent tracks expanding)
        self.spacer = TrackSpacer()
        self.splitter.addWidget(self.spacer)
        
        # Initial Stretch: Spacer=1
        self.splitter.setStretchFactor(0, 1)
        
        # Scrollbar with custom styling (Floating Overlay)
        self.v_scrollbar = QScrollBar(Qt.Vertical, self) # Parent is self, not in layout
        self.v_scrollbar.setRange(0, 10000)
        self.v_scrollbar.valueChanged.connect(self.scroll_mgr.on_scrollbar_moved)
        
        self.last_scroll_time = 0
        self.scroll_timer = QTimer(self)
        self.scroll_timer.setSingleShot(True)
        self.scroll_timer.timeout.connect(self.scroll_mgr._on_scroll_settled)
        self.loading_status_timer = QTimer(self)
        self.loading_status_timer.setSingleShot(True)
        self.loading_status_timer.timeout.connect(self.drop_controller.do_check_loading_status)
        
        # [STATE] Viewport Tracking
        self.last_y_min = -9999.0
        self.last_y_max = -9999.0
        self.current_h_scale = 1.0
        self.updating_scroll = False
        self._in_apply_depth_range = False
        self._track_x_cache = {}
        self._track_x_cache_dirty = True
        sb_color = app_config.get_theme_color("scrollbar_handle")
        self.v_scrollbar.setStyleSheet(f"""
            QScrollBar:vertical {{
                border: none;
                background: transparent;
                width: 14px;
                margin: 0px 0px 0px 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {sb_color};
                min-height: 20px;
                border-radius: 7px;
                border: 1px solid rgba(255, 255, 255, 120); /* Light border for contrast */
                margin: 2px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
                background: none;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
        """)
        
        # Opacity Effect for auto-hide
        self.sb_opacity = QGraphicsOpacityEffect(self.v_scrollbar)
        self.sb_opacity.setOpacity(0.0) # Start hidden
        self.v_scrollbar.setGraphicsEffect(self.sb_opacity)
        
        # Animation
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        self.sb_anim = QPropertyAnimation(self.sb_opacity, b"opacity")
        self.sb_anim.setDuration(200)
        self.sb_anim.setEasingCurve(QEasingCurve.InOutQuad)
        
        self.setAcceptDrops(True)
        self.updating_scroll = False
        # Global Range - None until first data is loaded
        self.global_min_depth = None
        self.global_max_depth = None

        self.SCROLL_PRECISION = 100 # Multiplier to support fractional depth scrolling (cm precision)
        self.enable_hard_slicing = True # [RE-ENABLED] Performance Toggle - User requested revert with improvements
        self.fracture_picking_enabled = False
        self.fracture_pick_type = "Conductive"
        self.active_fracture_track = None
        self.fracture_target_track = None
        
        # Use a per-plot thread pool so one window's template/image work
        # cannot starve unrelated plot windows via the global pool.
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(2) # Prevent IO bottleneck
        
        # Initial theme application (Must be at the end to ensure scroll_mgr exists)
        self.update_theme()

    def set_db_source(self, db_or_path):
        """Synchronize the active DBManager and db_path for this plot window."""
        if isinstance(db_or_path, str):
            self.db = DBManager(db_or_path, ensure_schema=False)
        else:
            self.db = db_or_path
        self.db_path = getattr(self.db, 'db_path', None)

    # ─── [DELEGATED] Scroll/Depth methods → ScrollManager ───

    # --- Controller Delegators ---
    def dragEnterEvent(self, event):
        self.drop_controller.dragEnterEvent(event)

    def dropEvent(self, event):
        self.drop_controller.dropEvent(event)

    def sync_track_list(self):
        self.selection_controller.sync_track_list()

    def deselect_all_tracks(self):
        self.selection_controller.deselect_all_tracks()

    def on_track_selection_changed(self):
        self.selection_controller.on_track_selection_changed()

    def create_new_track(self, *args, **kwargs):
        return self.drop_controller.create_new_track(*args, **kwargs)

    def add_curve_to_track(self, *args, **kwargs):
        return self.drop_controller.add_curve_to_track(*args, **kwargs)

    def async_fetch_data(self, *args, **kwargs):
        self.drop_controller.async_fetch_data(*args, **kwargs)

    def _invalidate_track_x_cache(self):
        self.scroll_mgr._invalidate_track_x_cache()

    def apply_depth_range(self, *a, **kw):
        self.scroll_mgr.apply_depth_range(*a, **kw)

    def on_depth_range_changed(self, _, y_range):
        self.scroll_mgr.on_depth_range_changed(_, y_range)

    def wheelEvent(self, event):
        self.scroll_mgr.wheelEvent(event)

    def set_horizontal_scale(self, factor):
        self.scroll_mgr.set_horizontal_scale(factor)

    def set_vertical_scale(self, scale_val):
        self.scroll_mgr.set_vertical_scale(scale_val)

    def force_image_refresh(self):
        if hasattr(self, 'scroll_mgr'):
            self.scroll_mgr.force_image_refresh()

    def on_image_slice_ready(self, *a, **kw):
        self.scroll_mgr.on_image_slice_ready(*a, **kw)












    def update_depth_limits(self, depth):
        self.scroll_mgr.update_depth_limits(depth)

    def set_custom_depth_limits(self, d_start, d_end):
        self.scroll_mgr.set_custom_depth_limits(d_start, d_end)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._invalidate_track_x_cache()
        
        if hasattr(self, 'v_scrollbar'):
            sb_w = 14 
            self.v_scrollbar.setGeometry(self.width() - sb_w, 0, sb_w, self.height())
            self.v_scrollbar.raise_()
            
        if hasattr(self, 'scale_control'):
            w = self.scale_control.width()
            h = self.scale_control.height()
            self.scale_control.move(22, self.height() - h - 5)
            self.scale_control.raise_()
            
        if hasattr(self, 'header_toggle'):
            self.header_toggle.move(0, 0)
            self.header_toggle.raise_()

        if hasattr(self, 'quick_add'):
            qa_w = self.quick_add.width()
            sb_w = 14 
            self.quick_add.setGeometry(self.width() - qa_w - sb_w, 0, qa_w, self.height())
            self.quick_add.show()
            self.quick_add.raise_()

        if hasattr(self, 'fracture_panel'):
            if hasattr(self.fracture_panel, 'fit_to_parent'):
                self.fracture_panel.fit_to_parent()
            if not getattr(self.fracture_panel, '_user_moved', False):
                self.fracture_panel.reset_position()
            if getattr(self, 'fracture_picking_enabled', False) and self._is_active_mdi_widget():
                self.fracture_panel.show()
                self.fracture_panel.raise_()
            else:
                self.fracture_panel.hide()

    def showEvent(self, event):
        super().showEvent(event)
        self._ensure_mdi_activation_hook()
        self._sync_fracture_panel_visibility()

    def hideEvent(self, event):
        if hasattr(self, 'fracture_panel'):
            self.fracture_panel.hide()
        super().hideEvent(event)

    def event(self, event):
        result = super().event(event)
        if event.type() in (QEvent.WindowActivate, QEvent.WindowDeactivate):
            self._sync_fracture_panel_visibility()
        return result

    def _is_active_mdi_widget(self):
        window = self.window()
        mdi_area = getattr(window, 'mdi_area', None)
        if mdi_area is None:
            return self.isVisible()
        active_sub = mdi_area.activeSubWindow()
        return bool(active_sub and active_sub.widget() is self and self.isVisible())

    def _ensure_mdi_activation_hook(self):
        if getattr(self, '_fracture_mdi_hooked', False):
            return
        window = self.window()
        mdi_area = getattr(window, 'mdi_area', None)
        if mdi_area is None:
            return
        try:
            mdi_area.subWindowActivated.connect(self._on_mdi_subwindow_activated)
            self._fracture_mdi_hooked = True
        except Exception:
            pass

    def _on_mdi_subwindow_activated(self, sub_window):
        if hasattr(self, 'fracture_panel') and (sub_window is None or sub_window.widget() is not self):
            self.fracture_panel.hide()
        self._sync_fracture_panel_visibility()

    def _sync_fracture_panel_visibility(self):
        if not hasattr(self, 'fracture_panel'):
            return
        if getattr(self, 'fracture_picking_enabled', False) and self._is_active_mdi_widget():
            self.fracture_panel.show()
            self.fracture_panel.raise_()
        else:
            self.fracture_panel.hide()

    def open_dialog(self, dlg):
        """Manage single active modeless dialog."""
        last_pos = None
        if self.current_settings_dialog:
            try:
                if self.current_settings_dialog.isVisible():
                    last_pos = self.current_settings_dialog.pos()
                self.current_settings_dialog.close()
            except RuntimeError:
                pass
        
        self.current_settings_dialog = dlg
        dlg.finished.connect(self._clear_dialog_ref)
        
        if last_pos:
            dlg.move(last_pos)
            
        dlg.show()
        dlg.raise_()
        
    def _clear_dialog_ref(self):
        self.current_settings_dialog = None

    def enterEvent(self, event):
        super().enterEvent(event)
        if hasattr(self, 'sb_anim'):
            self.sb_anim.stop()
            self.sb_anim.setStartValue(self.sb_opacity.opacity())
            self.sb_anim.setEndValue(1.0)
            self.sb_anim.start()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if hasattr(self, 'sb_anim'):
            self.sb_anim.stop()
            self.sb_anim.setStartValue(self.sb_opacity.opacity())
            self.sb_anim.setEndValue(0.0)
            self.sb_anim.start()

    def _add_track_to_layout(self, track, index=None, width=200):
        """Helper to insert a track into the splitter and manage sizes/factors."""
        track.base_width = width 
        scaled_width = int(width * getattr(self, 'current_h_scale', 1.0))
        current_sizes = self.splitter.sizes()
        spacer_idx_old = self.splitter.indexOf(self.spacer)
        
        if index is not None:
            self.splitter.insertWidget(index, track)
        else:
            self.splitter.insertWidget(spacer_idx_old, track)
            
        # [NEW] Connect selection signal
        track.selectionChanged.connect(self.on_track_selection_changed)
        
        # [NEW DECOUPLE] Connect resizing to scroll manager via signal
        if hasattr(track.plot_widget, 'viewResized'):
            # [FIX] Sync to current view range before connecting to prevent initial value pollution (starting from 0)
            master_vb = self.get_master_viewbox()
            if master_vb:
                _, (y_min, y_max) = master_vb.viewRange()
                track.plot_widget.setYRange(y_min, y_max, padding=0)
            
            track.plot_widget.viewResized.connect(
                lambda min_y, max_y, t=track: self.scroll_mgr.apply_depth_range(min_y, max_y, only_track=t)
            )
            
        new_track_idx = self.splitter.indexOf(track)
        self.splitter.setCollapsible(new_track_idx, False)
        self.splitter.setStretchFactor(new_track_idx, 0)
        if getattr(self, "fracture_picking_enabled", False) and hasattr(track, "set_fracture_pick_enabled"):
            track.set_fracture_pick_enabled(True)
        
        new_sizes = []
        MIN_SPACER_W = 60
        
        for i, s in enumerate(current_sizes):
            if i == spacer_idx_old:
                new_sizes.append(scaled_width)
                new_sizes.append(max(MIN_SPACER_W, s - scaled_width))
            else:
                new_sizes.append(s)
                
        if hasattr(self, 'left_divider'):
            self.left_divider.show()

        self._sync_container_width(new_sizes)
        self.splitter.setSizes(new_sizes)
        
        if self.global_min_depth is not None and self.global_max_depth is not None:
            if hasattr(track.plot_widget, 'getViewBox'):
                vb = track.plot_widget.getViewBox()
                if vb:
                    vb.setLimits(yMin=self.global_min_depth, yMax=self.global_max_depth)
        
        for i in range(self.splitter.count()):
            w = self.splitter.widget(i)
            self.splitter.setStretchFactor(i, 1 if isinstance(w, TrackSpacer) else 0)
        
        self.sync_track_list()
        self.sync_header_heights()
        self._invalidate_track_x_cache()
        self.refresh_fracture_target_tracks()

    def closeEvent(self, event):
        """Cleanup when plot window is closed."""
        if hasattr(self, 'sb_anim'):
            self.sb_anim.stop()
        if hasattr(self, 'scroll_timer'):
            self.scroll_timer.stop()
        if hasattr(self, 'loading_status_timer'):
            self.loading_status_timer.stop()
        if hasattr(self, 'scroll_mgr'):
            try:
                self.scroll_mgr._image_debounce_timer.stop()
            except Exception:
                pass
            try:
                self.scroll_mgr._pending_tile_requests.clear()
            except Exception:
                pass
        if hasattr(self, 'active_image_workers'):
            self.active_image_workers.clear()
        if hasattr(self, 'thread_pool'):
            try:
                self.thread_pool.clear()
            except Exception:
                pass
            try:
                self.thread_pool.waitForDone(200)
            except Exception:
                pass
        if self.current_settings_dialog:
            self.current_settings_dialog.close()
            self.current_settings_dialog = None
        for track in list(self.track_containers):
            try:
                if hasattr(track, 'cleanup'):
                    track.cleanup()
            except Exception:
                pass
        self.track_containers.clear()
        super().closeEvent(event)

    def set_skip_finite_check(self, enabled):
        """Update the skipFiniteCheck optimization flag for all curves."""
        self.skip_finite_check = enabled
        for track in self.track_containers:
            for curve_entry in track.plot_widget.curves:
                if not curve_entry.get('is_image') and curve_entry.get('item'):
                    curve_entry['item'].setSkipFiniteCheck(enabled)
                    curve_entry['item'].update()

    def toggle_headers(self, hidden):
        """Toggle visibility of all track headers."""
        for t in self.track_containers:
            if hasattr(t, 'header'):
                t.header.setVisible(not hidden)
                
    def scroll_to_right(self):
        """Scroll horizontal scrollbar to the maximum right."""
        sb = self.scroll_area.horizontalScrollBar()
        sb.setValue(sb.maximum())

    def set_fracture_picking_enabled(self, enabled):
        self.fracture_picking_enabled = bool(enabled)
        self.refresh_fracture_target_tracks()
        self._ensure_mdi_activation_hook()
        if self.fracture_picking_enabled:
            self._sync_fracture_panel_visibility()
            self._show_fracture_status("Fracture picking: left-click image points, Space/Enter to finish, Esc to cancel.")
        else:
            self.cancel_current_fracture_pick(show_message=False)
            self._sync_fracture_panel_visibility()
            self._show_fracture_status("Fracture picking disabled.")
        for track in self.track_containers:
            if hasattr(track, "set_fracture_pick_enabled"):
                track.set_fracture_pick_enabled(self.fracture_picking_enabled)

    def toggle_fracture_picking(self):
        self.set_fracture_picking_enabled(not self.fracture_picking_enabled)

    def set_fracture_pick_type(self, fracture_type):
        self.fracture_pick_type = fracture_type if fracture_type in FRACTURE_TYPE_STYLES else "Conductive"
        if self.active_fracture_track and hasattr(self.active_fracture_track, "refresh_fracture_preview_style"):
            self.active_fracture_track.refresh_fracture_preview_style()

    def get_fracture_pick_style(self):
        style = FRACTURE_TYPE_STYLES.get(self.fracture_pick_type, FRACTURE_TYPE_STYLES["Conductive"])
        return {
            "fracture_type": self.fracture_pick_type,
            "color": style["color"],
            "line_width": 2.0,
        }

    def _image_tracks_for_fracture_display(self):
        return [
            track for track in self.track_containers
            if isinstance(track, ImageTrackContainer) and getattr(track.plot_widget, "curves", None)
        ]

    def _fracture_track_label(self, track):
        if not track:
            return "Auto"
        track_name = getattr(track, "track_name", None)
        image_curve = next((c for c in getattr(track.plot_widget, "curves", []) if c.get("is_image")), None)
        curve_name = None
        if image_curve:
            info = image_curve.get("info", {})
            curve_name = info.get("title") or info.get("name")
        if track_name and curve_name and track_name != curve_name:
            return f"{track_name} / {curve_name}"
        return curve_name or track_name or "Image Track"

    def refresh_fracture_target_tracks(self):
        tracks = self._image_tracks_for_fracture_display()
        if self.fracture_target_track not in tracks:
            self.fracture_target_track = tracks[0] if tracks else None
        labels = [self._fracture_track_label(track) for track in tracks]
        current_index = tracks.index(self.fracture_target_track) if self.fracture_target_track in tracks else 0
        if hasattr(self, "fracture_panel"):
            self.fracture_panel.set_target_tracks(labels or ["No image tracks"], current_index)

    def set_fracture_target_track_index(self, index):
        tracks = self._image_tracks_for_fracture_display()
        if 0 <= index < len(tracks):
            self.fracture_target_track = tracks[index]
            self._show_fracture_status(f"Fractures will display on: {self._fracture_track_label(self.fracture_target_track)}")

    def get_fracture_display_track(self, fallback=None):
        tracks = self._image_tracks_for_fracture_display()
        if self.fracture_target_track in tracks:
            return self.fracture_target_track
        if fallback in tracks:
            self.fracture_target_track = fallback
            self.refresh_fracture_target_tracks()
            return fallback
        self.fracture_target_track = tracks[0] if tracks else None
        self.refresh_fracture_target_tracks()
        return self.fracture_target_track

    def set_active_fracture_track(self, track):
        if self.active_fracture_track is not track:
            if self.active_fracture_track and hasattr(self.active_fracture_track, "cancel_fracture_pick"):
                self.active_fracture_track.cancel_fracture_pick(show_message=False)
            self.active_fracture_track = track

    def finish_current_fracture_pick(self):
        if self.active_fracture_track and hasattr(self.active_fracture_track, "finish_fracture_pick"):
            return self.active_fracture_track.finish_fracture_pick(continue_picking=True)
        self._show_fracture_status("Click points on an image track before finishing a fracture.")
        return False

    def cancel_current_fracture_pick(self, show_message=True):
        if self.active_fracture_track and hasattr(self.active_fracture_track, "cancel_fracture_pick"):
            self.active_fracture_track.cancel_fracture_pick(show_message=show_message)
        self.active_fracture_track = None

    def undo_current_fracture_pick_point(self):
        if self.active_fracture_track and hasattr(self.active_fracture_track, "undo_fracture_pick_point"):
            self.active_fracture_track.undo_fracture_pick_point()

    def delete_selected_fractures(self):
        total = 0
        for track in self.track_containers:
            if hasattr(track, "delete_selected_fractures"):
                total += track.delete_selected_fractures()
        if total:
            self._show_fracture_status(f"Deleted {total} selected fracture(s).")
        else:
            self._show_fracture_status("Select fracture lines before deleting.")
        return total

    def clear_fracture_selection(self):
        for track in self.track_containers:
            if hasattr(track, "clear_fracture_selection"):
                track.clear_fracture_selection()

    def clear_fracture_annotations(self):
        for track in self.track_containers:
            if hasattr(track, "clear_fracture_annotations"):
                track.clear_fracture_annotations()
        self.cancel_current_fracture_pick(show_message=False)
        self._show_fracture_status("Fracture picks cleared.")

    def collect_fracture_annotations(self):
        annotations = []
        for track in self.track_containers:
            track_annotations = getattr(track, "fracture_annotations", None)
            if not track_annotations:
                continue
            track_label = self._fracture_track_label(track)
            image_curve = next((c for c in getattr(track.plot_widget, "curves", []) if c.get("is_image")), None)
            image_info = image_curve.get("info", {}) if image_curve else {}
            depth_unit = ""
            if getattr(track.plot_widget, "curves", None):
                depth_unit = track.plot_widget.curves[0].get("info", {}).get("depth_unit", "")
            for annotation in track_annotations:
                if not isinstance(annotation, dict):
                    continue
                item = enrich_fracture_interpretation(annotation)
                item.setdefault("source_track_label", track_label)
                item.setdefault("target_track_label", track_label)
                item.setdefault("source_curve_id", image_info.get("curve_id"))
                item.setdefault("source_curve_name", image_info.get("title") or image_info.get("name"))
                item.setdefault("depth_unit", depth_unit)
                annotations.append(item)
        return annotations

    def _infer_fracture_well_id(self):
        for track in self.track_containers:
            for curve in getattr(track.plot_widget, "curves", []):
                info = curve.get("info", {})
                if info.get("well_id") is not None:
                    return int(info.get("well_id"))
        try:
            wells = self.db.get_wells() if self.db else []
            if len(wells) == 1:
                return int(wells[0][0])
        except Exception:
            pass
        return None

    def save_fracture_results(self):
        well_id = self._infer_fracture_well_id()
        annotations = self.collect_fracture_annotations()
        db_path = getattr(self.db, "db_path", None)
        if not db_path:
            self._show_fracture_status("Cannot save fractures: no database path found.")
            return []
        if well_id is None:
            self._show_fracture_status("Cannot save fractures: no well context found.")
            return []
        if not annotations:
            self._show_fracture_status("No fracture results to save.")
            return []
        db = DBManager(db_path)
        inserted = db.save_fracture_interpretations(well_id, annotations, replace=True)
        self._show_fracture_status(f"Saved {len(inserted)} fracture result(s).")
        return inserted

    def load_fracture_results(self):
        well_id = self._infer_fracture_well_id()
        db_path = getattr(self.db, "db_path", None)
        if not db_path:
            self._show_fracture_status("Cannot load fractures: no database path found.")
            return []
        if well_id is None:
            self._show_fracture_status("Cannot load fractures: no well context found.")
            return []
        db = DBManager(db_path)
        annotations = db.get_fracture_interpretations(well_id)
        if not annotations:
            self._show_fracture_status("No saved fracture results found.")
            return []
        target_track = self.get_fracture_display_track()
        if target_track is None:
            self._show_fracture_status("Cannot load fractures: no image target track.")
            return []
        for track in self.track_containers:
            if hasattr(track, "clear_fracture_annotations"):
                track.clear_fracture_annotations()
        by_label = {self._fracture_track_label(track): track for track in self._image_tracks_for_fracture_display()}
        for annotation in annotations:
            track = by_label.get(annotation.get("target_track_label")) or target_track
            track.add_fracture_annotation(annotation)
        self._show_fracture_status(f"Loaded {len(annotations)} fracture result(s).")
        return annotations

    def show_fracture_results(self):
        from ..ui.dialogs.fracture_results_dialog import FractureResultsDialog

        existing = getattr(self, "fracture_results_dialog", None)
        if existing is not None and existing.isVisible():
            existing.refresh()
            existing.raise_()
            existing.activateWindow()
            return existing
        self.fracture_results_dialog = FractureResultsDialog(self, self.window())
        self.fracture_results_dialog.show()
        self.fracture_results_dialog.raise_()
        self.fracture_results_dialog.activateWindow()
        return self.fracture_results_dialog

    def _show_fracture_status(self, message):
        try:
            window = self.window()
            status_bar = window.statusBar() if window and hasattr(window, "statusBar") else None
            if status_bar:
                status_bar.showMessage(message, 5000)
        except Exception:
            pass

    def sync_header_heights(self):
        """Find max required header height and apply to all tracks."""
        max_h = 0
        tracks = []
        for i in range(self.splitter.count()):
            w = self.splitter.widget(i)
            if hasattr(w, 'header'):
                tracks.append(w)
                h_widget = w.header
                if not h_widget.is_auto_height:
                    max_h = max(max_h, h_widget.height())
                else:
                    n = len(h_widget.items)
                    needed = max(h_widget.base_row_height, n * h_widget.base_row_height)
                    max_h = max(max_h, needed)
        
        if max_h > 0:
            for t in tracks:
                if t.header.height() != max_h:
                    t.header.setFixedHeight(max_h)
                    t.header.update() 

    def add_depth_track(self, index=None):
        """Add a special PainterDepthTrack for manual scale drawing."""
        track = DepthTrackContainer(self)
        track.track_name = "Depth"
        track.header.set_title("Depth")
        track.header.set_unit("m")
        track.header.set_range_visible(False)
        
        if hasattr(self, 'header_toggle'):
            track.header.setVisible(not self.header_toggle.isChecked())
            
        track.resize(60, track.height()) 
        track.setMinimumWidth(60)       
        self._add_track_to_layout(track, index=index, width=60)
        
        for i in range(self.splitter.count()):
            w = self.splitter.widget(i)
            self.splitter.setStretchFactor(i, 1 if isinstance(w, TrackSpacer) else 0)

    def add_empty_track(self, index=None):
        """Add an empty standard curve track with no curves."""
        self.create_track_from_state({"type": "data"}, index=index)

    def create_track_from_state(self, track_state, index=None):
        """Build and insert a track container from saved/basic state."""
        t_type = track_state.get("type", "data")
        width = track_state.get("base_width", track_state.get("width", 200))

        if t_type == "depth":
            track = DepthTrackContainer(self)
            track.track_name = track_state.get("name") or "Depth"
            track.header.set_title(track_state.get("name", "Depth"))
            track.header.set_unit(track_state.get("unit", "m"))
            track.header.set_range_visible(False)

            if hasattr(self, 'header_toggle'):
                default_visible = not self.header_toggle.isChecked()
                track.header.setVisible(track_state.get("header_visible", default_visible))

            track.resize(60, track.height())
            track.setMinimumWidth(60)
            self._add_track_to_layout(track, index=index, width=60)
        else:
            is_accum = track_state.get("is_accum_fill", False)
            has_image = any(c.get("is_image", False) for c in track_state.get("curves", []))
            if is_accum:
                from ..tracks.track_container import AccumulativeTrackContainer
                track = AccumulativeTrackContainer(self)
            elif has_image:
                track = ImageTrackContainer(self)
            else:
                track = CurveTrackContainer(self)

            track.track_name = track_state.get("name")
            if hasattr(self, 'header_toggle'):
                default_visible = not self.header_toggle.isChecked()
                track.header.setVisible(track_state.get("header_visible", default_visible))

            self._add_track_to_layout(track, index=index, width=width)

        for i in range(self.splitter.count()):
            w = self.splitter.widget(i)
            self.splitter.setStretchFactor(i, 1 if isinstance(w, TrackSpacer) else 0)

        return track

    def apply_track_state(self, track, track_state):
        """Apply persisted track-level settings to an existing track."""
        if not track or not track_state:
            return

        settings = dict(track_state)
        settings.setdefault("width", track_state.get("base_width", track.width()))
        settings.setdefault("name", getattr(track, "track_name", None) or "")

        if hasattr(track, "apply_track_settings"):
            track.apply_track_settings(settings)

        if hasattr(track, 'header') and hasattr(self, 'header_toggle'):
            default_visible = not self.header_toggle.isChecked()
            track.header.setVisible(track_state.get("header_visible", default_visible))

    def schedule_initial_scale_update(self):
        """Run the same default first-frame scale initialization used by manual plotting."""
        if self._initial_scale_update_applied:
            return
        if self._pending_initial_scale_update:
            return

        self._pending_initial_scale_update = True

        def _apply():
            self._pending_initial_scale_update = False
            if not hasattr(self, 'scale_control'):
                return
            try:
                if hasattr(self.scale_control, 'block_auto') and hasattr(self.scale_control, 'combo'):
                    self.scale_control.block_auto = True
                    self.scale_control.combo.setCurrentText("1:50")
                    self.scale_control.block_auto = False
                self.scale_control.update_scale()
                self._initial_scale_update_applied = True
            except Exception:
                pass

        QTimer.singleShot(50, _apply)
        
    def get_master_viewbox(self):
        """Find the first legitimate plot widget ViewBox to act as master."""
        for track in self.track_containers:
            if isinstance(track.plot_widget, InteractivePlotWidget):
                return track.plot_widget.plotItem.vb
        return None
        


    def _sync_container_width(self, sizes=None):
        """Update container minimum width to match splitter sizes."""
        if hasattr(self, 'container') and hasattr(self, 'splitter'):
            if sizes is None:
                sizes = self.splitter.sizes()
            self.container.setMinimumWidth(sum(sizes))
            

    def get_plot_details(self):
        """[NEW] Return a structured summary of all tracks and curves in this plot."""
        details = {
            'window_title': self.windowTitle(),
            'well_name': self.windowTitle().replace("Plot: ", "").replace("Log Plot ", ""),
            'tracks': []
        }
        
        for track in self.track_containers:
            # [NEW] Prioritize custom track name (Track 1, Track 2...)
            track_name = getattr(track, 'track_name', None)
            if not track_name:
                if hasattr(track, 'header') and track.header.items:
                    h_item = track.header.items[0]
                    track_name = h_item.get('title') or h_item.get('name') or "Track"
                else:
                    track_name = "Track"
            
            track_info = {
                'name': track_name,
                'curves': []
            }
            if hasattr(track, 'plot_widget') and hasattr(track.plot_widget, 'curves'):
                for c in track.plot_widget.curves:
                    c_info = c.get('info', {})
                    c_name = c_info.get('title') or c_info.get('name') or "Unknown"
                    track_info['curves'].append({
                        'name': c_name,
                        'folder': c_info.get('folder'),
                        'unit': c_info.get('unit', ''),
                        'min': c_info.get('min', 0),
                        'max': c_info.get('max', 100)
                    })
            details['tracks'].append(track_info)
        return details

    # --- [EXPORT] Delegated to LogExporter ---
    def export_plot(self):
        """Launch the Advanced Export Dialog (delegated to LogExporter)."""
        LogExporter(self).launch_export()

    def get_state(self):
        """Extract overall plot state for template saving."""
        state = {
            "version": "1.0",
            "h_scale": getattr(self, 'current_h_scale', 1.0),
            "custom_min_depth": getattr(self, 'custom_min_depth', None),
            "custom_max_depth": getattr(self, 'custom_max_depth', None),
            "tracks": []
        }
        for track in self.track_containers:
            state["tracks"].append(track.get_state())
        return state

    def update_theme(self):
        """Update overall plot area theme, handles, and propagate to all tracks."""
        bg = app_config.get_theme_color('plot_bg')
        divider = app_config.get_theme_color('track_divider')
        accent = app_config.get_theme_color('accent')
        sb_color = app_config.get_theme_color("scrollbar_handle")
        is_dark = app_config.get_theme_name() != "Light"
        
        # Backgrounds
        self.scroll_area.setStyleSheet(f"background-color: {bg}; border: none;")
        self.container.setStyleSheet(f"background-color: {bg};")
        
        # Divider (Left)
        if hasattr(self, 'left_divider'):
            self.left_divider.setStyleSheet(f"background-color: {divider}; border: none;")
            
        # Splitter handles
        if hasattr(self, 'splitter'):
            self.splitter.setStyleSheet(f"""
                QSplitter::handle {{
                    background-color: {divider};
                }}
                QSplitter::handle:hover {{
                    background-color: {accent};
                }}
            """)
            
        # Main Vertical Scrollbar
        if hasattr(self, 'v_scrollbar'):
            border_alpha = 120 if is_dark else 30
            border_color = f"rgba(255, 255, 255, {border_alpha})" if is_dark else f"rgba(0, 0, 0, {border_alpha})"
            
            self.v_scrollbar.setStyleSheet(f"""
                QScrollBar:vertical {{
                    border: none;
                    background: transparent;
                    width: 14px;
                    margin: 0px;
                }}
                QScrollBar::handle:vertical {{
                    background: {sb_color};
                    min-height: 20px;
                    border-radius: 7px;
                    border: 1px solid {border_color};
                    margin: 2px;
                }}
                QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                    height: 0px;
                    background: none;
                }}
                QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                    background: none;
                }}
            """)
            
        # Floating Scrollbar (Horizontal)
        if hasattr(self, 'h_sb_mgr'):
            self.h_sb_mgr.update_theme()

        if hasattr(self, 'fracture_panel'):
            self.fracture_panel.update_theme()
            
        # Propagate to all sub-tracks
        for track in getattr(self, 'track_containers', []):
            if hasattr(track, 'update_theme'):
                track.update_theme()
                
        # [NEW] Force image refresh to apply theme-aware LUT (Null Color: Auto)
        self.force_image_refresh()
                
        self.update()

    def remove_track(self, container):
        """Safely remove a track and sync layout."""
        if container in self.track_containers:
            self.track_containers.remove(container)
            if hasattr(container, 'cleanup'):
                container.cleanup()
            container.setParent(None)
            container.deleteLater()
            has_data_tracks = any(
                isinstance(getattr(track, 'plot_widget', None), InteractivePlotWidget)
                for track in self.track_containers
            )
            if not has_data_tracks:
                self._pending_initial_scale_update = False
                self._initial_scale_update_applied = False
            self.sync_track_list()
            self._sync_container_width()
            self._invalidate_track_x_cache()
            self.refresh_fracture_target_tracks()

    def replace_track(self, old_track, new_track):
        """[PHASE 9] Replace a track container in place (used for morphing Curve -> Image track)."""
        idx = self.splitter.indexOf(old_track)
        if idx < 0: return
        
        # [BUGFIX] Capture Y-range before deleting old track to maintain scale
        y_min, y_max = 0, 10
        if hasattr(old_track.plot_widget, 'getViewBox'):
            vb_old = old_track.plot_widget.getViewBox()
            if vb_old:
                _, (y_min, y_max) = vb_old.viewRange()

        w = old_track.width()
        old_track.setParent(None)
        old_track.deleteLater()
        
        self.splitter.insertWidget(idx, new_track)
        new_track.base_width = getattr(old_track, 'base_width', 200)
        
        # [BUGFIX] Apply captured Y-range to the new track
        if hasattr(new_track.plot_widget, 'getViewBox'):
            vb_new = new_track.plot_widget.getViewBox()
            if vb_new:
                vb_new.setYRange(y_min, y_max, padding=0)

        sizes = self.splitter.sizes()
        sizes[idx] = w
        self.splitter.setSizes(sizes)
        
        new_track.selectionChanged.connect(self.on_track_selection_changed)
        self.sync_track_list()
        self.sync_header_heights()
        self._invalidate_track_x_cache()
        self.refresh_fracture_target_tracks()
