from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QTreeWidget, QTreeWidgetItem, QStackedWidget, 
                               QAbstractItemView, QHeaderView, QStyle, QFrame,
                               QMenu, QMessageBox, QInputDialog)
from PySide6.QtCore import Qt, QMimeData, Signal
from .floating_scrollbar import FloatingScrollbarManager
from core.app_config import app_config

def get_explorer_style():
    """Dynamically fetch explorer style from app_config."""
    c = lambda t: app_config.get_theme_color(t)
    is_dark = app_config.get_theme_name() == "Dark"
    # Subtle vertical divider color
    v_border = "rgba(255, 255, 255, 0.12)" if is_dark else "rgba(0, 0, 0, 0.08)"
    
    return f"""
QTreeWidget {{
    border: none;
    font-size: 10pt;
    background-color: {c('tree_bg')};
    color: {c('text_main')};
}}
QTreeWidget::item {{
    padding: 6px;
    border-bottom: 1px solid {c('tree_item_border')};
}}
QTreeWidget::item:selected {{
    background-color: {c('tree_item_selected_bg')};
    color: {c('tree_item_selected_text')};
}}
QHeaderView::section {{
    background-color: {c('tree_bg')};
    border: none;
    border-right: 1px solid {v_border};
    padding-left: 6px; 
    padding-right: 6px;
    padding-top: 5px;
    padding-bottom: 5px;
    font-weight: bold;
    color: {c('text_main')};
    font-size: 9pt;
}}
QHeaderView::section:last {{
    border-right: none;
}}
QHeaderView::section:first {{
    padding-left: 24px;
}}
"""


class CustomTreeWidget(QTreeWidget):
    """Base tree with drag support for curves."""
    def mimeData(self, items):
        mime = QMimeData()
        if not items: return mime
        
        valid_data = []
        for item in items:
             data = item.data(0, Qt.UserRole)
             if data and isinstance(data, dict) and data.get('type') == 'curve':
                  wid = data.get('well_id')
                  cid = data.get('id')
                  db_p = data.get('db_path')
                  if wid is not None and cid is not None and db_p:
                      valid_data.append(f"{wid}:{cid}:{db_p}")
        
        if valid_data:
            mime.setData("application/x-pylog-curve", "|".join(valid_data).encode('utf-8'))
        
        return mime


class DataExplorerTree(CustomTreeWidget):
    """Specialized for data exploration (Wells/Curves)."""
    item_loading_requested = Signal(object) # (item) signal to main window

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Name", "Type", "Unit"])
        self.setHeaderHidden(False)
        self.setColumnWidth(0, 180)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setIndentation(20)
        self.setIndentation(20)
        self.update_theme()
        self.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.header().setSectionResizeMode(2, QHeaderView.Stretch)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        
        # Add scrollbar manager
        self.sb_mgr = FloatingScrollbarManager(self)
        
        # Connect expansion for lazy loading
        self.itemExpanded.connect(self.on_item_expanded)

    def update_theme(self):
        """Update explorer style based on new theme config."""
        self.setStyleSheet(get_explorer_style())
        if hasattr(self, 'sb_mgr'):
            self.sb_mgr.update_theme()
        self.update()

    def on_item_expanded(self, item):
        """Trigger lazy loading if not already loaded."""
        data = item.data(0, Qt.UserRole)
        if not data or data.get('loaded'):
            return
            
        # Emit signal to parent/main window to perform DB query
        self.item_loading_requested.emit(item)


