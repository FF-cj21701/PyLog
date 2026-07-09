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
    def get_ai_workspace_scope():
        """Return the configured AI workspace scope."""
        settings = QSettings("PyLog", "AIAssistant")
        scope = str(settings.value("workspace_scope", "project") or "project").strip().lower()
        if scope in {"scripts", "scripts_user", "user_scripts"}:
            return "scripts_user"
        return "project"

    @staticmethod
    def is_scripts_user_workspace():
        return PathResolver.get_ai_workspace_scope() == "scripts_user"

    @staticmethod
    def resolve_workspace_write_path(filepath, allow_bare_scripts_user=True):
        """Resolve write targets according to the configured AI workspace scope."""
        raw = str(filepath or "").strip()
        if not raw:
            return {
                "ok": False,
                "blocked": True,
                "error": "filepath is required",
                "workspace_scope": PathResolver.get_ai_workspace_scope(),
            }

        root = os.path.abspath(PathResolver.get_project_root())
        scope = PathResolver.get_ai_workspace_scope()
        if scope != "scripts_user":
            resolved = raw if os.path.isabs(raw) else os.path.join(root, raw)
            return {
                "ok": True,
                "filepath": os.path.abspath(resolved),
                "workspace_scope": "project",
            }

        scripts_dir = os.path.abspath(PathResolver.get_scripts_user_dir(root))
        normalized_raw = raw.replace("\\", os.sep).replace("/", os.sep)
        if os.path.isabs(normalized_raw):
            resolved = os.path.abspath(normalized_raw)
            normalized_rel = ""
        else:
            normalized_rel = os.path.normpath(normalized_raw)
            if normalized_rel in {"", "."} or normalized_rel.startswith(".." + os.sep) or normalized_rel == "..":
                return PathResolver._workspace_write_blocked(raw, scripts_dir)

            parts = normalized_rel.split(os.sep)
            if parts and parts[0].lower() == "scripts_user":
                resolved = os.path.abspath(os.path.join(root, normalized_rel))
            elif allow_bare_scripts_user and len(parts) == 1:
                resolved = os.path.abspath(os.path.join(scripts_dir, parts[0]))
            else:
                return PathResolver._workspace_write_blocked(raw, scripts_dir)

        try:
            if os.path.commonpath([resolved, scripts_dir]) != scripts_dir:
                return PathResolver._workspace_write_blocked(raw, scripts_dir)
        except (ValueError, Exception):
            return PathResolver._workspace_write_blocked(raw, scripts_dir)

        return {
            "ok": True,
            "filepath": resolved,
            "workspace_scope": "scripts_user",
            "normalized_from": raw if resolved != os.path.abspath(raw) else "",
        }

    @staticmethod
    def _workspace_write_blocked(filepath, scripts_dir):
        return {
            "ok": False,
            "blocked": True,
            "workspace_scope": "scripts_user",
            "filepath": str(filepath or ""),
            "allowed_root": scripts_dir,
            "summary": "scripts_user workspace only allows writes inside scripts_user.",
            "error": (
                "scripts_user workspace only allows write targets inside scripts_user. "
                "Use a scripts_user/<name> path, or a bare filename for a new user script."
            ),
        }

    @staticmethod
    def clear_cache():
        """Force a re-discovery on next call."""
        PathResolver._cached_root = None
