from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QStackedWidget, QFrame, QStyle, QTreeWidgetItem)
from PySide6.QtCore import Qt, Slot
import os

from .data_tree import DataExplorerTree
from .script_tree import ScriptExplorerTree
from core.app_config import app_config

def get_header_style():
    c = lambda t: app_config.get_theme_color(t)
    return f"""
QPushButton {{
    border: none;
    border-bottom: 2px solid transparent;
    padding: 5px 15px;
    font-weight: bold;
    font-size: 10pt;
    color: {c('text_dim')};
    background-color: transparent;
}}
QPushButton:hover {{
    color: {c('accent')};
    background-color: {c('accent_hover')};
}}
QPushButton[active="true"] {{
    color: {c('accent')};
    border-bottom: 2px solid {c('accent')};
}}
"""

class UnifiedExplorer(QWidget):
    """Top-level container with Header + StackedWidget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # 1. Header with custom buttons
        self.header_frame = QFrame()
        self.header_frame.setObjectName("explorerHeader")
        self.header_container_layout = QVBoxLayout(self.header_frame)
        self.header_container_layout.setContentsMargins(0, 0, 0, 0)
        self.header_container_layout.setSpacing(0)

        self.btn_layout = QHBoxLayout()
        self.btn_layout.setContentsMargins(5, 0, 0, 0)
        self.btn_layout.setSpacing(2)
        
        self.btn_data = QPushButton("DATA")
        self.btn_scripts = QPushButton("SCRIPTS")
        
        # Apply style and default state
        for btn in [self.btn_data, self.btn_scripts]:
            btn.setCursor(Qt.PointingHandCursor)
            self.btn_layout.addWidget(btn)
        
        self.btn_data.setProperty("active", "true")
        self.btn_scripts.setProperty("active", "false")
        
        self.btn_layout.addStretch()

        self.header_container_layout.addLayout(self.btn_layout)
        self.main_layout.addWidget(self.header_frame)
        
        # 2. Stacked Content
        self.stack = QStackedWidget()
        self.data_tree = DataExplorerTree()
        self.script_tree = ScriptExplorerTree()
        
        # Script state
        self._is_scripts_loaded = False
        self.script_clipboard = None
        
        self.stack.addWidget(self.data_tree)
        self.stack.addWidget(self.script_tree)
        
        self.main_layout.addWidget(self.stack)
        
        # Connections
        self.btn_data.clicked.connect(lambda: self.switch_view(0))
        self.btn_scripts.clicked.connect(lambda: self.switch_view(1))
        
        # Apply initial theme
        self.update_theme()

    def update_theme(self):
        """Update all visual components of the explorer."""
        c = lambda t: app_config.get_theme_color(t)
        header_bg = c('explorer_header_bg')
        header_border = c('border_std')
        
        self.header_frame.setStyleSheet(f"""
            #explorerHeader {{
                background-color: {header_bg};
                border: none;
            }}
        """)
        
        # Buttons
        style = get_header_style()
        self.btn_data.setStyleSheet(style)
        self.btn_scripts.setStyleSheet(style)
        
        # Sub-trees (if they exist yet)
        if hasattr(self, 'data_tree'):
            self.data_tree.update_theme()
        if hasattr(self, 'script_tree'):
            self.script_tree.update_theme()
        
        self.update()

    def switch_view(self, index):
        self.stack.setCurrentIndex(index)
        
        # Update button properties and refresh style
        self.btn_data.setProperty("active", "true" if index == 0 else "false")
        self.btn_scripts.setProperty("active", "true" if index == 1 else "false")
        
        self.btn_data.style().unpolish(self.btn_data)
        self.btn_data.style().polish(self.btn_data)
        self.btn_scripts.style().unpolish(self.btn_scripts)
        self.btn_scripts.style().polish(self.btn_scripts)
        
        if index == 1 and not self._is_scripts_loaded:
            self.populate_scripts()

    @Slot()
    def populate_scripts(self):
        """Build the script tree from files on disk with re-entrancy protection."""
        if hasattr(self, '_is_populating') and self._is_populating:
            return
            
        self._is_populating = True
        self._is_scripts_loaded = True
        expanded_paths = set()
        
        def collect_expanded(item):
            data = item.data(0, Qt.UserRole)
            if item.isExpanded() and data and data.get('path'):
                expanded_paths.add(data.get('path'))
            for i in range(item.childCount()):
                collect_expanded(item.child(i))

        # Block updates to prevent flickering and reduce crash risk during clear()
        self.script_tree.setUpdatesEnabled(False)
        self.script_tree.blockSignals(True)
        
        from scripts.utils.logger import logger
        logger.info(f"Populating scripts from scripts_dir: {getattr(self, 'scripts_dir', 'scripts_user')}")
        
        try:
            for i in range(self.script_tree.topLevelItemCount()):
                collect_expanded(self.script_tree.topLevelItem(i))

            # 2. Re-populate
            self.script_tree.clear()
            scripts_dir = "scripts_user"
            if not os.path.exists(scripts_dir):
                os.makedirs(scripts_dir)
                
            self._add_files_to_tree(scripts_dir, self.script_tree)

            # 3. Restore expansion state
            def restore_expanded(item):
                data = item.data(0, Qt.UserRole)
                if data and data.get('path') in expanded_paths:
                    item.setExpanded(True)
                for i in range(item.childCount()):
                    restore_expanded(item.child(i))

            for i in range(self.script_tree.topLevelItemCount()):
                restore_expanded(self.script_tree.topLevelItem(i))
            
            logger.info("Script population complete.")
        except Exception as e:
            logger.error(f"Error populating scripts: {e}")
        finally:
            self.script_tree.blockSignals(False)
            self.script_tree.setUpdatesEnabled(True)
            self._is_populating = False

    def _add_files_to_tree(self, directory, parent_item):
        """Recursively add files and folders to the tree"""
        # Distinguish between folders and files for sorting
        items = os.listdir(directory)
        # Filter out __pycache__ and hidden folders (starting with .)
        dirs = [d for d in items if os.path.isdir(os.path.join(directory, d)) and d != "__pycache__" and not d.startswith(".")]
        files = [f for f in items if os.path.isfile(os.path.join(directory, f)) and not f.startswith(".")]
        
        # Add folders
        for d in sorted(dirs):
            path = os.path.join(directory, d)
            item = QTreeWidgetItem(parent_item)
            item.setText(0, d)
            item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
            item.setData(0, Qt.UserRole, {'type': 'folder', 'path': path})
            self._add_files_to_tree(path, item)
            
        # Add files
        for f in sorted(files):
            path = os.path.join(directory, f)
            try:
                size = os.path.getsize(path) / 1024 # KB
                size_str = f"{size:.1f} KB"
            except:
                size_str = "Unknown"
            
            item = QTreeWidgetItem(parent_item)
            item.setText(0, f)
            item.setText(1, size_str)
            item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
            item_type = 'script' if f.endswith(".py") else 'file'
            item.setData(0, Qt.UserRole, {'type': item_type, 'path': path})


