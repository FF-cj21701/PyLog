import sqlite3
import numpy as np
import os
import sys

# Ensure project root is in path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

from scripts.data.db_manager import DBManager
from scripts.utils.logger import logger

def migrate_all_wells():
    data_dir = os.path.join(project_root, "data")
    if not os.path.exists(data_dir):
        print(f"Error: Data directory not found: {data_dir}")
        return

    # Scan for all .db files excluding common non-well databases if any
    all_db_files = [f for f in os.listdir(data_dir) if f.endswith(".db") and not f.startswith(".")]
    
    print("=" * 60)
    print("PyLog Batch Migration Engine: SQLite -> HDF5")
    print(f"   Found {len(all_db_files)} databases to process.")
    print("=" * 60)

    total_stats = {
        "wells_processed": 0,
        "curves_migrated": 0,
        "space_saved_mb": 0.0
    }

    for db_name in all_db_files:
        db_path = os.path.join(data_dir, db_name)
        old_size = os.path.getsize(db_path)
        
        try:
            print(f"\n[WELL] Processing: {db_name}")
            migrated_count = migrate_well_to_h5(db_name)
            
            new_size = os.path.getsize(db_path)
            saved = (old_size - new_size) / (1024 * 1024)
            
            total_stats["wells_processed"] += 1
            total_stats["curves_migrated"] += migrated_count
            total_stats["space_saved_mb"] += saved
            
        except Exception as e:
            print(f"[ERROR] Critical Error processing {db_name}: {e}")

    print("\n" + "=" * 60)
    print("Full Project Migration Summary")
    print(f"   - Total Wells:     {total_stats['wells_processed']}")
    print(f"   - Total Curves:    {total_stats['curves_migrated']}")
    print(f"   - Disk Space Saved: {total_stats['space_saved_mb']:.2f} MB")
    print("=" * 60)

def migrate_well_to_h5(db_name):
    db_path = os.path.join(project_root, "data", db_name)
    db_manager = DBManager(db_path)
    
    # 1. Fetch all blobs
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, well_id, name, unit, shape, dtype, data_blob, folder_id FROM curves WHERE is_h5 = 0 OR is_h5 IS NULL")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error reading curves in {db_name}: {e}")
        return 0
    
    if not rows:
        print("   Status: Already migrated or no data found.")
        return 0

    print(f"   Found {len(rows)} curves to migrate.")
    migrated_this_well = 0
    
    for row in rows:
        cid, well_id, name, unit, shape_str, dtype_str, blob, folder_id = row
        if not blob: continue
            
        try:
            shape = tuple(map(int, shape_str.split(",")))
            if not dtype_str: dtype_str = 'float32'
            
            data_array = np.frombuffer(blob, dtype=np.dtype(dtype_str))
            data_array = data_array.reshape(shape)
            
            db_manager.save_curve_h5(well_id, name, unit, data_array, folder_id)
            
            cursor.execute("UPDATE curves SET data_blob = NULL WHERE id = ?", (cid,))
            conn.commit()
            migrated_this_well += 1
            
        except Exception as e:
            print(f"   [FAILED] {name}: {e}")

    # Vacuum to reclaim space
    print("   Vacuuming...")
    cursor.execute("VACUUM")
    conn.commit()
    conn.close()
    
    print(f"   [DONE] {migrated_this_well} curves moved to HDF5.")
    return migrated_this_well

if __name__ == "__main__":
    migrate_all_wells()
