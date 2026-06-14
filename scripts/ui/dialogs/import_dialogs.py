from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QDialogButtonBox)
from PySide6.QtCore import Qt
from ...data.import_workers import ImportWorker

from ..base_dialog import ThemeDialog

class DLISImportDialog(ThemeDialog):
    """Custom dialog to select curves and specify well name before import."""
    def __init__(self, well_name, curves, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DLIS Import Settings")
        self.resize(450, 600)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # 1. Header
        header = QLabel("<h3>DLIS Import Selection</h3>")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)
        
        # 2. Search Filter
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search curves...")
        self.search_edit.textChanged.connect(self.filter_curves)
        layout.addWidget(self.search_edit)

        # 3. Curve Selection
        layout.addWidget(QLabel("<b>Select Data Channels (Curves):</b>"))
        self.list_widget = QListWidget()
        
        for name, unit in curves:
            item = QListWidgetItem(f"{name} ({unit})")
            item.setData(Qt.UserRole, name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)
        
        # 4. Selection Actions
        sel_layout = QHBoxLayout()
        btn_all = QPushButton("Select All", self)
        btn_none = QPushButton("Select None", self)
        btn_all.clicked.connect(self.select_all)
        btn_none.clicked.connect(self.select_none)
        sel_layout.addWidget(btn_all)
        sel_layout.addWidget(btn_none)
        layout.addLayout(sel_layout)
        
        layout.addSpacing(10)
        
        # 5. Well Naming
        layout.addWidget(QLabel("<b>Export Well/Folder Name:</b>"))
        self.name_edit = QLineEdit(well_name)
        self.name_edit.setPlaceholderText("Enter Well Name...")
        layout.addWidget(self.name_edit)
        
        layout.addSpacing(20)
        
        # 6. Dialog Buttons
        self.btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.validate_and_accept)
        self.btns.rejected.connect(self.reject)
        layout.addWidget(self.btns)

    def filter_curves(self, text):
        text = text.lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item_text = item.text().lower()
            item.setHidden(text not in item_text)

    def select_all(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Checked)

    def select_none(self):
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.Unchecked)

    def validate_and_accept(self):
        selected = self.get_selected_curves()
        if not selected:
            ThemeDialog.message(self, "Warning", "Please select at least one curve to import.", icon_type="warning")
            return
        if not self.name_edit.text().strip():
            ThemeDialog.message(self, "Warning", "Please enter a well name.", icon_type="warning")
            return
        self.accept()

    def get_selected_curves(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        return selected

    def get_settings(self):
        return self.name_edit.text().strip(), self.get_selected_curves()

# Note: QPushButton needs to be imported for the select all/none buttons
from PySide6.QtWidgets import QPushButton
