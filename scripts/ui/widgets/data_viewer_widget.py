import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QWidget,
    QVBoxLayout,
    QTableView,
    QMenu,
    QGraphicsOpacityEffect,
    QSizePolicy,
)
from PySide6.QtCore import QItemSelection, QItemSelectionModel

from core.app_config import app_config
from scripts.data.db_manager import DBManager
from scripts.data.table_data import MultiCurveTableModel, MultiCurveDataFetchWorker, copy_table_selection_to_clipboard
from scripts.ui.curve_table_helpers import (
    apply_empty_curve_table_layout,
    configure_curve_table_view,
    enable_styled_background,
    install_corner_select_all,
    install_copy_shortcut,
    resize_index_and_depth_columns,
)
from scripts.ui.floating_scrollbar import FloatingScrollbarManager
from scripts.ui.base_dialog import ThemeDialog
from scripts.ui.theme_manager import ThemeManager


class DataViewerWidget(QWidget):
    """MDI widget for curve table viewing and comparison."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("curveTableRoot")
        enable_styled_background(self)
        self.setAcceptDrops(True)
        self.model = MultiCurveTableModel(self)
        self._workers = []
        self._curve_entries = []
        self._depth_union = np.array([], dtype=float)
        self._header_selection_snapshot = None
        self._header_current_index_snapshot = None
        self._dirty = False
        self._baseline_columns = []
        self._setup_ui()
        self.update_theme()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(0)

        self.table = QTableView()
        self.table.setModel(self.model)
        self._header = _DataViewerHeaderView(Qt.Horizontal, self.table, self)
        self.table.setHorizontalHeader(self._header)
        configure_curve_table_view(
            self.table,
            default_section_size=120,
            minimum_section_size=24,
            editable=True,
            on_context_menu=self._show_context_menu,
            on_header_context_menu=self._show_header_context_menu,
        )
        self.table.pressed.connect(self._handle_table_press)
        self.model.dataChanged.connect(self._on_model_data_changed)
        install_corner_select_all(self.table)
        layout.addWidget(self.table)

        self.actions_pill = _FloatingActionPill(self)
        self.actions_pill.save_requested.connect(self.save_changes)
        self.actions_pill.reset_requested.connect(self.reset_changes)
        self.actions_pill.hide()

        self.copy_shortcut = install_copy_shortcut(self, self.copy_selection)

        self.sb_mgr = FloatingScrollbarManager(self.table)
        self._apply_empty_table_layout()
        self._update_actions_state()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_V and event.modifiers() & Qt.ControlModifier:
            if self.paste_from_clipboard():
                event.accept()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-pylog-curve"):
            event.ignore()
            return
        if not self._confirm_discard_changes("Add more curves to this Data Viewer?"):
            event.ignore()
            return

        raw_data = event.mimeData().data("application/x-pylog-curve").data().decode("utf-8")
        payloads = [chunk for chunk in raw_data.split("|") if chunk]
        accepted = 0
        for payload in payloads:
            parts = payload.split(":")
            if len(parts) < 3:
                continue
            try:
                well_id = int(parts[0])
                curve_id = int(parts[1])
                db_path = ":".join(parts[2:])
            except ValueError:
                continue
            if self._has_curve(db_path, well_id, curve_id):
                ThemeDialog.message(self, "Data Viewer", f"Curve {curve_id} is already in the viewer.", icon_type="info")
                continue
            self.add_curve_request(well_id, curve_id, db_path)
            accepted += 1

        if accepted:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _has_curve(self, db_path, well_id, curve_id):
        key = (db_path, well_id, curve_id)
        return any((entry["db_path"], entry["well_id"], entry["curve_id"]) == key for entry in self._curve_entries)

    @staticmethod
    def _resolve_well_name(db, well_id):
        for wid, name in db.get_wells():
            if wid == well_id:
                return name
        return f"Well {well_id}"

    @staticmethod
    def _build_folder_path(db, folder_id):
        if not folder_id:
            return ""

        segments = []
        current_id = folder_id
        visited = set()
        while current_id and current_id not in visited:
            visited.add(current_id)
            folder_row = db.get_folder(current_id)
            if not folder_row:
                break
            _fid, _well_id, name, parent_id = folder_row
            segments.append(name)
            current_id = parent_id
        return "/".join(reversed(segments))

    @staticmethod
    def _build_curve_tooltip(well_name, curve_name, folder_path=""):
        tooltip = f"{well_name}/{curve_name}"
        if folder_path:
            tooltip = f"{well_name}/{folder_path}/{curve_name}"
        return tooltip

    def add_curve_request(self, well_id, curve_id, db_path, well_name=None, curve_name=None):
        if not db_path:
            ThemeDialog.message(self, "Data Viewer", "Curve source database is missing.", icon_type="warning")
            return

        if well_name is None or curve_name is None:
            from scripts.data.db_manager import DBManager

            db = DBManager(db_path)
            well_name = self._resolve_well_name(db, well_id)
            meta = db.get_curve_metadata(curve_id)
            curve_name = meta[1] if meta else f"Curve {curve_id}"

        worker = MultiCurveDataFetchWorker(db_path, well_id, curve_id, well_name, curve_name)
        worker.signals.finished.connect(self._on_curve_loaded)
        worker.signals.error.connect(self._on_curve_error)
        worker.finished.connect(lambda: self._cleanup_worker(worker))
        self._workers.append(worker)
        worker.start()

    def _cleanup_worker(self, worker):
        self._workers = [w for w in self._workers if w is not worker]

    def _build_entry_from_payload(self, payload):
        folder_path = payload.get("folder_path", "")
        folder_name = folder_path.split("/")[-1] if folder_path else ""
        return {
            "db_path": payload["db_path"],
            "well_id": payload["well_id"],
            "curve_id": payload["curve_id"],
            "well_name": payload["well_name"],
            "curve_name": payload["curve_name"],
            "unit": payload.get("unit", ""),
            "label": payload["curve_name"],
            "tooltip": self._build_curve_tooltip(payload["well_name"], payload["curve_name"], folder_path),
            "folder_path": folder_path,
            "folder_name": folder_name,
            "depth": np.asarray(payload["depth"], dtype=float),
            "data": np.asarray(payload["data"]),
        }

    def _resolve_main_window(self):
        window = self.window()
        while window is not None:
            if hasattr(window, "new_data_viewer_window"):
                return window
            window = window.parent()
        return None

    def _open_entry_in_new_viewer(self, entry):
        main_window = self._resolve_main_window()
        if main_window is None:
            ThemeDialog.message(
                self,
                "Data Viewer",
                "This curve uses a different depth index and needs a new Data Viewer page.",
                icon_type="info",
            )
            return False
        new_widget = main_window.new_data_viewer_window()
        if not new_widget:
            return False
        new_widget._append_loaded_entry(entry, allow_redirect=False)
        try:
            main_window.statusBar().showMessage(
                f"Data Viewer: opened '{entry['curve_name']}' in a new page because its depth index differs.",
                4000,
            )
        except Exception:
            pass
        return True

    def _redirect_entry_to_new_viewer(self, entry, reason_message):
        if self._open_entry_in_new_viewer(entry):
            return False
        ThemeDialog.message(
            self,
            "Data Viewer",
            reason_message,
            icon_type="info",
        )
        return False

    @staticmethod
    def _shares_folder_depth_source(reference_entry, incoming_entry):
        return (
            reference_entry.get("db_path") == incoming_entry.get("db_path")
            and reference_entry.get("well_id") == incoming_entry.get("well_id")
            and (reference_entry.get("folder_path") or "") == (incoming_entry.get("folder_path") or "")
        )

    def _should_save_on_view_depth_axis(self, entry):
        if not self._curve_entries:
            return False
        reference_entry = self._curve_entries[0]
        if not self._shares_folder_depth_source(reference_entry, entry):
            return False
        reference_depth = np.asarray(self._depth_union, dtype=np.float32)
        source_depth = np.asarray(entry.get("depth", []), dtype=np.float32)
        return not self._depth_values_match(reference_depth, source_depth)

    def _append_loaded_entry(self, entry, allow_redirect=True):
        if entry["data"].ndim > 1 and self._curve_entries:
            if allow_redirect:
                return self._redirect_entry_to_new_viewer(
                    entry,
                    "2D curves can currently be viewed in Data Viewer only when opened alone on the page.",
                )
            ThemeDialog.message(
                self,
                "Data Viewer",
                "2D curves can currently be viewed in Data Viewer only when opened alone on the page.",
                icon_type="info",
            )
            return False
        if entry["data"].ndim == 1 and any(existing["data"].ndim > 1 for existing in self._curve_entries):
            if allow_redirect:
                return self._redirect_entry_to_new_viewer(
                    entry,
                    "This page already contains a 2D curve. Please use a new Data Viewer page for 1D/2D mixed viewing.",
                )
            ThemeDialog.message(
                self,
                "Data Viewer",
                "This page already contains a 2D curve. Please use a new Data Viewer page for 1D/2D mixed viewing.",
                icon_type="info",
            )
            return False
        if (
            entry["data"].ndim == 1
            and self._curve_entries
            and all(existing["data"].ndim == 1 for existing in self._curve_entries)
        ):
            reference_entry = self._curve_entries[0]
            same_depth_source = self._shares_folder_depth_source(reference_entry, entry)
            if not same_depth_source:
                reference_depth = np.asarray(reference_entry["depth"], dtype=np.float32)
                incoming_depth = np.asarray(entry["depth"], dtype=np.float32)
                same_depth_source = self._depth_values_match(reference_depth, incoming_depth)
            if not same_depth_source:
                if allow_redirect and self._open_entry_in_new_viewer(entry):
                    return False
                ThemeDialog.message(
                    self,
                    "Data Viewer",
                    "This curve uses a different depth index and needs its own Data Viewer page.",
                    icon_type="info",
                )
                return False
        self._curve_entries.append(entry)
        self._rebuild_model()
        return True

    def _on_curve_loaded(self, payload):
        self._append_loaded_entry(self._build_entry_from_payload(payload))

    def _on_curve_error(self, message):
        ThemeDialog.message(self, "Data Viewer", message, icon_type="warning")

    def _rebuild_model(self):
        if not self._curve_entries:
            self._depth_union = np.array([], dtype=float)
            self.model.reset_data()
            self._baseline_columns = []
            self._set_dirty(False)
            self._apply_empty_table_layout()
            self._update_actions_state()
            return

        if len(self._curve_entries) == 1 and self._curve_entries[0]["data"].ndim > 1:
            entry = self._curve_entries[0]
            columns = []
            data_2d = entry["data"]
            for idx in range(data_2d.shape[1]):
                columns.append({
                    "label": f"{idx + 1}",
                    "tooltip": f"{entry.get('tooltip', entry['label'])} / slice {idx + 1}",
                    "folder_name": "",
                    "values": data_2d[:, idx],
                    "db_path": entry["db_path"],
                    "well_id": entry["well_id"],
                    "curve_id": entry["curve_id"],
                })
            self._depth_union = np.asarray(entry["depth"], dtype=float)
            self.model.set_viewer_data(self._depth_union, columns)
            self._refresh_baseline_from_model()
            self._apply_data_column_widths()
            self._resize_index_and_depth_columns()
            return

        if len(self._curve_entries) == 1 and self._curve_entries[0]["data"].ndim == 1:
            entry = self._curve_entries[0]
            self._depth_union = np.asarray(entry["depth"], dtype=float)
            columns = [{
                "label": entry["label"],
                "tooltip": entry.get("tooltip", entry["label"]),
                "folder_name": entry.get("folder_name", ""),
                "values": list(np.asarray(entry["data"], dtype=float)),
                "db_path": entry["db_path"],
                "well_id": entry["well_id"],
                "curve_id": entry["curve_id"],
            }]
            self.model.set_viewer_data(self._depth_union, columns)
            self._refresh_baseline_from_model()
            self._apply_data_column_widths()
            self._resize_index_and_depth_columns()
            return

        reference_depth = np.asarray(self._curve_entries[0]["depth"], dtype=float)
        columns = []
        for entry in self._curve_entries:
            columns.append({
                "label": entry["label"],
                "tooltip": entry.get("tooltip", entry["label"]),
                "folder_name": entry.get("folder_name", ""),
                "values": list(np.asarray(entry["data"], dtype=float)),
                "db_path": entry["db_path"],
                "well_id": entry["well_id"],
                "curve_id": entry["curve_id"],
            })

        self._depth_union = reference_depth
        self.model.set_viewer_data(reference_depth, columns)
        self._refresh_baseline_from_model()
        self._apply_data_column_widths()
        self._resize_index_and_depth_columns()

    def _apply_empty_table_layout(self):
        apply_empty_curve_table_layout(self.table)

    def _apply_data_column_widths(self):
        default_width = 96
        for column in range(2, self.model.columnCount()):
            self.table.setColumnWidth(column, default_width)

    def _resize_index_and_depth_columns(self):
        resize_index_and_depth_columns(self.table, self._depth_union)

    def clear_data(self):
        if not self._confirm_discard_changes("Clear all curves from this Data Viewer?"):
            return
        self._curve_entries.clear()
        self._rebuild_model()

    def load_single_curve_data(self, well_name, curve_name, depth, data, folder_path=""):
        if not self._confirm_discard_changes("Replace the current Data Viewer content?"):
            return
        folder_name = folder_path.split("/")[-1] if folder_path else ""

        self._curve_entries = [{
            "db_path": "",
            "well_id": None,
            "curve_id": None,
            "well_name": well_name,
            "curve_name": curve_name,
            "label": curve_name,
            "tooltip": self._build_curve_tooltip(well_name, curve_name, folder_path),
            "folder_path": folder_path,
            "folder_name": folder_name,
            "depth": np.asarray(depth, dtype=float),
            "data": np.asarray(data),
        }]
        self._rebuild_model()

    def remove_selected_columns(self):
        remove_indexes = self._selected_curve_column_indexes()
        if not remove_indexes:
            ThemeDialog.message(self, "Data Viewer", "Select one or more curve columns to remove.", icon_type="info")
            return
        if not self._confirm_discard_changes("Remove the selected curve columns from this Data Viewer?"):
            return
        for idx in remove_indexes:
            if 0 <= idx < len(self._curve_entries):
                self._curve_entries.pop(idx)
        self._rebuild_model()

    def copy_selection(self):
        copy_table_selection_to_clipboard(self.table, self.model)

    def paste_from_clipboard(self):
        text = QApplication.clipboard().text()
        if not text:
            return False

        current = self.table.currentIndex()
        if not current.isValid():
            return False
        start_row = current.row()
        start_col = max(2, current.column())

        rows = [row for row in text.replace("\r\n", "\n").split("\n") if row.strip()]
        if not rows:
            return False

        sep = "\t" if "\t" in rows[0] else ("," if "," in rows[0] else None)

        def split_row(raw):
            if sep:
                return raw.split(sep)
            return [part for part in raw.split(" ") if part]

        changed = False
        pasted_top_left = None
        pasted_bottom_right = None
        for row_offset, raw_row in enumerate(rows):
            target_row = start_row + row_offset
            if target_row >= self.model.rowCount():
                break
            values = split_row(raw_row)
            for col_offset, raw_val in enumerate(values):
                target_col = start_col + col_offset
                if target_col >= self.model.columnCount():
                    break
                if target_col <= 1:
                    continue
                index = self.model.index(target_row, target_col)
                if not (self.model.flags(index) & Qt.ItemIsEditable):
                    continue
                if self.model.setData(index, raw_val, Qt.EditRole):
                    changed = True
                    if pasted_top_left is None:
                        pasted_top_left = index
                    pasted_bottom_right = index

        if changed and pasted_top_left is not None and pasted_bottom_right is not None:
            selection_model = self.table.selectionModel()
            if selection_model is not None:
                selection = QItemSelection(pasted_top_left, pasted_bottom_right)
                selection_model.clearSelection()
                selection_model.select(selection, QItemSelectionModel.ClearAndSelect)
                selection_model.setCurrentIndex(pasted_top_left, QItemSelectionModel.NoUpdate)
                self.table.scrollTo(pasted_top_left, QTableView.PositionAtCenter)
        return changed

    def _selected_curve_column_indexes(self):
        columns = {index.column() for index in self.table.selectionModel().selectedIndexes()}
        return sorted({column - 2 for column in columns if column > 1}, reverse=True)

    def _select_column_from_header(self, section):
        if section < 0:
            return
        self.table.selectColumn(section)
        self.table.setFocus()

    def _capture_selection_snapshot(self):
        selection_model = self.table.selectionModel()
        if selection_model is None:
            self._header_selection_snapshot = None
            self._header_current_index_snapshot = None
            return
        self._header_selection_snapshot = selection_model.selection()
        self._header_current_index_snapshot = selection_model.currentIndex()

    def _restore_selection_snapshot(self):
        selection_model = self.table.selectionModel()
        if selection_model is None:
            return
        selection_model.clearSelection()
        if self._header_selection_snapshot:
            selection_model.select(self._header_selection_snapshot, selection_model.SelectionFlag.Select)
        if self._header_current_index_snapshot and self._header_current_index_snapshot.isValid():
            selection_model.setCurrentIndex(
                self._header_current_index_snapshot,
                selection_model.SelectionFlag.NoUpdate,
            )

    def _toggle_header_label(self, section):
        if section < 0:
            return
        self.model.toggle_header_expanded(section)

    def _handle_table_press(self, index):
        if not index.isValid():
            return
        if index.column() == 0:
            self.table.selectRow(index.row())
            self.table.setFocus()

    def _on_model_data_changed(self, top_left, bottom_right, roles):
        if top_left.column() <= 1:
            return
        self._set_dirty(self._compute_is_dirty())

    def _compute_is_dirty(self):
        return bool(self._get_modified_column_indexes())

    def _get_modified_column_indexes(self):
        modified = []
        if len(self.model.columns) != len(self._baseline_columns):
            return list(range(len(self.model.columns)))
        for idx, (current, baseline) in enumerate(zip(self.model.columns, self._baseline_columns)):
            if self._column_values_differ(current.get("values", []), baseline.get("values", [])):
                modified.append(idx)
        return modified

    @staticmethod
    def _column_values_differ(current_values, baseline_values):
        if len(current_values) != len(baseline_values):
            return True
        for cur_val, base_val in zip(current_values, baseline_values):
            if cur_val is None and base_val is None:
                continue
            if cur_val is None or base_val is None:
                return True
            if float(cur_val) != float(base_val):
                return True
        return False

    @staticmethod
    def _clone_columns(columns):
        clones = []
        for column in columns:
            cloned = dict(column)
            cloned["values"] = list(column.get("values", []))
            clones.append(cloned)
        return clones

    def _refresh_baseline_from_model(self):
        self._baseline_columns = self._clone_columns(self.model.columns)
        self._set_dirty(False)

    def _set_dirty(self, dirty):
        self._dirty = bool(dirty)
        self._update_actions_state()

    def _update_actions_state(self):
        has_content = self.model.columnCount() > 2
        self.actions_pill.setVisible(has_content)
        self.actions_pill.set_dirty(self._dirty)
        self.actions_pill.setEnabled(has_content)
        self.actions_pill.adjustSize()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "actions_pill") and self.actions_pill:
            x = max(10, self.width() - self.actions_pill.width() - 18)
            y = max(10, self.height() - self.actions_pill.height() - 18)
            self.actions_pill.move(x, y)
            self.actions_pill.raise_()

    def _confirm_discard_changes(self, action_text):
        if not self._dirty:
            return True
        return ThemeDialog.confirm(
            self,
            "Unsaved Changes",
            f"You have unsaved edits.\n\n{action_text}\n\nDiscard the current edits?",
        )

    def reset_changes(self):
        if not self._dirty:
            return
        if not ThemeDialog.confirm(self, "Reset Changes", "Discard all unsaved edits and restore the current viewer data?"):
            return
        self.model.beginResetModel()
        self.model.columns = self._clone_columns(self._baseline_columns)
        self.model._cache = {}
        self.model.endResetModel()
        self._set_dirty(False)

    def _can_save_current_view(self):
        if self._dirty is False:
            return False, "There are no unsaved edits to save."
        modified_columns = self._get_modified_column_indexes()
        if not modified_columns:
            return False, "There are no modified 1D curve columns to save."
        for idx in modified_columns:
            if idx >= len(self._curve_entries):
                return False, "The current viewer layout cannot be saved yet."
            entry = self._curve_entries[idx]
            if np.asarray(entry["data"]).ndim != 1:
                return False, "Saving 2D curve edits is not supported yet."
            if not entry.get("db_path") or entry.get("well_id") is None:
                return False, "One or more edited curves do not have a source database for saving."
        return True, ""

    def save_changes(self):
        can_save, message = self._can_save_current_view()
        if not can_save:
            ThemeDialog.message(self, "Data Viewer", message, icon_type="info")
            return
        modified_columns = self._build_modified_column_payloads()
        if not modified_columns:
            ThemeDialog.message(self, "Data Viewer", "There are no modified 1D curve columns to save.", icon_type="info")
            return

        if len(modified_columns) == 1:
            save_requests = self._collect_single_save_request(modified_columns[0])
        else:
            dialog = _BatchSaveCurvesDialog(self, modified_columns)
            if dialog.exec() != QDialog.Accepted:
                return
            save_requests = dialog.values()

        if not save_requests:
            return

        saved_indexes = []
        skipped = 0
        failures = []
        for request in save_requests:
            try:
                save_result = self._save_modified_curve_request(request)
                if save_result:
                    self._apply_saved_curve_result(request, save_result)
                    saved_indexes.append(request["column_index"])
                else:
                    skipped += 1
            except Exception as exc:
                failures.append(f"{request['curve_name']}: {exc}")

        if saved_indexes:
            self._refresh_baseline_for_columns(saved_indexes)
            self._set_dirty(self._compute_is_dirty())
            self._refresh_explorer_tree()

        summary_parts = []
        if saved_indexes:
            summary_parts.append(f"Saved {len(saved_indexes)} curve(s)")
        if skipped:
            summary_parts.append(f"skipped {skipped}")
        if failures:
            summary_parts.append(f"failed {len(failures)}")
        summary = ", ".join(summary_parts) if summary_parts else "No curves were saved."
        if failures:
            summary += "\n\n" + "\n".join(failures[:5])
        ThemeDialog.message(self, "Data Viewer", summary, icon_type="info")

    def _build_modified_column_payloads(self):
        payloads = []
        for idx in self._get_modified_column_indexes():
            if idx >= len(self._curve_entries) or idx >= len(self.model.columns):
                continue
            entry = self._curve_entries[idx]
            if np.asarray(entry["data"]).ndim != 1:
                continue
            payloads.append({
                "column_index": idx,
                "db_path": entry["db_path"],
                "well_id": entry["well_id"],
                "curve_id": entry["curve_id"],
                "well_name": entry["well_name"],
                "curve_name": entry["curve_name"],
                "default_name": self._build_default_save_name(entry["curve_name"]),
                "folder_path": entry.get("folder_path", ""),
                "folder_name": entry.get("folder_name", ""),
                "unit": entry.get("unit", ""),
                "values": list(self.model.columns[idx].get("values", [])),
                "source_depth_values": np.asarray(entry["depth"], dtype=np.float32),
                "depth_values": np.asarray(self._depth_union, dtype=np.float32),
                "save_on_view_depth_axis": self._should_save_on_view_depth_axis(entry),
            })
        return payloads

    def _collect_single_save_request(self, payload):
        dialog = _SaveCurveDialog(
            self,
            well_name=payload["well_name"],
            default_name=payload["default_name"],
            folder_path=payload.get("folder_path", ""),
        )
        if dialog.exec() != QDialog.Accepted:
            return []
        curve_name = dialog.value()
        request = dict(payload)
        request["target_name"] = curve_name
        return [request]

    def _save_modified_curve_request(self, request):
        db = DBManager(request["db_path"])
        target_folder_id = self._find_folder_id_by_path(db, request["well_id"], request.get("folder_path", ""))
        target_name = request["target_name"]
        source_curve_id = request["curve_id"]

        existing_curve_id = self._find_existing_curve_id(db, request["well_id"], target_name, target_folder_id)
        overwriting_source_curve = existing_curve_id is not None and existing_curve_id == source_curve_id
        if existing_curve_id is not None:
            if not ThemeDialog.confirm(
                self,
                "Overwrite Curve",
                f"Curve '{target_name}' already exists in the target folder.\n\nOverwrite it with the edited data?",
            ):
                return False
            db.delete_curve(existing_curve_id)

        _save_depth_values, save_data = self._build_curve_save_arrays(request)
        db.save_curve(request["well_id"], target_name, request["unit"], save_data, folder_id=target_folder_id)
        saved_curve_id = source_curve_id if overwriting_source_curve else self._find_existing_curve_id(
            db,
            request["well_id"],
            target_name,
            target_folder_id,
        )
        if saved_curve_id is None:
            raise RuntimeError(f"Saved curve '{target_name}' could not be resolved after write.")
        return {
            "curve_id": saved_curve_id,
            "curve_name": target_name,
            "folder_id": target_folder_id,
            "folder_path": request.get("folder_path", ""),
            "overwrote_source": overwriting_source_curve,
            "data": np.asarray(save_data, dtype=float),
        }

    def _apply_saved_curve_result(self, request, result):
        column_index = request["column_index"]
        if column_index >= len(self._curve_entries) or column_index >= len(self.model.columns):
            return

        entry = dict(self._curve_entries[column_index])
        entry["curve_id"] = result["curve_id"]
        entry["curve_name"] = result["curve_name"]
        entry["label"] = result["curve_name"]
        entry["folder_path"] = result.get("folder_path", entry.get("folder_path", ""))
        entry["folder_name"] = entry["folder_path"].split("/")[-1] if entry["folder_path"] else ""
        entry["tooltip"] = self._build_curve_tooltip(entry["well_name"], entry["curve_name"], entry["folder_path"])
        entry["depth"] = np.asarray(self._depth_union, dtype=float)
        entry["data"] = np.asarray(result["data"], dtype=float)
        self._curve_entries[column_index] = entry

        self.model.columns[column_index]["label"] = entry["label"]
        self.model.columns[column_index]["tooltip"] = entry["tooltip"]
        self.model.columns[column_index]["folder_name"] = entry["folder_name"]
        self.model.columns[column_index]["values"] = list(self._normalize_curve_model_values(entry["data"]))

    @staticmethod
    def _normalize_curve_model_values(values):
        normalized = []
        for value in np.asarray(values, dtype=float):
            normalized.append(None if not np.isfinite(value) else float(value))
        return normalized

    @staticmethod
    def _depth_key(depth):
        return round(float(depth), 8)

    @staticmethod
    def _normalize_curve_save_values(values):
        return np.asarray([np.nan if value is None else float(value) for value in values], dtype=np.float32)

    def _is_source_aligned_view(self, union_depths, source_depths, values):
        return (
            len(union_depths) == len(source_depths) == len(values)
            and self._depth_values_match(union_depths, source_depths)
        )

    def _build_source_aligned_save_arrays(self, source_depths, values):
        return np.asarray(source_depths, dtype=np.float32), self._normalize_curve_save_values(values)

    def _build_compare_aligned_save_arrays(self, union_depths, source_depths, values):
        # Preserve the curve's original sampling axis when saving edited compare columns.
        source_depth_keys = {self._depth_key(depth) for depth in source_depths}
        save_depths = []
        save_values = []
        for depth, value in zip(union_depths, values):
            if self._depth_key(depth) not in source_depth_keys:
                continue
            save_depths.append(float(depth))
            save_values.append(np.nan if value is None else float(value))

        if not save_depths:
            save_depths = [float(depth) for depth in source_depths]
            save_values = [np.nan] * len(save_depths)

        return np.asarray(save_depths, dtype=np.float32), np.asarray(save_values, dtype=np.float32)

    def _build_curve_save_arrays(self, request):
        union_depths = np.asarray(request["depth_values"], dtype=np.float32)
        source_depths = np.asarray(request.get("source_depth_values", []), dtype=np.float32)
        values = list(request["values"])

        if request.get("save_on_view_depth_axis"):
            return self._build_source_aligned_save_arrays(union_depths, values)

        if self._is_source_aligned_view(union_depths, source_depths, values):
            return self._build_source_aligned_save_arrays(source_depths, values)

        return self._build_compare_aligned_save_arrays(union_depths, source_depths, values)

    def _refresh_baseline_for_columns(self, saved_indexes):
        for idx in saved_indexes:
            if idx < len(self._baseline_columns) and idx < len(self.model.columns):
                self._baseline_columns[idx] = self._clone_columns([self.model.columns[idx]])[0]

    @staticmethod
    def _depth_values_match(existing_depths, requested_depths, tolerance=1e-6):
        existing = np.asarray(existing_depths, dtype=np.float32)
        requested = np.asarray(requested_depths, dtype=np.float32)
        if existing.shape != requested.shape:
            return False
        if existing.size == 0 and requested.size == 0:
            return True
        return np.allclose(existing, requested, rtol=0.0, atol=tolerance, equal_nan=True)

    @staticmethod
    def _build_default_save_name(curve_name):
        base = f"{curve_name}_edit"
        return base

    def _find_folder_id_by_path(self, db, well_id, folder_path):
        cleaned = (folder_path or "").strip().strip("/")
        if not cleaned:
            return None
        parent_id = None
        existing = {(name, pid): fid for fid, name, pid in db.get_folders(well_id)}
        for segment in [part.strip() for part in cleaned.split("/") if part.strip()]:
            key = (segment, parent_id)
            folder_id = existing.get(key)
            if folder_id is None:
                return None
            parent_id = folder_id
        return parent_id

    @staticmethod
    def _find_existing_curve_id(db, well_id, curve_name, folder_id):
        for row in db.get_curves(well_id):
            candidate_id, candidate_name, _unit, _shape, candidate_folder_id = row[:5]
            if candidate_name == curve_name and candidate_folder_id == folder_id:
                return candidate_id
        return None

    def closeEvent(self, event: QCloseEvent):
        if not self._confirm_discard_changes("Close this Data Viewer?"):
            event.ignore()
            return
        super().closeEvent(event)

    def _refresh_explorer_tree(self):
        window = self.window()
        while window is not None:
            controller = getattr(window, "tree_controller", None)
            if controller and hasattr(controller, "refresh_tree"):
                controller.refresh_tree()
                return
            if hasattr(window, "populate_tree"):
                window.populate_tree()
                return
            window = window.parent()

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        copy_action = menu.addAction("Copy")
        remove_action = menu.addAction("Remove Selected")
        clear_action = menu.addAction("Clear")

        has_cells = bool(self.table.selectionModel().selectedIndexes())
        has_curve_columns = bool(self._selected_curve_column_indexes())
        copy_action.setEnabled(has_cells)
        remove_action.setEnabled(has_curve_columns)
        clear_action.setEnabled(bool(self._curve_entries))

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == copy_action:
            self.copy_selection()
        elif chosen == remove_action:
            self.remove_selected_columns()
        elif chosen == clear_action:
            self.clear_data()

    def _show_header_context_menu(self, pos):
        section = self.table.horizontalHeader().logicalIndexAt(pos)
        if section >= 0:
            self._select_column_from_header(section)
        mapped = self.table.viewport().mapFromGlobal(self.table.horizontalHeader().mapToGlobal(pos))
        self._show_context_menu(mapped)

    def update_theme(self):
        ThemeManager.apply_curve_table_surface(self)
        self.style().unpolish(self)
        self.style().polish(self)
        if hasattr(self, "sb_mgr"):
            self.sb_mgr.update_theme()


class _DataViewerHeaderView(QHeaderView):
    _HEADER_CLICK_DELAY_MS = 110
    _RESIZE_HANDLE_MARGIN_PX = 5

    def __init__(self, orientation, parent, owner):
        super().__init__(orientation, parent)
        self._owner = owner
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._apply_pending_single_click)
        self._pending_section = None
        self._pressed_section = None
        self._suppress_release_selection = False
        self.setSectionsClickable(False)
        self.setHighlightSections(False)

    def _is_near_resize_handle(self, pos):
        section = self.logicalIndexAt(pos)
        if section < 0:
            return False
        x = pos.x()
        left = self.sectionViewportPosition(section)
        right = left + self.sectionSize(section)
        if abs(x - right) <= self._RESIZE_HANDLE_MARGIN_PX:
            return True
        if section > 0 and abs(x - left) <= self._RESIZE_HANDLE_MARGIN_PX:
            return True
        return False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_near_resize_handle(event.position().toPoint()):
                self._pressed_section = None
                super().mousePressEvent(event)
                return
            self._pressed_section = self.logicalIndexAt(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_near_resize_handle(event.position().toPoint()):
                self._pressed_section = None
                super().mouseReleaseEvent(event)
                return
            if self._suppress_release_selection:
                self._suppress_release_selection = False
                self._pressed_section = None
                event.accept()
                return
            section = self.logicalIndexAt(event.position().toPoint())
            if section >= 0 and section == self._pressed_section:
                self._owner._capture_selection_snapshot()
                self._pending_section = section
                self._click_timer.start(max(1, self._HEADER_CLICK_DELAY_MS))
                self._pressed_section = None
                event.accept()
                return
            self._pressed_section = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self._is_near_resize_handle(event.position().toPoint()):
                self._pressed_section = None
                super().mouseDoubleClickEvent(event)
                return
            section = self.logicalIndexAt(event.position().toPoint())
            self._click_timer.stop()
            self._pending_section = None
            self._pressed_section = None
            self._suppress_release_selection = True
            if section >= 0:
                self._owner._restore_selection_snapshot()
                self._owner._toggle_header_label(section)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def _apply_pending_single_click(self):
        if self._pending_section is None:
            return
        section = self._pending_section
        self._pending_section = None
        self._owner._select_column_from_header(section)


class _FloatingActionPill(QWidget):
    save_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dataViewerActionPill")
        self.setAttribute(Qt.WA_StyledBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        self.reset_button = QPushButton("Reset")
        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.reset_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.save_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.reset_button.clicked.connect(self.reset_requested.emit)
        self.save_button.clicked.connect(self.save_requested.emit)
        layout.addWidget(self.reset_button)
        layout.addWidget(self.save_button)

        self.opacity_effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity_effect)
        self.set_dirty(False)
        self.adjustSize()

    def set_dirty(self, dirty):
        active = bool(dirty)
        self.reset_button.setEnabled(active)
        self.save_button.setEnabled(active)
        self.opacity_effect.setOpacity(1.0 if active else 0.45)


class _SaveCurveDialog(ThemeDialog):
    def __init__(self, parent=None, *, well_name="", default_name="", folder_path=""):
        super().__init__(parent)
        self.setWindowTitle("Save Edited Curve")
        self.resize(420, 190)

        layout = QVBoxLayout()
        self.setLayout(layout)

        info = QLabel(f"Save edited data as a new curve in '{well_name}'.")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.name_edit = QLineEdit(default_name)
        self.name_edit.setPlaceholderText("Curve name")
        layout.addWidget(QLabel("Curve Name"))
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("Folder"))
        folder_label = QLabel(folder_path or "(root)")
        folder_label.setObjectName("dataViewerSaveFolderLabel")
        folder_label.setWordWrap(True)
        layout.addWidget(folder_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._handle_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _handle_accept(self):
        if not self.name_edit.text().strip():
            ThemeDialog.message(self, "Save Edited Curve", "Curve name cannot be empty.", icon_type="warning")
            return
        self.accept()

    def value(self):
        return self.name_edit.text().strip()


class _BatchSaveCurvesDialog(ThemeDialog):
    def __init__(self, parent=None, payloads=None):
        super().__init__(parent)
        self.setWindowTitle("Save Edited Curves")
        self.resize(640, 420)
        self._rows = []

        layout = QVBoxLayout()
        self.setLayout(layout)

        intro = QLabel("Save each modified 1D curve back to its source well and folder as a new curve.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        headers = ["Save", "Curve Name", "Well", "Folder"]
        for col, title in enumerate(headers):
            label = QLabel(title)
            label.setStyleSheet("font-weight: bold;")
            grid.addWidget(label, 0, col)

        for row_idx, payload in enumerate(payloads or [], start=1):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            name_edit = QLineEdit(payload["default_name"])
            well_label = QLabel(payload["well_name"])
            folder_label = QLabel(payload.get("folder_path", "") or "(root)")
            grid.addWidget(checkbox, row_idx, 0)
            grid.addWidget(name_edit, row_idx, 1)
            grid.addWidget(well_label, row_idx, 2)
            grid.addWidget(folder_label, row_idx, 3)
            self._rows.append({
                "payload": payload,
                "checkbox": checkbox,
                "name_edit": name_edit,
            })

        scroll.setWidget(container)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._handle_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _handle_accept(self):
        selected_count = 0
        for row in self._rows:
            if not row["checkbox"].isChecked():
                continue
            selected_count += 1
            if not row["name_edit"].text().strip():
                ThemeDialog.message(self, "Save Edited Curves", "Curve names cannot be empty.", icon_type="warning")
                return
        if selected_count == 0:
            ThemeDialog.message(self, "Save Edited Curves", "Select at least one modified curve to save.", icon_type="warning")
            return
        self.accept()

    def values(self):
        results = []
        for row in self._rows:
            if not row["checkbox"].isChecked():
                continue
            payload = dict(row["payload"])
            payload["target_name"] = row["name_edit"].text().strip()
            results.append(payload)
        return results
