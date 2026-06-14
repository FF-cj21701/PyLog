from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QHeaderView, QTableView, QApplication)
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeySequence
from ..floating_scrollbar import FloatingScrollbarManager
from ...data.table_data import CurveTableModel
from core.app_config import app_config

from ..base_dialog import ThemeDialog

class DataPreviewDialog(ThemeDialog):
    def __init__(self, well_name, curve_name, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Data Viewer - {well_name} : {curve_name}")
        self.resize(800, 600)
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        
        self._zoom_factor = 1.0 # [NEW] Zoom state
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)
        
        # Info & Loading Status
        self.status_label = QLabel("Loading data from database...")
        self.status_label.setStyleSheet(f"font-weight: bold; color: {app_config.get_theme_color('primary')}; padding: 10px;")
        self.layout.addWidget(self.status_label)
        
        # Table View (Hidden until loaded)
        self.table = QTableView()
        self.model = CurveTableModel()
        self.table.setModel(self.model)
        
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(80) 
        # [CRITICAL] Disable expensive section resizing for high-column counts
        self.table.horizontalHeader().setMinimumSectionSize(50)
        
        self.layout.addWidget(self.table)
        self.table.hide()
        
        # Floating Scrollbar for Table
        self.sb_mgr = FloatingScrollbarManager(self.table)

        # [NEW] Install event filter to capture Ctrl+Wheel for zooming
        self.table.viewport().installEventFilter(self)
        self.installEventFilter(self)

    def set_data(self, well_name, curve_name, depth, data):
        """Called when async worker finishes loading."""
        self.status_label.setText(f"Rows: {len(depth)} | Columns: {1 + (data.shape[1] if data.ndim>1 else 1)} | Type: {'2D (Imaging)' if data.ndim > 1 else '1D'}")
        self.status_label.setStyleSheet(f"color: {app_config.get_theme_color('text_main')}; padding: 4px;")
        
        self.model.update_data(depth, data)
        self.table.show()
        
        # Adjust only first few columns to save performance on 360-column images
        if data.ndim > 1 and data.shape[1] > 20:
             for i in range(10): # Just first 10
                 self.table.resizeColumnToContents(i)
        else:
             self.table.resizeColumnsToContents()

    def show_error(self, message):
        self.status_label.setText(f"Error: {message}")
        self.status_label.setStyleSheet(f"color: {app_config.get_theme_color('danger')}; font-weight: bold;")

    def eventFilter(self, obj, event):
        """[FIX] Capture Zoom events before they reach child widgets or parent window."""
        if event.type() == QEvent.Wheel:
            if event.modifiers() == Qt.ControlModifier:
                delta = event.angleDelta().y()
                if delta > 0:
                    self.apply_zoom(1.1)
                else:
                    self.apply_zoom(0.9)
                return True # Consume event: stop zooming AND stop scrolling
        return super().eventFilter(obj, event)

    def apply_zoom(self, factor):
        """[NEW] Adjust font and cell sizes based on zoom factor."""
        new_factor = self._zoom_factor * factor
        # Range limits: 6pt to 30pt (Base 10pt)
        if 0.6 <= new_factor <= 3.0:
            self._zoom_factor = new_factor
            
            # Apply font to table
            font = self.table.font()
            font.setPointSize(max(6, int(10 * self._zoom_factor)))
            self.table.setFont(font)
            
            # Apply to headers as well
            self.table.horizontalHeader().setFont(font)
            self.table.verticalHeader().setFont(font)
            
            # Scale cell sizes
            self.table.horizontalHeader().setDefaultSectionSize(int(80 * self._zoom_factor))
            self.table.verticalHeader().setDefaultSectionSize(int(25 * self._zoom_factor))
            
            # Refresh
            self.table.viewport().update()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
        else:
            super().keyPressEvent(event)

    def copy_selection(self):
        """Copy selected table data to clipboard in TSV format."""
        selection = self.table.selectionModel().selectedIndexes()
        if not selection:
            return

        # Group by row
        rows = {}
        for index in selection:
            r = index.row()
            c = index.column()
            val = self.model.data(index, Qt.DisplayRole)
            if r not in rows:
                rows[r] = {}
            rows[r][c] = str(val or "")

        # Sort and build string
        output = []
        for r in sorted(rows.keys()):
            row_vals = [rows[r][c] for c in sorted(rows[r].keys())]
            output.append("\t".join(row_vals))

        QApplication.clipboard().setText("\n".join(output))
