import os
from PySide6.QtCore import QSettings

class PathResolver:
    """
    Centralized path discovery and resolution for AI Assistant.
    Follows priority: Explicit -> Settings -> Auto-Discovery (.agents marker).
    """
    
    _cached_root = None
    
    @staticmethod
    def get_project_root(start_path=None):
        """
        Determine project root with priority:
        1. Explicit start_path (if it contains .agents)
        2. Settings: AIAssistant/root_path
        3. Discovery: Upward search (10 levels) for .agents directory marker
        """
        # Return cached if available and no override requested
        if PathResolver._cached_root and not start_path:
            return PathResolver._cached_root
            
        # 1. Check Settings first
        settings = QSettings("PyLog", "AIAssistant")
        config_path = settings.value("root_path", "")
        if config_path and os.path.exists(os.path.join(config_path, ".agents")):
            PathResolver._cached_root = os.path.abspath(config_path)
            return PathResolver._cached_root

        # 2. Discovery logic
        # Start from provided path or current file location
        curr = os.path.abspath(start_path) if start_path else os.path.abspath(__file__)
        
        # If we are starting from inside the plugin (like this file), go up first
        if curr.endswith(".py"):
            curr = os.path.dirname(curr)
            
        for _ in range(10):
            if os.path.exists(os.path.join(curr, ".agents")):
                PathResolver._cached_root = curr
                return curr
            parent = os.path.dirname(curr)
            if parent == curr: 
                break
            curr = parent
            
        # 3. Fallback to CWD
        fallback = os.getcwd()
        return fallback

    @staticmethod
    def get_skills_dir(root=None):
        """Get the absolute path to the specialized skills directory."""
        root = root or PathResolver.get_project_root()
        return os.path.join(root, ".agents", "skills")

    @staticmethod
    def get_scripts_user_dir(root=None):
        """Get the absolute path to the user-generated scripts directory."""
        root = root or PathResolver.get_project_root()
        return os.path.join(root, "scripts_user")

    @staticmethod
    def clear_cache():
        """Force a re-discovery on next call."""
        PathResolver._cached_root = None
