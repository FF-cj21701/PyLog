from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget, QInputDialog, QLineEdit, QLabel, QDialogButtonBox, QGraphicsDropShadowEffect
from .theme_manager import ThemeManager
from .custom_title_bar import ModernTitleBar
from .frameless_helper import FramelessHelper

class ThemeDialog(QDialog):
    """
    Base dialog class that automatically applies settings-specific styling.
    Ensures visual consistency across all configuration menus.
    Now supports a custom frameless title bar with dragging and resizing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        # 1. Enable Frameless architecture and Translucent background for shadows
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        # 2. Root layout to hold the Main Frame (with shadow)
        self._root_layout = QVBoxLayout(self)
        self._root_layout.setContentsMargins(12, 12, 12, 12) # Margin for shadow
        self._root_layout.setSpacing(0)
        
        # 3. Main Frame that contains everything and gets the shadow
        self.main_frame = QWidget()
        self.main_frame.setObjectName("dialogMainFrame")
        self.main_frame_layout = QVBoxLayout(self.main_frame)
        self.main_frame_layout.setContentsMargins(1, 1, 1, 1) # Border margin
        self.main_frame_layout.setSpacing(0)
        self._root_layout.addWidget(self.main_frame)
        
        # 4. Custom Title Bar
        self.title_bar = ModernTitleBar(self, is_dialog=True)
        self.main_frame_layout.addWidget(self.title_bar)
        
        # 5. Container for subclass content
        self.container = QWidget()
        self.container.setObjectName("dialogContainer")
        self.main_frame_layout.addWidget(self.container)
        
        # 6. Apply Shadow Effect to the main frame
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(20)
        self._shadow.setXOffset(0)
        self._shadow.setYOffset(2)
        self._shadow.setColor(QColor(0, 0, 0, 160)) # Default dark shadow
        self.main_frame.setGraphicsEffect(self._shadow)
        
        # 7. Frameless Helper for resizing and recursive event filtering
        # Monitor both the main frame and its children
        self.frameless_helper = FramelessHelper(self, border_width=12)
        self.frameless_helper.add_widget(self.main_frame)
        self.frameless_helper.add_widget(self.title_bar)
        self.frameless_helper.add_widget(self.container)
        
        # Apply the isolated dialog theme
        ThemeManager.apply_to_dialog(self)
        
    def setLayout(self, layout):
        """Redirect subclass layouts to the inner container."""
        if not hasattr(self, 'title_bar') or layout == self._root_layout:
            super().setLayout(layout)
            return
            
        # Ensure the layout is not already parented to 'self' in a way that prevents moving it
        self.container.setLayout(layout)
            
    def setWindowTitle(self, title):
        """Sync native window title with custom title bar."""
        super().setWindowTitle(title)
        if hasattr(self, 'title_bar'):
            self.title_bar.set_title(title)

    @staticmethod
    def get_text(parent, title, label, text=""):
        """Convenience static method delegating to FramelessInputDialog."""
        return FramelessInputDialog.get_text(parent, title, label, text)

    @staticmethod
    def confirm(parent, title, message):
        """Replacement for QMessageBox.question with theme and frameless title bar."""
        dlg = FramelessMessageDialog(parent, title, message, mode="confirm")
        return dlg.exec() == QDialog.Accepted

    @staticmethod
    def message(parent, title, message, icon_type="info"):
        """Replacement for QMessageBox.information/critical with theme and frameless title bar."""
        dlg = FramelessMessageDialog(parent, title, message, mode="message", icon_type=icon_type)
        dlg.exec()

class FramelessInputDialog(ThemeDialog):
    """Custom replacement for QInputDialog to maintain frameless aesthetic."""
    def __init__(self, parent=None, title="", label="", text=""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(350, 150)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        layout.addWidget(QLabel(label))
        self.line_edit = QLineEdit(text)
        layout.addWidget(self.line_edit)
        
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        
        self.line_edit.setFocus()
        self.line_edit.selectAll()

    def textValue(self):
        return self.line_edit.text()
        
    @staticmethod
    def get_text(parent, title, label, text=""):
        """
        Unified replacement for QInputDialog.getText with theme and frameless title bar applied.
        """
        dlg = FramelessInputDialog(parent, title, label, text)
        if dlg.exec() == QDialog.Accepted:
            return dlg.textValue(), True
        return "", False

class FramelessMessageDialog(ThemeDialog):
    """Custom replacement for QMessageBox to maintain frameless aesthetic."""
    def __init__(self, parent=None, title="", message="", mode="confirm", icon_type="info"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(380, 160)
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        content_widget = QWidget()
        content_widget.setStyleSheet("background: transparent; border: none;")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(10, 5, 10, 5)
        
        # Message Label
        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setAlignment(Qt.AlignCenter)
        msg_label.setStyleSheet("font-size: 11pt; margin-bottom: 5px; background: transparent; border: none;")
        content_layout.addWidget(msg_label)
        
        layout.addWidget(content_widget)
        
        # Buttons
        if mode == "confirm":
            self.buttons = QDialogButtonBox(QDialogButtonBox.Yes | QDialogButtonBox.No)
        else:
            self.buttons = QDialogButtonBox(QDialogButtonBox.Ok)
            
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        
        # Center horizontally
        self.buttons.setCenterButtons(True)
