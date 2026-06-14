import numpy as np
from PySide6.QtCore import Qt, QAbstractTableModel, QThread, Signal, QObject
from PySide6.QtGui import QColor, QPen, QBrush
from core.app_config import app_config
from .db_manager import DBManager
from ..utils.plot_value_utils import is_invalid_plot_value

class TableWorkerSignals(QObject):
    finished = Signal(str, str, object, object) # well_name, curve_name, depth, data
    error = Signal(str)

class TableDataFetchWorker(QThread):
    """Worker to fetch table data in background to avoid UI freeze."""
    signals = TableWorkerSignals()
    
    def __init__(self, db_path, well_id, curve_id, well_name, curve_name):
        super().__init__()
        self.db_path = db_path
        self.well_id = well_id
        self.curve_id = curve_id
        self.well_name = well_name
        self.curve_name = curve_name

    def run(self):
        try:
            local_db = DBManager(self.db_path)
            c_data = local_db.get_curve_data(self.curve_id)
            if c_data is None:
                self.signals.error.emit("Could not load curve data.")
                return

            # --- Smart Depth Alignment ---
            curves = local_db.get_curves(self.well_id)
            # 0. Find the folder_id of the target curve
            source_folder_id = None
            for row in curves:
                if row[0] == self.curve_id:
                    source_folder_id = row[4]
                    break

            # 1. Identify all candidate depth curves by mnemonic
            depth_mnemonics = ["DEPT", "TDEP", "DEPTH", "MDEPT"]
            depth_candidates = []
            for row in curves:
                if row[1].upper() in depth_mnemonics:
                    depth_candidates.append(row)
            
            # Prioritize candidates in the same folder
            sorted_candidates = [c for c in depth_candidates if c[4] == source_folder_id]
            sorted_candidates += [c for c in depth_candidates if c[4] != source_folder_id]

            depth_data = None
            if sorted_candidates:
                # Pick the best match (same length) or first candidate
                target_len = len(c_data)
                best_match = sorted_candidates[0]
                for candidate in sorted_candidates:
                    temp_depth = local_db.get_curve_data(candidate[0])
                    if temp_depth is not None and len(temp_depth) == target_len:
                        depth_data = temp_depth
                        break
                
                if depth_data is None:
                    depth_data = local_db.get_curve_data(best_match[0])
            
            # Fallback if specific names not found
            if depth_data is None:
                for row in curves:
                    if row[4] == source_folder_id and "DEPT" in row[1].upper():
                        depth_data = local_db.get_curve_data(row[0])
                        break
            
            if depth_data is None:
                depth_data = np.arange(len(c_data))
            
            n = min(len(c_data), len(depth_data))
            c_data = c_data[:n]
            depth_data = depth_data[:n]
            
            self.signals.finished.emit(self.well_name, self.curve_name, depth_data, c_data)
        except Exception as e:
            self.signals.error.emit(str(e))

class CurveTableModel(QAbstractTableModel):
    def __init__(self, depth=None, data=None, parent=None):
        super().__init__(parent)
        self.depth_data = depth if depth is not None else np.array([])
        self.curve_data = data if data is not None else np.array([])
        self._is_2d = self.curve_data.ndim > 1
        self._cols = self.curve_data.shape[1] if self._is_2d else 1
        # [OPTIMIZATION] Cache for formatted strings to avoid redundant float->str conversion
        self._cache = {} 
        
    def update_data(self, depth, data):
        self.beginResetModel()
        self.depth_data = depth
        self.curve_data = data
        self._is_2d = data.ndim > 1
        self._cols = data.shape[1] if self._is_2d else 1
        self._cache = {}
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self.depth_data)
        
    def columnCount(self, parent=None):
        return 1 + self._cols
        
    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
            
        row = index.row()
        col = index.column()
        
        if role == Qt.DisplayRole:
            # Check cache first
            cache_key = (row, col)
            if cache_key in self._cache:
                return self._cache[cache_key]

            if col == 0:
                res = f"{self.depth_data[row]:.4f}"
            else:
                data_col = col - 1
                val = self.curve_data[row, data_col] if self._is_2d else self.curve_data[row]
                
                # Professional Null Handling
                if is_invalid_plot_value(val):
                    res = ""
                elif abs(val) < 0.01 or abs(val) > 1000000:
                    res = f"{val:.4e}"
                else:
                    res = f"{val:.4f}"
            
            # [OPTIMIZATION] Limited cache size to prevent memory explosion for huge tables
            if len(self._cache) < 100000: # Cache up to 100k visible/semi-visible cells
                self._cache[cache_key] = res
            return res
        
        elif role == Qt.TextAlignmentRole:
             return Qt.AlignRight | Qt.AlignVCenter
             
        elif role == Qt.BackgroundRole:
            if col == 0:
                return QBrush(QColor(app_config.get_theme_color("bg_dim")))
                
        elif role == Qt.ForegroundRole:
            if col == 0:
                # Use accent color for depth column text to make it stand out
                return QBrush(QColor(app_config.get_theme_color("accent")))
            return QBrush(QColor(app_config.get_theme_color("text_main")))
                
        return None
        
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                if section == 0: return "Depth"
                return f"{section}"
            else:
                return str(section + 1)
        return None
