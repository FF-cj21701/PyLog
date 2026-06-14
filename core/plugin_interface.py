"""
插件接口定义模块
定义所有插件必须实现的接口规范
"""

import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from PySide6.QtWidgets import QWidget, QDockWidget
from PySide6.QtGui import QAction
from PySide6.QtCore import QObject, Signal


class PluginInterface(ABC):
    """所有插件必须实现的基类接口"""
    
    # 插件元数据
    name: str = ""
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    
    # 插件类型
    PLUGIN_TYPE_DOCK = "dock"           # 停靠窗口插件
    PLUGIN_TYPE_ACTION = "action"       # 菜单动作插件
    PLUGIN_TYPE_WIDGET = "widget"       # 独立窗口插件
    
    def __init__(self, main_window=None):
        self.main_window = main_window
        self._is_loaded = False
        self._is_enabled = False
        
    @abstractmethod
    def initialize(self) -> bool:
        """
        初始化插件
        返回: 是否初始化成功
        """
        pass
    
    @abstractmethod
    def shutdown(self) -> bool:
        """
        关闭插件
        返回: 是否关闭成功
        """
        pass
    
    def get_dock_widget(self) -> Optional[QDockWidget]:
        """
        获取停靠窗口（如果是停靠窗口类型）
        返回: QDockWidget实例或None
        """
        return None
    
    def get_menu_actions(self) -> List[QAction]:
        """
        获取菜单动作列表
        返回: QAction列表
        """
        return []
    
    def get_toolbar_actions(self) -> List[QAction]:
        """
        获取工具栏动作列表
        返回: QAction列表
        """
        return []
    
    def on_main_window_ready(self):
        """
        主窗口完全加载后的回调
        可以在这里进行需要主窗口的初始化
        """
        pass
    
    def on_database_loaded(self, db_path: str):
        """
        数据库加载后的回调
        """
        pass
    
    def on_selection_changed(self, selected_items: List[Dict]):
        """
        选择项改变时的回调
        """
        pass
    
    @property
    def is_loaded(self) -> bool:
        return self._is_loaded
    
    @property
    def is_enabled(self) -> bool:
        return self._is_enabled
    
    def enable(self):
        """启用插件"""
        self._is_enabled = True
        
    def disable(self):
        """禁用插件"""
        self._is_enabled = False


class PluginManager(QObject):
    """插件管理器 - 负责插件的加载、卸载和管理"""
    
    # 信号
    plugin_loaded = Signal(str)      # 插件名称
    plugin_unloaded = Signal(str)    # 插件名称
    plugin_enabled = Signal(str)     # 插件名称
    plugin_disabled = Signal(str)    # 插件名称
    
    def __init__(self, main_window=None):
        super().__init__()
        self.main_window = main_window
        self._plugins: Dict[str, PluginInterface] = {}
        self._plugin_paths: List[str] = []
        
    def register_plugin_path(self, path: str):
        """注册插件搜索路径"""
        if path not in self._plugin_paths:
            self._plugin_paths.append(path)
            
    def discover_plugins(self) -> List[str]:
        """
        发现所有可用的插件
        返回: 插件名称列表
        """
        import os
        plugins = []
        for path in self._plugin_paths:
            if not os.path.exists(path):
                continue
            for item in os.listdir(path):
                item_path = os.path.join(path, item)
                if os.path.isdir(item_path):
                    # 检查是否是有效插件目录
                    if os.path.exists(os.path.join(item_path, "plugin.py")) or \
                       os.path.exists(os.path.join(item_path, "__init__.py")):
                        plugins.append(item)
        return plugins
    
    def load_plugin(self, plugin_name: str) -> bool:
        """
        加载指定插件
        """
        if plugin_name in self._plugins:
            return True
            
        try:
            # 动态导入插件模块
            import importlib.util
            import sys
            
            for path in self._plugin_paths:
                plugin_path = os.path.join(path, plugin_name)
                if not os.path.exists(plugin_path):
                    continue
                    
                # 查找插件入口
                entry_file = os.path.join(plugin_path, "plugin.py")
                if not os.path.exists(entry_file):
                    entry_file = os.path.join(plugin_path, "__init__.py")
                    
                if os.path.exists(entry_file):
                    spec = importlib.util.spec_from_file_location(
                        f"plugins.{plugin_name}",
                        entry_file,
                        submodule_search_locations=[plugin_path],
                    )
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[f"plugins.{plugin_name}"] = module
                    spec.loader.exec_module(module)
                    
                    # 获取插件类
                    if hasattr(module, 'Plugin'):
                        plugin_class = module.Plugin
                        plugin_instance = plugin_class(self.main_window)
                        
                        if plugin_instance.initialize():
                            self._plugins[plugin_name] = plugin_instance
                            self.plugin_loaded.emit(plugin_name)
                            return True
                            
        except Exception as e:
            print(f"Failed to load plugin {plugin_name}: {e}")
            
        return False
    
    def unload_plugin(self, plugin_name: str) -> bool:
        """
        卸载指定插件
        """
        if plugin_name not in self._plugins:
            return False
            
        try:
            plugin = self._plugins[plugin_name]
            if plugin.shutdown():
                del self._plugins[plugin_name]
                self.plugin_unloaded.emit(plugin_name)
                return True
        except Exception as e:
            print(f"Failed to unload plugin {plugin_name}: {e}")
            
        return False
    
    def get_plugin(self, plugin_name: str) -> Optional[PluginInterface]:
        """获取已加载的插件实例"""
        return self._plugins.get(plugin_name)
    
    def get_loaded_plugins(self) -> List[str]:
        """获取所有已加载的插件名称"""
        return list(self._plugins.keys())
    
    def enable_plugin(self, plugin_name: str):
        """启用插件"""
        plugin = self._plugins.get(plugin_name)
        if plugin:
            plugin.enable()
            self.plugin_enabled.emit(plugin_name)
            
    def disable_plugin(self, plugin_name: str):
        """禁用插件"""
        plugin = self._plugins.get(plugin_name)
        if plugin:
            plugin.disable()
            self.plugin_disabled.emit(plugin_name)
