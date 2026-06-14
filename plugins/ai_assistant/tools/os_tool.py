
import subprocess
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

@register_tool
class TerminalTool(BaseTool):
    def __init__(self):
        super().__init__("tool_run_shell_command", "Execute a shell command in the terminal", {
            "command": {
                "type": "string",
                "description": "Shell command to execute"
            }
        }, metadata={
            "required_args": ["command"],
        })

    def execute(self, command):
        try:
            # Use shell=True for convenience, but be aware of security implications in production
            # For a local desktop app assistant, this is often desired by users for autonomy.
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
            stdout = (result.stdout or "")[:2000]
            stderr = (result.stderr or "")[:2000]
            combined = stdout.strip()
            if stderr.strip():
                combined = f"{combined}\n{stderr}".strip() if combined else stderr.strip()
            return {
                "ok": result.returncode == 0,
                "display_type": "terminal",
                "terminal_mode": "shell",
                "command": command,
                "terminal": combined or "Done (No Output)",
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": result.returncode,
                "summary": f"Shell command exited with code {result.returncode}",
            }
        except Exception as e:
            return {"error": str(e)}

@register_tool
class FileSearchTool(BaseTool):
    def __init__(self):
        super().__init__("tool_search_files", "Search for files by name pattern", {
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
