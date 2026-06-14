import dlisio
import numpy as np
import os
from .db_manager import DBManager
from ..utils.plot_value_utils import sanitize_invalid_plot_values
 
def _purge_metadata(frame):
    """
    DLISIO/NumPy internal fix: recursively ensure all channel metadata (names, units)
    are strings. If they are bytes (e.g., PHIT_AVE_\xb8), NumPy fails to build 
    the frame dtype, causing .curves() to fail for ALL channels in that frame.
    """
    for channel in frame.channels:
        # Patch name
        try:
            name = channel.name
            if isinstance(name, bytes):
                channel.name = name.decode('latin-1', errors='replace')
        except: pass
        
        # Patch units
        try:
            unit = channel.units
            if isinstance(unit, bytes):
                channel.units = unit.decode('latin-1', errors='replace')
        except: pass

def get_dlis_info(file_path):
    """
    Quickly scan DLIS for well name and available curves for UI selection.
    Returns: dict { 'well_name': str, 'curves': [ (name, unit, dims), ... ] }
    """
    import dlisio
    info = {'well_name': "Unknown", 'curves': []}
    try:
        with dlisio.dlis.load(file_path) as file:
            for d in file:
                # [NEW] Pre-purge metadata for all frames to avoid NumPy errors later
                for frame in d.frames:
                    _purge_metadata(frame)

                # 1. Well Name
                if info['well_name'] == "Unknown" and d.origins:
                    try:
                        well_name = d.origins[0].well_name
                        if isinstance(well_name, bytes):
                            well_name = well_name.decode('latin-1', errors='replace')
                        if well_name:
                            info['well_name'] = well_name
                    except: pass
                
                # 2. Curves
                for frame in d.frames:
                    for channel in frame.channels:
                        try:
                            name = channel.name
                            if isinstance(name, bytes):
                                name = name.decode('latin-1', errors='replace')
                        except:
                            name = "Unknown"
                            
                        try:
                            unit = str(channel.units) if channel.units else ""
                        except:
                            unit = ""
                        
                        # Avoid duplicates across frames if any
                        if not any(c[0] == name for c in info['curves']):
                            info['curves'].append((name, unit))

            if info['well_name'] == "Unknown":
                info['well_name'] = os.path.basename(file_path).split('.')[0]
                
    except Exception as e:
        print(f"Metadata extract error: {e}")
    return info

def import_dlis(file_path, callback=None, custom_well_name=None, selected_curves=None):
    """
    Import DLIS file content into the local database.
    - selected_curves: List of curve names to import. If None, import all.
    Returns: well_id of the imported well.
    """
    # 1. dlisio parsing
    try:
        if callback: callback("Analyzing DLIS metadata...")
        well_id = None
        well_name = custom_well_name
        
        # dlisio v1.0 structure: dlisio.dlis.load(path)
        with dlisio.dlis.load(file_path) as file:
            # 1a. Find Well Name if not provided
            if not well_name:
                well_name = "Unknown"
                for d in file:
                    if d.origins:
                        try:
                            well_name = d.origins[0].well_name
                            if isinstance(well_name, bytes):
                                well_name = well_name.decode('latin-1', errors='replace')
                            if well_name: break
                        except: pass
                
                if well_name == "Unknown" or not well_name:
                    well_name = os.path.basename(file_path).split('.')[0]

            print(f"Creating/Opening Well Database: data/{well_name}.db")
            if callback: callback(f"Preparing database for {well_name}...")
            db = DBManager(f"data/{well_name}.db")
            well_id = db.save_well(well_name)
            if callback: callback("Database ready. Starting curve import...")

            # 2. Iterate over Frames -> Channels
            curve_count = 0
            for d in file:
                for frame in d.frames:
                    # [CRITICAL] Purge metadata before ANY access to curves()
                    _purge_metadata(frame)
                    
                    frame_name = str(frame.name)
                    print(f"  Frame: {frame_name}")
                    if callback: callback(f"Processing frame: {frame_name}")
                    
                    # Create folder for this frame
                    folder_id = db.create_folder(well_id, frame_name)
                    
                    for channel in frame.channels:
                        # Robustly get channel name and units
                        try:
                            curve_name = channel.name
                            if isinstance(curve_name, bytes):
                                curve_name = curve_name.decode('latin-1', errors='replace')
                        except Exception as e:
                            print(f"    Warning: Could not read channel name: {e}")
                            continue

                        # Filter by selection
                        if selected_curves is not None and curve_name not in selected_curves:
                            continue

                        try:
                            unit = str(channel.units) if channel.units else ""
                        except:
                            unit = ""

                        try:
                            # Load data as numpy array
                            data = channel.curves()
                            if not isinstance(data, np.ndarray):
                                data = np.array(data)
                            
                            # [NEW] Unit Conversion: 0.1 in -> m
                            if unit.strip() == "0.1 in":
                                print(f"  - Converting {curve_name} from 0.1 in to m")
                                data = data * 0.00254
                                unit = "m"

                            # [OPTIMIZATION] Unified Null Handling during import
                            data = sanitize_invalid_plot_values(data)

                            # Safe print for Windows terminal
                            try:
                                print(f"  - Saving Curve: {curve_name} ({data.shape}) [{unit}] in folder {frame_name}")
                            except:
                                print(f"  - Saving Curve: [Unicode Name] ({data.shape}) [{unit}] in folder {frame_name}")

                            if callback:
                                try:
                                    callback(f"Importing: {curve_name} ({frame_name})")
                                except:
                                    callback(f"Importing: [Unicode Name] ({frame_name})")
                            db.save_curve_h5(well_id, curve_name, unit, data, folder_id=folder_id)
                            curve_count += 1
                        except Exception as e:
                            if "Field name must be a str" in str(e):
                                # This is a known dlisio issue with certain character encodings in metadata
                                try:
                                    print(f"  Skipping channel {curve_name} in frame {frame_name}: Metadata encoding issue (dlisio incompatibility).")
                                except:
                                    print(f"  Skipping channel: Metadata encoding issue.")
                            else:
                                try:
                                    print(f"  Error reading channel {curve_name} in frame {frame_name}: {e}")
                                except:
                                    print(f"  Error reading channel: {e}")
            
            if callback: callback(f"Import complete: {curve_count} curves.")
            return well_id # Returns ID

    except Exception as e:
        print(f"DLIS Import Error: {e}")
        return None
