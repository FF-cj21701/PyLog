from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
                               QTextEdit, QPushButton, QFrame, QWidget)
from PySide6.QtCore import Qt
from core.app_config import app_config

class SkillEditorDialog(QDialog):
    """A professional editor for AI Geoscience Skills."""
    
    def __init__(self, skill_name, title, description, instruction, parent=None):
        super().__init__(parent)
        self.skill_name = skill_name
        self.setWindowTitle(f"Skill Editor - {skill_name}")
        self.resize(800, 700)
        
        # Color helper
        self.c = lambda t: app_config.get_theme_color(t)
        
        self.init_ui(title, description, instruction)
        self.apply_theme()

    def init_ui(self, title, description, instruction):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 1. Name Field
        layout.addWidget(self._create_label("Skill Name (Title)"))
        self.name_edit = QLineEdit(title)
        self.name_edit.setPlaceholderText("e.g., Lasio - LAS File Specialist")
        layout.addWidget(self.name_edit)
        
        # 2. Description Field
        layout.addWidget(self._create_label("Description (Short Summary)"))
        self.desc_edit = QTextEdit(description)
        self.desc_edit.setMaximumHeight(80)
        self.desc_edit.setPlaceholderText("Tell the AI what this skill is for in one or two sentences.")
        layout.addWidget(self.desc_edit)
        
        # 3. Instruction Field (The Markdown Content)
        layout.addWidget(self._create_label("Instruction (Core Logic / Markdown)"))
        self.instruction_edit = QTextEdit(instruction)
        self.instruction_edit.setAcceptRichText(False)
        self.instruction_edit.setPlaceholderText("# Detailed Instructions...\n\nExplain formulas and workflows here.")
        layout.addWidget(self.instruction_edit)
        
        # 4. Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setMinimumWidth(100)
        btn_layout.addWidget(self.cancel_btn)
        
        self.save_btn = QPushButton("Save Skill")
        self.save_btn.clicked.connect(self.accept)
        self.save_btn.setMinimumWidth(120)
        btn_layout.addWidget(self.save_btn)
        
        layout.addLayout(btn_layout)

    def _create_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight: bold; color: {self.c('text_dim')};")
        return lbl

    def apply_theme(self):
        bg = self.c('dialog_bg')
        input_bg = self.c('input_bg')
        text = self.c('text_main')
        accent = self.c('accent')
        border = self.c('border_std')
        
        self.setStyleSheet(f"background-color: {bg}; color: {text};")
        
        input_style = f"""
            QLineEdit, QTextEdit {{
                background-color: {input_bg};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 8px;
                color: {text};
                font-family: 'Consolas', 'Monaco', monospace;
            }}
            QLineEdit:focus, QTextEdit:focus {{
                border: 1px solid {accent};
            }}
        """
        self.name_edit.setStyleSheet(input_style)
        self.desc_edit.setStyleSheet(input_style)
        self.instruction_edit.setStyleSheet(input_style)
        
        btn_style = f"""
            QPushButton {{
                background-color: {input_bg};
                border: 1px solid {border};
                border-radius: 4px;
                padding: 8px 15px;
                color: {text};
            }}
            QPushButton:hover {{
                background-color: {border};
            }}
        """
        self.cancel_btn.setStyleSheet(btn_style)
        self.save_btn.setStyleSheet(f"""
            {btn_style}
            QPushButton {{
                background-color: {accent};
                color: white;
                font-weight: bold;
                border: none;
            }}
            QPushButton:hover {{
                background-color: {accent};
                opacity: 0.8;
            }}
        """)

    def get_data(self):
        """Returns the edited metadata and content."""
        return {
            "title": self.name_edit.text().strip(),
            "description": self.desc_edit.toPlainText().strip(),
            "instruction": self.instruction_edit.toPlainText().strip()
        }
