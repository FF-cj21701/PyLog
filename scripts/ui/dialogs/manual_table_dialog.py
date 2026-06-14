import numpy as np
import re
import io
import csv
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
                                QLineEdit, QPushButton, QTableWidget, 
                                QTableWidgetItem, QDialogButtonBox,
                                QHeaderView, QApplication, QInputDialog, QMenu)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFontMetrics
from ...data.db_manager import DBManager
from ...utils.logger import logger
from core.app_config import app_config
from ..base_dialog import ThemeDialog
from ..curve_table_helpers import configure_curve_table_view
from ..curve_table_helpers import install_corner_select_all
from ..theme_manager import ThemeManager

class ManualTableDialog(ThemeDialog):
    """
    A dialog that allows users to manually enter or paste data into a table
     and save it as curves in a specific well.
    """
    def __init__(self, well_name, well_id, db_path, parent=None, initial_depth=None, folder_name="Custom_Curves"):
        super().__init__(parent)
        self.well_name = well_name
        self.well_id = well_id
        self.db_path = db_path
        self._initial_depth = initial_depth
        self._initial_folder = folder_name
        self._depth_loading = False
        self._depth_fill_batch_size = 500
        self._depth_fill_index = 0
        self._pending_depth_values = None
        self._depth_fill_timer = QTimer(self)
        self._depth_fill_timer.setSingleShot(True)
        self._depth_fill_timer.timeout.connect(self._fill_initial_depth_batch)
        
        self.setWindowTitle(f"Custom Curve Entry - {well_name}")
        self.resize(900, 700)
        
        # Fetch existing names to avoid duplicates (needed by setup_ui -> _get_unique_name)
        self._existing_names = self._fetch_existing_names()
        # Initialize Undo Stack
        self._undo_stack = []
        
        self.setup_ui()
        ThemeManager.apply_curve_table_surface(self)
        
        if self._initial_depth is not None:
            self.populate_initial_depth()
        else:
            self._populate_row_index_column()

    @staticmethod
    def _index_column():
        return 0

    @staticmethod
    def _depth_column():
        return 1

    @staticmethod
    def _first_data_column():
        return 2

    @staticmethod
    def _default_column_count():
        return 7  # index + depth + 5 data columns

    def _populate_row_index_column(self):
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        bg_brush = QBrush(QColor(app_config.get_theme_color("bg_pure")))
        for i in range(self.table.rowCount()):
            item = QTableWidgetItem(str(i + 1))
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setBackground(bg_brush)
            self.table.setItem(i, self._index_column(), item)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)

    def populate_initial_depth(self):
        """Pre-fill the first column with provided depth data."""
        if self._initial_depth is None:
            return

        self._depth_fill_timer.stop()
        self._pending_depth_values = np.asarray(self._initial_depth, dtype=float)
        self._depth_fill_index = 0
        row_count = max(20, len(self._pending_depth_values))
        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(row_count)
        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)
        self._depth_status_tick()
        self._apply_table_column_layout()
        self._depth_fill_timer.start(0)

    def _depth_status_tick(self):
        if not self._depth_loading:
            return
        total = len(self._pending_depth_values) if self._pending_depth_values is not None else 0
        done = min(self._depth_fill_index, total)
        if hasattr(self, "depth_status_label"):
            self.depth_status_label.setText(f"Loading depth column... {done}/{total}")

    def _fill_initial_depth_batch(self):
        if self._pending_depth_values is None:
            return

        total = len(self._pending_depth_values)
        start = self._depth_fill_index
        end = min(start + self._depth_fill_batch_size, self.table.rowCount())
        index_bg_brush = QBrush(QColor(app_config.get_theme_color("bg_pure")))
        bg_brush = QBrush(QColor(app_config.get_theme_color("bg_pure")))

        self.table.blockSignals(True)
        self.table.setUpdatesEnabled(False)
        for i in range(start, end):
            index_item = self.table.item(i, self._index_column())
            if index_item is None:
                index_item = QTableWidgetItem(str(i + 1))
                index_item.setFlags(index_item.flags() & ~Qt.ItemIsEditable)
                index_item.setBackground(index_bg_brush)
                self.table.setItem(i, self._index_column(), index_item)
            else:
                index_item.setText(str(i + 1))
                index_item.setFlags(index_item.flags() & ~Qt.ItemIsEditable)
                index_item.setBackground(index_bg_brush)

            depth_item = self.table.item(i, self._depth_column())
            if depth_item is None:
                depth_item = QTableWidgetItem()
                self.table.setItem(i, self._depth_column(), depth_item)
            depth_item.setFlags(depth_item.flags() & ~Qt.ItemIsEditable)
            depth_item.setBackground(bg_brush)
            depth_item.setText(f"{self._pending_depth_values[i]:.4f}" if i < total else "")

        self.table.setUpdatesEnabled(True)
        self.table.blockSignals(False)

        self._depth_fill_index = end
        self._depth_status_tick()

        if end < self.table.rowCount():
            self._depth_fill_timer.start(0)
            return

        self._pending_depth_values = None
        self.set_loading_depth_state(False)
        self._apply_table_column_layout()

    def set_loading_depth_state(self, loading=True):
        self._depth_loading = loading
        if loading:
            if hasattr(self, "depth_status_label"):
                self.depth_status_label.setText("Loading depth column...")
            self.folder_edit.setPlaceholderText("Loading depth column...")
        else:
            if hasattr(self, "depth_status_label"):
                self.depth_status_label.setText("")
            if self.folder_edit.placeholderText() == "Loading depth column...":
                self.folder_edit.setPlaceholderText("Enter folder name (optional)")

    def set_initial_depth_async(self, depth_data):
        self._initial_depth = depth_data
        if self._initial_depth is not None:
            self.populate_initial_depth()

    def _apply_table_column_layout(self):
        depth_values = self._initial_depth if self._initial_depth is not None else np.array([])
        depth_text = "Depth"
        if len(depth_values) > 0:
            depth_text = max((f"{value:.4f}" for value in depth_values), key=len)

        cell_metrics = QFontMetrics(self.table.font())
        header_metrics = QFontMetrics(self.table.horizontalHeader().font())
        vertical_header_metrics = QFontMetrics(self.table.verticalHeader().font())

        row_index_text = str(self.table.rowCount() or 1)
        row_header_width = max(
            vertical_header_metrics.horizontalAdvance(row_index_text),
            vertical_header_metrics.horizontalAdvance(" ")
        ) + 18
        depth_width = max(
            cell_metrics.horizontalAdvance(depth_text),
            header_metrics.horizontalAdvance("Depth")
        ) + 28

        self.table.verticalHeader().setFixedWidth(max(40, row_header_width))
        self.table.setColumnWidth(self._index_column(), max(40, row_header_width))
        self.table.setColumnWidth(self._depth_column(), max(84, depth_width))
        for column in range(self._first_data_column(), self.table.columnCount()):
            self.table.setColumnWidth(column, 96)
            
    def _fetch_existing_names(self):
        """Get all curve names in the target well/folder to prevent duplicates."""
        try:
            db = DBManager(self.db_path)
            # We want to check names in the target folder primarily, 
            # but checking the whole well or folder is safer.
            curves = db.get_curves(self.well_id)
            # Find folder id for the initial folder name if possible
            target_fid = None
            folders = db.get_folders(self.well_id)
            for fid, fname, pid in folders:
                if fname == self._initial_folder:
                    target_fid = fid
                    break
            
            return [c[1] for c in curves if (len(c) > 4 and c[4] == target_fid)]
        except:
            return []

    def _get_unique_name(self, base_name):
        """Generate a name that doesn't conflict with existing curves or current table headers."""
        # Current headers in table
        current_headers = []
        for j in range(self.table.columnCount()):
            item = self.table.horizontalHeaderItem(j)
            if item:
                label = item.text()
                name, _ = self._parse_label(label)
                current_headers.append(name)
            
        all_taken = set(self._existing_names + current_headers)
        
        if base_name not in all_taken:
            return base_name
            
        counter = 1
        new_name = f"{base_name}_{counter}"
        while new_name in all_taken:
            counter += 1
            new_name = f"{base_name}_{counter}"
        return new_name
        
    def setup_ui(self):
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Header Info
        top_layout = QHBoxLayout()
        top_layout.addWidget(QLabel(f"<b>Well:</b> {self.well_name}"))

        top_layout.addStretch()

        self.depth_status_label = QLabel("")
        self.depth_status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.depth_status_label.setStyleSheet(
            f"color: {app_config.get_theme_color('text_dim')}; font-size: 10px;"
        )
        top_layout.addWidget(self.depth_status_label)
        
        layout.addLayout(top_layout)
        
        # Folder Name Input
        folder_layout = QHBoxLayout()
        folder_layout.addWidget(QLabel("<b>Save to Folder:</b>"))
        self.folder_edit = QLineEdit(self._initial_folder)
        self.folder_edit.setPlaceholderText("Enter folder name (optional)")
        folder_layout.addWidget(self.folder_edit)
        layout.addLayout(folder_layout)
        
        # Instructions
        instr = QLabel("<i>Tip: You can paste data directly from Excel (Ctrl+V). The first row will be used as headers if they are non-numeric.</i>")
        instr.setStyleSheet(f"color: {app_config.get_theme_color('text_dim')}; font-size: 10px;")
        layout.addWidget(instr)
        
        # Table Widget
        self.table = QTableWidget(20, self._default_column_count()) # Index + Depth + 5 data columns
        configure_curve_table_view(
            self.table,
            default_section_size=96,
            minimum_section_size=24,
            editable=True,
            show_vertical_header=False,
            on_context_menu=self._show_context_menu,
        )
        install_corner_select_all(self.table)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setMinimumSectionSize(20)
        self.table.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        
        # Set initial headers
        self.table.setHorizontalHeaderItem(self._index_column(), QTableWidgetItem(""))
        self.table.setHorizontalHeaderItem(self._depth_column(), QTableWidgetItem("Depth"))
        for j in range(self._first_data_column(), self._default_column_count()):
            name = self._get_unique_name(f"Column {j - 1}")
            self.table.setHorizontalHeaderItem(j, QTableWidgetItem(name))
            
        # Make headers clickable for renaming
        self.table.horizontalHeader().sectionDoubleClicked.connect(self.rename_header)
        
        # Connect auto-expansion
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.cellPressed.connect(self._handle_cell_pressed)
        self._apply_table_column_layout()
        
        layout.addWidget(self.table)
        
        # Buttons Row
        btn_layout = QHBoxLayout()

        btn_layout.addStretch()
        
        self.btn_save = QPushButton("Save")
        self.btn_save.setDefault(True)
        self.btn_save.clicked.connect(self.handle_save)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        layout.addLayout(btn_layout)

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        delete_col_action = menu.addAction("Delete Column")
        clear_table_action = menu.addAction("Clear Table")

        current_col = self.table.currentColumn()
        delete_col_action.setEnabled(current_col >= self._first_data_column())
        clear_table_action.setEnabled(self.table.rowCount() > 0 and self.table.columnCount() > 0)

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == delete_col_action:
            self.delete_column()
        elif chosen == clear_table_action:
            self.clear_table()

    def keyPressEvent(self, event):
        """Handle Ctrl+V for quick pasting and Ctrl+Z for undo."""
        if event.modifiers() & Qt.ControlModifier:
            if event.key() == Qt.Key_V:
                self.paste_from_clipboard()
                event.accept()
                return
            elif event.key() == Qt.Key_Z:
                self.undo()
                event.accept()
                return
        super().keyPressEvent(event)

    def add_row(self, save_undo=True):
        if save_undo: self._save_undo_state()
        row_idx = self.table.rowCount()
        self.table.blockSignals(True)
        self.table.insertRow(row_idx)
        index_bg_brush = QBrush(QColor(app_config.get_theme_color("bg_pure")))
        index_item = QTableWidgetItem(str(row_idx + 1))
        index_item.setFlags(index_item.flags() & ~Qt.ItemIsEditable)
        index_item.setBackground(index_bg_brush)
        self.table.setItem(row_idx, self._index_column(), index_item)
        if self._initial_depth is not None:
            # Maintain the locked style for the new row's depth column
            bg_brush = QBrush(QColor(app_config.get_theme_color("bg_pure")))
            item = QTableWidgetItem("")
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setBackground(bg_brush)
            self.table.setItem(row_idx, self._depth_column(), item)
        self.table.blockSignals(False)
        self._apply_table_column_layout()

    def add_column(self, save_undo=True):
        if save_undo: self._save_undo_state()
        col_idx = self.table.columnCount()
        self.table.blockSignals(True)
        self.table.insertColumn(col_idx)
        name = self._get_unique_name(f"Column {col_idx - 1}")
        self.table.setHorizontalHeaderItem(col_idx, QTableWidgetItem(name))
        self.table.blockSignals(False)
        self._apply_table_column_layout()

    def _on_item_changed(self, item):
        """Automatically expand table when typing in last row or column."""
        row = item.row()
        col = item.column()
        
        # If user typed in the last row, add another empty row
        if row == self.table.rowCount() - 1 and item.text().strip():
            self.add_row(save_undo=False)
            
        # If user typed in the last column, add another empty column
        if col == self.table.columnCount() - 1 and item.text().strip():
            self.add_column(save_undo=False)

    def _handle_cell_pressed(self, row, col):
        if col == self._index_column():
            self.table.selectRow(row)
            self.table.setFocus()

    def delete_column(self):
        col_idx = self.table.currentColumn()
        if col_idx < self._first_data_column():
            ThemeDialog.message(self, "Warning", "Cannot delete the index or Depth column.", icon_type="warning")
            return
            
        if ThemeDialog.confirm(self, "Confirm", f"Delete selected column '{self.table.horizontalHeaderItem(col_idx).text()}'?"):
            self._save_undo_state()
            self.table.removeColumn(col_idx)

    def _save_undo_state(self):
        """Save current table data and headers to stack."""
        state = {
            'rows': self.table.rowCount(),
            'cols': self.table.columnCount(),
            'headers': [],
            'data': [] # List of lists
        }
        for j in range(state['cols']):
            h_item = self.table.horizontalHeaderItem(j)
            state['headers'].append(h_item.text() if h_item else "")
            
        for i in range(state['rows']):
            row_vals = []
            for j in range(state['cols']):
                item = self.table.item(i, j)
                row_vals.append(item.text() if item else "")
            state['data'].append(row_vals)
            
        self._undo_stack.append(state)
        if len(self._undo_stack) > 30:
            self._undo_stack.pop(0)

    def undo(self):
        if not self._undo_stack:
            ThemeDialog.message(self, "Undo", "No more actions to undo.", icon_type="info")
            return
            
        state = self._undo_stack.pop()
        
        self.table.setRowCount(state['rows'])
        self.table.setColumnCount(state['cols'])
        
        # Restore Headers
        for j, h_text in enumerate(state['headers']):
            self.table.setHorizontalHeaderItem(j, QTableWidgetItem(h_text))
            
        # Restore Data
        n_initial = len(self._initial_depth) if self._initial_depth is not None else 0
        bg_brush = QBrush(QColor(app_config.get_theme_color("bg_pure")))
        
        for i in range(state['rows']):
            for j in range(state['cols']):
                val = state['data'][i][j]
                item = QTableWidgetItem(val)
                
                # Re-apply depth locking if needed
                if j == self._index_column():
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(QBrush(QColor(app_config.get_theme_color("bg_pure"))))
                elif j == self._depth_column() and self._initial_depth is not None:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.setBackground(bg_brush)
                
                self.table.setItem(i, j, item)
        self._apply_table_column_layout()

    def clear_table(self):
        if ThemeDialog.confirm(self, "Clear Table", "Are you sure you want to clear all curves? (Depth will be preserved)"):
            self._save_undo_state()
            if self._initial_depth is not None:
                # Protect index + depth; only clear data columns
                for r in range(self.table.rowCount()):
                    for c in range(self._first_data_column(), self.table.columnCount()):
                        self.table.setItem(r, c, None)
            else:
                # Truly blank table, clear everything
                self.table.setRowCount(20)
                self.table.setColumnCount(self._default_column_count())
                self.table.clearContents()
                self.table.setHorizontalHeaderItem(self._index_column(), QTableWidgetItem(""))
                self.table.setHorizontalHeaderItem(self._depth_column(), QTableWidgetItem("Depth"))
                self._populate_row_index_column()
            
            # Reset header names for other columns
            for j in range(self._first_data_column(), self.table.columnCount()):
                # Regenerate default unique names
                name = f"Column {j - 1}"
                self.table.setHorizontalHeaderItem(j, QTableWidgetItem(name))
            self._apply_table_column_layout()

    def rename_header(self, index):
        """Allow renaming column headers (except index/depth fixed columns)."""
        if index < self._first_data_column():
            ThemeDialog.message(self, "Info", "The index and Depth columns are fixed.", icon_type="info")
            return
            
        old_label = self.table.horizontalHeaderItem(index).text()
        # Parse existing label "Name [Unit]"
        old_name, old_unit = self._parse_label(old_label)

        # Custom dialog for Name and Unit
        dlg = ThemeDialog(self)
        dlg.setWindowTitle("Edit Column Header")
        
        # [FIX] Use setLayout instead of passing 'dlg' to constructor to avoid QLayout error
        l = QVBoxLayout()
        dlg.setLayout(l)
        
        l.addWidget(QLabel("Curve Name:"))
        name_edit = QLineEdit(old_name)
        l.addWidget(name_edit)
        
        l.addWidget(QLabel("Unit:"))
        unit_edit = QLineEdit(old_unit)
        l.addWidget(unit_edit)
        
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        l.addWidget(bb)
        
        if dlg.exec() == QDialog.Accepted:
            new_name = name_edit.text().strip()
            new_unit = unit_edit.text().strip()
            if new_name:
                self._save_undo_state()
                # [NEW] Ensure uniqueness for the new name
                unique_name = self._get_unique_name(new_name)
                final_label = f"{unique_name} [{new_unit}]" if new_unit else unique_name
                self.table.setHorizontalHeaderItem(index, QTableWidgetItem(final_label))

    def _is_numeric(self, s):
        try:
            float(s.strip())
            return True
        except:
            return False

    def _parse_label(self, label):
        """Parse 'Name (Unit)' or 'Name [Unit]' into (Name, Unit)."""
        # Try Name (Unit) or Name [Unit]
        match = re.search(r'^(.*?)[\(\[](.*?)[\)\]]$', label)
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return label.strip(), ""

    def paste_from_clipboard(self):
        cb = QApplication.clipboard()
        text = cb.text()
        if not text: return
        
        rows = text.replace('\r\n', '\n').split('\n')
        rows = [r for r in rows if r.strip()]
        if not rows: return
        
        # Determine delimiter
        sep = '\t' if '\t' in rows[0] else (',' if ',' in rows[0] else None)
        
        def split_row(r):
            if sep: return r.split(sep)
            return [x for x in r.split(' ') if x]

        # Smart Header Detection (up to 2 rows)
        header_rows = 0
        names = []
        units = []
        
        first_row = split_row(rows[0])
        if not any(self._is_numeric(x) for x in first_row):
            header_rows = 1
            # Check for name(unit) in first row
            for col_val in first_row:
                n, u = self._parse_label(col_val)
                names.append(n)
                units.append(u)
            
            # Check if second row is also all text (likely units)
            if len(rows) > 1:
                second_row = split_row(rows[1])
                if not any(self._is_numeric(x) for x in second_row):
                    header_rows = 2
                    for i, col_val in enumerate(second_row):
                        if i < len(units) and not units[i]:
                            units[i] = col_val.strip()
                        elif i >= len(units):
                            units.append(col_val.strip())

        start_row = self.table.currentRow()
        start_col = self.table.currentColumn()
        if start_row < 0: start_row = 0
        if start_col < self._depth_column(): start_col = self._depth_column()

        # Adjust data rows to skip headers
        data_rows = rows[header_rows:]
        
        # Apply Headers
        if header_rows > 0:
            self._save_undo_state()
            for i, name in enumerate(names):
                target_col = start_col + i
                if target_col < self._first_data_column():
                    continue
                
                unit = units[i] if i < len(units) else ""
                final_name = self._get_unique_name(name if name else f"Column {target_col - 1}")
                final_label = f"{final_name} [{unit}]" if unit else final_name
                
                if target_col >= self.table.columnCount():
                    self.table.insertColumn(target_col)
                self.table.setHorizontalHeaderItem(target_col, QTableWidgetItem(final_label))

        # Paste Data
        if header_rows == 0:
            self._save_undo_state()
            
        for i, row in enumerate(data_rows):
            vals = split_row(row)
            target_row = start_row + i
            if target_row >= self.table.rowCount():
                self.table.insertRow(target_row)
                
            for j, val in enumerate(vals):
                target_col = start_col + j
                if target_col >= self.table.columnCount():
                    self.table.insertColumn(target_col)
                
                # Protect fixed columns if they are read-only
                existing_item = self.table.item(target_row, target_col)
                if existing_item and not (existing_item.flags() & Qt.ItemIsEditable):
                    if target_col <= self._depth_column():
                        continue

                self.table.setItem(target_row, target_col, QTableWidgetItem(str(val).strip()))
                # Ensure default headers for new columns if not set
                if not self.table.horizontalHeaderItem(target_col):
                    if target_col == self._index_column():
                        base = ""
                    elif target_col == self._depth_column():
                        base = "Depth"
                    else:
                        base = f"Column {target_col - 1}"
                    name = self._get_unique_name(base)
                    self.table.setHorizontalHeaderItem(target_col, QTableWidgetItem(name))
        self._apply_table_column_layout()

    def handle_save(self):
        row_count = self.table.rowCount()
        col_count = self.table.columnCount()
        
        if row_count == 0 or col_count == 0:
            ThemeDialog.message(self, "Warning", "No data to save.", icon_type="warning")
            return

        # 1. Collect data into numpy arrays
        data_matrix = []
        for i in range(row_count):
            row_data = []
            is_row_empty = True
            for j in range(col_count):
                item = self.table.item(i, j)
                val_str = item.text().strip() if item else ""
                if val_str:
                    is_row_empty = False
                try:
                    val = float(val_str) if val_str else np.nan
                except ValueError:
                    val = np.nan
                row_data.append(val)
            
            # Skip rows that are completely empty or have no depth
            if is_row_empty or np.isnan(row_data[self._depth_column()]):
                continue
                
            data_matrix.append(row_data)
            
        if not data_matrix:
            ThemeDialog.message(self, "Warning", "No valid data to save.", icon_type="warning")
            return
            
        data_np = np.array(data_matrix, dtype=np.float32)
        
        # Check if all nan (remaining data)
        if np.all(np.isnan(data_np)):
            ThemeDialog.message(self, "Warning", "All data cells are empty or invalid.", icon_type="warning")
            return

        # 2. Get Headers
        column_names = []
        for j in range(col_count):
            h_item = self.table.horizontalHeaderItem(j)
            name = h_item.text() if h_item else f"Column_{j+1}"
            column_names.append(name)

        # 3. Create Folder if needed
        db = DBManager(self.db_path)
        folder_name = self.folder_edit.text().strip()
        folder_id = None
        if folder_name:
            # Check if folder already exists in this well
            existing_folders = db.get_folders(self.well_id)
            for fid, fname, pid in existing_folders:
                if fname == folder_name:
                    folder_id = fid
                    break
            
            if folder_id is None:
                folder_id = db.create_folder(self.well_id, folder_name)

        # 4. Save curves
        # [NEW] Pre-check for duplicates to prompt user
        existing_curves = db.get_curves(self.well_id)
        duplicates = []
        for j in range(col_count):
            label = column_names[j]
            name, _ = self._parse_label(label)
            if j < self._first_data_column():
                continue
            if np.all(np.isnan(data_np[:, j])):
                continue
            
            # Check for existing curve with same name AND folder (if folder set)
            for row in existing_curves:
                eid, ename, efid = row[0], row[1], row[4]
                if ename == name and (efid == folder_id or (efid is None and folder_id is None)):
                    duplicates.append((eid, ename))
                    break
        
        if duplicates:
            dupe_names = ", ".join([d[1] for d in duplicates])
            if not ThemeDialog.confirm(
                self,
                "Overwrite Confirmation",
                f"The following curves already exist in this folder:\n\n{dupe_names}\n\nDo you want to overwrite them?",
            ):
                return

        saved_count = 0
        try:
            for j in range(col_count):
                label = column_names[j]
                name, unit = self._parse_label(label)
                
                if j == self._depth_column() and not unit:
                    unit = "m"
                
                curve_data = data_np[:, j]
                if j == self._index_column():
                    continue
                if j >= self._first_data_column() and np.all(np.isnan(curve_data)):
                    continue
                
                # [NEW] Explicitly delete existing curve if it was a confirmed duplicate
                for eid, ename in duplicates:
                    if ename == name:
                        db.delete_curve(eid)
                        break
                    
                db.save_curve(self.well_id, name, unit, curve_data, folder_id=folder_id)
                saved_count += 1
                
            ThemeDialog.message(self, "Success", f"Successfully saved {saved_count} curves to '{self.well_name}'.", icon_type="info")
            self.accept()
        except Exception as e:
            logger.error(f"Error saving manual data: {e}")
            ThemeDialog.message(self, "Error", f"Failed to save data: {e}", icon_type="error")

