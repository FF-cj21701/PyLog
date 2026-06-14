import json
import os
import importlib
from PySide6.QtCore import QEventLoop

try:
    from .base_tool import BaseTool
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        try:
            BaseTool = importlib.import_module("base_tool").BaseTool
            register_tool = importlib.import_module("registry").register_tool
        except ImportError:
            from .base_tool import BaseTool
            from .registry import register_tool

try:
    from ..common.paths import PathResolver
except ImportError:
    try:
        from plugins.ai_assistant.common.paths import PathResolver
    except ImportError:
        try:
            PathResolver = importlib.import_module("paths").PathResolver
        except ImportError:
            PathResolver = None


def _resolve_path(filepath):
    if os.path.isabs(filepath):
        return filepath
    root = PathResolver.get_project_root() if PathResolver else os.getcwd()
    return os.path.join(root, filepath)


def _fetch_script_state(tool_executor, editor_id=None, script_path=None):
    if not tool_executor:
        return None

    loop = QEventLoop()
    result = None

    def on_tool_executed(result_str):
        nonlocal result
        try:
            result = json.loads(result_str)
        except Exception:
            result = None
        finally:
            loop.quit()

    try:
        tool_executor.tool_executed.connect(on_tool_executed)
        tool_executor.execute_get_script_state.emit({
            "editor_id": editor_id,
            "script_path": script_path,
        })
        loop.exec()
    finally:
        try:
            tool_executor.tool_executed.disconnect(on_tool_executed)
        except Exception:
            pass

    return result if isinstance(result, dict) and result.get("ok") else None


def _preview_script_patch(tool_executor, script_path, new_code):
    state = _fetch_script_state(tool_executor, script_path=script_path)
    if not state or (not state.get("script_path") and not state.get("editor_id")):
        return None

    loop = QEventLoop()
    result = {"ok": False, "error": "preview failed"}

    def on_tool_executed(result_str):
        nonlocal result
        try:
            result = json.loads(result_str)
        except Exception as e:
            result = {"ok": False, "error": f"Failed to parse preview result: {e}"}
        finally:
            loop.quit()

    try:
        tool_executor.tool_executed.connect(on_tool_executed)
        tool_executor.execute_preview_script_code.emit({
            "editor_id": state.get("editor_id"),
            "script_path": state.get("script_path") or script_path,
        }, new_code)
        loop.exec()
    finally:
        try:
            tool_executor.tool_executed.disconnect(on_tool_executed)
        except Exception:
            pass

    if not isinstance(result, dict) or not result.get("ok"):
        return None

    result.setdefault("script_path", state.get("script_path") or script_path)
    result.setdefault("editor_id", state.get("editor_id"))
    result["previewed"] = True
    return result


@register_tool
class ApplyPatchTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "tool_apply_patch",
            "Apply a structured patch to a file. Prefer this over raw overwrite for code changes.",
            {
                "filepath": {
                    "type": "string",
                    "description": "Target file path."
                },
                "hunks": {
                    "type": "array",
                    "description": "Ordered patch hunks. Each hunk may replace exact old text with new text.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_string": {"type": "string"},
                            "new_string": {"type": "string"},
                            "replace_all": {"type": "boolean"}
                        },
                        "required": ["old_string", "new_string"]
                    }
                },
                "create_if_missing": {
                    "type": "boolean",
                    "description": "Create the file if it does not exist and there is a single create hunk.",
                    "nullable": True
                }
            },
            metadata={
                "side_effect_level": "write",
                "requires_verification": True,
                "requires_read_before_write": True,
                "required_args": ["filepath", "hunks"],
                "path_argument_names": ["filepath"],
                "capability_tags": ["code_edit", "patch"],
                "domain_tags": ["code", "script"],
                "usage_hint": "If the target path is unknown, locate it first with tool_find_files or tool_search_code before applying hunks.",
            }
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath=None, hunks=None, create_if_missing=False):
        if not filepath:
            return {"ok": False, "error": "filepath is required"}
        if not hunks:
            return {"ok": False, "error": "hunks are required"}

        resolved = _resolve_path(filepath)
        exists = os.path.exists(resolved)
        if not exists and not create_if_missing:
            return {"ok": False, "error": f"File not found: {resolved}"}

        try:
            if exists:
                with open(resolved, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            else:
                content = ""

            applied = 0
            for idx, hunk in enumerate(hunks, start=1):
                old_string = hunk.get("old_string", "")
                new_string = hunk.get("new_string", "")
                replace_all = bool(hunk.get("replace_all"))

                if not exists and create_if_missing and len(hunks) == 1 and old_string == "":
                    content = new_string
                    applied += 1
                    continue

                if old_string not in content:
                    return {
                        "ok": False,
                        "error": f"Hunk {idx} old_string not found in file",
                        "filepath": resolved,
                        "applied_hunks": applied,
                    }

                if replace_all:
                    occurrences = content.count(old_string)
                    content = content.replace(old_string, new_string)
                    applied += occurrences
                else:
                    content = content.replace(old_string, new_string, 1)
                    applied += 1

            preview_result = None
            if exists and self.tool_executor and str(resolved).lower().endswith(".py"):
                preview_result = _preview_script_patch(self.tool_executor, resolved, content)
            if preview_result:
                return {
                    "ok": True,
                    "filepath": resolved,
                    "applied_hunks": applied,
                    "previewed": True,
                    "editor_id": preview_result.get("editor_id"),
                    "script_path": preview_result.get("script_path"),
                    "message": f"Preview mode activated for patch on {resolved}",
                }

            os.makedirs(os.path.dirname(resolved), exist_ok=True)
            with open(resolved, "w", encoding="utf-8") as f:
                f.write(content)

            return {
                "ok": True,
                "filepath": resolved,
                "applied_hunks": applied,
                "message": f"Applied patch to {resolved}",
            }
        except Exception as e:
            return {"ok": False, "error": str(e), "filepath": resolved}
