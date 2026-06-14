from PySide6.QtWidgets import (QWidget, QScrollArea, QHBoxLayout, QComboBox, 
                               QPushButton, QSizePolicy, QMenu, QGraphicsOpacityEffect)
from PySide6.QtCore import Qt, Signal, QEvent, QRect, QPoint, QPointF, QTimer
from PySide6.QtGui import (QPainter, QColor, QFont, QPen, QAction)
import numpy as np
from core.app_config import app_config

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
