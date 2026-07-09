
import os
import importlib

# 尝试不同的导入路径
try:
    from .base_tool import BaseTool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool

try:
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        register_tool = importlib.import_module("registry").register_tool

try:
    from ..ai_core.shell_executor import ControlledShellExecutor
except ImportError:
    try:
        from plugins.ai_assistant.ai_core.shell_executor import ControlledShellExecutor
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ControlledShellExecutor = importlib.import_module("ai_core.shell_executor").ControlledShellExecutor

@register_tool
class TerminalTool(BaseTool):
    def __init__(self):
        super().__init__("run_shell_command", "Execute a controlled local command in the project root", {
            "command": {
                "type": "string",
                "description": "Command to execute without shell operators. Use verification tools for tests when possible."
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory. Defaults to the PyLog project root.",
                "nullable": True
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Optional timeout in seconds. Defaults to 30.",
                "nullable": True
            }
        }, metadata={
            "required_args": ["command"],
            "side_effect_level": "external",
            "risk_level": "high",
            "capability_tags": ["shell", "command_execution"],
            "domain_tags": ["code", "workspace"],
            "search_weight": -8,
            "keywords": [
                "run shell command",
                "run command",
                "terminal",
                "shell",
                "command line",
                "cli command",
            ],
            "usage_hint": "Runs a single controlled command without shell control operators. Destructive commands and package installs are blocked.",
        })

    def execute(self, command, cwd=None, timeout_seconds=None):
        result = ControlledShellExecutor().run(
            command,
            cwd=cwd,
            timeout_seconds=timeout_seconds,
            allow_shell=False,
        ).to_dict()
        combined = (result.get("stdout") or "").strip()
        stderr = (result.get("stderr") or "").strip()
        if stderr:
            combined = f"{combined}\n{stderr}".strip() if combined else stderr
        result.update({
            "display_type": "terminal",
            "terminal_mode": "controlled",
            "terminal": combined or "Done (No Output)",
        })
        return result

@register_tool
class FileSearchTool(BaseTool):
    def __init__(self):
        super().__init__("search_files", "Search for files by name pattern", {
            "pattern": {
                "type": "string",
                "description": "File name pattern to search for (supports wildcards like *.py)"
            },
            "root_dir": {
                "type": "string",
                "description": "Root directory to search from",
                "nullable": True
            }
        }, metadata={
            "required_args": ["pattern"],
            "domain_tags": ["code", "workspace", "script"],
            "capability_tags": ["path_discovery", "file_search"],
            "search_weight": -5,
            "keywords": [
                "search files",
                "find files",
                "file name search",
                "wildcard file search",
            ],
        })

    def execute(self, pattern, root_dir=None):
        import glob
        search_root = root_dir or os.getcwd()
        try:
            # Use recursive glob for deep search
            files = glob.glob(os.path.join(search_root, "**", pattern), recursive=True)
            # Limit to 50 results
            return {"files": files[:50], "total": len(files)}
        except Exception as e:
            return {"error": str(e)}
