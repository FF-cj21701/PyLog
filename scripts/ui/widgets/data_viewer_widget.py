import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHeaderView,
    QWidget,
    QVBoxLayout,
    QTableView,
    QMenu,
)

from core.app_config import app_config
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
            on_context_menu=self._show_context_menu,
            on_header_context_menu=self._show_header_context_menu,
        )
        self.table.pressed.connect(self._handle_table_press)
        install_corner_select_all(self.table)
        layout.addWidget(self.table)

        self.copy_shortcut = install_copy_shortcut(self, self.copy_selection)

        self.sb_mgr = FloatingScrollbarManager(self.table)
        self._apply_empty_table_layout()

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat("application/x-pylog-curve"):
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

    def _on_curve_loaded(self, payload):
        folder_path = payload.get("folder_path", "")
        folder_name = folder_path.split("/")[-1] if folder_path else ""
        tooltip = f"{payload['well_name']}/{payload['curve_name']}"
        if folder_path:
            tooltip = f"{payload['well_name']}/{folder_path}/{payload['curve_name']}"
        entry = {
            "db_path": payload["db_path"],
            "well_id": payload["well_id"],
            "curve_id": payload["curve_id"],
            "well_name": payload["well_name"],
            "curve_name": payload["curve_name"],
            "label": payload["curve_name"],
            "tooltip": tooltip,
            "folder_path": folder_path,
            "folder_name": folder_name,
            "depth": np.asarray(payload["depth"], dtype=float),
            "data": np.asarray(payload["data"]),
        }
        if entry["data"].ndim > 1 and self._curve_entries:
            ThemeDialog.message(
                self,
                "Data Viewer",
                "2D curves can currently be viewed in Data Viewer only when opened alone on the page.",
                icon_type="info",
            )
            return
        if entry["data"].ndim == 1 and any(existing["data"].ndim > 1 for existing in self._curve_entries):
            ThemeDialog.message(
                self,
                "Data Viewer",
                "This page already contains a 2D curve. Please use a new Data Viewer page for 1D/2D mixed viewing.",
                icon_type="info",
            )
            return
        self._curve_entries.append(entry)
        self._rebuild_model()

    def _on_curve_error(self, message):
        ThemeDialog.message(self, "Data Viewer", message, icon_type="warning")

    def _rebuild_model(self):
        if not self._curve_entries:
            self._depth_union = np.array([], dtype=float)
            self.model.reset_data()
            self._apply_empty_table_layout()
            return

        depth_union = np.unique(np.concatenate([entry["depth"] for entry in self._curve_entries if len(entry["depth"]) > 0]))
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
            self._apply_data_column_widths()
            self._resize_index_and_depth_columns()
            return

        columns = []
        for entry in self._curve_entries:
            value_map = {}
            for depth, value in zip(entry["depth"], entry["data"]):
                if depth not in value_map:
                    value_map[depth] = value
            aligned = [value_map.get(depth) for depth in depth_union]
            columns.append({
                "label": entry["label"],
                "tooltip": entry.get("tooltip", entry["label"]),
                "folder_name": entry.get("folder_name", ""),
                "values": aligned,
                "db_path": entry["db_path"],
                "well_id": entry["well_id"],
                "curve_id": entry["curve_id"],
            })

        self._depth_union = depth_union
        self.model.set_viewer_data(depth_union, columns)
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
        self._curve_entries.clear()
        self._rebuild_model()

    def load_single_curve_data(self, well_name, curve_name, depth, data, folder_path=""):
        folder_name = folder_path.split("/")[-1] if folder_path else ""
        tooltip = f"{well_name}/{curve_name}"
        if folder_path:
            tooltip = f"{well_name}/{folder_path}/{curve_name}"

        self._curve_entries = [{
            "db_path": "",
            "well_id": None,
            "curve_id": None,
            "well_name": well_name,
            "curve_name": curve_name,
            "label": curve_name,
            "tooltip": tooltip,
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
        for idx in remove_indexes:
            if 0 <= idx < len(self._curve_entries):
                self._curve_entries.pop(idx)
        self._rebuild_model()

    def copy_selection(self):
        copy_table_selection_to_clipboard(self.table, self.model)

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
