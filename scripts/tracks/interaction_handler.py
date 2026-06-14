import numpy as np
from PySide6.QtCore import Qt, QObject, QTimer
from PySide6.QtWidgets import QSplitter

class TrackInteractionHandler(QObject):
    """Handles keyboard and mouse interactions for LogTrackContainer."""
    def __init__(self, track):
        super().__init__(track)
        self.track = track

    @property
    def lw(self):
        return self.track.log_widget if self.track.log_widget else self.track.find_log_widget()

    def handle_mouse_press(self, event):
        self.track.setFocus()
        self.select_track(append=bool(event.modifiers() & Qt.ControlModifier))

    def handle_mouse_double_click(self, event):
        self.track.open_settings()

    def handle_key_press(self, event):
        if event.key() == Qt.Key_Left:
            self.handle_left_arrow()
        elif event.key() == Qt.Key_Right:
            self.handle_right_arrow()
        elif event.key() == Qt.Key_Up:
            if event.modifiers() & Qt.ControlModifier:
                self.select_previous_curve()
            else:
                self.move_curve_in_header(-1)
        elif event.key() == Qt.Key_Down:
            if event.modifiers() & Qt.ControlModifier:
                self.select_next_curve()
            else:
                self.move_curve_in_header(1)
        elif event.key() == Qt.Key_Escape:
            self.track.selected_curve_indices.clear()
            self.track.is_selected = True
            self.track.update_selection_style()
        else:
            # Note: We don't call super() here, the track's keyPressEvent will call it if we return False
            return False
        return True

    def select_track(self, append=False):
        log_w = self.lw
        if not append:
            if log_w:
                log_w.deselect_all_tracks()
            self.track.is_selected = True
        else:
            self.track.is_selected = not self.track.is_selected
        
        self.track.selected_curve_indices.clear()
        self.track.update_selection_style()
        
        if self.track.is_selected and log_w and log_w.current_settings_dialog:
             self.track.open_settings()
        
        self.track.selectionChanged.emit()

    def select_curve(self, idx, append=False):
        log_widget = self.lw
        if not append:
            if log_widget:
                log_widget.deselect_all_tracks()
            self.track.selected_curve_indices = {idx}
        else:
            if idx in self.track.selected_curve_indices:
                self.track.selected_curve_indices.remove(idx)
            else:
                self.track.selected_curve_indices.add(idx)

        self.track.is_selected = False
        self.track.update_selection_style()
        
        if log_widget and log_widget.current_settings_dialog:
            log_widget.current_settings_dialog.open_for_curve(self.track, idx)
        
        self.track.selectionChanged.emit()

    def handle_left_arrow(self):
        if self.track.selected_curve_idx >= 0:
            self.move_curve_to_adjacent_track(-1)
        else:
            self.move_track_left()

    def handle_right_arrow(self):
        if self.track.selected_curve_idx >= 0:
            self.move_curve_to_adjacent_track(1)
        else:
            self.move_track_right()

    def select_previous_curve(self):
        if len(self.track.plot_widget.curves) == 0: return
        
        if self.track.selected_curve_idx < 0:
            self.track.selected_curve_idx = len(self.track.plot_widget.curves) - 1
        else:
            self.track.selected_curve_idx = max(0, self.track.selected_curve_idx - 1)
        
        self.track.is_selected = False
        self.track.update_selection_style()

    def select_next_curve(self):
        if len(self.track.plot_widget.curves) == 0: return
        
        if self.track.selected_curve_idx < 0:
            self.track.selected_curve_idx = 0
        else:
            self.track.selected_curve_idx = min(len(self.track.plot_widget.curves) - 1, self.track.selected_curve_idx + 1)
        
        self.track.is_selected = False
        self.track.update_selection_style()

    def move_curve_in_header(self, direction):
        if self.track.selected_curve_idx < 0: return
        
        n = len(self.track.plot_widget.curves)
        old_idx = self.track.selected_curve_idx
        new_idx = old_idx + direction
        
        if 0 <= new_idx < n:
            pw = self.track.plot_widget
            pw.curves[old_idx], pw.curves[new_idx] = pw.curves[new_idx], pw.curves[old_idx]
            
            self.track.header.items[old_idx], self.track.header.items[new_idx] = \
                self.track.header.items[new_idx], self.track.header.items[old_idx]
            
            new_vbs = []
            for c in pw.curves:
                if not c.get('is_image'):
                    for vb_entry in pw.curve_viewboxes:
                        if vb_entry.get('curve') == c.get('item'):
                            new_vbs.append(vb_entry)
                            break
            pw.curve_viewboxes = new_vbs
            
            self.track.selected_curve_idx = new_idx
            self.track._refresh_z_orders()
            if self.track.is_accum_fill:
                self.track._update_accumulative_fills()
            self.track.header.update()
            self.track.update_selection_style()

    def move_track_left(self):
        log_widget = self.lw
        if not log_widget: return
        splitter = self.track.parent()
        if not isinstance(splitter, QSplitter): return
        
        # 1. Identify all selected tracks
        selected_tracks = [t for t in log_widget.track_containers if t.is_selected]
        if not selected_tracks:
            # Fallback to current track if nothing is selected (shouldn't happen if focused)
            selected_tracks = [self.track]
            
        # 2. Sort selected tracks by their current index in the splitter (left to right)
        selected_tracks.sort(key=lambda t: splitter.indexOf(t))
        
        # 3. Check if the block of selected tracks can move left
        # New logic: Find the first non-depth track to the left of the block.
        # Index 0 is often Depth, but we must check types.
        first_idx = splitter.indexOf(selected_tracks[0])
        if first_idx <= 0: return # Already at far left
        
        # Look for the target index (skipping depth tracks)
        target_idx = first_idx - 1
        while target_idx >= 0:
            target_widget = splitter.widget(target_idx)
            if target_widget.__class__.__name__ != 'DepthTrackContainer':
                break
            target_idx -= 1
        
        if target_idx < 0: return # No non-depth tracks to the left
            
        # 4. Move each track
        for t in selected_tracks:
            splitter.insertWidget(target_idx, t)
            target_idx += 1
            
        # 5. Maintain focus and sync
        self.track.setFocus() 
        log_widget.sync_track_list()

    def move_track_right(self):
        log_widget = self.lw
        if not log_widget: return
        splitter = self.track.parent()
        if not isinstance(splitter, QSplitter): return
        
        # 1. Identify all selected tracks
        selected_tracks = [t for t in log_widget.track_containers if t.is_selected]
        if not selected_tracks:
            selected_tracks = [self.track]
            
        # 2. Sort selected tracks by current index inverse (right to left)
        # We move from the rightmost track first to avoid shifting indices of tracks yet to move
        selected_tracks.sort(key=lambda t: splitter.indexOf(t), reverse=True)
        
        # 3. Check if the last track can move right
        # New logic: Find the first non-depth/non-spacer track to the right.
        last_idx = splitter.indexOf(selected_tracks[0]) # Descending sort, so index 0 is rightmost
        spacer_idx = splitter.indexOf(log_widget.spacer)
        
        if last_idx >= spacer_idx - 1: return # Already at spacer
        
        target_idx = last_idx + 1
        while target_idx < spacer_idx:
            target_widget = splitter.widget(target_idx)
            if target_widget.__class__.__name__ != 'DepthTrackContainer':
                break
            target_idx += 1
            
        if target_idx >= spacer_idx: return # No room before spacer
            
        # 4. Move each track
        # Since we're moving right, we insert them AFTER the target non-depth track
        # Because we sorted descending, we insert from rightmost to leftmost
        for t in selected_tracks:
            splitter.insertWidget(target_idx, t)
            # No need to decrement target_idx as insertWidget shifts existing
            
        # 5. Maintain focus and sync
        self.track.setFocus()
        log_widget.sync_track_list()

    def move_curve_to_adjacent_track(self, direction):
        if self.track.selected_curve_idx < 0 or self.track.selected_curve_idx >= len(self.track.plot_widget.curves):
            return
        
        log_w = self.lw
        if not log_w: return
        
        try:
            current_idx = log_w.track_containers.index(self.track)
        except ValueError:
            return
        
        # Find target track, skipping depth tracks
        target_idx = current_idx + direction
        while 0 <= target_idx < len(log_w.track_containers):
            target_candidate = log_w.track_containers[target_idx]
            if target_candidate.__class__.__name__ != 'DepthTrackContainer':
                break
            target_idx += direction
            
        if target_idx < 0 or target_idx >= len(log_w.track_containers):
            return
        
        target_track = log_w.track_containers[target_idx]
        curve_obj = self.track.plot_widget.curves[self.track.selected_curve_idx]
        
        data = curve_obj['data']
        depth = curve_obj['depth']
        info = curve_obj['info'].copy()
        
        self.track.remove_curve_at(self.track.selected_curve_idx)
        target_track.add_curve_at_index(data, depth, info, 0)
        
        self.track.selected_curve_idx = -1
        self.track.is_selected = False
        self.track.update_selection_style()
        
        target_track.setFocus()
        target_track.select_curve(0)
        self._refresh_tracks_after_curve_move(target_track)

    def move_curve_to_track(self, curve_idx, target_track):
        if curve_idx >= len(self.track.plot_widget.curves): return
        curve_obj = self.track.plot_widget.curves[curve_idx]
        data = curve_obj['data']
        depth = curve_obj['depth']
        info = curve_obj['info'].copy()
        self.track.remove_curve_at(curve_idx)
        target_track.add_curve(data, depth, info)
        self._refresh_tracks_after_curve_move(target_track)

    def _refresh_tracks_after_curve_move(self, target_track):
        """Force immediate redraw/slice refresh after keyboard-based curve moves."""
        source_track = self.track
        log_w = self.lw

        if source_track and getattr(source_track, "plot_widget", None):
            source_track.plot_widget.update()
        if target_track and getattr(target_track, "plot_widget", None):
            target_track.plot_widget.update()
        if source_track and getattr(source_track, "header", None):
            source_track.header.update()
        if target_track and getattr(target_track, "header", None):
            target_track.header.update()

        if not log_w or not hasattr(log_w, "get_master_viewbox"):
            return

        master_vb = log_w.get_master_viewbox()
        if not master_vb:
            return

        y_min, y_max = master_vb.viewRange()[1]
        if hasattr(log_w, "scroll_mgr"):
            log_w.scroll_mgr.apply_depth_range(y_min, y_max, force=True, only_track=target_track)

    def delete_me(self):
        log_w = self.lw
        if log_w:
            log_w.remove_track(self.track)
