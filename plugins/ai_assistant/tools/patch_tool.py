import json
import os
import importlib
from PySide6.QtCore import QEventLoop

try:
    from ..ai_core.file_editor import FileEditor
except ImportError:
    try:
        from plugins.ai_assistant.ai_core.file_editor import FileEditor
    except ImportError:
        FileEditor = importlib.import_module("file_editor").FileEditor

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


def _get_file_editor(filepath):
    root = PathResolver.get_project_root() if PathResolver else os.getcwd()
    # Keep the existing tool behavior compatible for now; stricter whitelist
    # enforcement will be introduced as a separate policy migration step.
    return FileEditor(project_root=root, allowed_roots=[])


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
                "keywords": [
                    "apply patch",
                    "patch file",
                    "structured patch",
                    "diff patch",
                    "modify hunks",
                    "patch code",
                ],
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

        try:
            editor = _get_file_editor(filepath)
            prepared = editor.prepare_patch(filepath, hunks, create_if_missing=create_if_missing)
            if not prepared.ok:
                return prepared.to_dict()

            resolved = prepared.filepath
            exists = bool(prepared.metadata.get("existed"))
            content = prepared.metadata.get("content", "")

            preview_result = None
            if exists and self.tool_executor and str(resolved).lower().endswith(".py"):
                preview_result = _preview_script_patch(self.tool_executor, resolved, content)
            if preview_result:
                return {
                    "ok": True,
                    "filepath": resolved,
                    "applied_hunks": prepared.applied_hunks,
                    "previewed": True,
                    "editor_id": preview_result.get("editor_id"),
                    "script_path": preview_result.get("script_path"),
                    "message": f"Preview mode activated for patch on {resolved}",
                }

            result = editor.apply_patch(filepath, hunks, create_if_missing=create_if_missing)
            payload = result.to_dict()
            if result.ok:
                payload["message"] = result.summary or f"Applied patch to {resolved}"

            return payload
        except Exception as e:
            resolved = _resolve_path(filepath)
            return {"ok": False, "error": str(e), "filepath": resolved}
