import sqlite3
import numpy as np
import io
import os
import h5py
from typing import List, Tuple, Optional, Any, Union
from ..utils.logger import logger
from ..utils.plot_value_utils import sanitize_invalid_plot_values

class DBManager:
    def __init__(self, db_path=None):
        self.db_path = db_path
        if self.db_path:
            self.init_db()

    def init_db(self):
        """Initialize the database schema."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Wells Table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS wells (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        ''')
        
        # Folders Table (New)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                well_id INTEGER,
                name TEXT NOT NULL,
                parent_id INTEGER,
                FOREIGN KEY(well_id) REFERENCES wells(id),
                FOREIGN KEY(parent_id) REFERENCES folders(id)
            )
        ''')
        
        # Curves Table
        # Check if folder_id col exists (Migration)
        try:
            cursor.execute("SELECT folder_id FROM curves LIMIT 1")
        except sqlite3.OperationalError:
            try:
                cursor.execute("ALTER TABLE curves ADD COLUMN folder_id INTEGER")
            except:
                pass # Table might not exist yet

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS curves (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                well_id INTEGER,
                name TEXT NOT NULL,
                unit TEXT,
                dimensions INTEGER,
                shape TEXT,
                dtype TEXT,
                data_blob BLOB,
                folder_id INTEGER,
                is_h5 INTEGER DEFAULT 0,
                h5_path TEXT,
                dataset_path TEXT,
                FOREIGN KEY(well_id) REFERENCES wells(id),
                FOREIGN KEY(folder_id) REFERENCES folders(id),
                UNIQUE(well_id, name, folder_id)
            )
        ''')
        
        # Migration for existing DBs
        try:
            cursor.execute("SELECT is_h5 FROM curves LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE curves ADD COLUMN is_h5 INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE curves ADD COLUMN h5_path TEXT")
            cursor.execute("ALTER TABLE curves ADD COLUMN dataset_path TEXT")
            
        # [NEW] Migration for min/max caching
        try:
            cursor.execute("SELECT val_min FROM curves LIMIT 1")
        except sqlite3.OperationalError:
            cursor.execute("ALTER TABLE curves ADD COLUMN val_min REAL")
            cursor.execute("ALTER TABLE curves ADD COLUMN val_max REAL")
        
        conn.commit()
        conn.close()

    def save_well(self, name):
        """Save well (if not exists) and return ID."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT OR IGNORE INTO wells (name) VALUES (?)", (name,))
            conn.commit()
            cursor.execute("SELECT id FROM wells WHERE name=?", (name,))
            well_id = cursor.fetchone()[0]
            return well_id
        finally:
            conn.close()

    def update_well_name(self, well_id: int, new_name: str) -> bool:
        """Update the name of an existing well."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE wells SET name=? WHERE id=?", (new_name, well_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating well name: {e}")
            return False
        finally:
            conn.close()

    def create_folder(self, well_id, name, parent_id=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO folders (well_id, name, parent_id) VALUES (?, ?, ?)", 
                           (well_id, name, parent_id))
            conn.commit()
            return cursor.lastrowid
        finally:
            conn.close()

    def update_folder_name(self, folder_id: int, new_name: str) -> bool:
        """Update the name of an existing folder."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE folders SET name=? WHERE id=?", (new_name, folder_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating folder name: {e}")
            return False
        finally:
            conn.close()

    def _delete_h5_dataset(self, h5_path: str, dataset_path: str) -> bool:
        """Delete a dataset from HDF5 and prune empty parent groups."""
        if not h5_path or not dataset_path:
            return False
        if not os.path.exists(h5_path):
            logger.warning(f"Cannot delete dataset because H5 file is missing: {h5_path}")
            return False

        try:
            with h5py.File(h5_path, 'a') as f:
                if dataset_path not in f:
                    return False

                del f[dataset_path]

                # Prune empty parent groups bottom-up, e.g. remove "f12" if now empty.
                parts = [p for p in dataset_path.split("/") if p]
                for i in range(len(parts) - 1, 0, -1):
                    grp_path = "/".join(parts[:i])
                    if grp_path not in f:
                        continue
                    grp = f[grp_path]
                    if isinstance(grp, h5py.Group) and len(grp.keys()) == 0:
                        del f[grp_path]
                    else:
                        break
            return True
        except Exception as e:
            logger.error(f"Failed to delete H5 dataset {dataset_path} in {h5_path}: {e}")
            return False

            
    def delete_curve(self, curve_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        h5_path = None
        dataset_path = None
        should_delete_h5 = False
        shared_refs = 0
        try:
            cursor.execute("SELECT is_h5, h5_path, dataset_path FROM curves WHERE id=?", (curve_id,))
            row = cursor.fetchone()
            if not row:
                return

            is_h5, h5_path, dataset_path = row
            should_delete_h5 = bool(is_h5 and h5_path and dataset_path)
            if should_delete_h5:
                cursor.execute(
                    "SELECT COUNT(*) FROM curves WHERE id <> ? AND is_h5 = 1 AND h5_path = ? AND dataset_path = ?",
                    (curve_id, h5_path, dataset_path)
                )
                shared_refs = cursor.fetchone()[0]

            cursor.execute("DELETE FROM curves WHERE id=?", (curve_id,))
            conn.commit()
        finally:
            conn.close()

        if should_delete_h5 and shared_refs == 0:
            self._delete_h5_dataset(h5_path, dataset_path)
        elif should_delete_h5 and shared_refs > 0:
            logger.info(f"Skip deleting shared H5 dataset: {dataset_path} (refs={shared_refs})")
        
    def delete_folder(self, folder_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM folders WHERE parent_id=?", (folder_id,))
            child_folder_ids = [row[0] for row in cursor.fetchall()]
            cursor.execute("SELECT id FROM curves WHERE folder_id=?", (folder_id,))
            curve_ids = [row[0] for row in cursor.fetchall()]
        finally:
            conn.close()

        for child_folder_id in child_folder_ids:
            try:
                self.delete_folder(child_folder_id)
            except Exception as e:
                logger.error(f"Failed deleting child folder {child_folder_id} during folder cleanup: {e}")

        for cid in curve_ids:
            try:
                self.delete_curve(cid)
            except Exception as e:
                logger.error(f"Failed deleting curve {cid} during folder cleanup: {e}")

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM folders WHERE id=?", (folder_id,))
            conn.commit()
        finally:
            conn.close()

    def move_curve(self, curve_id, target_folder_id):
        """Move a curve to a new folder (within the same database/well)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE curves SET folder_id=? WHERE id=?", (target_folder_id, curve_id))
            conn.commit()
        finally:
            conn.close()

    def update_curve_unit(self, curve_id: int, new_unit: str) -> bool:
        """Update the unit of an existing curve."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE curves SET unit=? WHERE id=?", (new_unit, curve_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating curve unit: {e}")
            return False
        finally:
            conn.close()

    def update_curve_name(self, curve_id: int, new_name: str) -> bool:
        """Update the name of an existing curve."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE curves SET name=? WHERE id=?", (new_name, curve_id))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating curve name: {e}")
            return False
        finally:
            conn.close()

    def update_h5_path_references(self, old_h5_path: str, new_h5_path: str) -> int:
        """Update H5 metadata references after well file rename."""
        if not old_h5_path or not new_h5_path:
            return 0

        old_norm = os.path.normcase(os.path.normpath(old_h5_path))
        updates = []
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, h5_path FROM curves WHERE is_h5 = 1 AND h5_path IS NOT NULL")
            for cid, h5_path in cursor.fetchall():
                if h5_path and os.path.normcase(os.path.normpath(h5_path)) == old_norm:
                    updates.append((new_h5_path, cid))

            if updates:
                cursor.executemany("UPDATE curves SET h5_path = ? WHERE id = ?", updates)
                conn.commit()
            return len(updates)
        except Exception as e:
            logger.error(f"Error updating H5 path references: {e}")
            return 0
        finally:
            conn.close()

    def copy_curve(self, curve_id, target_folder_id):
        """Duplicate a curve into a new folder, ensuring the clone is stored in HDF5."""
        try:
            # 1. Fetch source data (get_curve_data handles H5/BLOB transparency)
            metadata = self.get_curve_metadata(curve_id)
            if not metadata: return
            
            well_id, name, unit = metadata[0], metadata[1], metadata[2]
            data_array = self.get_curve_data(curve_id)
            
            if data_array is not None:
                new_name = f"{name}_Copy"
                # 2. Save as new record via 100% H5 save_curve
                self.save_curve(well_id, new_name, unit, data_array, target_folder_id)
        except Exception as e:
            logger.error(f"Error copying curve {curve_id}: {e}")

    def get_curve_metadata(self, curve_id):
        """Helper to fetch basic metadata without loading actual data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT well_id, name, unit, folder_id FROM curves WHERE id=?", (curve_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def get_folder(self, folder_id):
        """Return (id, well_id, name, parent_id) for a folder."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, well_id, name, parent_id FROM folders WHERE id=?", (folder_id,))
            return cursor.fetchone()
        finally:
            conn.close()

    def move_folder(self, folder_id, target_parent_id):
        """Move a folder to a new parent folder."""
        if folder_id == target_parent_id:
            return

        current_id = target_parent_id
        visited = set()
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            if current_id == folder_id:
                logger.warning(f"Rejected folder move that would create a cycle: folder_id={folder_id}, target_parent_id={target_parent_id}")
                return
            folder_row = self.get_folder(current_id)
            if not folder_row:
                break
            current_id = folder_row[3]

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE folders SET parent_id=? WHERE id=?", (target_parent_id, folder_id))
            conn.commit()
        finally:
            conn.close()

    def get_wells(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM wells")
        rows = cursor.fetchall()
        conn.close()
        return rows
        
    def get_folders(self, well_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, parent_id FROM folders WHERE well_id=?", (well_id,))
        rows = cursor.fetchall()
        conn.close()
        return rows

    def get_curves(self, well_id):
        """Return list of (id, name, unit, shape, folder_id, val_min, val_max) for a well."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name, unit, shape, folder_id, val_min, val_max FROM curves WHERE well_id=?", (well_id,))
            rows = cursor.fetchall()
        except:
             # Fallback for systems that might not have migrated the schema yet
            cursor.execute("SELECT id, name, unit, shape, folder_id, NULL, NULL FROM curves WHERE well_id=?", (well_id,))
            rows = cursor.fetchall()
            
        conn.close()
        return rows

    def save_curve(self, well_id, name, unit, data_array, folder_id=None):
        """Mandatory HDF5 save for all curve data. Legacy BLOB storage is bypassed."""
        self.save_curve_h5(well_id, name, unit, data_array, folder_id)

    def save_curve_h5(self, well_id, name, unit, data_array, folder_id=None):
        """Save curve data to an external HDF5 file and record metadata in SQLite."""
        if self.db_path is None: return
        
        # Derive .h5 path from .db path
        h5_path = self.db_path.rsplit('.', 1)[0] + ".h5"
        
        # 稳定的名称：f文件夹ID_曲线名 (清理特殊字符)
        clean_name = "".join(c for c in name if c.isalnum() or c in ('_', '-'))
        dataset_path = f"f{folder_id or 0}/{clean_name}" 
        
        try:
            # Phase A: HDF5 Storage
            with h5py.File(h5_path, 'a') as f:
                if dataset_path in f:
                    del f[dataset_path]
                f.create_dataset(dataset_path, data=data_array, compression="gzip")
                
            # Phase B: Metadata Calculation & SQLite Sync
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            shape_str = ",".join(map(str, data_array.shape))
            dims = data_array.ndim
            dtype_str = data_array.dtype.name
            
            # Global min/max for rendering cache
            cleaned_for_stats = sanitize_invalid_plot_values(data_array)
            valid_data = cleaned_for_stats[np.isfinite(cleaned_for_stats)]
            v_min = float(np.min(valid_data)) if len(valid_data) > 0 else 0.0
            v_max = float(np.max(valid_data)) if len(valid_data) > 0 else 100.0
            
            cursor.execute('''
                INSERT OR REPLACE INTO curves (well_id, name, unit, dimensions, shape, dtype, is_h5, h5_path, dataset_path, val_min, val_max, folder_id, data_blob)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ''', (well_id, name, unit, dims, shape_str, dtype_str, 1, h5_path, dataset_path, v_min, v_max, folder_id))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Error saving H5 curve {name}: {e}")
        except Exception as e:
            logger.error(f"Error saving H5 curve {name}: {e}")

    def get_curve_data(self, curve_id):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT data_blob, shape, dtype, is_h5, h5_path, dataset_path, val_min, val_max FROM curves WHERE id=?", (curve_id,))
            row = cursor.fetchone()
        except sqlite3.OperationalError:
            return None
        conn.close()
        
        if not row: return None
        
        blob, shape_str, dtype_str, is_h5, h5_path, dataset_path, v_min, v_max = row
        shape = tuple(map(int, shape_str.split(",")))
        if not dtype_str: dtype_str = 'float32'
        
        if is_h5 and h5_path and dataset_path:
            # Check if file exists
            if os.path.exists(h5_path):
                return H5LazyProxy(h5_path, dataset_path, shape, np.dtype(dtype_str), v_min, v_max)
            else:
                logger.warning(f"H5 file missing: {h5_path}")
        
        # Fallback to BLOB
        if blob:
            try:
                arr = np.frombuffer(blob, dtype=np.dtype(dtype_str))
                arr = arr.reshape(shape)
                return sanitize_invalid_plot_values(arr)
            except Exception as e:
                logger.error(f"Error loading BLOB curve: {e}")
        return None

class H5LazyProxy:
    """
    Proxy object that behaves like a numpy array but reads data lazily from HDF5.
    """
    def __init__(self, h5_path, dataset_path, shape, dtype, v_min=None, v_max=None):
        self.h5_path = h5_path
        self.dataset_path = dataset_path
        self.shape = shape
        self.dtype = dtype
        self.ndim = len(shape)
        self.size = np.prod(shape)
        self._v_min = v_min
        self._v_max = v_max

    def min(self): return self._v_min if self._v_min is not None else 0.0
    def max(self): return self._v_max if self._v_max is not None else 100.0
    
    def __array__(self, dtype=None, copy=None):
        """Conversion to actual numpy array (triggers full read)."""
        logger.debug(f"H5LazyProxy: [WARNING] Full read triggered for {self.dataset_path} (Size: {self.size})")
        data = np.asarray(self[:])
        if dtype is not None:
            data = data.astype(dtype, copy=False)
        if copy:
            data = data.copy()
        return data

    def __len__(self):
        return self.shape[0]

    def __getitem__(self, key):
        """Lazy access via slicing."""
        try:
            with h5py.File(self.h5_path, 'r') as f:
                ds = f[self.dataset_path]
                
                # 边界保护：检查 key 是否越界
                actual_shape = ds.shape
                actual_len = actual_shape[0]
                
                # 处理多维索引 (tuple)
                if isinstance(key, tuple):
                    # 目前支持 (slice, slice) 格式
                    processed_keys = []
                    for i, k in enumerate(key):
                        if i >= len(actual_shape): break
                        if isinstance(k, slice):
                            dim_len = actual_shape[i]
                            start = k.start if k.start is not None else 0
                            stop = k.stop if k.stop is not None else dim_len
                            # 补齐越界
                            if start >= dim_len: start = dim_len
                            if stop > dim_len: stop = dim_len
                            processed_keys.append(slice(start, stop, k.step))
                        else:
                            processed_keys.append(k)
                    key = tuple(processed_keys)
                elif isinstance(key, int):
                    if key < 0 or key >= actual_len:
                        return np.nan
                elif isinstance(key, slice):
                    # 对一维切片进行修正
                    start = (key.start if key.start is not None else 0)
                    stop = (key.stop if key.stop is not None else actual_len)
                    if start >= actual_len: 
                        return np.full((0,), np.nan, dtype=self.dtype)
                    if stop > actual_len: stop = actual_len
                    key = slice(start, stop, key.step)
                
                # [OPTIMIZATION] Lazy Slicing
                # If the slice is large (relative to the axis), return a new proxy instead of data
                # BUT: For ImageSliceWorker, it NEEDS the actual numpy data.
                # So we only return a Proxy if it's a simple alignment-style slice (step=1 or None)
                if isinstance(key, slice) and (key.step is None or key.step == 1):
                    # Check if we should stay lazy. 
                    # If this is called from DataFetchWorker (global align), stay lazy.
                    # We'll use a simple heuristic: if the requested length is > 50% of ds, stay lazy.
                    # Or better: Provide a .to_numpy() method and keep __getitem__ for real-reads.
                    pass 

                # Real Read from H5
                data = ds[key]
                
                # [INFO] 记录 2D 读取情况
                if isinstance(data, np.ndarray) and data.ndim > 1:
                    valid_count = np.count_nonzero(np.isfinite(data))
                    logger.debug(f"[H5_DEBUG] Read 2D Slice: {data.shape}, Valid/Total: {valid_count}/{data.size}, Mean: {np.nanmean(data) if valid_count>0 else 'N/A'}")
                
                # Apply Null Handling on the result
                if np.issubdtype(self.dtype, np.floating):
                    # Handle Scalar (single index)
                    if np.isscalar(data):
                        return sanitize_invalid_plot_values(data)
                    
                    # Handle Array (slice)
                    data = sanitize_invalid_plot_values(data)
                return data
        except Exception as e:
            logger.error(f"H5LazyProxy read error: {e}")
            return np.nan

    def __len__(self):
        return self.shape[0]

    @property
    def flags(self):
        # Fake flags to satisfy some numpy-checkers
        class Flags: writeable = False
        return Flags()

    def copy(self):
        # Allow UI components to call .copy() if needed
        return self[:] # Triggers full read
