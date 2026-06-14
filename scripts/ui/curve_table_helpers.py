from PySide6.QtCore import Qt, QObject, QEvent
from PySide6.QtGui import QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import QAbstractItemView, QHeaderView


class _CornerSelectAllFilter(QObject):
    def __init__(self, table):
        super().__init__(table)
        self._table = table

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            if self._table.model() is not None and self._table.model().columnCount() > 0:
                self._table.selectColumn(0)
            self._table.setFocus()
            return True
        return super().eventFilter(watched, event)


def enable_styled_background(widget):
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setAutoFillBackground(True)


def configure_curve_table_view(
    table,
    *,
    default_section_size=120,
    minimum_section_size=24,
    editable=False,
    show_vertical_header=False,
    on_context_menu=None,
    on_header_click=None,
    on_header_context_menu=None,
):
    enable_styled_background(table)
    enable_styled_background(table.viewport())
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectItems)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setEditTriggers(
        QAbstractItemView.DoubleClicked
        | QAbstractItemView.EditKeyPressed
        | QAbstractItemView.AnyKeyPressed
        if editable
        else QAbstractItemView.NoEditTriggers
    )
    table.verticalHeader().setVisible(show_vertical_header)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    table.horizontalHeader().setDefaultSectionSize(default_section_size)
    table.horizontalHeader().setMinimumSectionSize(minimum_section_size)
    table.horizontalHeader().setSectionsClickable(True)
    table.setSortingEnabled(False)

    if on_context_menu:
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(on_context_menu)
    if on_header_click:
        table.horizontalHeader().sectionPressed.connect(on_header_click)
    if on_header_context_menu:
        table.horizontalHeader().setContextMenuPolicy(Qt.CustomContextMenu)
        table.horizontalHeader().customContextMenuRequested.connect(on_header_context_menu)


def install_copy_shortcut(parent_widget, handler):
    shortcut = QShortcut(QKeySequence.Copy, parent_widget)
    shortcut.setContext(Qt.WidgetWithChildrenShortcut)
    shortcut.activated.connect(handler)
    return shortcut


def install_corner_select_all(table):
    corner_button = table.findChild(QObject, "qt_table_cornerbutton")
    if corner_button is None:
        return None
    event_filter = _CornerSelectAllFilter(table)
    corner_button.installEventFilter(event_filter)
    table._corner_select_all_filter = event_filter
    return event_filter


def apply_empty_curve_table_layout(table, *, index_width=40, depth_width=92):
    table.setColumnWidth(0, index_width)
    table.setColumnWidth(1, depth_width)


def resize_index_and_depth_columns(table, depth_values, *, index_min=40, depth_min=84):
    row_count = len(depth_values)
    index_text = str(row_count or 1)
    depth_text = "Depth"
    if row_count > 0:
        depth_samples = [f"{value:.4f}" for value in depth_values]
        depth_text = max(depth_samples, key=len)

    cell_metrics = QFontMetrics(table.font())
    header_metrics = QFontMetrics(table.horizontalHeader().font())

    index_width = max(
        cell_metrics.horizontalAdvance(index_text),
        header_metrics.horizontalAdvance(" ")
    ) + 24
    depth_width = max(
        cell_metrics.horizontalAdvance(depth_text),
        header_metrics.horizontalAdvance("Depth")
    ) + 28

    table.setColumnWidth(0, max(index_min, index_width))
    table.setColumnWidth(1, max(depth_min, depth_width))
