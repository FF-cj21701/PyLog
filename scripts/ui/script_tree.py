from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
                               QTreeWidget, QTreeWidgetItem, QStackedWidget, 
                               QAbstractItemView, QHeaderView, QStyle, QFrame,
                               QMenu, QMessageBox, QInputDialog)
from PySide6.QtCore import Qt, QMimeData, Signal
from .base_dialog import ThemeDialog
from .floating_scrollbar import FloatingScrollbarManager
from core.app_config import app_config
import os   

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
    color: {c('text_main')};
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


class ScriptExplorerTree(QTreeWidget):
    """Specialized for script file exploration."""
    script_renamed = Signal(str, str)  # (old_path, new_path)
    script_deleted = Signal(str)  # (path)
    script_open_requested = Signal(str)  # (path)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["File", "Size"])
        self.setHeaderHidden(False)
        self.setColumnWidth(0, 180)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setIndentation(20)
        self.setIndentation(20)
        self.update_theme()
        self.header().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.header().setStretchLastSection(True)
        self.header().setSectionResizeMode(0, QHeaderView.Interactive)
        self.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        
        # Add scrollbar manager
        self.sb_mgr = FloatingScrollbarManager(self)
        
        # Connect context menu
        self.customContextMenuRequested.connect(self.show_context_menu)
    
    def show_context_menu(self, position):
        """Show context menu for script items"""
        items = self.selectedItems()
        item = self.itemAt(position)
        
        menu = QMenu(self)
        
        # New Folder Action (always available)
        new_folder_action = menu.addAction("New Folder")
        new_script_action = menu.addAction("New Script")
        refresh_action = menu.addAction("Refresh List")
        
        # Determine parent path for new item
        parent_path = "scripts_user"
        if item:
            data = item.data(0, Qt.UserRole)
            if data:
                if data.get('type') == 'folder':
                    parent_path = data.get('path')
                else: # script
                    parent_path = os.path.dirname(data.get('path'))
        
        new_folder_action.triggered.connect(lambda: self.create_new_folder(parent_path))
        new_script_action.triggered.connect(lambda: self.create_new_script(parent_path))
        refresh_action.triggered.connect(lambda: self.get_unified_explorer().populate_scripts() if self.get_unified_explorer() else None)
        
        if not items:
            menu.exec(self.viewport().mapToGlobal(position))
            return
            
        menu.addSeparator()
        
        if len(items) == 1:
            item = items[0]
            data = item.data(0, Qt.UserRole)
            if not data: return
            
            path = data.get('path')
            if not path or not os.path.exists(path): return
            
            # Rename action
            rename_action = menu.addAction("Rename")
            rename_action.triggered.connect(lambda: self.rename_script(item, path))
            
            # Delete action
            delete_action = menu.addAction("Delete")
            delete_action.triggered.connect(lambda: self.delete_scripts(items))

            menu.addSeparator()
            # Cut/Copy
            cut_act = menu.addAction("Cut")
            cut_act.triggered.connect(lambda: self.handle_cut(items))
            copy_act = menu.addAction("Copy")
            copy_act.triggered.connect(lambda: self.handle_copy(items))
            
            if data.get('type') == 'script':
                # Open in editor action
                menu.addSeparator()
                open_action = menu.addAction("Open in Editor")
                open_action.triggered.connect(lambda: self.open_script_in_editor(path))
        else:
            # Bulk actions
            delete_action = menu.addAction(f"Delete ({len(items)} items)")
            delete_action.triggered.connect(lambda: self.delete_scripts(items))
            menu.addSeparator()
            cut_act = menu.addAction(f"Cut ({len(items)} items)")
            cut_act.triggered.connect(lambda: self.handle_cut(items))
            copy_act = menu.addAction(f"Copy ({len(items)} items)")
            copy_act.triggered.connect(lambda: self.handle_copy(items))

        # Paste Action (if clipboard exists)
        parent_explorer = self.get_unified_explorer()
        if parent_explorer and parent_explorer.script_clipboard:
            menu.addSeparator()
            paste_act = menu.addAction("Paste")
            # Determine target path
            target_path = "scripts_user"
            if item:
                data = item.data(0, Qt.UserRole)
                if data:
                    if data.get('type') == 'folder':
                        target_path = data.get('path')
                    else:
                        target_path = os.path.dirname(data.get('path'))
            paste_act.triggered.connect(lambda: self.handle_paste(target_path))
        
        menu.exec(self.viewport().mapToGlobal(position))
    
    def get_unified_explorer(self):
        """Find the UnifiedExplorer parent"""
        parent = self.parent()
        while parent and not parent.__class__.__name__ == 'UnifiedExplorer':
            parent = parent.parent()
        return parent

    def handle_cut(self, items):
        explorer = self.get_unified_explorer()
        if explorer:
            paths = [item.data(0, Qt.UserRole).get('path') for item in items if item.data(0, Qt.UserRole)]
            explorer.script_clipboard = {'paths': paths, 'op': 'cut'}
            # Visually dim items? (Optional, skipping for now)

    def handle_copy(self, items):
        explorer = self.get_unified_explorer()
        if explorer:
            paths = [item.data(0, Qt.UserRole).get('path') for item in items if item.data(0, Qt.UserRole)]
            explorer.script_clipboard = {'paths': paths, 'op': 'copy'}

    def handle_paste(self, target_dir):
        explorer = self.get_unified_explorer()
        if not explorer or not explorer.script_clipboard:
            return
            
        clipboard = explorer.script_clipboard
        paths = clipboard['paths']
        op = clipboard['op']
        
        try:
            for src in paths:
                if not os.path.exists(src): continue
                
                # Check if target is same as source or subfolder of source
                if os.path.abspath(target_dir).startswith(os.path.abspath(src)):
                    QMessageBox.warning(self, "Error", f"Cannot paste '{os.path.basename(src)}' into itself or its subfolders.")
                    continue

                dest = os.path.join(target_dir, os.path.basename(src))
                
                # Handle filename collision
                if os.path.exists(dest):
                    base, ext = os.path.splitext(dest)
                    counter = 1
                    while os.path.exists(f"{base}_copy{counter}{ext}"):
                        counter += 1
                    dest = f"{base}_copy{counter}{ext}"

                if op == 'cut':
                    shutil.move(src, dest)
                else: # copy
                    if os.path.isdir(src):
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
            
            if op == 'cut':
                explorer.script_clipboard = None

            explorer.populate_scripts()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Paste failed:\n{str(e)}")

    def update_theme(self):
        """Update explorer style based on new theme config."""
        self.setStyleSheet(get_explorer_style())
        if hasattr(self, 'sb_mgr'):
            self.sb_mgr.update_theme()
        self.update()

    def create_new_folder(self, parent_path):
        """Create a new folder in the scripts directory"""
        folder_name, ok = ThemeDialog.get_text(
            self,
            "New Folder",
            "Enter folder name:"
        )
        
        if not ok or not folder_name.strip():
            return
            
        new_path = os.path.join(parent_path, folder_name.strip())
        
        try:
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error", "Folder already exists.")
                return
            os.makedirs(new_path)
            # Find the UnifiedExplorer to trigger refresh
            parent = self.parent()
            while parent and not parent.__class__.__name__ == 'UnifiedExplorer':
                parent = parent.parent()
            if parent:
                parent.populate_scripts()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create folder: {str(e)}")

    def create_new_script(self, parent_path):
        """Create a new script file in the scripts directory"""
        script_name, ok = ThemeDialog.get_text(
            self,
            "New Script",
            "Enter script name:"
        )
        
        if not ok or not script_name.strip():
            return
            
        script_name = script_name.strip()
        if not script_name.endswith(".py"):
            script_name += ".py"
            
        new_path = os.path.join(parent_path, script_name)
        
        try:
            if os.path.exists(new_path):
                QMessageBox.warning(self, "Error", "File already exists.")
                return
            
            # Create empty file
            with open(new_path, 'w', encoding='utf-8') as f:
                f.write("# New Script\n")
            
            # Refresh tree
            explorer = self.get_unified_explorer()
            if explorer:
                explorer.populate_scripts()
                
            # Automatically request to open the new script
            self.script_open_requested.emit(new_path)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create script: {str(e)}")

    def delete_scripts(self, items):
        """Delete one or more script files or folders"""
        if not items: return
        
        names = []
        for item in items:
            data = item.data(0, Qt.UserRole)
            if data and data.get('path'):
                names.append(os.path.basename(data.get('path')))
        
        msg = f"Are you sure you want to delete {len(items)} item(s)?\n\n" + ", ".join(names[:5])
        if len(names) > 5:
            msg += "..."
        msg += "\n\nThis action cannot be undone."
        
        reply = QMessageBox.question(
            self,
            "Confirm Delete",
            msg,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
            
        for item in items:
            data = item.data(0, Qt.UserRole)
            if not data or not data.get('path'): continue
            path = data.get('path')
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                # Emit signal (for individual scripts if needed, though bulk delete might need a new signal)
                if data.get('type') == 'script':
                    self.script_deleted.emit(path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to delete {path}:\n{str(e)}")
        
        # Refresh the tree
        parent = self.parent()
        while parent and not parent.__class__.__name__ == 'UnifiedExplorer':
            parent = parent.parent()
        if parent:
            parent.populate_scripts()
    
    def rename_script(self, item, old_path):
        """Rename a script file or folder"""
        old_name = os.path.basename(old_path)
        is_dir = os.path.isdir(old_path)
        
        # Get new name from user
        new_name, ok = ThemeDialog.get_text(
            self,
            "Rename",
            "Enter new name:",
            text=old_name
        )
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        
        # Ensure .py extension for files
        if not is_dir and not new_name.endswith(".py"):
            new_name += ".py"
        
        # Check if name is the same
        if new_name == old_name:
            return
        
        # Check if new name already exists
        parent_dir = os.path.dirname(old_path)
        new_path = os.path.join(parent_dir, new_name)
        
        if os.path.exists(new_path):
            QMessageBox.warning(
                self,
                "Rename Failed",
                f"A file or folder named '{new_name}' already exists."
            )
            return
        
        try:
            os.rename(old_path, new_path)
            # Refresh tree to be safe
            parent = self.parent()
            while parent and not parent.__class__.__name__ == 'UnifiedExplorer':
                parent = parent.parent()
            if parent:
                parent.populate_scripts()
            
            if not is_dir:
                self.script_renamed.emit(old_path, new_path)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Rename Failed",
                f"Failed to rename:\n{str(e)}"
            )
    
    def open_script_in_editor(self, path):
        """Open script in editor - emit signal to be handled by parent"""
        self.script_open_requested.emit(path)


