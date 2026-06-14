from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt, QTimer, QObject, QMimeData, QPoint
from core.app_config import app_config
from ..utils.logger import logger
from ..utils.plot_style_utils import DEFAULT_IMAGE_CMAP, DEFAULT_NULL_COLOR
from ..utils.workers import DataFetchWorker
from ..tracks.track_container import BaseTrackContainer, CurveTrackContainer, ImageTrackContainer
from .track_widgets import InteractivePlotWidget

class DataDropController(QObject):
    """Handles drag/drop operations and asynchronous database fetching for LogWidget."""
    def __init__(self, log_widget):
        super().__init__(log_widget)
        self.log_widget = log_widget

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"):
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        raw_data = event.mimeData().data("application/x-pylog-curve").data().decode('utf-8')
        try:
            items = raw_data.split('|') if '|' in raw_data else [raw_data]
            target = self.get_target_container(event.pos())
            
            for item in items:
                if not item: continue
                parts = item.split(':')
                if len(parts) >= 3:
                    well_id, curve_id = int(parts[0]), int(parts[1])
                    db_path = parts[2]
                else:
                    well_id, curve_id = map(int, parts)
                    db_path = None
                
                if target:
                    self.add_curve_to_track(target, well_id, curve_id, db_path=db_path)
                else:
                    self.create_new_track(well_id, curve_id, db_path=db_path)
        except Exception as e:
            print(f"Drop Error: {e}")

    def get_target_container(self, pos):
        lw = self.log_widget
        p = lw.splitter.mapFromGlobal(lw.mapToGlobal(pos))
        child = lw.splitter.childAt(p)
        while child:
            # [FIX] Prohibit dropping curves directly onto the Depth track
            if child.__class__.__name__ == 'DepthTrackContainer': return None
            if isinstance(child, BaseTrackContainer): return child
            if child.__class__.__name__ == 'TrackSpacer': return None
            child = child.parent()
        return None

    def add_curve_to_track(self, container, well_id, curve_id, db_path=None):
        self.async_fetch_data(well_id, curve_id, context=container, db_path=db_path)

    def create_new_track(self, well_id, curve_id, db_path=None):
        lw = self.log_widget
        is_first_track = not lw.track_containers
        if is_first_track:
            lw.add_depth_track(index=0)
            if hasattr(lw, 'scale_control'):
                QTimer.singleShot(50, lw.scale_control.update_scale)
        # [PHASE 9] Default to CurveTrackContainer for placeholder
        container = CurveTrackContainer(lw)
        track_count = sum(1 for t in lw.track_containers if isinstance(t.plot_widget, InteractivePlotWidget))
        container.track_name = f"Track {track_count + 1}"
        if hasattr(lw, 'header_toggle'):
            container.header.setVisible(not lw.header_toggle.isChecked())
            
        lw._add_track_to_layout(container, width=200)
        
        existing = next((t for t in lw.track_containers if isinstance(t.plot_widget, InteractivePlotWidget) and t != container), None)
        if existing:
            (min_y, max_y) = existing.plot_widget.getViewBox().viewRange()[1]
            container.plot_widget.setYRange(min_y, max_y, padding=0)
        
        placeholder_info = {
            'name': 'Loading...', 'unit': '', 'is_image': False,
            'color': app_config.get_theme_color("text_dim"), 'min': 0, 'max': 1
        }
        container.header.add_curve_info(placeholder_info)
        self.async_fetch_data(well_id, curve_id, context=container, db_path=db_path)

    def async_fetch_data(self, well_id, curve_id, context, db_path=None):
        lw = self.log_widget
        lw.setCursor(Qt.WaitCursor)
        if lw.window():
             try: lw.window().statusBar().showMessage(f"Loading curve data (ID:{curve_id})...")
             except: pass

        prefs = {'cmap': DEFAULT_IMAGE_CMAP, 'null_color': DEFAULT_NULL_COLOR}
        db_p = db_path if db_path else lw.db.db_path
        worker = DataFetchWorker(db_p, well_id, curve_id, context, preferences=prefs)
        worker.signals.finished.connect(self.on_data_loaded)
        worker.signals.error.connect(lambda e: QMessageBox.critical(lw, "Error", e))
        
        lw.pending_loads += 1
        self._check_loading_status()
        lw.thread_pool.start(worker)

    def on_data_loaded(self, data, depth, info, context, well_id, curve_id, rgb_full=None):
        lw = self.log_widget
        lw.pending_loads = max(0, lw.pending_loads - 1)

        if data is None: 
            self._check_loading_status()
            return
        lw.update_depth_limits(depth)
        
        if context and isinstance(context, BaseTrackContainer):
            track = context
            track.header.remove_placeholder()
            
            # [PHASE 9: Track Hierarchy] Morph track if it's the wrong type for the data
            is_env_image = info.get('is_image', False) or (data is not None and data.ndim > 1)
            is_track_image = isinstance(track, ImageTrackContainer)
            
            if is_env_image and not is_track_image:
                new_track = ImageTrackContainer(lw)
                new_track.track_name = track.track_name
                if hasattr(lw, 'header_toggle'):
                    new_track.header.setVisible(not lw.header_toggle.isChecked())
                lw.replace_track(track, new_track)
                track = new_track
            elif not is_env_image and is_track_image:
                # [FIX] Do NOT morph an existing ImageTrackContainer into a CurveTrackContainer
                # when receiving 1D data. This allows 1D curves to be overlaid on images.
                pass
            
            c_name = info.get('name')
            if hasattr(track, '_template_curve_settings') and c_name in track._template_curve_settings:
                # [FIX] Pop from the list-based queue to support duplicate mnemonics (dual CAL, etc)
                queue = track._template_curve_settings[c_name]
                if queue:
                    template_cfg = queue.pop(0)
                    for key, val in template_cfg.items():
                        if key not in ['well_id', 'curve_id']:
                            info[key] = val
                    
                    # Cleanup empty lists and the attribute if no more settings remain
                    if not queue: del track._template_curve_settings[c_name]
                    if not track._template_curve_settings: delattr(track, '_template_curve_settings')

            track.add_curve(data, depth, info, rgb_full_bg=rgb_full)
            track.apply_curve_settings(0 if not hasattr(track.plot_widget, 'curves') else len(track.plot_widget.curves)-1, info)
            
            if not hasattr(track, '_template_curve_settings') and track.is_accum_fill:
                track._update_accumulative_fills()
        else:
            self._create_new_track_final(data, depth, info, rgb_full)
            
        self._check_loading_status()

    def _check_loading_status(self):
        self.log_widget.loading_status_timer.start(100)

    def do_check_loading_status(self):
        lw = self.log_widget
        p = lw.pending_loads
        w = len(lw.active_image_workers)
        
        if p > 0 or w > 0: lw.setCursor(Qt.WaitCursor)
        else:
            lw.setCursor(Qt.ArrowCursor)
            if lw.window():
                sb = lw.window().statusBar()
                if sb and "Loading curve data" in sb.currentMessage():
                    sb.showMessage("Ready", 3000)
            lw.loadingFinished.emit()

    def _on_fetch_error(self, message):
        print(f"Fetch Error: {message}")

    def _create_new_track_final(self, data, depth, info, rgb_full=None):
        lw = self.log_widget
        is_env_image = info.get('is_image', False) or (data is not None and data.ndim > 1)
        container = ImageTrackContainer(lw) if is_env_image else CurveTrackContainer(lw)
        container.add_curve(data, depth, info, rgb_full_bg=rgb_full)
        lw._add_track_to_layout(container, width=200)
        
        # [REFACTORED] Sync logic moved to _add_track_to_layout. 
        # Only handle positioning for the VERY FIRST track added to the plot.
        if len(lw.track_containers) <= 1: 
            d_min, d_max = float(depth[0]), float(depth[-1])
            if d_min > d_max: d_min, d_max = d_max, d_min
            container.plot_widget.setYRange(d_min, d_min + 10, padding=0)
            if hasattr(lw, 'scale_control'):
                QTimer.singleShot(50, lw.scale_control.update_scale)
