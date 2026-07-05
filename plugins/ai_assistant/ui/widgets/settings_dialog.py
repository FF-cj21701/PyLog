from PySide6.QtWidgets import (QVBoxLayout, QFormLayout, QComboBox, QLineEdit, 
                                QDialogButtonBox, QSpinBox, QTextEdit, QLabel, QPushButton, QHBoxLayout, 
                               QFileDialog, QCheckBox, QListWidget, QWidget, QScrollArea, QFrame, QMessageBox, QInputDialog, QDialog,
                               QTreeWidget, QTreeWidgetItem, QHeaderView, QSizePolicy)
from PySide6.QtCore import QSettings, Qt
from core.app_config import app_config
from ...ai_core.config import AIConfig
from scripts.ui.settings_base import SidebarSettingsDialog

# 尝试多种方式导入组件，确保在不同加载环境下都能工作
try:
    from ...services.skill_service import SkillService
    from ...ai_core.prompts import SystemPrompts
    from ...common.paths import PathResolver
    from ...ai_core.api_client import AsyncAIWorker
    from ...ai_core.mcp_integration import MCPToolProvider, parse_mcp_args_input, test_mcp_server_connection
except ImportError:
    try:
        from plugins.ai_assistant.services.skill_service import SkillService
        from plugins.ai_assistant.ai_core.prompts import SystemPrompts
        from plugins.ai_assistant.common.paths import PathResolver
        from plugins.ai_assistant.ai_core.api_client import AsyncAIWorker
        from plugins.ai_assistant.ai_core.mcp_integration import MCPToolProvider, parse_mcp_args_input, test_mcp_server_connection
    except ImportError:
        SkillService = None
        SystemPrompts = None
        PathResolver = None
        AsyncAIWorker = None
        MCPToolProvider = None
        parse_mcp_args_input = None
        test_mcp_server_connection = None

import os
import json
import qasync

try:
    # 方式 1: 直接基于搜索路径
    from .skill_editor import SkillEditorDialog
except ImportError:
    try:
        # 方式 2: 基于全路径
        from plugins.ai_assistant.ui.widgets.skill_editor import SkillEditorDialog
    except ImportError:
        try:
            # 方式 3: 相对导入
            from .skill_editor import SkillEditorDialog
        except ImportError:
            SkillEditorDialog = None

import os
import json

def get_project_root():
    """更稳健地寻找项目根目录，通过寻找 .agents 文件夹或 main.py 来确定"""
    curr = os.path.abspath(__file__)
    # 向上寻找最多 10 层
    for _ in range(10):
        curr = os.path.dirname(curr)
        if os.path.exists(os.path.join(curr, ".agents")):
            return curr
        if os.path.exists(os.path.join(curr, "main.py")):
            return curr
    # 回退到硬编码计算
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


TOOL_CATEGORY_RULES = [
    ("Plot / Window", {"plotting", "plot_spec", "plot_style", "curve_style", "track_style", "image_style", "colormap"}),
    ("Data / Wells", {"geoscience", "pylog", "well", "curve", "data"}),
    ("Scripts", {"script", "python", "run script", "script editor"}),
    ("Files / Workspace", {"file", "patch", "workspace", "document", "html"}),
    ("Search / Discovery", {"search", "find", "inspect", "help", "locate"}),
    ("Planning", {"task plan", "plan"}),
    ("Verification", {"verify", "test", "pytest", "lint", "format", "import"}),
    ("Skills", {"skill"}),
]


