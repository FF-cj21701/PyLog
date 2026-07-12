from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QBrush, QColor

from core.app_config import app_config


class StaticRowsTableModel(QAbstractTableModel):
    """Read-only table model for non-curve tabular data."""

    def __init__(self, headers=None, rows=None, parent=None):
        super().__init__(parent)
        self._headers = list(headers or [])
        self._rows = [list(row) for row in (rows or [])]
        # DataViewerWidget expects table models to expose the curve-model
        # selection hooks. Static tables implement them as lightweight no-ops.
        self.columns = []
        self._virtual_selected_columns = set()
        self._virtual_current_column = None

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = index.row()
        col = index.column()
        if role in (Qt.DisplayRole, Qt.EditRole):
            try:
                return self._rows[row][col]
            except IndexError:
                return ""
        if role == Qt.TextAlignmentRole:
            return Qt.AlignLeft | Qt.AlignVCenter
        if role == Qt.BackgroundRole and col in self._virtual_selected_columns:
            return QBrush(QColor(app_config.get_theme_color("accent_light")))
        if role == Qt.ForegroundRole:
            return QBrush(QColor(app_config.get_theme_color("text_main")))
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.BackgroundRole and section in self._virtual_selected_columns:
            return QBrush(QColor(app_config.get_theme_color("accent_light")))
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            try:
                return self._headers[section]
            except IndexError:
                return None
        return section + 1

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def set_virtual_selected_columns(self, columns, current=None):
        normalized = {column for column in columns if 0 <= column < self.columnCount()}
        self._virtual_selected_columns = normalized
        self._virtual_current_column = current if current in normalized else None
        if self.rowCount() > 0 and self.columnCount() > 0:
            self.dataChanged.emit(
                self.index(0, 0),
                self.index(self.rowCount() - 1, self.columnCount() - 1),
                [Qt.BackgroundRole, Qt.ForegroundRole],
            )
        if self.columnCount() > 0:
            self.headerDataChanged.emit(Qt.Horizontal, 0, self.columnCount() - 1)

    def clear_virtual_selected_columns(self):
        self.set_virtual_selected_columns(set(), current=None)

    def toggle_header_expanded(self, section):
        return

    def column_names(self):
        return list(self._headers)
