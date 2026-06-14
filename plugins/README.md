# ALIVE 插件系统

## 概述

ALIVE 插件系统允许将AI助手和脚本编辑器等功能作为独立插件加载，实现主程序与扩展功能的分离。

## 架构特点

### 1. 延迟加载
- 主程序启动时只加载核心功能
- AI助手和脚本编辑器按需加载
- 减少启动时间和内存占用

### 2. 热插拔支持
- 插件可以在运行时加载和卸载
- 支持动态启用/禁用插件
- 不影响主程序稳定性

### 3. 标准接口
- 所有插件实现统一的 `PluginInterface` 接口
- 通过插件管理器统一管理
- 便于开发和维护

## 目录结构

```
plugins/
├── __init__.py              # 插件包初始化
├── ai_assistant/            # AI助手插件
│   ├── __init__.py
│   ├── plugin.py            # 插件入口
│   ├── services/            # 服务层
│   ├── ui/                  # 界面组件
│   │   ├── main_window.py
│   │   └── widgets/
│   │       └── web_script_editor.py
│   ├── core/                # 核心功能
│   └── tools/               # 工具函数
└── README.md                # 本文档
```

## 使用方法

### 对于用户

1. **启动主程序**：只加载核心功能，启动速度快
2. **使用插件菜单**：
   - `Plugins` → `AI助手` (Ctrl+Shift+A)
   - `Plugins` → `脚本编辑器` (Ctrl+N)
3. **首次使用**：点击菜单后自动加载对应插件

### 对于开发者

#### 创建新插件

1. 在 `plugins/` 目录下创建新文件夹
2. 创建 `plugin.py` 文件，实现 `PluginInterface`：

```python
from core.plugin_interface import PluginInterface

class Plugin(PluginInterface):
    name = "My Plugin"
    version = "1.0.0"
    description = "插件描述"
    author = "作者名"
    
    def initialize(self) -> bool:
        # 初始化插件
        return True
    
    def shutdown(self) -> bool:
        # 关闭插件
        return True
    
    def get_menu_actions(self):
        # 返回菜单动作列表
        return []
```

3. 在 `__init__.py` 中导出插件类：

```python
from .plugin import Plugin
__all__ = ['Plugin']
```

#### 插件接口方法

- `initialize()`: 初始化插件，返回是否成功
- `shutdown()`: 关闭插件，返回是否成功
- `get_dock_widget()`: 获取停靠窗口（可选）
- `get_menu_actions()`: 获取菜单动作列表
- `get_toolbar_actions()`: 获取工具栏动作列表
- `on_main_window_ready()`: 主窗口就绪回调
- `on_database_loaded(db_path)`: 数据库加载回调
- `on_selection_changed(items)`: 选择项变化回调

## 主程序集成

### 在主程序中使用插件

```python
# 初始化插件管理器（延迟）
self.init_plugin_manager()

# 加载特定插件
plugin = self.load_ai_assistant_plugin()

# 使用插件功能
if plugin:
    plugin.show_ai_assistant()
```

### 插件配置

插件的配置文件可以存放在插件目录下的 `config/` 文件夹中，格式可以是 JSON 或 YAML。

## 现有插件

### AI助手插件
- **功能**：智能对话、任务执行、代码生成
- **入口**：`plugins/ai_assistant/plugin.py`
- **依赖**：需要配置API密钥

### 脚本编辑器插件
- **功能**：Python脚本编写和执行
- **入口**：`plugins/ai_assistant/plugin.py` (ScriptEditorPlugin类)
- **依赖**：无特殊依赖

## 故障排除

### 插件无法加载
1. 检查插件目录结构是否正确
2. 确认 `plugin.py` 中定义了 `Plugin` 类
3. 查看控制台错误信息

### 插件功能异常
1. 检查插件是否正确初始化
2. 确认主程序版本与插件兼容
3. 查看插件日志（如果有）

## 扩展计划

- [ ] 插件配置管理界面
- [ ] 插件市场/仓库
- [ ] 插件版本管理
- [ ] 插件依赖管理
- [ ] 插件权限控制

## 贡献指南

欢迎贡献新的插件！请遵循以下规范：

1. 插件名称使用英文，描述清晰
2. 实现完整的 `PluginInterface` 接口
3. 提供详细的文档和示例
4. 遵循代码风格和命名规范
5. 添加适当的错误处理和日志
