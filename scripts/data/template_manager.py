import json
import os
import numpy as np
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import Qt
from scripts.services.plot_spec_service import build_plot_spec_from_template
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
    def _get_well_curve_cache(db, candidate_well_id, cache):
        if candidate_well_id not in cache:
            curves = db.get_curves(candidate_well_id)
            folders = db.get_folders(candidate_well_id)
            folder_map = {fid: fname for fid, fname, _fpid in folders}
            cache[candidate_well_id] = {
                "curves": curves,
                "folder_map": folder_map,
                "curve_ids": {row[0] for row in curves},
            }
        return cache[candidate_well_id]

    @staticmethod
    def _find_curve_by_identity(db, curve_cfg, well_id=None, well_curve_cache=None):
        """Resolve a curve using stable identifiers first, then fall back to path/name matching."""
        if not db:
            return None
        if well_curve_cache is None:
            well_curve_cache = {}

        stored_well_id = curve_cfg.get("well_id")
        stored_curve_id = curve_cfg.get("curve_id")
        folder = curve_cfg.get("folder")
        original_name = curve_cfg.get("name")
        display_title = curve_cfg.get("title")

        candidate_well_ids = []
        if well_id is not None:
            candidate_well_ids.append(well_id)
        elif stored_well_id is not None:
            candidate_well_ids.append(stored_well_id)
        else:
            candidate_well_ids.extend([wid for wid, _wname in db.get_wells()])

        seen = set()
        ordered_well_ids = []
        for wid in candidate_well_ids:
            if wid not in seen:
                seen.add(wid)
                ordered_well_ids.append(wid)

        if stored_curve_id is not None:
            for candidate_well_id in ordered_well_ids:
                cache_entry = TemplateManager._get_well_curve_cache(db, candidate_well_id, well_curve_cache)
                if stored_curve_id in cache_entry["curve_ids"]:
                    return candidate_well_id, stored_curve_id

        lookup_names = []
        if folder and original_name:
            lookup_names.append(f"{folder}/{original_name}")
        if original_name:
            lookup_names.append(original_name)
        if display_title and display_title != original_name:
            if folder:
                lookup_names.append(f"{folder}/{display_title}")
            lookup_names.append(display_title)

        for candidate_well_id in ordered_well_ids:
            cache_entry = TemplateManager._get_well_curve_cache(db, candidate_well_id, well_curve_cache)
            curves = cache_entry["curves"]
            folder_map = cache_entry["folder_map"]
            for lookup_name in lookup_names:
                resolved = resolve_curve_row(lookup_name, curves, folder_map)
                if resolved.get("ok"):
                    return candidate_well_id, resolved["row"][0]

        return None
    
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
        """Backward-compatible thin wrapper. Prefer resolving to plot spec first."""
        try:
            spec = TemplateManager.resolve_template_to_plot_spec(log_widget.db, file_path, well_id=well_id)
            return bool(spec.get("tracks"))
        except Exception as e:
            print(f"Error applying template: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def load_template_spec(file_path):
        if not file_path or not os.path.exists(file_path):
            return {}
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    @staticmethod
    def resolve_template_curve_groups(db, file_path, well_id=None):
        """Resolve template tracks into grouped (well_id, curve_id) pairs."""
        if not db or not os.path.exists(file_path):
            return []

        state = TemplateManager.load_template_spec(file_path)

        well_curve_cache = {}
        load_groups = []

        for track_state in state.get("tracks", []):
            if track_state.get("type", "data") == "depth":
                continue

            resolved_curves = []
            for curve_cfg in track_state.get("curves", []):
                name = curve_cfg.get("name")
                title = curve_cfg.get("title")
                if not name and not title:
                    continue

                matching_curve = TemplateManager._find_curve_by_identity(
                    db,
                    curve_cfg,
                    well_id=well_id,
                    well_curve_cache=well_curve_cache,
                )
                if matching_curve:
                    resolved_curves.append(matching_curve)

            if resolved_curves:
                load_groups.append(resolved_curves)

        return load_groups

    @staticmethod
    def resolve_template_curve_items(db, file_path, well_id=None):
        """Resolve template curves into flat quick-plot style item payloads."""
        items = []
        for group in TemplateManager.resolve_template_curve_groups(db, file_path, well_id=well_id):
            for resolved_well_id, curve_id in group:
                items.append({
                    "type": "curve",
                    "well_id": resolved_well_id,
                    "id": curve_id,
                    "db_path": getattr(db, "db_path", None),
                })
        return items

    @staticmethod
    def resolve_template_to_plot_spec(db, file_path, well_id=None):
        template_state = TemplateManager.load_template_spec(file_path)
        if not template_state:
            return {"db_path": getattr(db, "db_path", None), "well_id": well_id, "tracks": []}
        return build_plot_spec_from_template(
            template_state,
            db,
            well_id,
            resolve_curve_fn=TemplateManager._find_curve_by_identity,
        )

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
