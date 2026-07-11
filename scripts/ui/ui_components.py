import os

from PySide6.QtWidgets import (QWidget, QScrollArea, QHBoxLayout, QVBoxLayout, QComboBox,
                               QPushButton, QSizePolicy, QMenu, QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, Signal, QEvent, QRect, QPoint, QPointF, QTimer, QObject, Property, Slot, QUrl
from PySide6.QtGui import (QPainter, QColor, QFont, QPen, QAction, QCursor)
from PySide6.QtQuickWidgets import QQuickWidget
import numpy as np
from core.app_config import app_config
from scripts.rendering.fracture_annotations import FRACTURE_TYPE_STYLES

class QuickAddZone(QWidget):
    def __init__(self, log_widget, parent=None):
        super().__init__(parent)
        self.log_widget = log_widget
        self.setFixedWidth(50); self.setAcceptDrops(True); self.is_over = False
        self.setToolTip("Drag curves here to add a new track at the end")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False); self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("background: transparent; border: none;")

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"):
            self.is_over = True; self.update(); event.accept(); event.setDropAction(Qt.CopyAction)
        else: event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"): event.accept()
        else: event.ignore()

    def dragLeaveEvent(self, event):
        self.is_over = False; self.update()

    def dropEvent(self, event):
        self.is_over = False; self.update()
        raw_data = event.mimeData().data("application/x-pylog-curve").data().decode('utf-8')
        try:
            items = raw_data.split('|') if '|' in raw_data else [raw_data]
            for item in items:
                if not item: continue
                parts = item.split(':')
                if len(parts) >= 3:
                    self.log_widget.create_new_track(int(parts[0]), int(parts[1]), db_path=parts[2])
                else: self.log_widget.create_new_track(int(parts[0]), int(parts[1]))
        except Exception as e: print(f"QuickAddZone Drop Error: {e}")

    def paintEvent(self, event):
        if not self.is_over: return
        painter = QPainter(self); painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 60))
        painter.setPen(QPen(QColor(255, 255, 255, 100), 1)); painter.drawLine(0, 0, 0, self.height())
        painter.setPen(QColor(255, 255, 255, 200)); painter.setFont(QFont("Arial", 20, QFont.Bold))
        painter.drawText(self.rect(), Qt.AlignCenter, "+")

class TrackSpacer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True); self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)

    def show_context_menu(self, pos):
        menu = QMenu(self); add_depth_act = QAction("Add Depth Track", self); add_empty_act = QAction("Add Empty Track", self)
        log_w = self.find_log_widget()
        add_depth_act.triggered.connect(lambda: log_w.add_depth_track() if log_w else None)
        add_empty_act.triggered.connect(lambda: log_w.add_empty_track() if log_w else None)
        menu.addAction(add_depth_act); menu.addAction(add_empty_act); menu.exec(self.mapToGlobal(pos))

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), QColor(app_config.get_theme_color("plot_bg")))
        
    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-pylog-curve"): event.accept()
        else: event.ignore()

    def dropEvent(self, event):
        raw_data = event.mimeData().data("application/x-pylog-curve").data().decode('utf-8')
        try:
            items = raw_data.split('|') if '|' in raw_data else [raw_data]
            mw = self.find_log_widget()
            if mw:
                for item in items:
                    if not item: continue
                    parts = item.split(':')
                    if len(parts) >= 3: mw.create_new_track(int(parts[0]), int(parts[1]), db_path=parts[2])
                    else: mw.create_new_track(int(parts[0]), int(parts[1]))
        except Exception as e: print(f"Spacer Drop Error: {e}")

    def find_log_widget(self):
        p = self.parent()
        while p:
            if p.__class__.__name__ == "LogWidget": return p
            p = p.parent()
        return None
    
    def mousePressEvent(self, event):
        log_widget = self.find_log_widget()
        if log_widget: log_widget.deselect_all_tracks()
        super().mousePressEvent(event)

