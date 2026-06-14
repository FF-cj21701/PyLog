from PySide6.QtWidgets import QVBoxLayout, QLabel, QHBoxLayout, QFrame, QScrollArea, QWidget
from PySide6.QtCore import Qt
from ..base_dialog import ThemeDialog

class AboutDialog(ThemeDialog):
    """
    A premium About dialog for PyLog with a scrollable content area.
    Displays developer information and open source technology stack.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PyLog")
        self.resize(500, 500)
        
        # 1. Main layout for the inner container part of ThemeDialog
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(main_layout)
        
        # 2. Create a Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QScrollArea.NoFrame)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Transparent background for the scroll area to match ThemeDialog
        self.scroll_area.setStyleSheet("background: transparent;")
        
        # 3. Content Widget inside Scroll Area
        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(scroll_content)
        content_layout.setContentsMargins(30, 20, 30, 30)
        content_layout.setSpacing(15)
        
        # Header - App Name & Version
        app_title = QLabel("PyLog")
        app_title.setStyleSheet("font-size: 32px; font-weight: bold; color: #7289da; margin-top: 10px;")
        app_title.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(app_title)
        
        version_label = QLabel("Version 1.0.0 (Stable)")
        version_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #888888;")
        version_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(version_label)
        
        # Separator line
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Plain)
        line.setStyleSheet("background-color: rgba(128, 128, 128, 0.2); max-height: 1px; margin: 5px 0;")
        content_layout.addWidget(line)
        
        # Developer Info
        dev_label = QLabel("Developer: XXX")
        dev_label.setStyleSheet("font-size: 18px; font-weight: 500; margin: 10px 0;")
        dev_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(dev_label)
        
        # Tech Stack Title
        tech_title = QLabel("Powered by Open Source Excellence:")
        tech_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #7289da;")
        content_layout.addWidget(tech_title)
        
        # Tech Stack Content
        tech_stack = (
            "• <b>PySide6</b> - High Performance Qt Framework<br>"
            "• <b>pyqtgraph</b> - Scientfic Data Visualization<br>"
            "• <b>numpy & scipy</b> - Numerical Computing & Processing<br>"
            "• <b>dlisio</b> - Log Data Interchange Support<br>"
            "• <b>openai</b> - Intelligent AI Integration<br>"
            "• <b>requests</b> - Robust Network Communication"
        )
        tech_label = QLabel(tech_stack)
        tech_label.setStyleSheet("font-size: 13px; line-height: 1.8; margin-top: 5px;")
        tech_label.setWordWrap(True)
        content_layout.addWidget(tech_label)
        
        content_layout.addStretch()
        
        # Footer
        footer = QLabel("© 2026 PyLog Team. All rights reserved.")
        footer.setStyleSheet("font-size: 11px; color: #999999;")
        footer.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(footer)
        
        # Final Assembly
        self.scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.scroll_area)
