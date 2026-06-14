"""
TreeController - 负责 Explorer 树的 CRUD 操作和右键菜单。
从 MainWindow 中提取，遵循单一职责原则。
"""
import os
from PySide6.QtWidgets import (QMenu, QMessageBox, QInputDialog, QLineEdit, 
                                QTreeWidgetItem, QStyle, QDialog)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from scripts.data.db_manager import DBManager
from scripts.utils.logger import logger
from scripts.ui.dialogs.manual_table_dialog import ManualTableDialog
from .base_dialog import ThemeDialog
from ..rendering.plot_widget import LogWidget


class TreeController:
    """管理 Explorer 树的上下文菜单、CRUD、剪切/复制/粘贴、延迟加载等操作。"""
    
    def __init__(self, main_window):
        self.mw = main_window
    
    # --- Context Menu ---
    
    def show_context_menu(self, pos):
        mw = self.mw
        selected_items = mw.tree.selectedItems()
        
        db_paths = set()
        types = set()
        well_ids = set()
        
        valid_items_data = []
        for item in selected_items:
            d = item.data(0, Qt.UserRole)
            if d:
                valid_items_data.append(d)
                types.add(d.get('type'))
                if d.get('db_path'): db_paths.add(d['db_path'])
                if d.get('well_id'): well_ids.add(d['well_id'])
                elif d.get('type') == 'well': well_ids.add(d['id'])

        if not valid_items_data: 
            # Case 0: Clicked in blank area
            menu = QMenu(mw)
            new_well = QAction("New Well", mw)
            new_well.triggered.connect(self.handle_new_well)
            menu.addAction(new_well)
            
            menu.addSeparator()
            refresh_act = QAction("Refresh", mw)
            refresh_act.triggered.connect(lambda: self.refresh_tree())
            menu.addAction(refresh_act)
            
            menu.exec(mw.tree.mapToGlobal(pos))
            return
        
        menu = QMenu(mw)
        
        # Case 1: Single item clicked
        if len(selected_items) == 1:
            data = valid_items_data[0]
            if data['type'] == 'well':
                add_folder = QAction("New Folder", mw)
                add_folder.triggered.connect(lambda: self.handle_new_folder(data['id'], data['db_path']))
                menu.addAction(add_folder)
                
                rename_well = QAction("Rename", mw)
                rename_well.triggered.connect(lambda: self.handle_rename_well(data['id'], data['db_path']))
                menu.addAction(rename_well)

                del_well = QAction("Delete", mw)
                del_well.triggered.connect(lambda: self.handle_delete_well(data['db_path']))
                menu.addAction(del_well)

                menu.addSeparator()
                new_table = QAction("New Custom Curve...", mw)
                new_table.triggered.connect(lambda: self.handle_manual_entry(data['id'], data['db_path'], data.get('name', 'Well')))
                menu.addAction(new_table)
                
                if mw.explorer_clipboard and mw.explorer_clipboard.get('db_path') == data['db_path']:
                    menu.addSeparator()
                    paste_act = QAction("Paste", mw)
                    paste_act.triggered.connect(lambda: self.handle_paste(data['db_path'], data['id'], None))
                    menu.addAction(paste_act)
                    
            elif data['type'] == 'folder':
                add_sub = QAction("New Sub-Folder", mw)
                add_sub.triggered.connect(lambda: self.handle_new_folder(data.get('well_id'), data['db_path'], parent_id=data['id']))
                menu.addAction(add_sub)

                new_curve = QAction("New Custom Curve...", mw)
                new_curve.triggered.connect(lambda: self.handle_new_manual_curve(data.get('well_id'), data['db_path'], "Well", data['id'], data.get('name')))
                menu.addAction(new_curve)
                
                menu.addSeparator()
                cut_act = QAction("Cut", mw)
                cut_act.triggered.connect(lambda: self.handle_cut(valid_items_data))
                menu.addAction(cut_act)
                
                copy_act = QAction("Copy", mw)
                copy_act.triggered.connect(lambda: self.handle_copy(valid_items_data))
                menu.addAction(copy_act)
                
                if mw.explorer_clipboard and mw.explorer_clipboard.get('db_path') == data['db_path']:
                    paste_act = QAction("Paste", mw)
                    paste_act.triggered.connect(lambda: self.handle_paste(data['db_path'], data.get('well_id'), data['id']))
                    menu.addAction(paste_act)
                
                menu.addSeparator()
                del_folder = QAction("Delete Folder", mw)
                del_folder.triggered.connect(lambda: self.handle_delete_folder_bulk(valid_items_data))
                menu.addAction(del_folder)
                
            elif data['type'] == 'curve':
                quick_plot = QAction("Quick Plot", mw)
                quick_plot.triggered.connect(lambda: mw.handle_quick_plot(valid_items_data))
                menu.addAction(quick_plot)
                menu.addSeparator()

                cut_act = QAction("Cut", mw)
                cut_act.triggered.connect(lambda: self.handle_cut(valid_items_data))
                menu.addAction(cut_act)
                
                copy_act = QAction("Copy", mw)
                copy_act.triggered.connect(lambda: self.handle_copy(valid_items_data))
                menu.addAction(copy_act)
                
                rename_curve = QAction("Rename", mw)
                rename_curve.triggered.connect(lambda: self.handle_rename_curve(data['id'], data['db_path'], data.get('name', 'Curve')))
                menu.addAction(rename_curve)
                
                menu.addSeparator()
                del_curve = QAction("Delete Curve", mw)
                del_curve.triggered.connect(lambda: self.handle_delete_curve_bulk(valid_items_data))
                menu.addAction(del_curve)
        
        # Case 2: Multi-selection
        else:
            if len(db_paths) > 1:
                menu.addAction("Multiple wells selected (No actions available)")
            else:
                db_path = list(db_paths)[0] if db_paths else None
                
                if 'well' not in types:
                    if 'curve' in types:
                        quick_plot = QAction(f"Quick Plot ({len([d for d in valid_items_data if d['type']=='curve'])} curves)", mw)
                        quick_plot.triggered.connect(lambda: mw.handle_quick_plot(valid_items_data))
                        menu.addAction(quick_plot)
                        menu.addSeparator()

                    cut_act = QAction(f"Cut ({len(selected_items)} items)", mw)
                    cut_act.triggered.connect(lambda: self.handle_cut(valid_items_data))
                    menu.addAction(cut_act)
                    
                    copy_act = QAction(f"Copy ({len(selected_items)} items)", mw)
                    copy_act.triggered.connect(lambda: self.handle_copy(valid_items_data))
                    menu.addAction(copy_act)
                    
                    menu.addSeparator()
                    
                    item_desc = "Items"
                    if len(types) == 1:
                        item_desc = list(types)[0].capitalize() + "s"
                    
                    del_bulk = QAction(f"Delete ({len(selected_items)} {item_desc})", mw)
                    del_bulk.triggered.connect(lambda: self.handle_delete_bulk(valid_items_data))
                    menu.addAction(del_bulk)
                else:
                     menu.addAction("Bulk actions not available for wells")

        # Global actions for items
        menu.addSeparator()
        refresh_act = QAction("Refresh", mw)
        refresh_act.triggered.connect(lambda: self.refresh_tree())
        menu.addAction(refresh_act)

        menu.exec(mw.tree.mapToGlobal(pos))
    
    # --- CRUD Operations ---

    def handle_new_well(self):
        text, ok = ThemeDialog.get_text(self.mw, "New Well", "Well Name:")
        if ok and text:
            db_p = f"data/{text}.db"
            new_db = DBManager(db_p)
            well_id = new_db.save_well(text)
            self.refresh_tree(expand_keys=[('well', well_id, db_p)])

    def handle_new_folder(self, well_id, db_path, parent_id=None):
        text, ok = ThemeDialog.get_text(self.mw, "New Folder", "Folder Name:")
        if ok and text:
            fid = DBManager(db_path).create_folder(well_id, text, parent_id=parent_id)
            self.refresh_tree(expand_keys=[('folder', fid, db_path)])

    def handle_manual_entry(self, well_id, db_path, well_name):
        dlg = ManualTableDialog(well_name, well_id, db_path, self.mw)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_tree()

    def handle_new_manual_curve(self, well_id, db_path, well_name, target_folder_id=None, folder_name="Custom_Curves"):
        # Try to find depth data for this well
        depth_data = None
        try:
            db = DBManager(db_path)
            curves = db.get_curves(well_id)
            depth_mnemonics = ["DEPT", "TDEP", "DEPTH", "MDEPT"]
            for row in curves:
                cid, cname, fid = row[0], row[1], row[4]
                # [FIX] Only pre-fill depth if it belongs to the SAME folder
                if fid == target_folder_id and cname.upper() in depth_mnemonics:
                    depth_data = db.get_curve_data(cid)
                    break
            
            # Fallback (within folder)
            if depth_data is None:
                for row in curves:
                    cid, cname, fid = row[0], row[1], row[4]
                    if fid == target_folder_id and "DEPT" in cname.upper():
                        depth_data = db.get_curve_data(cid)
                        break
        except Exception as e:
            logger.error(f"Error fetching depth for new curve: {e}")

        dlg = ManualTableDialog(well_name, well_id, db_path, self.mw, 
                                initial_depth=depth_data, folder_name=folder_name)
        if dlg.exec() == QDialog.Accepted:
            self.refresh_tree()

    def handle_delete_folder(self, folder_id, db_path):
        ret = QMessageBox.question(self.mw, "Confirm", "Delete folder and all contents?")
        if ret == QMessageBox.Yes:
            DBManager(db_path).delete_folder(folder_id)
            self.refresh_tree()

    def handle_delete_curve(self, curve_id, db_path):
        ret = QMessageBox.question(self.mw, "Confirm", "Delete this curve?")
        if ret == QMessageBox.Yes:
            DBManager(db_path).delete_curve(curve_id)
            self.refresh_tree()

    def handle_rename_curve(self, curve_id, db_path, current_name):
        text, ok = ThemeDialog.get_text(self.mw, "Rename Curve", "New Curve Name:", current_name)
        if ok and text and text != current_name:
            if DBManager(db_path).update_curve_name(curve_id, text):
                self.refresh_tree()
            else:
                QMessageBox.critical(self.mw, "Error", "Failed to rename curve.")

    def handle_rename_well(self, well_id, db_path):
        """Rename the well in the DB and rename the file itself."""
        current_name = os.path.basename(db_path).replace(".db", "")
        text, ok = ThemeDialog.get_text(self.mw, "Rename Well", "New Well Name:", current_name)
        if ok and text and text != current_name:
            new_db_path = os.path.join(os.path.dirname(db_path), f"{text}.db")
            old_h5_path = db_path.rsplit(".", 1)[0] + ".h5"
            new_h5_path = new_db_path.rsplit(".", 1)[0] + ".h5"
            db_renamed = False
            h5_renamed = False
            try:
                db = DBManager(db_path)
                if db.update_well_name(well_id, text):
                    if os.path.exists(new_db_path):
                        raise Exception(f"A well named '{text}' already exists.")

                    if os.path.exists(old_h5_path) and os.path.exists(new_h5_path):
                        raise Exception(f"A companion H5 file named '{os.path.basename(new_h5_path)}' already exists.")

                    os.rename(db_path, new_db_path)
                    db_renamed = True

                    if os.path.exists(old_h5_path):
                        os.rename(old_h5_path, new_h5_path)
                        h5_renamed = True

                    updated = DBManager(new_db_path).update_h5_path_references(old_h5_path, new_h5_path)
                    self.mw.statusBar().showMessage(f"Well renamed to: {text}", 3000)
                    if updated:
                        logger.info(f"Updated {updated} curve H5 path references after well rename.")
                    self._sync_runtime_well_references(db_path, new_db_path, text)
                    self.refresh_tree()
                else:
                    raise Exception("Failed to update database record.")
            except Exception as e:
                # Best-effort rollback for file renames.
                if h5_renamed and os.path.exists(new_h5_path) and not os.path.exists(old_h5_path):
                    try:
                        os.rename(new_h5_path, old_h5_path)
                    except Exception as rb_e:
                        logger.error(f"Rollback failed for H5 rename: {rb_e}")
                if db_renamed and os.path.exists(new_db_path) and not os.path.exists(db_path):
                    try:
                        os.rename(new_db_path, db_path)
                    except Exception as rb_e:
                        logger.error(f"Rollback failed for DB rename: {rb_e}")
                ThemeDialog.message(self.mw, "Error", f"Failed to rename well: {e}", icon_type="error")

    def _sync_runtime_well_references(self, old_db_path, new_db_path, new_well_name):
        """Update in-memory runtime references that still point at the old DB path."""
        mw = self.mw

        if getattr(mw, 'db', None) and getattr(mw.db, 'db_path', None) == old_db_path:
            mw.db = DBManager(new_db_path)

        clipboard = getattr(mw, 'explorer_clipboard', None)
        if clipboard and clipboard.get('db_path') == old_db_path:
            clipboard['db_path'] = new_db_path
            for item in clipboard.get('items', []):
                if isinstance(item, dict) and item.get('db_path') == old_db_path:
                    item['db_path'] = new_db_path

        mdi_area = getattr(mw, 'mdi_area', None)
        if not mdi_area:
            return

        old_well_name = os.path.basename(old_db_path).replace('.db', '')
        for sub in mdi_area.subWindowList():
            widget = sub.widget()
            if isinstance(widget, LogWidget):
                if (
                    getattr(widget, 'db_path', None) == old_db_path
                    or (getattr(widget, 'db', None) and getattr(widget.db, 'db_path', None) == old_db_path)
                ):
                    widget.set_db_source(new_db_path)
                if sub.windowTitle() == f"Plot: {old_well_name}":
                    sub.setWindowTitle(f"Plot: {new_well_name}")

    def handle_delete_well(self, db_path):
        """Delete the entire well database file and its companion H5 file."""
        well_name = os.path.basename(db_path).replace(".db", "")
        h5_path = db_path.replace(".db", ".h5")
        
        # Prepare file list for confirmation
        files_to_delete = [db_path]
        if os.path.exists(h5_path):
            files_to_delete.append(h5_path)
            
        file_list_str = "\n".join([f"- {os.path.basename(f)}" for f in files_to_delete])
        msg = f"Are you sure you want to delete Well '{well_name}' and ALL its data?\n\nThis will permanently delete the following files:\n{file_list_str}"
        
        if ThemeDialog.confirm(self.mw, "Confirm Delete Well", msg):
            try:
                # Validation (Safety check)
                if not db_path.endswith(".db") or "data" not in db_path:
                    raise Exception("Invalid database path for deletion.")
                
                deleted_count = 0
                for f in files_to_delete:
                    if os.path.exists(f):
                        os.remove(f)
                        deleted_count += 1
                
                if deleted_count > 0:
                    ThemeDialog.message(self.mw, "Success", f"Well '{well_name}' and its associated data have been permanently deleted.")
                    self.refresh_tree()
                else:
                    ThemeDialog.message(self.mw, "Error", "Target files not found or already removed.", icon_type="warning")
            except Exception as e:
                ThemeDialog.message(self.mw, "Error", f"Failed to delete well data: {e}", icon_type="error")

    # --- Clipboard Operations ---
    
    def handle_cut(self, items_data):
        db_path = items_data[0].get('db_path')
        self.mw.explorer_clipboard = {'items': items_data, 'op': 'cut', 'db_path': db_path}
        self.mw.statusBar().showMessage(f"Cut {len(items_data)} items", 3000)

    def handle_copy(self, items_data):
        db_path = items_data[0].get('db_path')
        self.mw.explorer_clipboard = {'items': items_data, 'op': 'copy', 'db_path': db_path}
        self.mw.statusBar().showMessage(f"Copied {len(items_data)} items", 3000)

    def handle_paste(self, target_db, well_id, folder_id):
        mw = self.mw
        if not mw.explorer_clipboard:
            return
            
        items = mw.explorer_clipboard['items']
        op = mw.explorer_clipboard['op']
        source_db = mw.explorer_clipboard['db_path']
        
        if source_db != target_db:
             QMessageBox.warning(mw, "Restriction", "Cross-well curve movement is NOT supported.")
             return

        try:
            db = DBManager(target_db)
            for data in items:
                if data['type'] == 'curve':
                    if op == 'cut':
                        db.move_curve(data['id'], folder_id)
                    else:
                        db.copy_curve(data['id'], folder_id)
                elif data['type'] == 'folder':
                    if op == 'cut':
                        db.move_folder(data['id'], folder_id)
                    else:
                        QMessageBox.information(mw, "Info", f"Folder copy ({data.get('name')}) not implemented. Skipping.")
            
            if op == 'cut':
                mw.explorer_clipboard = None
                
            self.refresh_tree()
            mw.statusBar().showMessage("Paste complete.", 3000)
            
        except Exception as e:
            QMessageBox.critical(mw, "Error", f"Paste failed: {e}")
    
    # --- Bulk Delete Operations ---

    def handle_delete_folder_bulk(self, items_data):
        ret = QMessageBox.question(self.mw, "Confirm", "Delete folder and all contents?")
        if ret == QMessageBox.Yes:
            for data in items_data:
                DBManager(data['db_path']).delete_folder(data['id'])
            self.refresh_tree()

    def handle_delete_curve_bulk(self, items_data):
        ret = QMessageBox.question(self.mw, "Confirm", "Delete selected curve(s)?")
        if ret == QMessageBox.Yes:
            for data in items_data:
                DBManager(data['db_path']).delete_curve(data['id'])
            self.refresh_tree()

    def handle_delete_bulk(self, items_data):
        ret = QMessageBox.question(self.mw, "Confirm Bulk Delete", f"Delete {len(items_data)} selected items?")
        if ret == QMessageBox.Yes:
            for data in items_data:
                db = DBManager(data['db_path'])
                if data['type'] == 'folder':
                    db.delete_folder(data['id'])
                elif data['type'] == 'curve':
                    db.delete_curve(data['id'])
            self.refresh_tree()
    
    # --- Tree Population and State Management ---

    def get_expansion_state(self):
        """Recursively record expanded nodes."""
        state = set()
        def traverse(item):
            if item.isExpanded():
                data = item.data(0, Qt.UserRole)
                if data:
                    # Identifier: (type, id, db_path)
                    state.add((data.get('type'), data.get('id'), data.get('db_path')))
                for i in range(item.childCount()):
                    traverse(item.child(i))
        
        root = self.mw.tree.invisibleRootItem()
        for i in range(root.childCount()):
            traverse(root.child(i))
        return state

    def apply_expansion_state(self, state):
        """Recursively restore expanded nodes (triggers lazy loading)."""
        if not state: return
        
        # Helper to find and expand
        def expand_recursively(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                data = child.data(0, Qt.UserRole)
                if data:
                    key = (data.get('type'), data.get('id'), data.get('db_path'))
                    if key in state:
                        # Trigger lazy load
                        self.load_children_for_item(child)
                        child.setExpanded(True)
                        # Recurse (since children were just loaded)
                        expand_recursively(child)
        
        self.mw.tree.setUpdatesEnabled(False)
        try:
            root = self.mw.tree.invisibleRootItem()
            expand_recursively(root)
        finally:
            self.mw.tree.setUpdatesEnabled(True)

    def refresh_tree(self, expand_keys=None):
        """Refresh the tree while maintaining expansion state."""
        state = self.get_expansion_state()
        if expand_keys:
            for k in expand_keys:
                state.add(k)
        self.populate_tree()
        self.apply_expansion_state(state)

    def populate_tree(self):
        """Initial scan for well databases in data/ folder. Only loads Well nodes (Lazy Loading)."""
        mw = self.mw
        mw.tree.clear()
        
        for well_info in mw._scan_all_wells():
            well_node = QTreeWidgetItem(mw.tree)
            well_node.setText(0, well_info['name'])
            well_node.setText(1, "WellData")
            well_node.setData(0, Qt.UserRole, {
                'type': 'well', 
                'id': well_info['id'], 
                'name': well_info['name'],
                'db_path': well_info['db_path'], 
                'loaded': False
            })
            
            # Add dummy child to make it expandable
            dummy = QTreeWidgetItem(well_node)
            dummy.setText(0, "Loading...")

    def load_children_for_item(self, item):
        """Lazy Load folders and curves for a Well or Folder node."""
        mw = self.mw
        data = item.data(0, Qt.UserRole)
        if not data or data.get('loaded'):
            return
            
        # Clear placeholder children
        while item.childCount() > 0:
            item.removeChild(item.child(0))
            
        db_path = data['db_path']
        well_id = data.get('well_id') if data['type'] == 'folder' else data['id']
        parent_folder_id = data['id'] if data['type'] == 'folder' else None
        
        try:
            db = DBManager(db_path)
            
            # 1. Fetch Folders
            folders = db.get_folders(well_id)
            for row in folders:
                fid, fname, pid = row[0], row[1], row[2]
                if pid == parent_folder_id:
                    fnode = QTreeWidgetItem(item)
                    fnode.setText(0, fname)
                    fnode.setText(1, "Folder")
                    fnode.setData(0, Qt.UserRole, {
                        'type': 'folder', 
                        'id': fid, 
                        'name': fname,
                        'well_id': well_id, 
                        'db_path': db_path, 
                        'loaded': False
                    })
                    fnode.setIcon(0, mw.style().standardIcon(QStyle.SP_DirIcon))
                    # Add dummy for subfolders
                    dummy = QTreeWidgetItem(fnode)
                    dummy.setText(0, "Loading...")
            
            # 2. Fetch Curves
            all_curves = db.get_curves(well_id)
            # Filter by folder (fid is index 4)
            curves_at_this_level = [c for c in all_curves if (len(c) > 4 and c[4] == parent_folder_id)]
            
            # Sort: 1D first, then 2D (shape is index 3)
            curves_1d = []
            curves_2d = []
            for c_struct in curves_at_this_level:
                if mw._is_2d_curve(c_struct[3]): 
                    curves_2d.append(c_struct)
                else: 
                    curves_1d.append(c_struct)
            
            # 3. Populate Curves (Robust unpacking)
            for c in (curves_1d + curves_2d):
                cid, cname, unit, shape, fid, vmin, vmax = c[:7]
                cnode = QTreeWidgetItem(item)
                cnode.setText(0, cname)
                cnode.setText(1, "2D" if mw._is_2d_curve(shape) else "1D") 
                cnode.setText(2, str(unit) if unit else "")
                cnode.setData(0, Qt.UserRole, {
                    'type': 'curve', 
                    'id': cid, 
                    'name': cname, 
                    'folder': data.get('name') if data['type'] == 'folder' else None,
                    'well_id': well_id, 
                    'db_path': db_path,
                    'min': vmin,
                    'max': vmax
                })
            
            # Mark as loaded
            data['loaded'] = True
            item.setData(0, Qt.UserRole, data)
            
        except Exception as e:
            logger.error(f"Lazy load error: {e}")
            import traceback
            traceback.print_exc()
            item.setText(0, f"{item.text(0)} (Error loading)")
