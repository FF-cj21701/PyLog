from PySide6.QtWidgets import QVBoxLayout, QLabel, QHBoxLayout, QFrame, QScrollArea, QWidget
from PySide6.QtCore import Qt
from ..base_dialog import ThemeDialog

class AboutDialog(ThemeDialog):
    """
    A premium About dialog for PyLog with a scrollable content area.
    Displays project information, open source license, and technology stack.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About PyLog")
        self.resize(500, 620)
        
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
        
        subtitle = QLabel("AI-Powered Well Log Visualization & Analysis")
        subtitle.setStyleSheet("font-size: 13px; font-weight: 500; color: #888888;")
        subtitle.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(subtitle)
        
        version_label = QLabel("Version 1.0.0")
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
        dev_label = QLabel("Developer: Li FengFeng")
        dev_label.setStyleSheet("font-size: 16px; font-weight: 500; margin: 5px 0;")
        dev_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(dev_label)
        
        # GitHub Link
        github_label = QLabel(
            '<a href="https://github.com/729244088/PyLog" '
            'style="color: #7289da; text-decoration: none; font-size: 14px;">'
            '⭐ github.com/729244088/PyLog</a>'
        )
        github_label.setOpenExternalLinks(True)
        github_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(github_label)
        
        # License
        license_label = QLabel("Licensed under the MIT License")
        license_label.setStyleSheet("font-size: 12px; color: #999999;")
        license_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(license_label)
        
        # Separator line
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Plain)
        line2.setStyleSheet("background-color: rgba(128, 128, 128, 0.2); max-height: 1px; margin: 5px 0;")
        content_layout.addWidget(line2)
        
        # Tech Stack Title
        tech_title = QLabel("Powered by Open Source:")
        tech_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #7289da;")
        content_layout.addWidget(tech_title)
        
        # Tech Stack Content
        tech_stack = (
            "• <b>PySide6</b> — Qt for Python GUI Framework (LGPL)<br>"
            "• <b>pyqtgraph</b> — Scientific Data Visualization (MIT)<br>"
            "• <b>HDF5 / h5py</b> — High-Performance Data Storage (BSD)<br>"
            "• <b>NumPy & SciPy</b> — Numerical Computing (BSD)<br>"
            "• <b>Matplotlib</b> — Publication-Quality Plotting (PSF)<br>"
            "• <b>dlisio</b> — DLIS Log Data Parser (LGPL)<br>"
            "• <b>OpenAI</b> — AI Assistant Integration (Apache 2.0)"
        )
        tech_label = QLabel(tech_stack)
        tech_label.setStyleSheet("font-size: 13px; line-height: 1.8; margin-top: 5px;")
        tech_label.setWordWrap(True)
        content_layout.addWidget(tech_label)
        
        # Bundled Third-Party Libraries
        bundled_title = QLabel("Bundled Libraries:")
        bundled_title.setStyleSheet("font-size: 14px; font-weight: bold; color: #7289da; margin-top: 5px;")
        content_layout.addWidget(bundled_title)
        
        bundled_stack = (
            "• <b>Ace Editor</b> — Code Editor (BSD 3-Clause)<br>"
            "• <b>highlight.js</b> — Syntax Highlighting (BSD 3-Clause)<br>"
            "• <b>marked</b> — Markdown Parser (MIT)<br>"
            "• <b>QWebChannel.js</b> — Qt Bridge (LGPL 3.0)"
        )
        bundled_label = QLabel(bundled_stack)
        bundled_label.setStyleSheet("font-size: 13px; line-height: 1.8; margin-top: 5px;")
        bundled_label.setWordWrap(True)
        content_layout.addWidget(bundled_label)
        
        content_layout.addStretch()
        
        # Footer
        footer = QLabel("© 2026 PyLog Contributors. MIT License.")
        footer.setStyleSheet("font-size: 11px; color: #999999;")
        footer.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(footer)
        
        # Final Assembly
        self.scroll_area.setWidget(scroll_content)
        main_layout.addWidget(self.scroll_area)

