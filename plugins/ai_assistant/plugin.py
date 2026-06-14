"""
AI助手插件
提供智能AI助手功能，支持自然语言交互和任务执行
"""

import sys
import os
import importlib

# 获取插件目录路径
plugin_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(plugin_dir))

# 添加项目根目录到路径
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 添加插件目录到路径，使内部导入可以工作
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)

from PySide6.QtWidgets import QDockWidget, QWidget, QMdiSubWindow
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence

# 导入核心插件接口
from core.plugin_interface import PluginInterface

# 导入AI助手组件 - 使用直接从插件目录导入
try:
    from plugins.ai_assistant.ui.main_window import AIAssistantWidget
    from plugins.ai_assistant.ui.widgets.web_script_editor import WebScriptEditor
except ImportError:
    AIAssistantWidget = importlib.import_module("ui.main_window").AIAssistantWidget
    WebScriptEditor = importlib.import_module("ui.widgets.web_script_editor").WebScriptEditor


class Plugin(PluginInterface):
    """AI助手插件主类"""
    
    name = "AI Assistant"
    version = "1.0.0"
    description = "Intelligent Log Analysis Assistant"
    author = "PyLog Team"
    
    def __init__(self, main_window=None):
        super().__init__(main_window)
        self.ai_widget = None
        self.ai_dock = None
        self._actions = []
        
    def initialize(self) -> bool:
        """初始化AI助手插件"""
        try:
            if not self.main_window:
                return False
                
            # 创建AI助手停靠窗口
            self.ai_dock = QDockWidget("AI Assistant", self.main_window)
            self.ai_dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
            self.ai_dock.setTitleBarWidget(QWidget())
            self.ai_dock.setMinimumWidth(200)  # 设置最小宽度
            
            # 创建AI助手组件
            self.ai_widget = AIAssistantWidget(self.main_window)
            self.ai_dock.setWidget(self.ai_widget)

            # Apply current theme immediately
            from core.app_config import app_config
            theme = app_config.get_theme_name().lower()
            self.ai_widget.set_theme(theme)
            
            # 默认隐藏
            self.ai_dock.hide()
            self.main_window.addDockWidget(Qt.RightDockWidgetArea, self.ai_dock)
            
            # 设置初始默认宽度
            self.main_window.resizeDocks([self.ai_dock], [350], Qt.Horizontal)
            
            # 连接主窗口信号
            if hasattr(self.main_window, 'explorer_selection_changed'):
                self.main_window.explorer_selection_changed.connect(
                    self.on_selection_changed
                )
            
            # [NEW] Also listen for plot selections
            if hasattr(self.main_window, 'plot_selection_changed'):
                self.main_window.plot_selection_changed.connect(
                    self.on_selection_changed
                )
            
            self._is_loaded = True
            return True
            
        except Exception as e:
            print(f"AI Assistant plugin initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def shutdown(self) -> bool:
        """关闭AI助手插件"""
        try:
            if self.ai_dock:
                self.ai_dock.close()
                self.ai_dock = None
            self.ai_widget = None
            self._is_loaded = False
            return True
        except Exception as e:
            print(f"AI Assistant plugin shutdown failed: {e}")
            return False
    
    def get_dock_widget(self):
        """获取停靠窗口"""
        return self.ai_dock
    
    def toggle_ai_assistant(self):
        """切换AI助手显示/隐藏"""
        if self.ai_dock:
            if self.ai_dock.isVisible():
                self.ai_dock.hide()
            else:
                self.ai_dock.show()
                self.ai_dock.raise_()
    
    def on_selection_changed(self, selected_items):
        """选择项改变时的回调"""
        if self.ai_widget and self._is_enabled:
            try:
                self.ai_widget.set_selection_context(selected_items)
            except Exception:
                pass
    
    def show_ai_assistant(self):
        """显示AI助手"""
        if self.ai_dock:
            self.ai_dock.show()
            self.ai_dock.raise_()
    
    def hide_ai_assistant(self):
        """隐藏AI助手"""
        if self.ai_dock:
            self.ai_dock.hide()


# 脚本编辑器相关功能
class ScriptEditorPlugin(PluginInterface):
    """脚本编辑器插件"""
    
    name = "Script Editor"
    version = "1.0.0"
    description = "Python脚本编辑器，支持代码编写和执行"
    author = "PyLog Team"
    
    def __init__(self, main_window=None):
        super().__init__(main_window)
        self._editors = []
        
    def initialize(self) -> bool:
        """初始化脚本编辑器插件"""
        self._is_loaded = True
        return True
    
    def shutdown(self) -> bool:
        """关闭脚本编辑器插件"""
        # 关闭所有打开的编辑器
        for editor in self._editors:
            try:
                editor.close()
            except:
                pass
        self._editors.clear()
        self._is_loaded = False
        return True
    
    def create_script_editor(self, db_or_path=None):
        """创建新的脚本编辑器实例"""
        if not self.main_window:
            return None
            
        editor = WebScriptEditor(db_or_path)
        
        # Apply current theme immediately
        from core.app_config import app_config
        theme = app_config.get_theme_name().lower()
        editor.set_theme(theme)
        
        self._editors.append(editor)
        return editor
