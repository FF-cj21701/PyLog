import json
from PySide6.QtCore import QSettings

from .mcp_integration import normalize_mcp_servers

class AIConfig:
    def __init__(self):
        self.settings = QSettings("PyLog", "AIAssistant")
        self._migrate_legacy_settings()

    def _migrate_legacy_settings(self):
        """Migrate legacy settings to the new profile format if needed."""
        profiles = self.get_profiles()
        if not profiles:
            api_key = self.settings.value("api_key", "")
            if api_key:
                base_url = self.settings.value("base_url", "")
                model = self.settings.value("model", "")
                
                default_profile = {
                    "name": "Default",
                    "provider": "Custom / Other",
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model
                }
                self.set_profiles([default_profile])
                self.set_current_profile_name("Default")

    def get_profiles(self):
        """Get all connection profiles."""
        profiles_str = self.settings.value("profiles", "[]")
        try:
            return json.loads(profiles_str)
        except:
            return []

    def set_profiles(self, profiles):
        """Save connection profiles."""
        self.settings.setValue("profiles", json.dumps(profiles))

    def get_current_profile_name(self):
        """Get the name of the active profile."""
        return self.settings.value("current_profile", "Default")

    def set_current_profile_name(self, name):
        """Set the active profile name."""
        self.settings.setValue("current_profile", name)

    def get_current_profile(self):
        """Get the configuration dictionary for the current profile."""
        name = self.get_current_profile_name()
        profiles = self.get_profiles()
        for p in profiles:
            if p.get("name") == name:
                return p
        if profiles:
            return profiles[0]
        return {}

    def get_api_key(self):
        return self.get_current_profile().get("api_key", "")

    def get_base_url(self):
        return self.get_current_profile().get("base_url", "")

    def get_model(self):
        return self.get_current_profile().get("model", "")

    def set_api_key(self, value):
        # Update current profile
        profiles = self.get_profiles()
        name = self.get_current_profile_name()
        for p in profiles:
            if p.get("name") == name:
                p["api_key"] = value
                break
        self.set_profiles(profiles)

    def set_base_url(self, value):
        profiles = self.get_profiles()
        name = self.get_current_profile_name()
        for p in profiles:
            if p.get("name") == name:
                p["base_url"] = value
                break
        self.set_profiles(profiles)

    def set_model(self, value):
        profiles = self.get_profiles()
        name = self.get_current_profile_name()
        for p in profiles:
            if p.get("name") == name:
                p["model"] = value
                break
        self.set_profiles(profiles)

    def is_configured(self):
        return bool(self.get_api_key())


    def get_max_rounds(self):
        return int(self.settings.value("max_rounds", 5))

    def set_max_rounds(self, value):
        self.settings.setValue("max_rounds", value)

    def get_max_history(self):
        """获取最大历史记录数量"""
        return int(self.settings.value("max_history", 10))

    def set_max_history(self, value):
        """设置最大历史记录数量"""
        self.settings.setValue("max_history", value)

    def get_whitelist(self):
        """获取路径白名单列表（文件和文件夹）"""
        import json
        import os
        import sys
        
        # 1. 优先尝试新键名 'path_whitelist'
        whitelist_str = self.settings.value("path_whitelist", "")
        
        # 2. 回退到旧键名 'folder_whitelist' 以兼容旧数据
        if not whitelist_str:
            whitelist_str = self.settings.value("folder_whitelist", "")
            
        # 3. 动态获取默认白名单
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

        default_whitelist = [
            os.path.join(base_dir, "data"),
            os.path.join(base_dir, "docs"),
            os.path.join(base_dir, "scripts_user")
        ]
        
        if not whitelist_str:
            return default_whitelist
        try:
            return json.loads(whitelist_str)
        except:
            return default_whitelist

    def set_whitelist(self, whitelist):
        """设置路径白名单列表"""
        import json
        import os
        self.settings.setValue("path_whitelist", json.dumps(whitelist))
        # 清除旧键名以完成迁移
        self.settings.remove("folder_whitelist")
        
        # 同步更新当前环境变量，确保实时生效无需重启
        os.environ['PYLOG_TOOL_WHITELIST'] = ';'.join(whitelist)

    def get_mcp_enabled(self):
        """Whether optional local MCP tools are enabled."""
        return str(self.settings.value("mcp_enabled", "false")).lower() in ("1", "true", "yes", "on")

    def set_mcp_enabled(self, enabled):
        """Enable or disable optional local MCP tools."""
        self.settings.setValue("mcp_enabled", bool(enabled))

    def get_mcp_servers(self):
        """获取 MCP 服务器配置字典"""
        servers_str = self.settings.value("mcp_servers", "{}")
        try:
            return normalize_mcp_servers(json.loads(servers_str))
        except:
            return {}

    def set_mcp_servers(self, servers):
        """设置 MCP 服务器配置字典"""
        self.settings.setValue("mcp_servers", json.dumps(normalize_mcp_servers(servers)))
