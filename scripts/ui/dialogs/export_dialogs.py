from __future__ import annotations

import os
from collections import defaultdict
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QWidget,
    QVBoxLayout,
)

from ..base_dialog import ThemeDialog
from core.app_config import app_config


class DLISExportDialog(ThemeDialog):
    """Dialog for selecting a well, curves, and output file for DLIS export."""

    ROOT_FRAME_NAME = "ROOT"

    def __init__(self, wells: List[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("DLIS Export Settings")
        self.resize(860, 620)
        self._wells = list(wells or [])
        self._well_snapshots: Dict[tuple, dict] = {}
        self._current_well: Optional[dict] = None
        self._export_request_handler = None
        self._export_in_progress = False

        layout = QVBoxLayout()
        self.setLayout(layout)

        header = QLabel("<h3>DLIS Curve Export</h3>")
        header.setAlignment(Qt.AlignCenter)
        layout.addWidget(header)

        body_layout = QHBoxLayout()
        layout.addLayout(body_layout, stretch=1)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("<b>Select Well:</b>"))
        self.well_list = QListWidget()
        self.well_list.currentItemChanged.connect(self._handle_well_changed)
        left_layout.addWidget(self.well_list)
        body_layout.addLayout(left_layout, stretch=2)

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("<b>Select Curves:</b>"))
        self.curve_tree = QTreeWidget()
        self.curve_tree.setHeaderLabels(["Curve", "Unit"])
        self.curve_tree.header().setStretchLastSection(False)
        self.curve_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.curve_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        right_layout.addWidget(self.curve_tree)

        selection_layout = QHBoxLayout()
        btn_all = QPushButton("Select All", self)
        btn_none = QPushButton("Select None", self)
        btn_all.clicked.connect(lambda: self._set_all_curve_checks(Qt.Checked))
        btn_none.clicked.connect(lambda: self._set_all_curve_checks(Qt.Unchecked))
        selection_layout.addWidget(btn_all)
        selection_layout.addWidget(btn_none)
        right_layout.addLayout(selection_layout)
        body_layout.addLayout(right_layout, stretch=5)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("<b>File Name:</b>"))
        self.file_name_edit = QLineEdit()
        self.file_name_edit.setPlaceholderText("Enter file name...")
        self.file_name_edit.textChanged.connect(self._sync_output_path_from_name)
        name_layout.addWidget(self.file_name_edit)
        layout.addLayout(name_layout)

        output_layout = QHBoxLayout()
        output_layout.addWidget(QLabel("<b>Save To:</b>"))
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Choose output .dlis file...")
        output_layout.addWidget(self.output_path_edit, stretch=1)
        browse_btn = QPushButton("Browse...", self)
        browse_btn.clicked.connect(self._browse_output_path)
        output_layout.addWidget(browse_btn)
        layout.addLayout(output_layout)

        self.btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.btns.accepted.connect(self.validate_and_accept)
        self.btns.rejected.connect(self.reject)
        layout.addWidget(self.btns)

        self.progress_label = QLabel("")
        self.progress_label.setWordWrap(True)
        self.progress_label.hide()
        layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self._populate_wells()

    def _populate_wells(self):
        self.well_list.clear()
        for well in self._wells:
            item = QListWidgetItem(well.get("name", "Unknown"))
            item.setData(Qt.UserRole, well)
            self.well_list.addItem(item)
        if self.well_list.count():
            self.well_list.setCurrentRow(0)

    def set_well_snapshot(self, db_path: str, well_id: int, snapshot: dict):
        self._well_snapshots[(db_path, well_id)] = snapshot or {}
        if (
            self._current_well
            and self._current_well.get("db_path") == db_path
            and self._current_well.get("id") == well_id
        ):
            self._populate_curve_tree(snapshot or {})

    def _handle_well_changed(self, current: QListWidgetItem, _previous: QListWidgetItem):
        well = current.data(Qt.UserRole) if current else None
        self._current_well = well
        self.curve_tree.clear()
        if not well:
            return

        default_name = self._sanitize_file_name(well.get("name", "export"))
        if not self.file_name_edit.text().strip():
            self.file_name_edit.setText(default_name)
        else:
            self.file_name_edit.setText(default_name)

        snapshot = self._well_snapshots.get((well.get("db_path"), well.get("id")))
        if snapshot:
            self._populate_curve_tree(snapshot)

    def _populate_curve_tree(self, snapshot: dict):
        self.curve_tree.clear()
        curves = list(snapshot.get("curves", []))
        grouped = defaultdict(list)
        for curve in curves:
            grouped[curve.get("folder") or self.ROOT_FRAME_NAME].append(curve)

        for folder_name in sorted(grouped.keys(), key=lambda value: (value != self.ROOT_FRAME_NAME, value.upper())):
            folder_item = QTreeWidgetItem([folder_name, ""])
            folder_item.setFlags(folder_item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            folder_item.setCheckState(0, Qt.Checked)
            self.curve_tree.addTopLevelItem(folder_item)

            for curve in sorted(grouped[folder_name], key=lambda value: str(value.get("name", "")).upper()):
                curve_item = QTreeWidgetItem(
                    [
                        f"{curve.get('name', 'Unknown')} ({curve.get('unit') or ''})".strip(),
                        curve.get("unit") or "",
                    ]
                )
                curve_item.setData(0, Qt.UserRole, curve)
                curve_item.setFlags(curve_item.flags() | Qt.ItemIsUserCheckable)
                curve_item.setCheckState(0, Qt.Checked)
                folder_item.addChild(curve_item)

            folder_item.setExpanded(True)

    def _set_all_curve_checks(self, state: Qt.CheckState):
        for i in range(self.curve_tree.topLevelItemCount()):
            folder_item = self.curve_tree.topLevelItem(i)
            for j in range(folder_item.childCount()):
                folder_item.child(j).setCheckState(0, state)

    def _browse_output_path(self):
        initial = self.output_path_edit.text().strip()
        if not initial:
            file_name = self.file_name_edit.text().strip() or "export"
            initial = os.path.abspath(f"{file_name}.dlis")

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export DLIS File",
            initial,
            "DLIS Files (*.dlis);;All Files (*)",
        )
        if file_path:
            if not file_path.lower().endswith(".dlis"):
                file_path += ".dlis"
            self.output_path_edit.setText(file_path)
            self.file_name_edit.setText(os.path.splitext(os.path.basename(file_path))[0])

    def _sync_output_path_from_name(self, text: str):
        sanitized = self._sanitize_file_name(text)
        if sanitized != text:
            self.file_name_edit.blockSignals(True)
            self.file_name_edit.setText(sanitized)
            self.file_name_edit.blockSignals(False)
        current_path = self.output_path_edit.text().strip()
        if current_path:
            directory = os.path.dirname(current_path) or os.getcwd()
            self.output_path_edit.setText(os.path.join(directory, f"{sanitized or 'export'}.dlis"))

    def _sanitize_file_name(self, name: str) -> str:
        text = str(name or "").strip()
        invalid = '<>:"/\\|?*'
        cleaned = "".join("_" if c in invalid else c for c in text)
        cleaned = cleaned.rstrip(". ")
        return cleaned or "export"

    def get_selected_curves(self) -> List[dict]:
        selected = []
        for i in range(self.curve_tree.topLevelItemCount()):
            folder_item = self.curve_tree.topLevelItem(i)
            for j in range(folder_item.childCount()):
                curve_item = folder_item.child(j)
                if curve_item.checkState(0) == Qt.Checked:
                    payload = dict(curve_item.data(0, Qt.UserRole) or {})
                    payload["folder_name"] = payload.get("folder") or self.ROOT_FRAME_NAME
                    selected.append(payload)
        return selected

    def get_selected_well(self) -> Optional[dict]:
        item = self.well_list.currentItem()
        return item.data(Qt.UserRole) if item else None

    def get_settings(self) -> dict:
        return {
            "well": self.get_selected_well(),
            "curves": self.get_selected_curves(),
            "output_path": self.output_path_edit.text().strip(),
            "file_name": self.file_name_edit.text().strip(),
        }

    def set_export_request_handler(self, handler):
        self._export_request_handler = handler

    def set_export_controls_enabled(self, enabled: bool):
        self._export_in_progress = not enabled
        self.well_list.setEnabled(enabled)
        self.curve_tree.setEnabled(enabled)
        self.file_name_edit.setEnabled(enabled)
        self.output_path_edit.setEnabled(enabled)
        ok_button = self.btns.button(QDialogButtonBox.Ok)
        if ok_button:
            ok_button.setEnabled(enabled)
        cancel_button = self.btns.button(QDialogButtonBox.Cancel)
        if cancel_button:
            cancel_button.setText("Close" if enabled else "Cancel")
            cancel_button.setEnabled(True)

    def begin_export(self):
        self.set_export_controls_enabled(False)
        self.progress_label.setText("Preparing DLIS export...")
        self.progress_label.show()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setValue(0)
        self.progress_bar.show()

    def update_export_progress(self, payload: dict):
        phase = payload.get("phase")
        curve_name = payload.get("curve") or ""
        if phase == "preparing_curve":
            total = max(int(payload.get("total") or 0), 1)
            current = min(int(payload.get("current") or 0), total)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_label.setText(f"Preparing curves {current}/{total}: {curve_name}")
        elif phase == "writing_file":
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText(f"Writing DLIS file: {curve_name}")
        elif phase == "writing_records":
            total = max(int(payload.get("total") or 0), 1)
            current = min(int(payload.get("current") or 0), total)
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
            self.progress_label.setText(f"Writing DLIS records {current}/{total}")
        else:
            self.progress_bar.setRange(0, 0)
            self.progress_label.setText("Exporting DLIS...")

    def finish_export(self):
        self.set_export_controls_enabled(True)

    def set_export_summary(self, text: str):
        self.progress_label.setText(text)
        self.progress_label.show()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(1)
        self.progress_bar.show()

    def reject(self):
        if self._export_in_progress:
            ThemeDialog.message(
                self,
                "Export DLIS",
                "DLIS export is still in progress. Please wait for it to finish before closing this window.",
                icon_type="warning",
            )
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent):
        if self._export_in_progress:
            event.ignore()
            ThemeDialog.message(
                self,
                "Export DLIS",
                "DLIS export is still in progress. Please wait for it to finish before closing this window.",
                icon_type="warning",
            )
            return
        super().closeEvent(event)

    def validate_and_accept(self):
        selected_well = self.get_selected_well()
        if not selected_well:
            ThemeDialog.message(self, "Warning", "Please select a well to export.", icon_type="warning")
            return

        selected_curves = self.get_selected_curves()
        if not selected_curves:
            ThemeDialog.message(self, "Warning", "Please select at least one curve to export.", icon_type="warning")
            return

        file_name = self.file_name_edit.text().strip()
        if not file_name:
            ThemeDialog.message(self, "Warning", "Please enter a file name.", icon_type="warning")
            return

        output_path = self.output_path_edit.text().strip()
        if not output_path:
            output_path = os.path.abspath(f"{self._sanitize_file_name(file_name)}.dlis")
            self.output_path_edit.setText(output_path)

        if not output_path.lower().endswith(".dlis"):
            output_path += ".dlis"
            self.output_path_edit.setText(output_path)

        if self._export_request_handler:
            self.begin_export()
            self._export_request_handler(self.get_settings(), self)
            return

        self.accept()