class CustomScrollArea(QScrollArea):
    def wheelEvent(self, event):
        if self.parent(): self.parent().wheelEvent(event)
        else: super().wheelEvent(event)

class FloatingScaleControl(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_widget = parent
        self.setObjectName("FloatingScaleControl")
        self.setFixedSize(40, 30) # Slightly wider for better fit
        layout = QHBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.combo = QComboBox()
        self.combo.addItems(["1:5", "1:10", "1:20", "1:50", "1:100", "1:200", "1:500"])
        self.combo.setEditable(True); self.combo.lineEdit().setReadOnly(True); self.combo.lineEdit().setAlignment(Qt.AlignCenter)
        self.combo.setInsertPolicy(QComboBox.NoInsert); self.combo.setCurrentText("1:50")
        self.combo.textActivated.connect(lambda t: self.update_scale())
        self.combo.lineEdit().installEventFilter(self)
        self.block_auto = False
        layout.addWidget(self.combo)
        
        # Style and Translucency for Popup
        view = self.combo.view()
        view.window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        view.window().setAttribute(Qt.WA_TranslucentBackground)
        view.viewport().setAttribute(Qt.WA_TranslucentBackground)
        view.setStyleSheet("background-color: rgba(50, 50, 50, 200); color: white; border: none; outline: 0px; selection-background-color: rgba(100, 100, 100, 220);")

        self.setAttribute(Qt.WA_StyledBackground)
        # Use simpler selectors for better compatibility
        self.setStyleSheet("""
            #FloatingScaleControl { 
                background-color: rgba(50, 50, 50, 160); 
                border-radius: 12px; 
                border: 1px solid rgba(255, 255, 255, 120);
            } 
            QComboBox { 
                background: transparent; 
                color: white; 
                border: none; 
                padding: 0px; 
                font-weight: bold; 
            } 
            QComboBox::drop-down { 
                border: none; 
                width: 0px; 
            } 
        """)
        self.opacity_effect = QGraphicsOpacityEffect(self); self.opacity_effect.setOpacity(0.7); self.setGraphicsEffect(self.opacity_effect)
        
    def eventFilter(self, obj, event):
        if obj == self.combo.lineEdit():
            if event.type() == QEvent.MouseButtonRelease: self.combo.showPopup(); return True
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        self.opacity_effect.setOpacity(1.0); super().enterEvent(event)
        
    def leaveEvent(self, event):
        self.opacity_effect.setOpacity(0.7); super().leaveEvent(event)
        
    def update_scale(self):
        if self.block_auto: return
        try: scale = int(self.combo.currentText().split(':')[1])
        except: return
        if not self.log_widget: return
        dpi = self.screen().physicalDotsPerInchY() if self.screen() else 96.0
        pixels_per_meter = (39.3701 / scale) * dpi
        vb = self.log_widget.get_master_viewbox()
        if not vb or not self.log_widget.track_containers: return
        track_height_px = self.log_widget.track_containers[0].plot_widget.height()
        if track_height_px <= 0: return
        target_span = track_height_px / pixels_per_meter
        (min_y, max_y) = vb.viewRange()[1]
        start_at_top = (max_y - min_y) > target_span * 2 or (self.log_widget.global_min_depth is not None and abs(min_y - self.log_widget.global_min_depth) < 0.5)
        if start_at_top: 
            vb.setYRange(min_y, min_y + target_span, padding=0)
            self.log_widget.apply_depth_range(min_y, min_y + target_span, force_low_res=True)
        else:
            center = (min_y + max_y) / 2
            vb.setYRange(center - target_span / 2, center + target_span / 2, padding=0)
            self.log_widget.apply_depth_range(center - target_span / 2, center + target_span / 2, force_low_res=True)
        
        # Then trigger high-res update after a small delay
        QTimer.singleShot(200, lambda: self.log_widget.apply_depth_range(vb.viewRange()[1][0], vb.viewRange()[1][1], force_low_res=False))
        
    def update_display(self):
        if not self.log_widget or not self.log_widget.track_containers: return
        vb = self.log_widget.get_master_viewbox()
        if not vb: return
        track_height_px = self.log_widget.track_containers[0].plot_widget.height()
        if track_height_px <= 0: return
        (_, (min_y, max_y)) = vb.viewRange()
        span_m = max_y - min_y
        if span_m <= 0: return
        dpi = self.screen().physicalDotsPerInchY() if self.screen() else 96.0
        scale = (39.3701 * dpi) / (track_height_px / span_m)
        self.block_auto = True; self.combo.setCurrentText(f"1:{int(round(scale))}"); self.block_auto = False

class FloatingHeaderToggle(QPushButton):
    def __init__(self, parent=None):
        super().__init__("H", parent)
        self.setObjectName("FloatingHeaderToggle")
        self.setCheckable(True); self.setFixedSize(40, 30); self.setToolTip("Toggle Headers Visibility")
        self.setAttribute(Qt.WA_StyledBackground)
        # Use simpler selectors for better compatibility
        self.setStyleSheet("""
            #FloatingHeaderToggle { 
                background-color: rgba(50, 50, 50, 160); 
                color: white; 
                border-radius: 12px; 
                font-weight: bold; 
                border: 1px solid rgba(255, 255, 255, 120); 
            } 
            #FloatingHeaderToggle:hover { 
                background-color: rgba(70, 70, 70, 200); 
            } 
            #FloatingHeaderToggle:checked { 
                background-color: rgba(80, 80, 80, 240); 
                color: #55FF55; 
            }
        """)
        self.opacity_effect = QGraphicsOpacityEffect(self); self.opacity_effect.setOpacity(0); self.setGraphicsEffect(self.opacity_effect)

    def enterEvent(self, event): self.opacity_effect.setOpacity(1.0); super().enterEvent(event)
    def leaveEvent(self, event): self.opacity_effect.setOpacity(0); super().leaveEvent(event)


class FracturePickingBridge(QObject):
    targetLabelsChanged = Signal()
    currentTargetIndexChanged = Signal()
    collapsedChanged = Signal(bool)
    themeChanged = Signal()

    def __init__(self, panel, log_widget):
        super().__init__(panel)
        self.panel = panel
        self.log_widget = log_widget
        self._target_labels = ["Auto"]
        self._current_target_index = 0
        self._collapsed = False
        self._theme = {}
        self.refresh_theme()

    def _theme_color(self, token, default):
        return app_config.get_theme_color(token, default) or default

    def refresh_theme(self):
        self._theme = {
            "panelBg": self._theme_color("dialog_bg", "#FFFFFF"),
            "panelBorder": self._theme_color("border_std", "#D0D0D0"),
            "text": self._theme_color("text_main", "#101828"),
            "muted": self._theme_color("text_dim", "#475467"),
            "divider": self._theme_color("border_std", "#D9E0EA"),
            "inputBg": self._theme_color("input_bg", "#FFFFFF"),
            "inputBorder": self._theme_color("input_border", "#CDD6E2"),
            "buttonBg": self._theme_color("button_bg", "#F0F0F0"),
            "buttonHover": self._theme_color("button_hover", "#E0E0E0"),
            "primary": self._theme_color("primary", "#2F7CDC"),
            "primaryHover": self._theme_color("primary_hover", "#246CC8"),
            "danger": self._theme_color("danger", "#E81123"),
            "accentLight": self._theme_color("accent_light", "#EAF2FD"),
        }
        self.themeChanged.emit()

    @Property("QStringList", notify=targetLabelsChanged)
    def targetLabels(self):
        return self._target_labels

    @Property(int, notify=currentTargetIndexChanged)
    def currentTargetIndex(self):
        return self._current_target_index

    @Property(bool, notify=collapsedChanged)
    def collapsed(self):
        return self._collapsed

    @Property("QStringList", constant=True)
    def fractureTypeLabels(self):
        return [str(style.get("label", key)) for key, style in FRACTURE_TYPE_STYLES.items()]

    @Property(str, notify=themeChanged)
    def panelBg(self):
        return self._theme["panelBg"]

    @Property(str, notify=themeChanged)
    def panelBorder(self):
        return self._theme["panelBorder"]

    @Property(str, notify=themeChanged)
    def themeText(self):
        return self._theme["text"]

    @Property(str, notify=themeChanged)
    def themeMuted(self):
        return self._theme["muted"]

    @Property(str, notify=themeChanged)
    def themeDivider(self):
        return self._theme["divider"]

    @Property(str, notify=themeChanged)
    def inputBg(self):
        return self._theme["inputBg"]

    @Property(str, notify=themeChanged)
    def inputBorder(self):
        return self._theme["inputBorder"]

    @Property(str, notify=themeChanged)
    def buttonBg(self):
        return self._theme["buttonBg"]

    @Property(str, notify=themeChanged)
    def buttonHover(self):
        return self._theme["buttonHover"]

    @Property(str, notify=themeChanged)
    def primaryColor(self):
        return self._theme["primary"]

    @Property(str, notify=themeChanged)
    def primaryHoverColor(self):
        return self._theme["primaryHover"]

    @Property(str, notify=themeChanged)
    def dangerColor(self):
        return self._theme["danger"]

    @Property(str, notify=themeChanged)
    def accentLightColor(self):
        return self._theme["accentLight"]

    def set_target_tracks(self, labels, current_index):
        labels = [str(label) for label in (labels or ["Auto"])]
        index = max(0, min(int(current_index or 0), len(labels) - 1)) if labels else 0
        changed_labels = labels != self._target_labels
        changed_index = index != self._current_target_index
        self._target_labels = labels
        self._current_target_index = index
        if changed_labels:
            self.targetLabelsChanged.emit()
        if changed_index:
            self.currentTargetIndexChanged.emit()

    @Slot(bool)
    def setCollapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self.collapsedChanged.emit(self._collapsed)

    @Slot(str)
    def setFractureType(self, text):
        if self.log_widget and hasattr(self.log_widget, "set_fracture_pick_type"):
            self.log_widget.set_fracture_pick_type(text)

    @Slot(int)
    def setTargetIndex(self, index):
        if self.log_widget and hasattr(self.log_widget, "set_fracture_target_track_index"):
            self.log_widget.set_fracture_target_track_index(index)

    @Slot()
    def finish(self):
        if self.log_widget and hasattr(self.log_widget, "finish_current_fracture_pick"):
            self.log_widget.finish_current_fracture_pick()

    @Slot()
    def undo(self):
        if self.log_widget and hasattr(self.log_widget, "undo_current_fracture_pick_point"):
            self.log_widget.undo_current_fracture_pick_point()

    @Slot()
    def cancel(self):
        if self.log_widget and hasattr(self.log_widget, "cancel_current_fracture_pick"):
            self.log_widget.cancel_current_fracture_pick()

    @Slot()
    def deleteSelected(self):
        if self.log_widget and hasattr(self.log_widget, "delete_selected_fractures"):
            self.log_widget.delete_selected_fractures()

    @Slot()
    def clearSelection(self):
        if self.log_widget and hasattr(self.log_widget, "clear_fracture_selection"):
            self.log_widget.clear_fracture_selection()

    @Slot()
    def clearAll(self):
        if self.log_widget and hasattr(self.log_widget, "clear_fracture_annotations"):
            self.log_widget.clear_fracture_annotations()

    @Slot()
    def exitMode(self):
        if self.log_widget and hasattr(self.log_widget, "set_fracture_picking_enabled"):
            self.log_widget.set_fracture_picking_enabled(False)

    @Slot(float, float)
    def beginDrag(self, x, y):
        if self.panel and hasattr(self.panel, "begin_drag"):
            self.panel.begin_drag(x, y)

    @Slot(float, float)
    def dragTo(self, x, y):
        if self.panel and hasattr(self.panel, "drag_to"):
            self.panel.drag_to(x, y)

    @Slot()
    def endDrag(self):
        if self.panel and hasattr(self.panel, "end_drag"):
            self.panel.end_drag()


class FracturePickingPanel(QQuickWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.log_widget = parent
        self._expanded_size = (480, 365)
        self._collapsed_size = (128, 365)
        self._drag_start_panel_pos = None
        self._drag_start_pointer = None
        self._user_moved = False
        self.bridge = FracturePickingBridge(self, parent)
        self.bridge.collapsedChanged.connect(self._on_collapsed_changed)

        self.setObjectName("FracturePickingPanel")
        self.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self._apply_host_background()
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.rootContext().setContextProperty("bridge", self.bridge)
        qml_path = os.path.join(os.path.dirname(__file__), "qml", "FracturePickingPanel.qml")
        self.setSource(QUrl.fromLocalFile(qml_path))
        self.setFixedSize(*self._expanded_size)

    def _apply_host_background(self):
        bg = QColor(self.bridge.panelBg)
        if not bg.isValid():
            bg = app_config.get_theme_qcolor("dialog_bg", "#FFFFFF")
        self.setClearColor(bg)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setStyleSheet(f"background: {bg.name()}; border: none;")

    def set_target_tracks(self, labels, current_index):
        self.bridge.set_target_tracks(labels, current_index)

    def fit_to_parent(self):
        size = self._collapsed_size if self.bridge.collapsed else self._expanded_size
        self.setFixedSize(*size)
        if self._user_moved:
            self._clamp_to_parent()

    def update_theme(self):
        self.bridge.refresh_theme()
        self._apply_host_background()
        self.update()

    def reset_position(self):
        self._user_moved = False
        parent = self.parentWidget()
        if parent:
            self.move(max(8, parent.width() - self.width() - 28), 8)

    def _bounded_pos(self, x, y):
        parent = self.parentWidget()
        if not parent:
            return int(x), int(y)
        margin = 8
        max_x = max(margin, parent.width() - self.width() - margin)
        max_y = max(margin, parent.height() - self.height() - margin)
        return (
            max(margin, min(int(round(x)), max_x)),
            max(margin, min(int(round(y)), max_y)),
        )

    def _clamp_to_parent(self):
        x, y = self._bounded_pos(self.x(), self.y())
        self.move(x, y)

    def begin_drag(self, x, y):
        self._drag_start_panel_pos = self.pos()
        global_pos = QCursor.pos()
        if global_pos.isNull():
            global_pos = self.mapToGlobal(QPoint(int(round(float(x))), int(round(float(y)))))
        self._drag_start_pointer = global_pos
        self._user_moved = True

    def drag_to(self, x, y):
        if self._drag_start_panel_pos is None or self._drag_start_pointer is None:
            self.begin_drag(x, y)
            return
        global_pos = QCursor.pos()
        if global_pos.isNull():
            global_pos = self.mapToGlobal(QPoint(int(round(float(x))), int(round(float(y)))))
        dx = global_pos.x() - self._drag_start_pointer.x()
        dy = global_pos.y() - self._drag_start_pointer.y()
        new_x = self._drag_start_panel_pos.x() + dx
        new_y = self._drag_start_panel_pos.y() + dy
        bounded_x, bounded_y = self._bounded_pos(new_x, new_y)
        self.move(bounded_x, bounded_y)
        self.raise_()

    def end_drag(self):
        self._drag_start_panel_pos = None
        self._drag_start_pointer = None
        self._clamp_to_parent()

    def _on_collapsed_changed(self, collapsed):
        self.setFixedSize(*(self._collapsed_size if collapsed else self._expanded_size))
        if self._user_moved:
            self._clamp_to_parent()
        else:
            self.reset_position()
