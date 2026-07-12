"""
TreeController - 负责 Explorer 树的 CRUD 操作和右键菜单。
从 MainWindow 中提取，遵循单一职责原则。
"""
import os
from PySide6.QtWidgets import (QMenu,
                                QTreeWidgetItem, QStyle, QDialog)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from core.app_config import app_config
from scripts.data.db_manager import DBManager
from scripts.utils.logger import logger
from scripts.utils.well_queries import DEPTH_MNEMONICS
from scripts.ui.dialogs.manual_table_dialog import ManualTableDialog
from scripts.data.table_data import DepthCurveFetchWorker
from .base_dialog import ThemeDialog
from ..rendering.plot_widget import LogWidget


class TreeController:
    """管理 Explorer 树的上下文菜单、CRUD、剪切/复制/粘贴、延迟加载等操作。"""
    
    def __init__(self, main_window):
        self.mw = main_window
    
    def _add_action(self, menu, text, handler):
        action = QAction(text, self.mw)
        action.triggered.connect(handler)
        menu.addAction(action)
        return action

    def _add_refresh_action(self, menu):
        self._add_action(menu, "Refresh", lambda: self.refresh_tree())

    def _can_paste_into(self, db_path):
        clipboard = getattr(self.mw, 'explorer_clipboard', None)
        return bool(clipboard and clipboard.get('db_path') == db_path)

    def _table_group_icon(self):
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        try:
            border = QColor(app_config.get_theme_color("text_main"))
            fill = QColor(app_config.get_theme_color("accent_light"))
            fill.setAlpha(120)
            painter.setBrush(fill)
            painter.setPen(QPen(border, 1.1))
            painter.drawRoundedRect(2, 3, 12, 10, 1.5, 1.5)
            painter.drawLine(2, 8, 14, 8)
            painter.drawLine(8, 3, 8, 13)
        finally:
            painter.end()
        return QIcon(pixmap)

    def _build_blank_area_menu(self, menu):
        self._add_action(menu, "New Well", self.handle_new_well)
        menu.addSeparator()
        self._add_refresh_action(menu)

    def _build_well_menu(self, menu, data):
        self._add_action(menu, "New Folder", lambda: self.handle_new_folder(data['id'], data['db_path']))
        self._add_action(menu, "Rename", lambda: self.handle_rename_well(data['id'], data['db_path']))
        self._add_action(menu, "Delete", lambda: self.handle_delete_well(data['db_path']))
        menu.addSeparator()
        self._add_action(
            menu,
            "New Custom Curve...",
            lambda: self.handle_manual_entry(data['id'], data['db_path'], data.get('name', 'Well'))
        )
        if self._can_paste_into(data['db_path']):
            menu.addSeparator()
            self._add_action(menu, "Paste", lambda: self.handle_paste(data['db_path'], data['id'], None))

    def _build_folder_menu(self, menu, data, valid_items_data):
        self._add_action(
            menu,
            "New Sub-Folder",
            lambda: self.handle_new_folder(data.get('well_id'), data['db_path'], parent_id=data['id'])
        )
        self._add_action(
            menu,
            "New Custom Curve...",
            lambda: self.handle_new_manual_curve(data.get('well_id'), data['db_path'], "Well", data['id'], data.get('name'))
        )
        menu.addSeparator()
        self._add_action(menu, "Cut", lambda: self.handle_cut(valid_items_data))
        self._add_action(menu, "Copy", lambda: self.handle_copy(valid_items_data))
        self._add_action(
            menu,
            "Rename",
            lambda: self.handle_rename_folder(data['id'], data['db_path'], data.get('name', 'Folder'))
        )
        if self._can_paste_into(data['db_path']):
            self._add_action(
                menu,
                "Paste",
                lambda: self.handle_paste(data['db_path'], data.get('well_id'), data['id'])
            )
        menu.addSeparator()
        self._add_action(menu, "Delete Folder", lambda: self.handle_delete_folder_bulk(valid_items_data))

    def _build_curve_menu(self, menu, data, valid_items_data):
        self._add_action(menu, "Quick Plot", lambda: self.mw.handle_quick_plot(valid_items_data))
        self._add_action(menu, "Data Viewer", lambda: self.mw.handle_open_data_viewer(valid_items_data))
        menu.addSeparator()
        self._add_action(menu, "Cut", lambda: self.handle_cut(valid_items_data))
        self._add_action(menu, "Copy", lambda: self.handle_copy(valid_items_data))
        self._add_action(
            menu,
            "Rename",
            lambda: self.handle_rename_curve(data['id'], data['db_path'], data.get('name', 'Curve'))
        )
        menu.addSeparator()
        self._add_action(menu, "Delete Curve", lambda: self.handle_delete_curve_bulk(valid_items_data))

    def _build_fracture_table_menu(self, menu, data, valid_items_data):
        self._add_action(menu, "Open Table", lambda: self.mw.handle_open_fracture_table(data))

    def _build_single_item_menu(self, menu, data, valid_items_data):
        builders = {
            'well': self._build_well_menu,
            'folder': self._build_folder_menu,
            'curve': self._build_curve_menu,
            'fracture_table': self._build_fracture_table_menu,
        }
        builder = builders.get(data.get('type'))
        if builder:
            if data.get('type') == 'well':
                builder(menu, data)
            else:
                builder(menu, data, valid_items_data)

    def _build_multi_selection_menu(self, menu, selected_items, valid_items_data, db_paths, types):
        if len(db_paths) > 1:
            menu.addAction("Multiple wells selected (No actions available)")
            return

        if 'well' in types:
            menu.addAction("Bulk actions not available for wells")
            return

        if 'curve' in types:
            curve_count = len([d for d in valid_items_data if d['type'] == 'curve'])
            self._add_action(
                menu,
                f"Quick Plot ({curve_count} curves)",
                lambda: self.mw.handle_quick_plot(valid_items_data)
            )
            self._add_action(
                menu,
                f"Data Viewer ({curve_count} curves)",
                lambda: self.mw.handle_open_data_viewer(valid_items_data)
            )
            menu.addSeparator()

        item_count = len(selected_items)
        self._add_action(menu, f"Cut ({item_count} items)", lambda: self.handle_cut(valid_items_data))
        self._add_action(menu, f"Copy ({item_count} items)", lambda: self.handle_copy(valid_items_data))
        menu.addSeparator()

        item_desc = "Items"
        if len(types) == 1:
            item_desc = list(types)[0].capitalize() + "s"
        self._add_action(
            menu,
            f"Delete ({item_count} {item_desc})",
            lambda: self.handle_delete_bulk(valid_items_data)
        )
    
    # --- Context Menu ---
    
    def show_context_menu(self, pos):
        mw = self.mw
        selected_items = mw.tree.selectedItems()
        
        db_paths = set()
        types = set()
        valid_items_data = []
        for item in selected_items:
            d = item.data(0, Qt.UserRole)
            if d:
                valid_items_data.append(d)
                types.add(d.get('type'))
                if d.get('db_path'): db_paths.add(d['db_path'])

        if not valid_items_data: 
            # Case 0: Clicked in blank area
            menu = QMenu(mw)
            self._build_blank_area_menu(menu)
            menu.exec(mw.tree.mapToGlobal(pos))
            return
        
        menu = QMenu(mw)
        
        # Case 1: Single item clicked
        if len(selected_items) == 1:
            self._build_single_item_menu(menu, valid_items_data[0], valid_items_data)
        
        # Case 2: Multi-selection
        else:
            self._build_multi_selection_menu(menu, selected_items, valid_items_data, db_paths, types)

        # Global actions for items
        menu.addSeparator()
        self._add_refresh_action(menu)

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
        # Try to find the matching depth curve id for this folder, but defer heavy data loading
        depth_curve_id = None
        try:
            db = DBManager(db_path)
            curves = db.get_curves(well_id)
            depth_mnemonics = ["DEPT", "TDEP", "DEPTH", "MDEPT"]
            for row in curves:
                cid, cname, fid = row[0], row[1], row[4]
                # [FIX] Only pre-fill depth if it belongs to the SAME folder
                if fid == target_folder_id and cname.upper() in depth_mnemonics:
                    depth_curve_id = cid
                    break
            
            # Fallback (within folder)
            if depth_curve_id is None:
                for row in curves:
                    cid, cname, fid = row[0], row[1], row[4]
                    if fid == target_folder_id and "DEPT" in cname.upper():
                        depth_curve_id = cid
                        break
        except Exception as e:
            logger.error(f"Error fetching depth for new curve: {e}")

        dlg = ManualTableDialog(well_name, well_id, db_path, self.mw, 
                                initial_depth=None, folder_name=folder_name)
        if depth_curve_id is not None:
            dlg.set_loading_depth_state(True)
            worker = DepthCurveFetchWorker(db_path, depth_curve_id)
            worker.signals.finished.connect(dlg.set_initial_depth_async)
            worker.signals.error.connect(lambda message: logger.error(f"Error loading depth curve async: {message}"))
            worker.finished.connect(lambda: setattr(dlg, "_depth_worker", None))
            dlg._depth_worker = worker
            worker.start()
        if dlg.exec() == QDialog.Accepted:
            self.refresh_tree()

    def handle_delete_folder(self, folder_id, db_path):
        if ThemeDialog.confirm(self.mw, "Confirm", "Delete folder and all contents?"):
            DBManager(db_path).delete_folder(folder_id)
            self.refresh_tree()

    def handle_delete_curve(self, curve_id, db_path):
        if ThemeDialog.confirm(self.mw, "Confirm", "Delete this curve?"):
            DBManager(db_path).delete_curve(curve_id)
            self.refresh_tree()

    def handle_rename_folder(self, folder_id, db_path, current_name):
        text, ok = ThemeDialog.get_text(self.mw, "Rename Folder", "New Folder Name:", current_name)
        if ok and text and text != current_name:
            if DBManager(db_path).update_folder_name(folder_id, text):
                self.refresh_tree()
            else:
                ThemeDialog.message(self.mw, "Error", "Failed to rename folder.", icon_type="error")

    def handle_rename_curve(self, curve_id, db_path, current_name):
        text, ok = ThemeDialog.get_text(self.mw, "Rename Curve", "New Curve Name:", current_name)
        if ok and text and text != current_name:
            if DBManager(db_path).update_curve_name(curve_id, text):
                self.refresh_tree()
            else:
                ThemeDialog.message(self.mw, "Error", "Failed to rename curve.", icon_type="error")

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

    def _curve_belongs_to_folder_tree(self, source_db, curve_id, root_folder_id):
        metadata = source_db.get_curve_metadata(curve_id)
        if not metadata:
            return False

        folder_id = metadata[3]
        if folder_id is None:
            return root_folder_id is None

        current_id = folder_id
        visited = set()
        while current_id is not None and current_id not in visited:
            visited.add(current_id)
            if current_id == root_folder_id:
                return True
            folder_row = source_db.get_folder(current_id)
            if not folder_row:
                break
            current_id = folder_row[3]
        return False

    def _find_curve_depth_id(self, source_db, curve_id):
        metadata = source_db.get_curve_metadata(curve_id)
        if not metadata:
            return None

        well_id, _name, _unit, source_folder_id = metadata
        curves = source_db.get_curves(well_id)
        same_folder = []
        fallback = []
        for row in curves:
            candidate_id, candidate_name, _unit, _shape, candidate_folder_id = row[:5]
            candidate_upper = str(candidate_name).upper()
            if candidate_upper in DEPTH_MNEMONICS or "DEPT" in candidate_upper:
                if candidate_folder_id == source_folder_id:
                    same_folder.append(candidate_id)
                else:
                    fallback.append(candidate_id)
        if same_folder:
            return same_folder[0]
        if fallback:
            return fallback[0]
        return None

    def _resolve_cross_well_target_folder(self, target_db, target_well_id, requested_folder_id, group_name):
        if requested_folder_id:
            return requested_folder_id

        existing_names = {name for _fid, name, _pid in target_db.get_folders(target_well_id)}
        base_name = group_name or "FRAME_MOVE"
        candidate = base_name
        suffix = 2
        while candidate in existing_names:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        return target_db.create_folder(target_well_id, candidate)

    def _create_unique_folder(self, target_db, target_well_id, folder_name, parent_id=None):
        sibling_names = {
            name for _fid, name, pid in target_db.get_folders(target_well_id)
            if pid == parent_id
        }
        candidate = folder_name or "FRAME_MOVE"
        suffix = 2
        while candidate in sibling_names:
            candidate = f"{folder_name}_{suffix}"
            suffix += 1
        return target_db.create_folder(target_well_id, candidate, parent_id=parent_id)

    def _copy_curve_between_dbs(self, source_db, target_db, curve_id, target_well_id, target_folder_id):
        metadata = source_db.get_curve_metadata(curve_id)
        if not metadata:
            return False

        _source_well_id, name, unit, _source_folder_id = metadata
        data_array = source_db.get_curve_data(curve_id)
        if data_array is None:
            return False

        target_db.save_curve(target_well_id, name, unit, data_array, target_folder_id)
        return True

    def _is_depth_curve_still_used(self, source_db, depth_id):
        depth_metadata = source_db.get_curve_metadata(depth_id)
        if not depth_metadata:
            return False

        source_well_id = depth_metadata[0]
        for row in source_db.get_curves(source_well_id):
            if row[0] == depth_id:
                continue
            if self._find_curve_depth_id(source_db, row[0]) == depth_id:
                return True
        return False

    def _transfer_folder_tree_cross_well(self, source_db, target_db, source_folder_id, target_well_id, requested_parent_id, op):
        source_folder = source_db.get_folder(source_folder_id)
        if not source_folder:
            return 0

        _fid, source_well_id, source_folder_name, _parent_id = source_folder
        target_root_folder_id = self._create_unique_folder(
            target_db,
            target_well_id,
            source_folder_name,
            parent_id=requested_parent_id,
        )

        source_folders = source_db.get_folders(source_well_id)
        source_curves = source_db.get_curves(source_well_id)
        folder_map = {source_folder_id: target_root_folder_id}
        transferred = 0

        pending = [source_folder_id]
        while pending:
            current_source_folder_id = pending.pop(0)
            current_target_folder_id = folder_map[current_source_folder_id]

            child_folders = [
                row for row in source_folders
                if row[2] == current_source_folder_id
            ]
            for child_source_id, child_name, _child_parent_id in child_folders:
                child_target_id = self._create_unique_folder(
                    target_db,
                    target_well_id,
                    child_name,
                    parent_id=current_target_folder_id,
                )
                folder_map[child_source_id] = child_target_id
                pending.append(child_source_id)

            curves_in_folder = [
                row for row in source_curves
                if len(row) > 4 and row[4] == current_source_folder_id
            ]
            for curve_row in curves_in_folder:
                if self._copy_curve_between_dbs(
                    source_db,
                    target_db,
                    curve_row[0],
                    target_well_id,
                    current_target_folder_id,
                ):
                    transferred += 1

        if op == 'cut':
            source_db.delete_folder(source_folder_id)

        return transferred

    def _transfer_curve_group_cross_well(self, source_db_path, target_db_path, target_well_id, requested_folder_id, items, op):
        source_db = DBManager(source_db_path)
        target_db = DBManager(target_db_path)

        selected_folder_ids = [data['id'] for data in items if data['type'] == 'folder']
        transferred_count = 0
        for source_folder_id in selected_folder_ids:
            transferred_count += self._transfer_folder_tree_cross_well(
                source_db,
                target_db,
                source_folder_id,
                target_well_id,
                requested_folder_id,
                op,
            )

        selected_curve_ids = []
        source_folder_names = []
        for data in items:
            if data['type'] == 'curve':
                if any(self._curve_belongs_to_folder_tree(source_db, data['id'], folder_id) for folder_id in selected_folder_ids):
                    continue
                selected_curve_ids.append(data['id'])
                folder_name = data.get('folder')
                if folder_name:
                    source_folder_names.append(folder_name)

        ordered_curve_ids = []
        for cid in selected_curve_ids:
            if cid not in ordered_curve_ids:
                ordered_curve_ids.append(cid)

        related_depth_ids = []
        for cid in ordered_curve_ids:
            depth_id = self._find_curve_depth_id(source_db, cid)
            if depth_id is not None and depth_id not in ordered_curve_ids and depth_id not in related_depth_ids:
                related_depth_ids.append(depth_id)

        group_curve_ids = related_depth_ids + ordered_curve_ids
        if not group_curve_ids:
            return transferred_count

        group_name = source_folder_names[0] if source_folder_names else "FRAME_MOVE"
        target_folder_id = self._resolve_cross_well_target_folder(target_db, target_well_id, requested_folder_id, group_name)

        transferred_ids = []
        for cid in group_curve_ids:
            if self._copy_curve_between_dbs(source_db, target_db, cid, target_well_id, target_folder_id):
                transferred_ids.append(cid)

        if op == 'cut':
            for cid in ordered_curve_ids:
                source_db.delete_curve(cid)
            for depth_id in related_depth_ids:
                if not self._is_depth_curve_still_used(source_db, depth_id):
                    source_db.delete_curve(depth_id)

            for data in items:
                if data['type'] == 'folder':
                    source_db.delete_folder(data['id'])

        return transferred_count + len(transferred_ids)

    def handle_paste(self, target_db, well_id, folder_id):
        mw = self.mw
        if not mw.explorer_clipboard:
            return
            
        items = mw.explorer_clipboard['items']
        op = mw.explorer_clipboard['op']
        source_db = mw.explorer_clipboard['db_path']

        try:
            db = DBManager(target_db)
            if source_db != target_db:
                transferred = self._transfer_curve_group_cross_well(source_db, target_db, well_id, folder_id, items, op)
                if transferred == 0:
                    ThemeDialog.message(mw, "Info", "No curves were transferred.", icon_type="info")
                    return
            else:
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
                            ThemeDialog.message(mw, "Info", f"Folder copy ({data.get('name')}) not implemented. Skipping.", icon_type="info")
            
            if op == 'cut':
                mw.explorer_clipboard = None
                
            self.refresh_tree()
            mw.statusBar().showMessage("Paste complete.", 3000)
            
        except Exception as e:
            ThemeDialog.message(mw, "Error", f"Paste failed: {e}", icon_type="error")
    
    # --- Bulk Delete Operations ---

    def handle_delete_folder_bulk(self, items_data):
        if ThemeDialog.confirm(self.mw, "Confirm", "Delete folder and all contents?"):
            for data in items_data:
                DBManager(data['db_path']).delete_folder(data['id'])
            self.refresh_tree()

    def handle_delete_curve_bulk(self, items_data):
        if ThemeDialog.confirm(self.mw, "Confirm", "Delete selected curve(s)?"):
            for data in items_data:
                DBManager(data['db_path']).delete_curve(data['id'])
            self.refresh_tree()

    def handle_delete_bulk(self, items_data):
        if ThemeDialog.confirm(self.mw, "Confirm Bulk Delete", f"Delete {len(items_data)} selected items?"):
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

            if data['type'] == 'well':
                tables_node = QTreeWidgetItem(item)
                tables_node.setText(0, "Tables")
                tables_node.setText(1, "Group")
                tables_node.setText(2, "")
                tables_node.setData(0, Qt.UserRole, {
                    'type': 'table_group',
                    'id': f"tables:{well_id}",
                    'name': "Tables",
                    'well_id': well_id,
                    'db_path': db_path,
                    'loaded': True,
                })
                tables_node.setIcon(0, self._table_group_icon())

                fracture_rows = db.get_fracture_interpretations(well_id)
                if fracture_rows:
                    fracture_node = QTreeWidgetItem(tables_node)
                    fracture_node.setText(0, "Fracture Picks")
                    fracture_node.setText(1, "Table")
                    fracture_node.setText(2, f"{len(fracture_rows)} rows")
                    fracture_node.setData(0, Qt.UserRole, {
                        'type': 'fracture_table',
                        'id': f"fracture_table:{well_id}",
                        'name': "Fracture Picks",
                        'well_id': well_id,
                        'db_path': db_path,
                        'loaded': True,
                    })
                    fracture_node.setIcon(0, self._table_group_icon())
            
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