class DLISExportResultDialog(ThemeDialog):
    """Scrollable, sectioned result dialog for DLIS export summaries."""

    def __init__(self, title: str, output_path: str, result: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(700, 760)
        self.setMinimumHeight(420)
        self.setMaximumHeight(860)

        self._theme = self._theme_tokens()

        layout = QVBoxLayout()
        self.setLayout(layout)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll_area.setStyleSheet(
            f"""
            QScrollArea {{
                background-color: {self._theme['bg_pure']};
                border: none;
                border-radius: 0px;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {self._theme['bg_pure']};
            }}
            """
        )

        content = QWidget()
        content.setObjectName("dlisExportResultContent")
        content.setStyleSheet(
            f"""
            QWidget#dlisExportResultContent {{
                background-color: {self._theme['bg_pure']};
            }}
            """
        )
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(18, 16, 18, 16)
        content_layout.setSpacing(12)

        exported_curves = list(result.get("exported_curves") or [])
        unit_warnings = list(result.get("unit_warnings") or [])
        skipped_curves = list(result.get("skipped_multidim") or [])
        warning_text = result.get("warning", "")

        content_layout.addWidget(
            self._build_summary_card(
                output_path=output_path,
                exported_count=int(result.get("exported_curve_count", 0)),
                warning_text=warning_text,
            )
        )

        if exported_curves:
            content_layout.addWidget(
                self._build_text_section(
                    "Exported Curves",
                    exported_curves,
                    min_height=220,
                )
            )

        if unit_warnings:
            content_layout.addWidget(
                self._build_text_section(
                    "Unit Handling",
                    unit_warnings,
                    min_height=170,
                )
            )

        if skipped_curves:
            content_layout.addWidget(
                self._build_text_section(
                    "Skipped Curves",
                    skipped_curves,
                    min_height=140,
                )
            )

        if warning_text:
            content_layout.addWidget(
                self._build_text_section(
                    "Notes",
                    [line for line in warning_text.splitlines() if line.strip()],
                    min_height=110,
                )
            )

        scroll_area.setWidget(content)
        layout.addWidget(scroll_area)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _theme_tokens(self):
        return {
            "bg_pure": app_config.get_theme_color("bg_pure"),
            "dialog_bg": app_config.get_theme_color("dialog_bg"),
            "input_bg": app_config.get_theme_color("input_bg"),
            "input_border": app_config.get_theme_color("input_border"),
            "button_bg": app_config.get_theme_color("button_bg"),
            "text_main": app_config.get_theme_color("text_main"),
            "text_dim": app_config.get_theme_color("text_dim"),
            "accent": app_config.get_theme_color("accent"),
            "tree_item_border": app_config.get_theme_color("tree_item_border"),
            "accent_light": app_config.get_theme_color("accent_light"),
        }

    def _build_summary_card(self, output_path: str, exported_count: int, warning_text: str):
        card = QFrame()
        card.setObjectName("dlisExportSummaryCard")
        card.setStyleSheet(
            f"""
            QFrame#dlisExportSummaryCard {{
                background-color: {self._theme['bg_pure']};
                border: 1px solid rgba(0, 0, 0, 0);
                border-radius: 10px;
            }}
            """
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        title = QLabel(f"<b>Exported {exported_count} curve(s)</b>")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"font-size: 16px; color: {self._theme['text_main']};")
        layout.addWidget(title)

        path_block = QWidget()
        path_layout = QVBoxLayout(path_block)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(4)

        path_title = QLabel("Output File")
        path_title.setAlignment(Qt.AlignLeft)
        path_title.setStyleSheet(
            f"font-size: 11px; font-weight: bold; letter-spacing: 0.5px; color: {self._theme['accent']};"
        )
        path_layout.addWidget(path_title)

        path_label = QLabel(output_path)
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setStyleSheet(f"font-size: 13px; color: {self._theme['text_main']};")
        path_layout.addWidget(path_label)
        layout.addWidget(path_block)

        if warning_text:
            warning_label = QLabel("Export completed with notes. See the sections below for details.")
            warning_label.setWordWrap(True)
            warning_label.setStyleSheet(f"font-size: 12px; color: {self._theme['text_dim']};")
            layout.addWidget(warning_label)

        return card

    def _build_text_section(self, heading: str, lines: List[str], min_height: int = 140):
        card = QFrame()
        card.setObjectName(f"section_{heading}")
        card.setStyleSheet(
            f"""
            QFrame {{
                background-color: {self._theme['bg_pure']};
                border: 1px solid rgba(0, 0, 0, 0);
                border-radius: 10px;
            }}
            """
        )

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        layout.setSpacing(6)

        title = QLabel(heading)
        title.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {self._theme['accent']};"
        )
        layout.addWidget(title)

        list_frame = QFrame()
        list_frame.setStyleSheet(
            f"""
            QFrame {{
                background-color: {self._theme['input_bg']};
                border: none;
                border-radius: 8px;
            }}
            """
        )
        list_layout = QVBoxLayout(list_frame)
        list_layout.setContentsMargins(0, 0, 0, 0)

        line_list = QListWidget()
        line_list.setMinimumHeight(min_height)
        line_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        line_list.setAlternatingRowColors(False)
        line_list.setSelectionMode(QListWidget.ExtendedSelection)
        line_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        line_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        line_list.setStyleSheet(
            f"""
            QListWidget {{
                background-color: transparent;
                border: none;
                color: {self._theme['text_main']};
                font-family: Consolas, 'Courier New', monospace;
                font-size: 12px;
                outline: none;
            }}
            QListWidget::item {{
                background-color: transparent;
                border: none;
                padding: 2px 4px;
                border-bottom: 1px solid {self._theme['tree_item_border']};
            }}
            QListWidget::item:selected {{
                background-color: {self._theme['accent_light']};
                color: {self._theme['accent']};
            }}
            """
        )
        for line in lines:
            line_list.addItem(line)

        list_layout.addWidget(line_list)
        layout.addWidget(list_frame)

        return card
