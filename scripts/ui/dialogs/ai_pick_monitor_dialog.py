from __future__ import annotations

import base64
from datetime import datetime

from PySide6.QtCore import QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..base_dialog import ThemeDialog


class _MonitorImageLabel(QLabel):
    def __init__(self, placeholder, parent=None):
        super().__init__(placeholder, parent)
        self._source = QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(260, 260)
        self.setFrameShape(QFrame.StyledPanel)
        self.setWordWrap(True)

    def set_data_url(self, data_url):
        raw = str(data_url or "")
        if "," not in raw:
            self._source = QPixmap()
            self.setText("No image available")
            return
        pixmap = QPixmap()
        try:
            loaded = pixmap.loadFromData(base64.b64decode(raw.split(",", 1)[1]), "PNG")
        except Exception:
            loaded = False
        if not loaded:
            self._source = QPixmap()
            self.setText("Unable to decode image")
            return
        self._source = pixmap
        self.setText("")
        self._fit_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_pixmap()

    def _fit_pixmap(self):
        if self._source.isNull():
            return
        size = self.contentsRect().size()
        if size.width() > 0 and size.height() > 0:
            self.setPixmap(self._source.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))


class _ImagePane(QWidget):
    def __init__(self, title, placeholder, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        heading = QLabel(title)
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        self.image = _MonitorImageLabel(placeholder)
        layout.addWidget(self.image, 1)


class _MonitorTimeline(QTreeWidget):
    REASON_COLUMN = 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabels(["Time", "Step", "Action", "Status", "Reason"])
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setUniformRowHeights(False)
        header = self.header()
        for column in range(self.REASON_COLUMN):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.REASON_COLUMN, QHeaderView.Stretch)

    def append_event(self, values):
        item = QTreeWidgetItem([str(value or "") for value in values])
        self.addTopLevelItem(item)
        self._update_item_height(item)
        return item

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.reflow_rows)

    def reflow_rows(self):
        for index in range(self.topLevelItemCount()):
            self._update_item_height(self.topLevelItem(index))

    def _update_item_height(self, item):
        reason_width = max(80, self.columnWidth(self.REASON_COLUMN) - 14)
        bounds = self.fontMetrics().boundingRect(
            0,
            0,
            reason_width,
            10000,
            Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop,
            item.text(self.REASON_COLUMN),
        )
        row_height = max(self.fontMetrics().height() + 8, bounds.height() + 8)
        item.setSizeHint(self.REASON_COLUMN, QSize(reason_width, row_height))


