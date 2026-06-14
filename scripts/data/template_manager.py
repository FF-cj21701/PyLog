import json
import os
import numpy as np
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt
from ..utils.curve_resolution import resolve_curve_row

class SafeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle Qt enums, numpy types, and other non-standard types."""
    def default(self, obj):
        # 1. Handle numpy types
        if isinstance(obj, (np.integer, np.floating)):
            return obj.item()
        if isinstance(obj, np.ndarray):
            return obj.tolist()
            
        # 2. Handle Qt Enums (Generic check for anything that can be cast to int)
        type_str = str(type(obj))
        if "PySide6" in type_str or "Qt" in type_str:
            if hasattr(obj, 'value'):
                return obj.value
            try:
                return int(obj)
            except:
                pass
                
        # 3. Handle other objects with a 'value' attribute (Python Enums)
        if hasattr(obj, 'value'):
            return obj.value
            
        return str(obj) # Fallback to string representation to avoid crash


class TemplateManager:
    """Handles serialization and deserialization of plot templates."""
    
    @staticmethod
    def save_template(log_widget, file_path):
        """Saves the current plot state to a JSON file."""
        try:
            state = log_widget.get_state()
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=4, cls=SafeJSONEncoder)
            return True
        except Exception as e:
            print(f"Error saving template: {e}")
            return False

    @staticmethod
    def apply_template(log_widget, file_path, well_id=None):
        """Loads a template and applies it to the current plot."""
        try:
            if not os.path.exists(file_path):
                return False
                
            with open(file_path, 'r', encoding='utf-8') as f:
                state = json.load(f)
            
            # 1. Clear existing tracks (except depth track if needed? Actually better to start fresh)
            for track in list(log_widget.track_containers):
                log_widget.remove_track(track)
            
            # 2. Apply Global Settings
            log_widget.set_horizontal_scale(state.get("h_scale", 1.0))
            
            # [NEW] Restore Custom Depth Limits
            c_min = state.get("custom_min_depth")
            c_max = state.get("custom_max_depth")
            if c_min is not None and c_max is not None:
                log_widget.set_custom_depth_limits(c_min, c_max)
            
            # 3. Reconstruct Tracks
            # Find the active well_id if any tracks were loaded before or from somewhere
            # In PyLog, a plot widget might not be tied to ONE well, but usually is.
            # We'll try to find curves matching by name in the current database.
            
            for track_state in state.get("tracks", []):
                t_type = track_state.get("type", "data")
                width = track_state.get("base_width", 200)
                
                if t_type == "depth":
                    log_widget.add_depth_track()
                    # Apply width if possible (LogTrackContainer doesn't easily expose direct width set after creation in a way that respects splitter)
                    # _add_track_to_layout handles width
                else:
                    # Create Data Track
                    from ..tracks.track_container import CurveTrackContainer, ImageTrackContainer, AccumulativeTrackContainer
                    is_accum = track_state.get("is_accum_fill", False)
                    has_image = any(c.get("is_image", False) for c in track_state.get("curves", []))
                    if is_accum: container = AccumulativeTrackContainer(log_widget)
                    elif has_image: container = ImageTrackContainer(log_widget)
                    else: container = CurveTrackContainer(log_widget)

                    container.track_name = track_state.get("name") # [NEW] Restore track name
                    log_widget._add_track_to_layout(container, width=width)
                    
                    # Add Curves
                    for curve_cfg in track_state.get("curves", []):
                        name = curve_cfg.get("name")
                        if not name: continue
                        
                        # Find matching curve in DB
                        # Note: This is an async operation in the original LogWidget.create_new_track
                        # We'll use a simplified search here.
                        matching_curve = TemplateManager.find_curve_by_name(log_widget.db, name, well_id=well_id)
                        if matching_curve:
                            w_id, c_id = matching_curve
                            # Fetch and apply settings after data loads?
                            # OR: Pass settings to async_fetch_data?
                            # Let's modify async_fetch_data slightly or use a callback.
                            # For simplicity, we'll store the desired settings and apply them in on_data_loaded.
                            
                            # Add a temporary property to the container to store template settings
                            if not hasattr(container, '_template_curve_settings'):
                                container._template_curve_settings = {}
                            
                            # [FIX] Use a list-based queue per curve name to handle duplicate mnemonics (e.g. dual CAL logs)
                            # This prevents the second CAL from overwriting the first's template settings.
                            container._template_curve_settings.setdefault(name, []).append(curve_cfg)
                            
                            
                            # Apply track-level settings (like accumulative fill) 
                            # We'll set this on the container so it's applied after curves are added
                            if "is_accum_fill" in track_state:
                                container.is_accum_fill = track_state["is_accum_fill"]
                            
                            log_widget.add_curve_to_track(container, w_id, c_id)
            
            return True
        except Exception as e:
            print(f"Error applying template: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def find_curve_by_name(db, name, well_id=None):
        """Helper to find well_id and curve_id by name in the database."""
        if not db:
            return None
            
        # 1. Search in specific well if provided
        if well_id is not None:
            curves = db.get_curves(well_id)
            folders = db.get_folders(well_id)
            folder_map = {fid: fname for fid, fname, fpid in folders}
            resolved = resolve_curve_row(name, curves, folder_map)
            if resolved.get("ok"):
                return well_id, resolved["row"][0]
            return None # Not found in this well
            
        # 2. Global search across all wells (Fallback)
        wells = db.get_wells()
        for w_id, w_name in wells:
            curves = db.get_curves(w_id)
            folders = db.get_folders(w_id)
            folder_map = {fid: fname for fid, fname, fpid in folders}
            resolved = resolve_curve_row(name, curves, folder_map)
            if resolved.get("ok"):
                return w_id, resolved["row"][0]
        return None
