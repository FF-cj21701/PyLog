import numpy as np
from PySide6.QtCore import Qt, QAbstractTableModel, QThread, Signal, QObject
from PySide6.QtGui import QColor, QPen, QBrush
from core.app_config import app_config
from .db_manager import DBManager
from ..utils.plot_value_utils import is_invalid_plot_value

class TableWorkerSignals(QObject):
    finished = Signal(str, str, object, object) # well_name, curve_name, depth, data
    error = Signal(str)


class MultiCurveWorkerSignals(QObject):
    finished = Signal(dict)
    error = Signal(str)


class DepthCurveWorkerSignals(QObject):
    finished = Signal(object)
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


class MultiCurveDataFetchWorker(QThread):
    """Fetch a single curve plus resolved depth for the compare page."""

    def __init__(self, db_path, well_id, curve_id, well_name, curve_name):
        super().__init__()
        self.db_path = db_path
        self.well_id = well_id
        self.curve_id = curve_id
        self.well_name = well_name
        self.curve_name = curve_name
        self.signals = MultiCurveWorkerSignals()

    def run(self):
        try:
            local_db = DBManager(self.db_path)
            c_data = local_db.get_curve_data(self.curve_id)
            if c_data is None:
                self.signals.error.emit("Could not load curve data.")
                return

            data_arr = np.asarray(c_data)

            curves = local_db.get_curves(self.well_id)
            source_folder_id = None
            for row in curves:
                if row[0] == self.curve_id:
                    source_folder_id = row[4]
                    break

            folder_segments = []
            current_folder_id = source_folder_id
            visited = set()
            while current_folder_id and current_folder_id not in visited:
                visited.add(current_folder_id)
                folder_row = local_db.get_folder(current_folder_id)
                if not folder_row:
                    break
                folder_segments.append(folder_row[2])
                current_folder_id = folder_row[3]
            folder_path = "/".join(reversed(folder_segments))

            depth_mnemonics = ["DEPT", "TDEP", "DEPTH", "MDEPT"]
            depth_candidates = [row for row in curves if row[1].upper() in depth_mnemonics]
            sorted_candidates = [c for c in depth_candidates if c[4] == source_folder_id]
            sorted_candidates += [c for c in depth_candidates if c[4] != source_folder_id]

            depth_data = None
            if sorted_candidates:
                target_len = len(data_arr)
                best_match = sorted_candidates[0]
                for candidate in sorted_candidates:
                    temp_depth = local_db.get_curve_data(candidate[0])
                    if temp_depth is not None and len(temp_depth) == target_len:
                        depth_data = temp_depth
                        break
                if depth_data is None:
                    depth_data = local_db.get_curve_data(best_match[0])

            if depth_data is None:
                for row in curves:
                    if row[4] == source_folder_id and "DEPT" in row[1].upper():
                        depth_data = local_db.get_curve_data(row[0])
                        break

            if depth_data is None:
                depth_data = np.arange(len(data_arr))

            depth_arr = np.asarray(depth_data)
            n = min(len(data_arr), len(depth_arr))
            depth_arr = depth_arr[:n]
            data_arr = data_arr[:n]

            self.signals.finished.emit({
                "db_path": self.db_path,
                "well_id": self.well_id,
                "curve_id": self.curve_id,
                "well_name": self.well_name,
                "curve_name": self.curve_name,
                "folder_path": folder_path,
                "depth": depth_arr,
                "data": data_arr,
            })
        except Exception as e:
            self.signals.error.emit(str(e))


class DepthCurveFetchWorker(QThread):
    """Fetch a single depth curve in the background for custom-curve dialogs."""

    def __init__(self, db_path, curve_id):
        super().__init__()
        self.db_path = db_path
        self.curve_id = curve_id
        self.signals = DepthCurveWorkerSignals()

    def run(self):
        try:
            local_db = DBManager(self.db_path)
            depth_data = local_db.get_curve_data(self.curve_id)
            if depth_data is None:
                self.signals.error.emit("Could not load depth curve data.")
                return
            self.signals.finished.emit(np.asarray(depth_data))
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
        return 2 + self._cols
        
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
                res = str(row + 1)
            elif col == 1:
                res = f"{self.depth_data[row]:.4f}"
            else:
                data_col = col - 2
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
            if col in (0, 1):
                return QBrush(QColor(app_config.get_theme_color("bg_pure")))
                
        elif role == Qt.ForegroundRole:
            if col in (0, 1):
                # Use accent color for depth column text to make it stand out
                return QBrush(QColor(app_config.get_theme_color("accent")))
            return QBrush(QColor(app_config.get_theme_color("text_main")))
                
        return None
        
    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                if section == 0: return ""
                if section == 1: return "Depth"
                return f"{section - 1}"
            else:
                return str(section + 1)
        return None


class MultiCurveTableModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.depth_data = np.array([], dtype=float)
        self.columns = []
        self._cache = {}
        self._expanded_headers = set()

    def reset_data(self):
        self.beginResetModel()
        self.depth_data = np.array([], dtype=float)
        self.columns = []
        self._cache = {}
        self._expanded_headers = set()
        self.endResetModel()

    def set_viewer_data(self, depth_data, columns):
        self.beginResetModel()
        self.depth_data = np.asarray(depth_data, dtype=float) if len(depth_data) else np.array([], dtype=float)
        self.columns = list(columns)
        self._cache = {}
        self._expanded_headers = set()
        self.endResetModel()

    def toggle_header_expanded(self, section):
        if section <= 1 or section >= self.columnCount():
            return
        if section in self._expanded_headers:
            self._expanded_headers.remove(section)
        else:
            self._expanded_headers.add(section)
        self.headerDataChanged.emit(Qt.Horizontal, section, section)

    def rowCount(self, parent=None):
        return len(self.depth_data)

    def columnCount(self, parent=None):
        return 2 + len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        row = index.row()
        col = index.column()

        if role == Qt.DisplayRole:
            cache_key = (row, col)
            if cache_key in self._cache:
                return self._cache[cache_key]

            if col == 0:
                res = str(row + 1)
            elif col == 1:
                res = f"{self.depth_data[row]:.4f}"
            else:
                column = self.columns[col - 2]
                values = column.get("values", [])
                val = values[row] if row < len(values) else None
                if val is None or is_invalid_plot_value(val):
                    res = ""
                elif abs(val) < 0.01 or abs(val) > 1000000:
                    res = f"{val:.4e}"
                else:
                    res = f"{val:.4f}"

            if len(self._cache) < 100000:
                self._cache[cache_key] = res
            return res

        if role == Qt.TextAlignmentRole:
            return Qt.AlignRight | Qt.AlignVCenter

        if role == Qt.BackgroundRole and col in (0, 1):
            return QBrush(QColor(app_config.get_theme_color("bg_pure")))

        if role == Qt.ForegroundRole:
            if col in (0, 1):
                return QBrush(QColor(app_config.get_theme_color("accent")))
            return QBrush(QColor(app_config.get_theme_color("text_main")))

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.ToolTipRole:
            if section == 0:
                return "Row"
            if section == 1:
                return "Depth"
            column = self.columns[section - 2]
            return column.get("tooltip") or column.get("label", f"Curve {section}")
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            if section == 0:
                return ""
            if section == 1:
                return "Depth"
            column = self.columns[section - 2]
            label = column.get("label", f"Curve {section}")
            folder_name = column.get("folder_name")
            if section in self._expanded_headers and folder_name:
                return f"{label}/{folder_name}"
            return label
        return str(section + 1)


def copy_table_selection_to_clipboard(table, model, include_headers=False):
    """Copy current table selection to clipboard as TSV."""
    selection_model = table.selectionModel()
    if not selection_model:
        return False

    selection = selection_model.selectedIndexes()
    if not selection:
        return False

    row_map = {}
    selected_columns = set()
    for index in selection:
        row = index.row()
        col = index.column()
        selected_columns.add(col)
        row_map.setdefault(row, {})[col] = model.data(index, Qt.DisplayRole) or ""

    ordered_columns = sorted(selected_columns)
    output = []

    if include_headers:
        headers = [str(model.headerData(col, Qt.Horizontal, Qt.DisplayRole) or "") for col in ordered_columns]
        output.append("\t".join(headers))

    for row in sorted(row_map.keys()):
        output.append("\t".join(str(row_map[row].get(col, "")) for col in ordered_columns))

    from PySide6.QtWidgets import QApplication
    QApplication.clipboard().setText("\n".join(output))
    return True