class AIPickMonitorDialog(ThemeDialog):
    """Non-modal, polling-only monitor for one Plot's current or latest AI pick run."""

    def __init__(self, log_widget, parent=None):
        super().__init__(parent)
        self.log_widget = log_widget
        self.run_id = None
        self._event_count = 0
        self._last_input_url = None
        self._last_overlay_url = None
        self.setWindowTitle("AI Pick Monitor")
        self.resize(1240, 720)

        root = QVBoxLayout()
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        self.setLayout(root)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.timeline = _MonitorTimeline()
        left_layout.addWidget(self.timeline, 1)
        self.final_summary = QLabel("Kept: -\nDiscarded: -")
        self.final_summary.setWordWrap(True)
        left_layout.addWidget(self.final_summary)
        splitter.addWidget(left)

        self.input_pane = _ImagePane("Current input view", "Waiting for an analysis view...")
        splitter.addWidget(self.input_pane)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)
        self.overlay_pane = _ImagePane("Sine overlay", "Waiting for a fitted candidate...")
        right_layout.addWidget(self.overlay_pane, 1)
        parameter_form = QFormLayout()
        self.center_value = QLabel("-")
        self.amplitude_value = QLabel("-")
        self.phase_value = QLabel("-")
        parameter_form.addRow("Center depth", self.center_value)
        parameter_form.addRow("Amplitude", self.amplitude_value)
        parameter_form.addRow("Phase", self.phase_value)
        right_layout.addLayout(parameter_form)
        splitter.addWidget(right)
        splitter.setSizes([390, 420, 420])

        footer = QHBoxLayout()
        self.budget_label = QLabel("View budget: -")
        self.candidate_label = QLabel("Candidates: -")
        self.current_label = QLabel("Current: -")
        self.round_label = QLabel("Round: -")
        self.api_label = QLabel("API: -")
        for label in (
            self.budget_label,
            self.candidate_label,
            self.current_label,
            self.round_label,
            self.api_label,
        ):
            footer.addWidget(label)
        footer.addStretch(1)
        self.diagnostics_button = QPushButton("Diagnostics")
        self.stop_button = QPushButton("Stop AI")
        footer.addWidget(self.diagnostics_button)
        footer.addWidget(self.stop_button)
        root.addLayout(footer)

        self.stop_button.clicked.connect(self._stop_ai)
        self.diagnostics_button.clicked.connect(self._open_diagnostics)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self.refresh_snapshot)

    def show_for_run(self, run_id):
        run_id = str(run_id or "")
        if run_id and run_id != self.run_id:
            self.run_id = run_id
            self._event_count = 0
            self._last_input_url = None
            self._last_overlay_url = None
            self.timeline.clear()
            self.final_summary.setText("Kept: -\nDiscarded: -")
        self.refresh_snapshot()
        self._timer.start()
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh_snapshot(self):
        if not self.run_id:
            return
        try:
            from plugins.ai_assistant.services.fracture_detection_service import get_fracture_detection_manager

            snapshot = get_fracture_detection_manager().get_monitor_snapshot(self.run_id)
        except Exception as exc:
            self.api_label.setText(f"API: {exc}")
            return

        events = snapshot.get("events") or []
        for event in events[self._event_count:]:
            timestamp = str(event.get("timestamp") or "")
            try:
                timestamp = datetime.fromisoformat(timestamp).astimezone().strftime("%H:%M:%S")
            except Exception:
                timestamp = timestamp[-8:]
            self.timeline.append_event([
                timestamp,
                str(event.get("stage") or ""),
                str(event.get("action") or ""),
                str(event.get("status") or ""),
                str(event.get("reason") or ""),
            ])
        if len(events) > self._event_count:
            self._event_count = len(events)
            self.timeline.scrollToBottom()

        monitor = snapshot.get("monitor") or {}
        media = monitor.get("media") or {}
        input_url = str((media.get("input_view") or {}).get("data_url") or "")
        overlay_payload = media.get("final_overlay") or media.get("overlay") or {}
        overlay_url = str(overlay_payload.get("data_url") or "")
        if input_url and input_url != self._last_input_url:
            self._last_input_url = input_url
            self.input_pane.image.set_data_url(input_url)
        if overlay_url and overlay_url != self._last_overlay_url:
            self._last_overlay_url = overlay_url
            self.overlay_pane.image.set_data_url(overlay_url)

        parameters = monitor.get("parameters") or {}
        self.center_value.setText(self._format_parameter(parameters.get("center_depth_m"), "m"))
        self.amplitude_value.setText(self._format_parameter(parameters.get("amplitude_m"), "m"))
        self.phase_value.setText(self._format_parameter(parameters.get("phase_deg"), "deg"))
        used = monitor.get("view_budget_used", "-")
        limit = monitor.get("view_budget_limit", "-")
        stage = monitor.get("budget_stage", "-")
        self.budget_label.setText(f"View budget: {used}/{limit} ({stage})")
        self.candidate_label.setText(
            f"Candidates: {monitor.get('candidate_count', 0)} / kept {monitor.get('kept_count', 0)}"
        )
        self.current_label.setText(f"Current: {monitor.get('current_candidate') or '-'}")
        self.round_label.setText(f"Round: {monitor.get('correction_round', 0)}")
        run = snapshot.get("run") or {}
        api_status = monitor.get("api_status") or run.get("stage") or run.get("status")
        self.api_label.setText(f"API: {api_status}")
        self.stop_button.setEnabled(run.get("status") not in {"completed", "cancelled", "failed"})

        diagnostics = snapshot.get("diagnostics") or {}
        kept_ids = diagnostics.get("kept_candidate_ids") or []
        discarded = diagnostics.get("discarded") or []
        discarded_text = [f"{item.get('candidate_id')}: {item.get('reason')}" for item in discarded]
        self.final_summary.setText(
            "Kept: " + (", ".join(str(item) for item in kept_ids) or "-")
            + "\nDiscarded: " + ("; ".join(discarded_text) or "-")
        )

    def closeEvent(self, event: QCloseEvent):
        event.ignore()
        self.hide()

    def _stop_ai(self):
        if self.log_widget and hasattr(self.log_widget, "cancel_ai_fracture_detection"):
            self.log_widget.cancel_ai_fracture_detection()

    def _open_diagnostics(self):
        if not self.run_id:
            return
        try:
            from plugins.ai_assistant.services.fracture_detection_service import get_fracture_detection_manager

            bundle = get_fracture_detection_manager().export_debug_bundle(self.run_id)
            QDesktopServices.openUrl(QUrl.fromLocalFile(bundle["directory"]))
        except Exception as exc:
            self.api_label.setText(f"Diagnostics: {exc}")

    @staticmethod
    def _format_parameter(value, unit):
        try:
            return f"{float(value):.4f} {unit}"
        except (TypeError, ValueError):
            return "-"
