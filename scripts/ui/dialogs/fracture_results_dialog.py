from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableView,
    QVBoxLayout,
)

from ..base_dialog import ThemeDialog
from ..curve_table_helpers import configure_curve_table_view, enable_styled_background
from ..theme_manager import ThemeManager


class _FractureResultsModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._headers = []
        self._rows = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.EditRole):
            return None
        try:
            return self._rows[index.row()][index.column()]
        except IndexError:
            return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
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

    def set_results(self, headers, rows):
        self.beginResetModel()
        self._headers = list(headers)
        self._rows = [list(row) for row in rows]
        self.endResetModel()


class FractureResultsDialog(ThemeDialog):
    """Table view for fracture picking results in the active plot."""

    HEADERS = ["Center Depth", "Type", "Dip Height", "Image Azimuth (deg)", "Apparent Dip (deg)", "Source"]

    def __init__(self, log_widget, parent=None):
        super().__init__(parent)
        self.log_widget = log_widget
        self.container.setObjectName("curveTableRoot")
        enable_styled_background(self.container)
        self.setWindowTitle("Fracture Results")
        self.resize(760, 420)

        root = QVBoxLayout()
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)
        self.setLayout(root)

        self.summary = QLabel()
        root.addWidget(self.summary)

        self.model = _FractureResultsModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        configure_curve_table_view(self.table, default_section_size=126, minimum_section_size=64)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh")
        self.save_button = QPushButton("Save")
        self.load_button = QPushButton("Load")
        actions.addWidget(self.refresh_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.load_button)
        actions.addStretch(1)
        root.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.refresh_button.clicked.connect(self.refresh)
        self.save_button.clicked.connect(self._save)
        self.load_button.clicked.connect(self._load)
        self.update_theme()
        self.refresh()

    def refresh(self):
        annotations = []
        if self.log_widget and hasattr(self.log_widget, "collect_fracture_annotations"):
            annotations = self.log_widget.collect_fracture_annotations()
        rows = []
        for annotation in annotations:
            rows.append([
                self._fmt(annotation.get("center_depth", annotation.get("offset"))),
                annotation.get("fracture_type", ""),
                self._fmt(annotation.get("dip_height", annotation.get("amplitude"))),
                self._fmt(annotation.get("image_azimuth")),
                self._fmt(annotation.get("apparent_dip")),
                annotation.get("source_curve_name") or annotation.get("source_track_label") or "",
            ])
        self.model.set_results(self._headers_for(annotations), rows)
        self.summary.setText(f"{len(annotations)} fracture result(s)")
        self.table.resizeColumnsToContents()

    def update_theme(self):
        ThemeManager.apply_curve_table_surface(self.container)
        self.container.style().unpolish(self.container)
        self.container.style().polish(self.container)

    def _save(self):
        if self.log_widget and hasattr(self.log_widget, "save_fracture_results"):
            self.log_widget.save_fracture_results()
        self.refresh()

    def _load(self):
        if self.log_widget and hasattr(self.log_widget, "load_fracture_results"):
            self.log_widget.load_fracture_results()
        self.refresh()

    @staticmethod
    def _fmt(value):
        try:
            return f"{float(value):.3f}"
        except Exception:
            return ""

    @classmethod
    def _headers_for(cls, annotations):
        depth_unit = ""
        for annotation in annotations or []:
            depth_unit = str(annotation.get("depth_unit") or "").strip()
            if depth_unit:
                break
        if not depth_unit:
            return cls.HEADERS
        headers = list(cls.HEADERS)
        headers[0] = f"Center Depth ({depth_unit})"
        headers[2] = f"Dip Height ({depth_unit})"
        return headers