def _tool_text_blob(spec):
    parts = [
        getattr(spec, "name", ""),
        getattr(spec, "description", ""),
        getattr(spec, "usage_hint", ""),
        " ".join(getattr(spec, "capability_tags", []) or []),
        " ".join(getattr(spec, "domain_tags", []) or []),
        " ".join(getattr(spec, "keywords", []) or []),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def categorize_local_tool_spec(spec):
    """Return the settings-page category for a local tool spec."""
    text = _tool_text_blob(spec)
    for category, markers in TOOL_CATEGORY_RULES:
        if any(marker in text for marker in markers):
            return category
    return "General"


def build_local_tool_category_groups(specs):
    groups = {}
    for spec in specs or []:
        if getattr(spec, "source", "local") != "local":
            continue
        category = categorize_local_tool_spec(spec)
        groups.setdefault(category, []).append(spec)

    for category in groups:
        groups[category].sort(key=lambda item: getattr(item, "name", ""))

    category_order = {name: index for index, (name, _markers) in enumerate(TOOL_CATEGORY_RULES)}
    return dict(sorted(groups.items(), key=lambda item: (category_order.get(item[0], 999), item[0])))


class LocalMCPServerDialog(QDialog):
    def __init__(self, name, conf=None, parent=None):
        super().__init__(parent)
        conf = conf or {}
        self.setWindowTitle(f"Local MCP Server: {name}")
        self.resize(640, 320)

        c = lambda t: app_config.get_theme_color(t)
        is_manga = app_config.get_theme_name() == "Manga"
        b_weight = "2px" if is_manga else "1px"
        b_radius = "0px" if is_manga else "4px"

        layout = QVBoxLayout(self)

        intro = QLabel(
            "Configure a local stdio MCP server. Use an executable command plus startup arguments."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        field_style = f"""
            QLineEdit, QTextEdit {{
                background-color: {c('input_bg') if c('input_bg') else c('panel_bg')};
                color: {c('text_main')};
                border: {b_weight} solid {c('border_std')};
                border-radius: {b_radius};
                padding: 6px;
            }}
        """

        form = QFormLayout()
        self.command_edit = QLineEdit(conf.get("command", ""))
        self.command_edit.setStyleSheet(field_style)
        form.addRow("Command:", self.command_edit)
        layout.addLayout(form)

        args_label = QLabel("Arguments:")
        layout.addWidget(args_label)

        self.args_edit = QTextEdit()
        self.args_edit.setStyleSheet(field_style)
        self.args_edit.setPlaceholderText("One argument per line, or paste a JSON list.")
        self.args_edit.setPlainText("\n".join(conf.get("args", [])))
        self.args_edit.setAcceptRichText(False)
        self.args_edit.setMinimumHeight(140)
        layout.addWidget(self.args_edit)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_values(self):
        return {
            "command": self.command_edit.text().strip(),
            "args_text": self.args_edit.toPlainText(),
        }

class AISettingsDialog(SidebarSettingsDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Assistant Settings")
        self.resize(900, 650)
        
        self.settings = QSettings("PyLog", "AIAssistant")
        self.config = AIConfig()
        self.disabled_skills = [] # Names of disabled skills
        
        self._profiles = [] # Current profiles in UI
        self._current_profile_index = -1
        
        # 1. Create Panels
        self._create_panels()
        
        # 2. Add Buttons to the bottom
        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Apply)
        self.button_box.accepted.connect(self.save_settings)
        self.button_box.rejected.connect(self.reject)
        self.button_box.button(QDialogButtonBox.Apply).clicked.connect(self.apply_settings)
        
        self.set_footer_widget(self.button_box)
        
        # 3. Initial Load
        self.load_settings()

    def _create_panels(self):
        """Create the modular setting panels."""
        self.connection_panel = self._create_connection_panel()
        self.behavior_panel = self._create_behavior_panel()
        self.extensions_panel = self._create_extensions_panel()
        self.tools_panel = self._create_tools_panel()
        self.skills_panel = self._create_skills_panel()
        
        self.add_panel("Connection", self.connection_panel)
        self.add_panel("Behavior", self.behavior_panel)
        self.add_panel("Extensions", self.extensions_panel)
        self.add_panel("Tools", self.tools_panel)
        self.add_panel("Expert Skills", self.skills_panel)

        # Apply unified styling to all created buttons
        self._apply_panel_button_styles()

    def _apply_panel_button_styles(self):
        """统一应用按钮样式，确保在不同主题下都有良好的视觉反馈"""
        c = lambda t: app_config.get_theme_color(t)
        # 获取边框粗细和圆角 (参考 ThemeManager)
        is_manga = app_config.get_theme_name() == "Manga"
        b_weight = "2px" if is_manga else "1px"
        b_radius = "0px" if is_manga else "4px"
        
        btn_style = f"""
            QPushButton {{
                background-color: {c('button_bg')};
                border: {b_weight} solid {c('border_std')};
                border-radius: {b_radius};
                padding: 6px 12px;
                color: {c('text_main')};
                font-weight: 500;
            }}
            QPushButton:hover {{
                background-color: {c('button_hover')};
                border-color: {c('accent')};
            }}
            QPushButton:pressed {{
                background-color: {c('accent')};
                color: #FFFFFF;
            }}
        """
        
        # Apply to all panel buttons
        buttons = [
            self.add_profile_btn, self.rename_profile_btn, self.del_profile_btn,
            self.fetch_models_btn, self.add_folder_btn, self.add_file_btn,
            self.remove_selected_btn, self.mcp_add_btn, self.mcp_test_btn, self.mcp_remove_btn,
            self.refresh_tools_btn, self.refresh_skills_btn, self.create_skill_btn
        ]
        
        for btn in buttons:
            btn.setStyleSheet(btn_style)
            btn.setCursor(Qt.PointingHandCursor)

        # Danger buttons
        danger_style = btn_style.replace(f"color: {c('text_main')};", f"color: {c('danger')};")
        self.del_profile_btn.setStyleSheet(danger_style)
        self.mcp_remove_btn.setStyleSheet(danger_style)

    def _create_connection_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(20)
        
        c = lambda t: app_config.get_theme_color(t)
        
        # --- Section 1: Profile Management ---
        mgmt_group = QWidget()
        mgmt_layout = QHBoxLayout(mgmt_group)
        mgmt_layout.setContentsMargins(0, 0, 0, 0)
        mgmt_layout.setSpacing(10)
        
        profile_label = QLabel("Active Profile:")
        profile_label.setStyleSheet("font-weight: bold; font-size: 10pt;")
        mgmt_layout.addWidget(profile_label)
        
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(200)
        self.profile_combo.currentIndexChanged.connect(self.on_profile_index_changed)
        mgmt_layout.addWidget(self.profile_combo, 1)
        
        self.add_profile_btn = QPushButton("+ New")
        self.add_profile_btn.setFixedWidth(85)
        self.add_profile_btn.clicked.connect(self.add_new_profile)
        mgmt_layout.addWidget(self.add_profile_btn)
        
        self.rename_profile_btn = QPushButton("Rename")
        self.rename_profile_btn.setFixedWidth(85)
        self.rename_profile_btn.clicked.connect(self.rename_current_profile)
        mgmt_layout.addWidget(self.rename_profile_btn)
        
        self.del_profile_btn = QPushButton("Delete")
        self.del_profile_btn.setFixedWidth(85)
        self.del_profile_btn.clicked.connect(self.delete_current_profile)
        mgmt_layout.addWidget(self.del_profile_btn)
        
        layout.addWidget(mgmt_group)
        
        # --- Section 2: Configuration Card ---
        card = QFrame()
        card.setObjectName("configCard")
        # 直接使用样式注入
        card.setStyleSheet(f"""
            #configCard {{
                background-color: {c('input_bg')};
                border: 1px solid {c('border_std')};
                border-radius: 12px;
            }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(25, 25, 25, 25)
        card_layout.setSpacing(15)
        
        card_header = QLabel("SERVICE CONFIGURATION")
        card_header.setStyleSheet(f"color: {c('text_dim')}; font-size: 8pt; font-weight: bold; letter-spacing: 1px;")
        card_layout.addWidget(card_header)
        
        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(15)
        form.setLabelAlignment(Qt.AlignRight)
        

        
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.api_key_edit)
        
        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("https://api.example.com/v1")
        form.addRow("Base URL:", self.base_url_edit)
        
        # Model Name Row with Fetch Button
        model_layout = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("model-name")
        model_layout.addWidget(self.model_edit, 1)
        
        self.fetch_models_btn = QPushButton("Auto Fetch")
        self.fetch_models_btn.setFixedWidth(85)
        self.fetch_models_btn.clicked.connect(self.fetch_available_models)
        model_layout.addWidget(self.fetch_models_btn)
        
        form.addRow("Model Name:", model_layout)
        
        card_layout.addWidget(form_widget)
        layout.addWidget(card)
        
        layout.addStretch()
        return widget

    def _create_behavior_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        
        self.max_rounds_spin = QSpinBox()
        self.max_rounds_spin.setMinimum(1)
        self.max_rounds_spin.setMaximum(100)
        form.addRow("Max Chat Rounds:", self.max_rounds_spin)
        
        self.max_history_spin = QSpinBox()
        self.max_history_spin.setMinimum(1)
        self.max_history_spin.setMaximum(100)
        form.addRow("Max History Rounds:", self.max_history_spin)
        
        self.auto_load_checkbox = QCheckBox("Auto-load AI Assistant on startup")
        form.addRow(self.auto_load_checkbox)

        self.mcp_enabled_checkbox = QCheckBox("Enable optional local MCP tools")
        form.addRow(self.mcp_enabled_checkbox)
        
        layout.addLayout(form)
        layout.addStretch()
        return widget

    def _create_extensions_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        layout.addWidget(QLabel("<b>Path Whitelist (Files/Folders):</b>"))
        self.whitelist_edit = QListWidget()
        layout.addWidget(self.whitelist_edit)
        
        btn_layout = QHBoxLayout()
        self.add_folder_btn = QPushButton("Add Folder")
        self.add_folder_btn.clicked.connect(self.add_folder)
        btn_layout.addWidget(self.add_folder_btn)
        
        self.add_file_btn = QPushButton("Add File")
        self.add_file_btn.clicked.connect(self.add_file)
        btn_layout.addWidget(self.add_file_btn)
        
        self.remove_selected_btn = QPushButton("Remove Selected")
        self.remove_selected_btn.clicked.connect(self.remove_selected)
        btn_layout.addWidget(self.remove_selected_btn)
        layout.addLayout(btn_layout)
        
        layout.addSpacing(20)
        layout.addWidget(QLabel("<b>Local MCP Servers (stdio):</b>"))
        hint = QLabel(
            "Only needed for external local tool processes. "
            "Built-in PyLog tools do not depend on MCP."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.mcp_list = QListWidget()
        self.mcp_list.itemDoubleClicked.connect(self.edit_mcp_server)
        layout.addWidget(self.mcp_list)
        
        mcp_btn_layout = QHBoxLayout()
        self.mcp_add_btn = QPushButton("Add Server")
        self.mcp_add_btn.clicked.connect(self.add_mcp_server)
        mcp_btn_layout.addWidget(self.mcp_add_btn)
        self.mcp_test_btn = QPushButton("Test Selected Local Server")
        self.mcp_test_btn.clicked.connect(self.test_selected_mcp_server)
        mcp_btn_layout.addWidget(self.mcp_test_btn)
        self.mcp_remove_btn = QPushButton("Remove Selected")
        self.mcp_remove_btn.clicked.connect(self.remove_mcp_server)
        mcp_btn_layout.addWidget(self.mcp_remove_btn)
        layout.addLayout(mcp_btn_layout)
        
        layout.addStretch()
        return widget

    def _create_tools_panel(self):
        widget = QWidget()
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        intro = QLabel(
            "Read-only inventory of built-in local AI tools. External MCP tools are configured on the Extensions page."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.tools_summary_label = QLabel("Local tools: not loaded")
        self.tools_summary_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.tools_summary_label)

        self.tools_tree = QTreeWidget()
        self.tools_tree.setColumnCount(4)
        self.tools_tree.setHeaderLabels(["Tool", "Description", "Tags", "Risk"])
        self.tools_tree.setRootIsDecorated(True)
        self.tools_tree.setAlternatingRowColors(False)
        self.tools_tree.setUniformRowHeights(False)
        self.tools_tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tools_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.tools_tree.setMinimumHeight(420)
        self._style_tools_tree()
        header = self.tools_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.tools_tree, 1)

        self.refresh_tools_btn = QPushButton("Refresh Local Tools")
        self.refresh_tools_btn.clicked.connect(self.refresh_local_tools)
        layout.addWidget(self.refresh_tools_btn)

        return widget

    def _style_tools_tree(self):
        c = lambda t: app_config.get_theme_color(t)
        self.tools_tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {c('dialog_bg')};
                color: {c('text_main')};
                border: 1px solid {c('border_std')};
                border-radius: 8px;
                outline: none;
                alternate-background-color: {c('dialog_bg')};
            }}
            QTreeWidget::item {{
                color: {c('text_main')};
                padding: 6px 4px;
                border-bottom: 1px solid {c('border_std')};
            }}
            QTreeWidget::item:hover {{
                background-color: {c('input_bg')};
            }}
            QTreeWidget::item:selected {{
                background-color: {c('input_bg')};
                color: {c('text_main')};
            }}
            QHeaderView::section {{
                background-color: {c('input_bg')};
                color: {c('text_main')};
                border: none;
                border-right: 1px solid {c('border_std')};
                border-bottom: 1px solid {c('border_std')};
                padding: 6px 8px;
                font-weight: bold;
            }}
        """)

    def refresh_local_tools(self):
        """Refresh the read-only local tool inventory shown in settings."""
        if not hasattr(self, "tools_tree"):
            return

        self.tools_tree.clear()
        try:
            specs = self._load_local_tool_specs()
            groups = build_local_tool_category_groups(specs)
        except Exception as e:
            self.tools_summary_label.setText("Local tools: failed to load")
            self.tools_tree.addTopLevelItem(QTreeWidgetItem(["Error", str(e), "", ""]))
            return

        total = sum(len(items) for items in groups.values())
        self.tools_summary_label.setText(f"Local tools: {total} across {len(groups)} categories")

        if not groups:
            self.tools_tree.addTopLevelItem(QTreeWidgetItem(["No local tools discovered", "", "", ""]))
            return

        for category, specs in groups.items():
            parent = QTreeWidgetItem([f"{category} ({len(specs)})", "", "", ""])
            parent.setFirstColumnSpanned(True)
            self.tools_tree.addTopLevelItem(parent)
            for spec in specs:
                tags = self._format_tool_tags(spec)
                description = self._compact_tool_description(getattr(spec, "description", ""))
                child = QTreeWidgetItem([
                    getattr(spec, "name", ""),
                    description,
                    tags,
                    getattr(spec, "risk_level", "low"),
                ])
                tooltip = spec.to_model_description() if hasattr(spec, "to_model_description") else description
                for col in range(4):
                    child.setToolTip(col, tooltip)
                parent.addChild(child)
            parent.setExpanded(True)

        for col in range(4):
            self.tools_tree.resizeColumnToContents(col)

    def _load_local_tool_specs(self):
        from ...tools.registry import tool_registry

        tools_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tools"))
        tool_registry.discover(tools_dir)
        specs = tool_registry.get_tool_specs()
        return [spec for spec in specs if getattr(spec, "source", "local") == "local"]

    def _format_tool_tags(self, spec):
        tags = list(getattr(spec, "capability_tags", []) or [])
        if not tags:
            tags = list(getattr(spec, "domain_tags", []) or [])
        return ", ".join(tags[:4])

    def _compact_tool_description(self, text, max_len=140):
        text = " ".join(str(text or "").split())
        if len(text) <= max_len:
            return text
        return text[: max_len - 3].rstrip() + "..."

    def _create_skills_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(QLabel("Manage specialized AI capabilities (discovered in .agents/skills/):"))
        
        self.scroll_skills = QScrollArea()
        self.scroll_skills.setWidgetResizable(True)
        self.scroll_skills.setFrameShape(QFrame.NoFrame)
        self.skill_container = QWidget()
        self.skill_list_layout = QVBoxLayout(self.skill_container)
        self.skill_list_layout.setAlignment(Qt.AlignTop)
        self.scroll_skills.setWidget(self.skill_container)
        layout.addWidget(self.scroll_skills)
        
        self.refresh_skills_btn = QPushButton("Scan for New Skills")
        self.refresh_skills_btn.clicked.connect(self.refresh_skills)
        self.create_skill_btn = QPushButton("Create Skill")
        self.create_skill_btn.clicked.connect(self.create_skill)

        manage_btn_layout = QHBoxLayout()
        manage_btn_layout.addWidget(self.refresh_skills_btn)
        manage_btn_layout.addWidget(self.create_skill_btn)
        layout.addLayout(manage_btn_layout)
        
        return widget

    def refresh_skills(self):
        """Dynamic skill card generation with metadata auto-repair and cache clearing."""
        # 强制清除系统提示词缓存，确保扫描结果即时同步到 AI 记忆
        if SystemPrompts:
            SystemPrompts.clear_cache()
            
        while self.skill_list_layout.count():
            item = self.skill_list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
            
        if not SkillService:
            self.skill_list_layout.addWidget(QLabel("SkillService missing."))
            return
            
        project_root = get_project_root()
        ss = SkillService(project_root)
        c = lambda t: app_config.get_theme_color(t)
        
        all_skills = ss.list_skills() # List everything on disk
        for s_name in all_skills:
            meta = ss.get_skill_metadata(s_name)
            is_enabled = s_name not in self.disabled_skills
            
            # --- Skill Card ---
            card = QFrame()
            card.setObjectName("skill_card")
            cl = QVBoxLayout(card)
            cl.setContentsMargins(15, 15, 15, 12)
            cl.setSpacing(8)
            
            # 样式的深度定制
            card.setStyleSheet(f"""
                #skill_card {{ 
                    background-color: {c('dialog_bg')}; 
                    border: 1px solid {c('border_std')}; 
                    border-radius: 12px; 
                    margin-bottom: 5px;
                }}
                #skill_card:hover {{
                    border: 1px solid {c('accent')};
                }}
            """)
            
            # Header Row
            h_layout = QHBoxLayout()
            h_layout.setSpacing(10)
            
            # Skill Title Badge
            t_label = QLabel(meta.get('title', s_name))
            t_label.setStyleSheet(f"""
                font-weight: bold; font-size: 11pt; 
                color: {c('accent')};
                background-color: {c('input_bg')};
                border: 1px solid {c('border_std')};
                border-radius: 4px;
                padding: 4px 12px;
            """)
            h_layout.addWidget(t_label)
            h_layout.addStretch()
            
            sw = QCheckBox("Enabled")
            sw.setChecked(is_enabled)
            sw.setCursor(Qt.PointingHandCursor)
            sw.clicked.connect(lambda checked, name=s_name: self._toggle_skill(name, checked))
            h_layout.addWidget(sw)
            cl.addLayout(h_layout)
            
            # Description Flow
            d_label = QLabel(meta.get('description', 'Specialized AI expertise for geoscience workflows.'))
            d_label.setWordWrap(True)
            d_label.setStyleSheet(f"""
                color: {c('text_main')}; font-size: 9.5pt; 
                line-height: 1.4;
                margin: 5px 2px 10px 2px;
            """)
            cl.addWidget(d_label)

            aliases = ss.get_skill_aliases(s_name)
            alias_text = ", ".join(aliases) if aliases else "-"
            meta_label = QLabel(f"ID: {s_name} | Aliases: {alias_text}")
            meta_label.setWordWrap(True)
            meta_label.setStyleSheet(f"color: {c('text_dim')}; font-size: 8.5pt; margin: 0 2px 8px 2px;")
            cl.addWidget(meta_label)
            
            # Footer Action Bar
            f_layout = QHBoxLayout()
            f_layout.setContentsMargins(0, 5, 0, 0)
            f_layout.addStretch()
            
            edit_btn = QPushButton("Edit Instruction")
            edit_btn.setCursor(Qt.PointingHandCursor)
            edit_btn.setStyleSheet(f"color: {c('accent')}; border: none; font-size: 9pt; font-weight: 500; margin-right: 12px;")
            edit_btn.clicked.connect(lambda _, name=s_name: self._edit_skill_instruction(name))
            f_layout.addWidget(edit_btn)
            
            del_btn = QPushButton("Delete Skill")
            del_btn.setCursor(Qt.PointingHandCursor)
            del_btn.setStyleSheet(f"color: {c('danger')}; border: none; font-size: 9pt;")
            del_btn.clicked.connect(lambda _, name=s_name: self._delete_skill(name))
            f_layout.addWidget(del_btn)
            
            cl.addLayout(f_layout)
            self.skill_list_layout.addWidget(card)

        if not all_skills:
            self.skill_list_layout.addWidget(QLabel("No skills discovered in the project."))

    def create_skill(self):
        """Create a new empty skill by id path."""
        if not SkillService:
            QMessageBox.critical(self, "Error", "SkillService missing.")
            return

        skill_id, ok = QInputDialog.getText(
            self,
            "Create Skill",
            "Skill ID (e.g., custom/my-skill):"
        )
        if not ok:
            return

        skill_id = (skill_id or "").strip()
        if not skill_id:
            return

        project_root = get_project_root()
        ss = SkillService(project_root)
        success, message = ss.create_skill(skill_id)
        if not success:
            QMessageBox.warning(self, "Create Skill", f"Failed: {message}")
            return

        self.refresh_skills()
        if SystemPrompts:
            SystemPrompts.clear_cache()

    def _edit_skill_instruction(self, name):
        """Open the skill editor dialog."""
        if SkillEditorDialog is None:
            QMessageBox.critical(self, "Error", "SkillEditorDialog component not found. Please check plugin file structure.")
            return
            
        project_root = get_project_root()
        ss = SkillService(project_root)
        
        # 1. Fetch current data
        meta = ss.get_skill_metadata(name)
        instruction = ss.get_skill_content(name, include_frontmatter=False)
        
        # 2. Show Editor
        dlg = SkillEditorDialog(name, meta.get('title', name), meta.get('description', ''), instruction, self)
        if dlg.exec():
            # 3. Save Changes
            data = dlg.get_data()
            if ss.update_skill_content(name, data['title'], data['description'], data['instruction']):
                self.refresh_skills()
                # Clear system prompt cache as metadata/content changed
                if SystemPrompts:
                    SystemPrompts.clear_cache()
            else:
                QMessageBox.critical(self, "Error", "Failed to save skill changes to disk.")

    def _toggle_skill(self, name, enabled):
        """Update disabled list in memory."""
        if enabled:
            if name in self.disabled_skills:
                self.disabled_skills.remove(name)
        else:
            if name not in self.disabled_skills:
                self.disabled_skills.append(name)

    def _delete_skill(self, name):
        """Handle destructive deletion with confirmation."""
        reply = QMessageBox.warning(
            self, 
            "Delete Expert Skill", 
            f"Are you sure you want to permanently delete the '{name}' skill?\n\nThis will physically remove the directory and its documentation.",
            QMessageBox.Yes | QMessageBox.No, 
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            project_root = get_project_root()
            ss = SkillService(project_root)
            if ss.delete_skill(name):
                # Also remove from disabled list if it was there
                if name in self.disabled_skills:
                    self.disabled_skills.remove(name)
                self.refresh_skills()
            else:
                QMessageBox.critical(self, "Error", f"Failed to delete skill directory for '{name}'.")

    def load_settings(self):
        """Restore all settings, including the disabled skills list."""
        # 1. Connection Profiles
        self._profiles = self.config.get_profiles()
        current_name = self.config.get_current_profile_name()
        
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self._profiles:
            self.profile_combo.addItem(p.get("name", "Unnamed"))
        
        idx = -1
        for i, p in enumerate(self._profiles):
            if p.get("name") == current_name:
                idx = i
                break
        
        if idx == -1 and self._profiles:
            idx = 0
            
        self.profile_combo.setCurrentIndex(idx)
        self._current_profile_index = idx
        self.profile_combo.blockSignals(False)
        self._update_form_from_profile()
        
        # 2. Behavior
        self.max_rounds_spin.setValue(self.config.get_max_rounds())
        self.auto_load_checkbox.setChecked(app_config.get_ai_auto_load())
        self.max_history_spin.setValue(self.config.get_max_history())
        self.mcp_enabled_checkbox.setChecked(self.config.get_mcp_enabled())
        
        # 3. Disabled Skills
        self_disabled = self.settings.value("disabled_skills", [])
        if isinstance(self_disabled, str): # Handle JSON string serialization
            try: self.disabled_skills = json.loads(self_disabled)
            except: self.disabled_skills = []
        else:
            self.disabled_skills = self_disabled
        if not isinstance(self.disabled_skills, list):
            self.disabled_skills = []
            
        # Path Whitelist
        whitelist = self.config.get_whitelist()
        self.whitelist_edit.clear()
        for item in whitelist:
            self.whitelist_edit.addItem(item)
        
        # MCP
        self.mcp_servers = {}
        try:
            self.mcp_servers = self.config.get_mcp_servers()
            for name in self.mcp_servers:
                self.mcp_list.addItem(name)
        except: pass
        
        # Populate local tools UI
        self.refresh_local_tools()

        # Populate skills UI
        self.refresh_skills()

    def apply_settings(self):
        self.save_settings(close_after=False)

    def save_settings(self, close_after=True):
        """Save all settings, including the disabled skills list."""
        # 1. Connection (Save current form to active profile)
        self._update_profile_from_form()
        self.config.set_profiles(self._profiles)
        if 0 <= self._current_profile_index < len(self._profiles):
            self.config.set_current_profile_name(self._profiles[self._current_profile_index]["name"])
        
        # 2. Behavior
        self.config.set_max_rounds(self.max_rounds_spin.value())
        self.config.set_max_history(self.max_history_spin.value())
        app_config.set_ai_auto_load(self.auto_load_checkbox.isChecked())
        self.config.set_mcp_enabled(self.mcp_enabled_checkbox.isChecked())
        
        # Persist disabled skills as JSON string for cross-module reliability
        self.settings.setValue("disabled_skills", json.dumps(self.disabled_skills))
        
        # Clear AI prompt cache to reflect changes immediately
        if SystemPrompts:
            SystemPrompts.clear_cache()
            
        whitelist = [self.whitelist_edit.item(i).text() for i in range(self.whitelist_edit.count())]
        self.config.set_whitelist(whitelist)
        self.config.set_mcp_servers(self.mcp_servers)
        
        if close_after:
            self.accept()



    def on_profile_index_changed(self, index):
        """Switch current profile."""
        if index < 0 or index >= len(self._profiles):
            return
            
        # Save current form work before switching
        if 0 <= self._current_profile_index < len(self._profiles):
            self._update_profile_from_form()
            
        self._current_profile_index = index
        self._update_form_from_profile()

    def _update_form_from_profile(self):
        """Update line edits from memory data."""
        if 0 <= self._current_profile_index < len(self._profiles):
            p = self._profiles[self._current_profile_index]
            self.api_key_edit.setText(p.get("api_key", ""))
            self.base_url_edit.setText(p.get("base_url", ""))
            self.model_edit.setText(p.get("model", ""))
            


    def _update_profile_from_form(self):
        """Sync UI edits back to memory list."""
        if 0 <= self._current_profile_index < len(self._profiles):
            p = self._profiles[self._current_profile_index]
            p["api_key"] = self.api_key_edit.text().strip()
            p["base_url"] = self.base_url_edit.text().strip()
            p["model"] = self.model_edit.text().strip()
            p["provider"] = "Custom / Other"

    def add_new_profile(self):
        name, ok = QInputDialog.getText(self, "New Profile", "Profile Name:")
        if not ok or not name: return
        
        new_prof = {
            "name": name,
            "provider": "Custom / Other",
            "api_key": "",
            "base_url": "",
            "model": ""
        }
        self._profiles.append(new_prof)
        self.profile_combo.addItem(name)
        self.profile_combo.setCurrentIndex(len(self._profiles) - 1)

    def rename_current_profile(self):
        if self._current_profile_index < 0: return
        old_name = self._profiles[self._current_profile_index]["name"]
        new_name, ok = QInputDialog.getText(self, "Rename Profile", "New Name:", QLineEdit.Normal, old_name)
        if not ok or not new_name: return
        
        self._profiles[self._current_profile_index]["name"] = new_name
        self.profile_combo.setItemText(self._current_profile_index, new_name)

    def delete_current_profile(self):
        if len(self._profiles) <= 1:
            QMessageBox.warning(self, "Delete Profile", "Cannot delete the last profile.")
            return

        reply = QMessageBox.question(self, "Delete Profile", 
                                   f"Are you sure you want to delete profile '{self._profiles[self._current_profile_index]['name']}'?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self._profiles.pop(self._current_profile_index)
            self.profile_combo.removeItem(self._current_profile_index)
            # currentIndexChanged will trigger automatic update

    @qasync.asyncSlot()
    async def fetch_available_models(self):
        """异步获取当前服务商支持的模型列表"""
        if not AsyncAIWorker:
            QMessageBox.critical(self, "Error", "AsyncAIWorker missing.")
            return
            
        api_key = self.api_key_edit.text().strip()
        base_url = self.base_url_edit.text().strip()
        
        if not api_key or not base_url:
            QMessageBox.warning(self, "Fetch Models", "Please provide API Key and Base URL first.")
            return
            
        self.fetch_models_btn.setEnabled(False)
        self.fetch_models_btn.setText("Fetching...")
        
        try:
            models = await AsyncAIWorker.list_models(api_key, base_url)
            if not models:
                QMessageBox.information(self, "Fetch Models", "Connected but no models discovered.")
                return
            
            # 创建浮动菜单供选择
            from PySide6.QtWidgets import QMenu
            menu = QMenu(self)
            # 限制菜单高度或只显示部分
            actual_models = models[:50] # 避免菜单过长
            for m in actual_models:
                action = menu.addAction(m)
                action.triggered.connect(lambda checked, name=m: self.model_edit.setText(name))
            
            if len(models) > 50:
                menu.addSeparator()
                menu.addAction(f"... and {len(models)-50} more")

            # 在按钮下方执行菜单
            menu.exec(self.fetch_models_btn.mapToGlobal(self.fetch_models_btn.rect().bottomLeft()))
            
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", f"Failed to fetch models:\n{str(e)}")
        finally:
            self.fetch_models_btn.setEnabled(True)
            self.fetch_models_btn.setText("Auto Fetch")

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if folder: self.whitelist_edit.addItem(folder)

    def add_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", "All Files (*.*)")
        if file_path: self.whitelist_edit.addItem(file_path)

    def remove_selected(self):
        curr = self.whitelist_edit.currentRow()
        if curr >= 0: self.whitelist_edit.takeItem(curr)

    def add_mcp_server(self):
        name, ok1 = QInputDialog.getText(self, "Add Local MCP", "Local server name:")
        if not ok1 or not name:
            return
        conf = self._prompt_mcp_server_config(name)
        if not conf:
            return
        self.mcp_servers[name] = conf
        self.mcp_list.addItem(name)

    def edit_mcp_server(self, item):
        name = item.text()
        conf = self.mcp_servers.get(name, {})
        updated = self._prompt_mcp_server_config(name, conf)
        if updated:
            self.mcp_servers[name] = updated

    def remove_mcp_server(self):
        curr = self.mcp_list.currentRow()
        if curr >= 0:
            item = self.mcp_list.takeItem(curr)
            if item.text() in self.mcp_servers: del self.mcp_servers[item.text()]

    @qasync.asyncSlot()
    async def test_selected_mcp_server(self):
        item = self.mcp_list.currentItem()
        if not item:
            QMessageBox.information(self, "Local MCP Test", "Please select a local MCP server first.")
            return

        if test_mcp_server_connection is None:
            QMessageBox.critical(self, "Local MCP Test", "MCP integration module is unavailable.")
            return

        name = item.text()
        conf = self.mcp_servers.get(name)
        if not conf:
            QMessageBox.warning(self, "Local MCP Test", f"No configuration found for local server '{name}'.")
            return

        try:
            tool_names = await test_mcp_server_connection(name, conf)
            details = "\n".join(tool_names[:20]) if tool_names else "(No tools reported)"
            if len(tool_names) > 20:
                details += f"\n... and {len(tool_names) - 20} more"
            args_preview = " ".join(conf.get("args", [])) if conf.get("args") else "(none)"
            QMessageBox.information(
                self,
                "Local MCP Test",
                f"Connected to local server '{name}' successfully.\n\n"
                f"Command: {conf.get('command', '')}\n"
                f"Args: {args_preview}\n\n"
                f"Discovered {len(tool_names)} tool(s):\n{details}"
            )
        except Exception as e:
            args_preview = " ".join(conf.get("args", [])) if conf.get("args") else "(none)"
            QMessageBox.critical(
                self,
                "Local MCP Test Failed",
                f"Failed to connect to local server '{name}'.\n\n"
                f"Command: {conf.get('command', '')}\n"
                f"Args: {args_preview}\n\n"
                f"{e}"
            )

    def _prompt_mcp_server_config(self, name, conf=None):
        conf = conf or {}
        dialog = LocalMCPServerDialog(name, conf, self)
        if dialog.exec() != QDialog.Accepted:
            return None

        values = dialog.get_values()
        cmd = values["command"]
        if not cmd:
            return None

        args_text = values["args_text"]

        try:
            args = self._parse_mcp_args(args_text)
        except ValueError as e:
            QMessageBox.warning(self, "Invalid Local MCP Arguments", str(e))
            return None

        return {"command": cmd.strip(), "args": args}

    def _parse_mcp_args(self, args_text):
        if parse_mcp_args_input is None:
            return []
        return parse_mcp_args_input(args_text)
