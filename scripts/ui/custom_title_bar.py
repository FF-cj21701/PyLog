import os
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QLabel, QPushButton, 
                             QSpacerItem, QSizePolicy, QApplication, QGridLayout)
from PySide6.QtCore import Qt, Signal, QPoint, QSize
from PySide6.QtGui import QIcon, QColor, QFont
from core.app_config import app_config

class TitleButton(QPushButton):
    """Custom title bar buttons with hover/press effects."""
    def __init__(self, text="", icon_path=None, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(45, 30)
        self.setObjectName("TitleButton")
        if icon_path:
            self.setIcon(QIcon(icon_path))
        
class ModernTitleBar(QWidget):
    """
    A modern, theme-aware title bar for frameless windows.
    Supports dragging, window controls, and integration with the app's MenuBar.
    """
    def __init__(self, parent=None, is_dialog=False):
        super().__init__(parent)
        self.parent_window = parent
        self.is_dialog = is_dialog
        self.setObjectName("ModernTitleBar")
        
        self.height_val = 32 if is_dialog else 38
        self.setFixedHeight(self.height_val)
        
        self.main_layout = QGridLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # --- Left: Menu Bar Area ---
        self.menu_container = QWidget()
        self.menu_container.setObjectName("TitleBarMenuContainer")
        self.menu_layout = QHBoxLayout(self.menu_container)
        self.menu_layout.setContentsMargins(5, 0, 0, 0)
        self.menu_layout.setSpacing(0)
        self.main_layout.addWidget(self.menu_container, 0, 0, Qt.AlignVCenter | Qt.AlignLeft)
        
        if is_dialog:
            self.menu_container.hide()
        
        # --- Center: App Title ---
        initial_title = parent.windowTitle() if parent else "PyLog"
        self.title_label = QLabel(initial_title)
        self.title_label.setFont(QFont("Segoe UI", 9, QFont.Bold if not is_dialog else QFont.Normal))
        self.title_label.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.title_label, 0, 0, Qt.AlignCenter)
        
        # --- Right: Window Controls ---
        self.controls_container = QWidget()
        self.controls_container.setObjectName("TitleBarControlsContainer")
        self.controls_layout = QHBoxLayout(self.controls_container)
        self.controls_layout.setContentsMargins(0, 0, 0, 0)
        self.controls_layout.setSpacing(0)
        
        self.btn_min = TitleButton("\uE921")
        self.btn_max = TitleButton("\uE922")
        self.btn_close = TitleButton("\uE8BB")
        self.btn_close.setObjectName("TitleButtonClose")
        
        # Adjust button size to fit title bar
        for btn in [self.btn_min, self.btn_max, self.btn_close]:
            btn.setFixedHeight(self.height_val)
        
        if not is_dialog:
            self.controls_layout.addWidget(self.btn_min)
            self.controls_layout.addWidget(self.btn_max)
        self.controls_layout.addWidget(self.btn_close)
        
        self.main_layout.addWidget(self.controls_container, 0, 0, Qt.AlignRight)
        
        # Connections
        self.btn_min.clicked.connect(self.on_min)
        self.btn_max.clicked.connect(self.on_max)
        self.btn_close.clicked.connect(self.on_close)
        
        # Dragging support
        self._dragging = False
        self._drag_start_pos = QPoint()

    def set_title(self, title):
        self.title_label.setText(title)

    def set_menu_bar(self, menu_bar):
        """Integrate an existing QMenuBar into the title bar."""
        self.menu_bar = menu_bar
        self.menu_layout.addWidget(menu_bar)
        self.update_theme() # Refresh to apply correct colors to menu

    def on_min(self):
        if self.parent_window:
            self.parent_window.showMinimized()

    def on_max(self):
        if self.parent_window:
            if self.parent_window.isMaximized():
                self.parent_window.showNormal()
                self.btn_max.setText("\uE922")
            else:
                self.parent_window.showMaximized()
                self.btn_max.setText("\uE923")

    def on_close(self):
        if self.parent_window:
            self.parent_window.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            # For modern snapping on Windows, we'd use native windows API,
            # but for manual dragging:
            self._drag_start_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_start_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        """Maximize/Restore on double click."""
        self.on_max()

    def update_theme(self):
        """Update colors based on AppConfig."""
        bg = app_config.get_theme_color("bg_pure")
        text = app_config.get_theme_color("text_main")
        accent = app_config.get_theme_color("accent")
        accent_light = app_config.get_theme_color("accent_light")
        border = app_config.get_theme_color("border_std")
        btn_hover = "rgba(128, 128, 128, 60)"
        close_hover = "#E81123"
        close_hover_text = "white"
        
        # Button styles (QSS for better hover states)
        if hasattr(self, 'menu_bar') and self.menu_bar:
            self.menu_bar.setStyleSheet(f"""
                QMenuBar {{ background: transparent; border: none; color: {text}; font-size: 11pt; }}
                QMenuBar::item {{ background: transparent; padding: 4px 10px; margin: 0 2px; border-radius: 4px; color: {text}; }}
                QMenuBar::item:selected {{ background-color: {accent_light}; color: {accent}; }}
            """)
        
        is_manga = app_config.get_theme_name() == "Manga"
        b_weight = "2px" if is_manga else "1px"
        
        qss = f"""
            #ModernTitleBar {{
                background-color: {bg};
                border-bottom: {b_weight} solid {border};
            }}
            #TitleBarMenuContainer, #TitleBarControlsContainer {{
                background: transparent;
            }}
            QLabel {{ color: {text}; border: none; background: transparent; }}
            #TitleButton, #TitleButtonClose {{
                background-color: transparent;
                border: none;
                color: {text};
                font-family: 'Segoe MDL2 Assets', 'Segoe UI Symbolic', 'Symbol';
                font-size: 10px;
            }}
            #TitleButton:hover {{
                background-color: {btn_hover};
            }}
            #TitleButtonClose:hover {{
                background-color: {close_hover};
                color: {close_hover_text};
            }}
        """
        self.setStyleSheet(qss)
