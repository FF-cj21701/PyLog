from PySide6.QtCore import QObject
from .track_widgets import InteractivePlotWidget, PainterDepthTrack
from ..tracks.track_container import BaseTrackContainer

class TrackSelectionController(QObject):
    """Manages track selection state and bi-directional synchronization with the UI."""
    def __init__(self, log_widget):
        super().__init__(log_widget)
        self.log_widget = log_widget

    def sync_track_list(self):
        """Update track list order and sync scrolling."""
        lw = self.log_widget
        was_blocked = lw.splitter.signalsBlocked()
        lw.splitter.blockSignals(True)
        
        new_list = []
        for i in range(lw.splitter.count()):
            w = lw.splitter.widget(i)
            if isinstance(w, BaseTrackContainer):
                new_list.append(w)
        lw.track_containers = new_list
        
        first_interactive = next((t for t in lw.track_containers if isinstance(t.plot_widget, InteractivePlotWidget)), None)

        master_vb = lw.get_master_viewbox()
        for track in lw.track_containers:
            if isinstance(track.plot_widget, PainterDepthTrack):
                track.plot_widget.sync_with_plot(master_vb)
        
        if not hasattr(lw, '_connected_track') or lw._connected_track != first_interactive:
            if hasattr(lw, '_connected_track') and lw._connected_track:
                try: lw._connected_track.plot_widget.sigRangeChanged.disconnect(lw.on_depth_range_changed)
                except: pass
            
            if first_interactive:
                first_interactive.plot_widget.sigRangeChanged.connect(lw.on_depth_range_changed)
                lw._connected_track = first_interactive
            else:
                lw._connected_track = None

        if hasattr(lw, 'scale_control'):
            vb = first_interactive.plot_widget.getViewBox() if first_interactive else None
            if not hasattr(lw, '_connected_vb_scale') or lw._connected_vb_scale != vb:
                if hasattr(lw, '_connected_vb_scale') and lw._connected_vb_scale:
                    try: lw._connected_vb_scale.sigYRangeChanged.disconnect(lw.scale_control.update_display)
                    except: pass
                
                if vb:
                    vb.sigYRangeChanged.connect(lw.scale_control.update_display)
                    lw._connected_vb_scale = vb
                else:
                    lw._connected_vb_scale = None
        
        lw.splitter.blockSignals(was_blocked)
        
        for i, track in enumerate(lw.track_containers):
            if hasattr(track, 'show_depth_axis') and getattr(track, 'is_depth_track', False):
                # Custom logic for depth tracks if needed, otherwise no-op here for now
                pass

    def deselect_all_tracks(self):
        """Deselect all tracks in this plot."""
        for track in self.log_widget.track_containers:
            track.is_selected = False
            track.selected_curve_indices.clear()
            track.update_selection_style()

    def on_track_selection_changed(self):
        """Handle selection change from any track and emit unified metadata for ALL selections."""
        lw = self.log_widget
        all_metadata = []
        
        for track in lw.track_containers:
            t_name = getattr(track, 'track_name', None)
            if not t_name:
                if hasattr(track, 'header') and hasattr(track.header, 'title'): t_name = track.header.title or "Track"
                else: t_name = "Track"

            if hasattr(track, 'selected_curve_indices') and track.selected_curve_indices:
                for idx in sorted(list(track.selected_curve_indices)):
                    if hasattr(track.plot_widget, 'curves') and idx < len(track.plot_widget.curves):
                        info = track.plot_widget.curves[idx].get('info', {})
                        db_p = info.get('db_path', getattr(lw.db, 'db_path', ''))
                        w_name = info.get('well_name', lw.windowTitle().replace("Plot: ", "") if lw.window() else "Unknown Well")
                        
                        all_metadata.append({
                            'db_path': db_p,
                            'well_name': w_name,
                            'type': 'curve',
                            'name': info.get('name', 'Unknown'),
                            'display_name': info.get('name', 'Unknown'),
                            'track_name': t_name,
                            'unit': info.get('unit', ''),
                            'min': info.get('min', 0),
                            'max': info.get('max', 100),
                            'log': info.get('log', False),
                            'breadcrumbs': [
                                {"type": "database", "name": db_p},
                                {"type": "well", "name": w_name},
                                {"type": "plot", "name": lw.windowTitle().replace("Plot: ", "")},
                                {"type": "track", "name": t_name},
                                {"type": "curve", "name": info.get('name', 'Unknown')}
                            ],
                            'attributes': [
                                {"label": "单位", "value": info.get('unit', '无')},
                                {"label": "最小值", "value": info.get('min', 0)},
                                {"label": "最大值", "value": info.get('max', 100)},
                                {"label": "坐标轴", "value": "对数 (Logarithmic)" if info.get('log') else "线性 (Linear)"}
                            ]
                        })
            elif track.is_selected:
                curves = []
                db_p = getattr(lw.db, 'db_path', '')
                w_name = lw.windowTitle().replace("Plot: ", "") if lw.window() else "Unknown Well"

                if hasattr(track.plot_widget, 'curves'):
                    for c in track.plot_widget.curves:
                        info = c.get('info', {})
                        c_name = info.get('name')
                        if c_name: curves.append(c_name)
                        if not db_p and info.get('db_path'): db_p = info.get('db_path')
                        if info.get('well_name') and info.get('well_name') != "Unknown": w_name = info.get('well_name')
                
                all_metadata.append({
                    'db_path': db_p,
                    'well_name': w_name,
                    'type': 'track',
                    'name': t_name,
                    'display_name': t_name,
                    'curves': curves,
                    'breadcrumbs': [
                                {"type": "database", "name": db_p},
                                {"type": "well", "name": w_name},
                                {"type": "plot", "name": lw.windowTitle().replace("Plot: ", "")},
                                {"type": "track", "name": t_name}
                    ],
                    'attributes': [
                        {"label": "所属井", "value": w_name},
                        {"label": "包含曲线", "value": ", ".join(curves) if curves else "无"}
                    ]
                })
            
        lw.selectionChanged.emit(all_metadata)
        lw._invalidate_track_x_cache()
