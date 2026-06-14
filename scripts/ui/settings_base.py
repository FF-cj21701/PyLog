from PySide6.QtWidgets import (QHBoxLayout, QListWidget, QStackedWidget, 
                               QWidget, QVBoxLayout, QFrame, QLabel, 
                               QListWidgetItem)
from PySide6.QtCore import Qt, QSize
from .base_dialog import ThemeDialog
from core.app_config import app_config

class SidebarSettingsDialog(ThemeDialog):
    """
    A premium base class for settings dialogs with a left navigation sidebar.
    Theme-aware and easily extensible for adding multiple setting panels.
    Now supports a dedicated footer area for buttons (Ok/Cancel).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.resize(900, 650)
        
        # 1. Root Vertical Layout for the entire container
        self.root_layout = QVBoxLayout()
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(0)
        super().setLayout(self.root_layout) # Use ThemeDialog's layout redirection
        
        # 2. Body Layout (Sidebar + Content)
        self.body_layout = QHBoxLayout()
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(0)
        self.root_layout.addLayout(self.body_layout)
        
        # 2a. Left Sidebar
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("settingsSidebar")
        self.sidebar.setFixedWidth(200)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body_layout.addWidget(self.sidebar)
        
        # Divider Line
        self.v_line = QFrame()
        self.v_line.setFrameShape(QFrame.VLine)
        self.v_line.setObjectName("settingsDivider")
        self.body_layout.addWidget(self.v_line)
        
        # 2b. Right Content Area (Stacked)
        self.content_stack = QStackedWidget()
        self.content_stack.setObjectName("settingsContentStack")
        self.body_layout.addWidget(self.content_stack)
        
        # 3. Footer Area (for buttons)
        self.footer_container = QWidget()
        self.footer_container.setObjectName("settingsFooter")
        self.footer_layout = QHBoxLayout(self.footer_container)
        self.footer_layout.setContentsMargins(20, 10, 20, 15)
        self.root_layout.addWidget(self.footer_container)
        
        # Connect sidebar selection to content stack
        self.sidebar.currentRowChanged.connect(self.content_stack.setCurrentIndex)
        
        # Apply initial theme
        self.update_theme()

    def add_panel(self, name, widget):
        """Add a new panel to the settings dialog."""
        # Add to sidebar
        item = QListWidgetItem(name)
        item.setSizeHint(QSize(0, 45))
        item.setTextAlignment(Qt.AlignCenter | Qt.AlignLeft)
        self.sidebar.addItem(item)
        
        # Add to stack
        panel_container = QWidget()
        panel_container.setObjectName("settingsPanelContainer")
        panel_layout = QVBoxLayout(panel_container)
        panel_layout.setContentsMargins(30, 20, 30, 20)
        
        # Header for the panel
        header = QLabel(name.upper())
        header.setObjectName("panelHeader")
        header.setStyleSheet("font-weight: bold; font-size: 14pt; margin-bottom: 10px;")
        panel_layout.addWidget(header)
        
        panel_layout.addWidget(widget)
        panel_layout.addStretch()
        
        self.content_stack.addWidget(panel_container)
        
        # Default selection
        if self.sidebar.count() == 1:
            self.sidebar.setCurrentRow(0)

    def set_footer_widget(self, widget):
        """Helper to quickly add a QDialogButtonBox or similar to the footer."""
        # Clear existing footer
        while self.footer_layout.count():
            item = self.footer_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.footer_layout.addWidget(widget)

    def update_theme(self):
        """Apply theme-aware styling from global app_config with safety checks."""
        # Safety check: ensure components exist before styling
        if not hasattr(self, 'sidebar'):
            return
            
        c = lambda t: app_config.get_theme_color(t)
        
        # Use dialog_bg for everything to create a unified, single-pane look
        main_bg = c('dialog_bg')
        sidebar_text = c('text_dim')
        accent = c('accent')
        border = c('border_std')
        
        # Use Data Browser's selection colors for consistency
        selected_bg = c('tree_item_selected_bg')
        selected_text = c('tree_item_selected_text')
        
        self.sidebar.setStyleSheet(f"""
            QListWidget#settingsSidebar {{
                background-color: {main_bg};
                border: none;
                padding-top: 15px;
                outline: none;
            }}
            QListWidget#settingsSidebar::item {{
                color: {sidebar_text};
                padding-left: 20px;
                height: 40px;
                border: none;
                margin: 4px 10px;
                border-radius: 6px;
            }}
            QListWidget#settingsSidebar::item:hover {{
                background-color: {selected_bg};
                color: {selected_text};
            }}
            QListWidget#settingsSidebar::item:selected {{
                background-color: {selected_bg};
                color: {selected_text};
                font-weight: bold;
            }}
        """)
        
        self.v_line.setStyleSheet(f"""
            QFrame#settingsDivider {{
                background-color: {border};
                max-width: 1px;
                border: none;
                opacity: 0.5;
            }}
        """)
        
        self.content_stack.setStyleSheet(f"background-color: {main_bg};")
        
        self.footer_container.setStyleSheet(f"""
            QWidget#settingsFooter {{
                background-color: {main_bg};
                border-top: 1px solid {border};
            }}
        """)
