import os
import json
import importlib
from PySide6.QtCore import QCoreApplication, QEventLoop

import sys

# 动态注入插件根目录，确保内部模块导入的家园始终在 path 中
_plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

try:
    from ..common.paths import PathResolver
except ImportError:
    try:
        from plugins.ai_assistant.common.paths import PathResolver
    except ImportError:
        PathResolver = None

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
    from .tool_executor import ToolExecutor
except ImportError:
    try:
        from plugins.ai_assistant.tools.tool_executor import ToolExecutor
    except ImportError:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        ToolExecutor = importlib.import_module("tool_executor").ToolExecutor

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
    from scripts.ui.widgets.html_preview_widget import is_html_previewable
except ImportError:
    is_html_previewable = None


def _normalize_document_path(filepath):
    if filepath is None:
        return ""
    normalized = str(filepath).strip()
    if not normalized:
        return ""
    if not os.path.isabs(normalized) and PathResolver:
        normalized = os.path.join(PathResolver.get_project_root(), normalized)
    return os.path.abspath(normalized)


def _classify_document_path(filepath):
    lower_path = str(filepath or "").lower()
    if lower_path.endswith(".py"):
        return "script"
    if is_html_previewable and is_html_previewable(lower_path):
        return "html"
    return "unsupported"


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


def _attach_script_state(result, tool_executor, editor_id=None, script_path=None):
    if not isinstance(result, dict):
        return result

    state = _fetch_script_state(tool_executor, editor_id=editor_id, script_path=script_path)
    if not state:
        return result

    result["script_state"] = {
        "editor_id": state.get("editor_id"),
        "script_path": state.get("script_path"),
        "is_preview_active": state.get("is_preview_active"),
        "has_review_record": state.get("has_review_record"),
        "has_unsaved_changes": state.get("has_unsaved_changes"),
        "preview_source": state.get("preview_source"),
        "should_run_from": state.get("should_run_from"),
        "should_save_to": state.get("should_save_to"),
        "last_review_session_id": state.get("last_review_session_id"),
        "last_review_source": state.get("last_review_source"),
        "last_review_created_at": state.get("last_review_created_at"),
        "last_review_saved_to_disk": state.get("last_review_saved_to_disk"),
        "last_review_mode": state.get("last_review_mode"),
        "last_review_diff_stats": state.get("last_review_diff_stats"),
    }
    result.setdefault("editor_id", state.get("editor_id"))
    result.setdefault("script_path", state.get("script_path"))
    return result


def _preview_script_update(tool_executor, new_code, editor_id=None, script_path=None):
    if not tool_executor:
        return None

    state = _fetch_script_state(tool_executor, editor_id=editor_id, script_path=script_path)
    if not state:
        return None

    target_path = state.get("script_path") or script_path
    target_editor_id = state.get("editor_id") or editor_id
    if not target_path and not target_editor_id:
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
            "editor_id": target_editor_id,
            "script_path": target_path,
        }, new_code)
        loop.exec()
    finally:
        try:
            tool_executor.tool_executed.disconnect(on_tool_executed)
        except Exception:
            pass

    if not isinstance(result, dict) or not result.get("ok"):
        return None

    result.setdefault("editor_id", target_editor_id)
    result.setdefault("script_path", target_path)
    result["previewed"] = True
    return _attach_script_state(
        result,
        tool_executor,
        editor_id=result.get("editor_id"),
        script_path=target_path,
    )


def _get_script_editor_code(main_window, editor_id=None, script_path=None):
    if not main_window or not hasattr(main_window, "mdi_area"):
        return None

    normalized_path = os.path.abspath(script_path).lower() if script_path else None
    for sub in main_window.mdi_area.subWindowList():
        widget = sub.widget()
        if editor_id and getattr(widget, "editor_id", None) == editor_id and hasattr(widget, "get_code"):
            return widget.get_code()
        if normalized_path and getattr(widget, "script_path", None):
            existing_path = os.path.abspath(widget.script_path).lower()
            if existing_path == normalized_path and hasattr(widget, "get_code"):
                return widget.get_code()
    return None

@register_tool
class OpenScriptTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_open_script", "Open a new empty script editor window and return its editor_id for later editor operations.", {
            "title": {
                "type": "string",
                "description": "Title for the script editor window",
                "nullable": True
            }
        }, metadata={
            "capability_tags": ["editor", "script_session"],
            "domain_tags": ["script"],
            "keywords": [
                "open script editor",
                "new script",
                "new python script",
                "create script tab",
            ],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, title=None):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}
        
        loop = QEventLoop()
        result = {"error": "execution failed"}
        
        def on_tool_executed(result_str):
            nonlocal result
            result = json.loads(result_str)
            loop.quit()
        
        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_open_script.emit(title or "")
        
        loop.exec()
        
        result = _attach_script_state(result, self.tool_executor, editor_id=result.get("editor_id"))
        if isinstance(result, dict):
            result.setdefault("open_only", True)
        return result

@register_tool
class OpenScriptFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_open_script_file", "Open an existing script file in a new editor window. Use this when user wants to open a specific script file by name or path. IMPORTANT: Always use tool_search_code or tool_find_files to locate the file first if the path is unknown.", {
            "filepath": {
                "type": "string",
                "description": "Full path to the script file to open. For example: 'scripts_user/list_wells.py' or 'scripts_user/direct_plot_sample.py'"
            }
        }, metadata={
            "required_args": ["filepath"],
            "path_argument_names": ["filepath"],
            "capability_tags": ["editor", "script_session"],
            "domain_tags": ["script"],
            "keywords": [
                "open script",
                "open python file",
                "script editor",
                "python editor",
                "open .py",
            ],
            "usage_hint": "If the exact path is unknown, call tool_find_files or tool_search_code first to locate candidate files.",
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}
        
        loop = QEventLoop()
        result = {"error": "execution failed"}
        
        def on_tool_executed(result_str):
            nonlocal result
            result = json.loads(result_str)
            loop.quit()
        
        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_open_script_file.emit(filepath)
        
        loop.exec()
        
        result = _attach_script_state(result, self.tool_executor, editor_id=result.get("editor_id"), script_path=result.get("filepath") or filepath)
        if isinstance(result, dict):
            result.setdefault("open_only", True)
        return result


@register_tool
class OpenHtmlPreviewTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "tool_open_html_preview",
            "Open an existing local HTML file in the workspace as a rendered web preview. Use this for .html or .htm documents when the user wants to view the page itself instead of raw source.",
            {
                "filepath": {
                    "type": "string",
                    "description": "Full path to the HTML file to open. For example: 'scripts_user/report.html' or 'docs/local_preview.htm'",
                }
            },
            metadata={
                "required_args": ["filepath"],
                "path_argument_names": ["filepath"],
                "capability_tags": ["ui", "html_preview", "workspace"],
                "domain_tags": ["agent", "script"],
                "keywords": [
                    "html",
                    "htm",
                    "open html",
                    "html preview",
                    "web preview",
                    "web page",
                    "rendered html",
                    "local webpage",
                ],
                "usage_hint": "Use this when the target file is a local HTML page and the user wants the rendered result inside PyLog.",
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath):
        if not self.main_window or not self.tool_executor:
            return {"ok": False, "error": "no main window"}

        normalized_path = _normalize_document_path(filepath)
        if not normalized_path:
            return {"ok": False, "error": "filepath is required"}

        loop = QEventLoop()
        result = {"ok": False, "error": "execution failed"}

        def on_tool_executed(result_str):
            nonlocal result
            result = json.loads(result_str)
            loop.quit()

        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_open_html_preview.emit(normalized_path)

        loop.exec()
        if isinstance(result, dict):
            result.setdefault("open_only", True)
        return result


@register_tool
class OpenDocumentTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "tool_open_document",
            "Open a local workspace document using the most suitable built-in surface. Python scripts open in the script editor, while HTML files open as rendered web previews. This reuses the existing file-specific open tools so future document types can be added centrally.",
            {
                "filepath": {
                    "type": "string",
                    "description": "Path to the local document to open. Currently supported: .py, .html, .htm",
                }
            },
            metadata={
                "required_args": ["filepath"],
                "path_argument_names": ["filepath"],
                "capability_tags": ["workspace", "document_open", "routing"],
                "domain_tags": ["agent", "script"],
                "keywords": [
                    "open document",
                    "open file",
                    "open workspace file",
                    "html",
                    "web page",
                    "html preview",
                    "script",
                    "python file",
                    "script editor",
                    "auto detect file type",
                ],
                "usage_hint": "Use this as the default opener when you know the file path but want PyLog to choose between script editing and rendered HTML preview.",
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath):
        normalized_path = _normalize_document_path(filepath)
        if not normalized_path:
            return {"ok": False, "error": "filepath is required"}

        document_kind = _classify_document_path(normalized_path)
        if document_kind == "script":
            result = OpenScriptFileTool(self.main_window, self.tool_executor).execute(normalized_path)
        elif document_kind == "html":
            result = OpenHtmlPreviewTool(self.main_window, self.tool_executor).execute(normalized_path)
        else:
            return {
                "ok": False,
                "filepath": normalized_path,
                "error": "Unsupported document type. Currently supported: .py, .html, .htm",
            }

        if isinstance(result, dict):
            result.setdefault("document_kind", document_kind)
            result.setdefault("filepath", normalized_path)
            result.setdefault("open_only", True)
        return result

@register_tool
class WriteScriptFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_write_script_file", "Create a new script file on disk. Optionally open it in an editor so later editor tools can target it by editor_id.", {
            "filepath": {
                "type": "string",
                "description": "Full path to the script file to create. For example: 'scripts_user/new_script.py'"
            },
            "code": {
                "type": "string",
                "description": "Python code to write into the file"
            },
            "open_after_write": {
                "type": "boolean",
                "description": "Whether to open the created file in an editor tab and return editor_id.",
                "nullable": True
            }
        }, metadata={
            "side_effect_level": "script_write",
            "requires_verification": True,
            "requires_read_before_write": False,
            "required_args": ["filepath"],
            "creates_file": True,
            "path_argument_names": ["filepath"],
            "capability_tags": ["script_creation", "editor"],
            "domain_tags": ["script"],
            "keywords": [
                "write script file",
                "create python file",
                "new script file",
                "save new script",
            ],
            "usage_hint": "Use tool_find_files or tool_search_code first when you only know the filename or feature, not the exact path.",
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath=None, code="", open_after_write=False):
        if not filepath or not filepath.strip():
            return {"error": "filepath is required"}
        
        try:
            filepath = filepath.strip()
            
            # Resolve relative paths against project root
            if not os.path.isabs(filepath):
                filepath = os.path.join(PathResolver.get_project_root(), filepath)
            
            # 确保目录存在
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # 写入文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(code)
            
            # 刷新脚本浏览器
            self._refresh_script_explorer()
            
            result = {
                "ok": True,
                "filepath": filepath,
                "message": f"Script file created successfully: {filepath}"
            }
            
            if open_after_write and self.tool_executor:
                loop = QEventLoop()
                open_result = {"error": "failed to open created script"}

                def on_tool_executed(result_str):
                    nonlocal open_result
                    try:
                        open_result = json.loads(result_str)
                    except Exception as e:
                        open_result = {"error": f"Failed to parse open result: {e}"}
                    finally:
                        loop.quit()

                self.tool_executor.tool_executed.connect(on_tool_executed)
                self.tool_executor.execute_open_script_file.emit(filepath)
                loop.exec()
                try:
                    self.tool_executor.tool_executed.disconnect(on_tool_executed)
                except Exception:
                    pass

                if open_result.get("ok"):
                    result["editor_id"] = open_result.get("editor_id")
                    result["opened"] = True
                else:
                    result["opened"] = False
                    result["open_error"] = open_result.get("error")

            return _attach_script_state(result, self.tool_executor, editor_id=result.get("editor_id"), script_path=result.get("filepath"))
        except Exception as e:
            return {"error": str(e)}
    
    def _refresh_script_explorer(self):
        """Thread-safe refresh of the script explorer to show newly created files."""
        try:
            if self.main_window and hasattr(self.main_window, 'explorer'):
                explorer = self.main_window.explorer
                if explorer and hasattr(explorer, 'populate_scripts'):
                    # CRITICAL: Always use invokeMethod with QueuedConnection for cross-thread UI calls
                    from PySide6.QtCore import QMetaObject, Qt
                    QMetaObject.invokeMethod(explorer, "populate_scripts", Qt.QueuedConnection)
        except Exception:
            pass

@register_tool
class SetScriptCodeTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_set_script_code", "Set the full content of a script editor. Prefer passing editor_id returned by tool_open_script or tool_open_script_file.", {
            "code": {
                "type": "string",
                "description": "Python code to place in the script editor"
            },
            "editor_id": {
                "type": "string",
                "description": "Optional target editor id",
                "nullable": True
            }
        }, metadata={
            "capability_tags": ["editor", "script_write"],
            "domain_tags": ["script"],
            "keywords": [
                "set script code",
                "replace script content",
                "write code in editor",
                "set editor content",
            ],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, code="", editor_id=None):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}

        preview_result = _preview_script_update(
            self.tool_executor,
            code or "",
            editor_id=editor_id,
        )
        if preview_result:
            preview_result.setdefault("message", "Preview mode activated in existing script editor")
            return preview_result

        loop = QEventLoop()
        result = {"error": "execution failed"}

        def on_tool_executed(result_str):
            nonlocal result
            result = json.loads(result_str)
            loop.quit()

        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_set_script_code.emit({"code": code or "", "editor_id": editor_id})

        loop.exec()
        return _attach_script_state(result, self.tool_executor, editor_id=result.get("editor_id") or editor_id)

@register_tool
class AppendScriptCodeTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_append_script_code", "Append Python code to a script editor. Prefer passing editor_id returned by tool_open_script or tool_open_script_file.", {
            "code": {
                "type": "string",
                "description": "Python code to append to the script editor"
            },
            "editor_id": {
                "type": "string",
                "description": "Optional target editor id",
                "nullable": True
            }
        }, metadata={
            "side_effect_level": "script_write",
            "requires_verification": True,
            "requires_read_before_write": False,
            "path_argument_names": ["editor_id"],
            "capability_tags": ["editor", "script_write"],
            "domain_tags": ["script"],
            "keywords": [
                "append script code",
                "append code",
                "add code to script",
                "append to editor",
            ],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, code="", editor_id=None):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}

        state = _fetch_script_state(self.tool_executor, editor_id=editor_id)
        if state and state.get("script_path"):
            current_code = _get_script_editor_code(
                self.main_window,
                editor_id=state.get("editor_id"),
                script_path=state.get("script_path"),
            )
            if current_code is not None:
                add = code or ""
                new_code = current_code + ("\n" if current_code and add else "") + add
                preview_result = _preview_script_update(
                    self.tool_executor,
                    new_code,
                    editor_id=state.get("editor_id"),
                    script_path=state.get("script_path"),
                )
                if preview_result:
                    preview_result.setdefault("message", "Preview mode activated in existing script editor")
                    return preview_result
        
        loop = QEventLoop()
        result = {"error": "execution failed"}
        
        def on_tool_executed(result_str):
            nonlocal result
            result = json.loads(result_str)
            loop.quit()
        
        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_append_script_code.emit({"code": code or "", "editor_id": editor_id})
        
        loop.exec()
        
        return _attach_script_state(result, self.tool_executor, editor_id=result.get("editor_id") or editor_id)

@register_tool
class RunScriptTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_run_script", "Run a script in the dedicated AI terminal. You can provide raw code, a script_path, or an editor_id.", {
            "code": {
                "type": "string",
                "description": "Optional: Raw Python code to execute directly",
                "nullable": True
            },
            "script_path": {
                "type": "string",
                "description": "Optional: Path to a .py file to execute",
                "nullable": True
            },
            "editor_id": {
                "type": "string",
                "description": "Optional: editor id to run from an open script tab",
                "nullable": True
            }
        }, metadata={
            "argument_rules": [
                {
                    "type": "at_least_one_of",
                    "fields": ["code", "script_path", "editor_id"],
                }
            ],
            "capability_tags": ["script_execution", "python_execution"],
            "domain_tags": ["script"],
            "keywords": [
                "run script",
                "execute script",
                "run python code",
                "run editor code",
                "script execution",
            ],
            "usage_hint": "Provide at least one of raw code, script_path, or editor_id so the runtime knows what to execute.",
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, code=None, script_path=None, editor_id=None):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}

        loop = QEventLoop()
        result = {"error": "execution failed"}

        def on_tool_executed(result_str):
            nonlocal result
            try:
                result = json.loads(result_str)
            except Exception as e:
                result = {"error": f"Failed to parse result: {e}"}
            finally:
                loop.quit()

        self.tool_executor.tool_executed.connect(on_tool_executed)
        payload = {"code": code, "editor_id": editor_id, "script_path": script_path}
        self.tool_executor.execute_run_script.emit(payload, script_path)

        loop.exec()

        return _attach_script_state(result, self.tool_executor, editor_id=editor_id or result.get("editor_id"), script_path=script_path)

@register_tool
class SaveScriptTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_save_script", "Save a script editor to disk. Prefer passing editor_id to avoid saving the wrong tab.", {
            "filename": {
                "type": "string",
                "description": "Filename or full path to save the script as. If omitted, save to existing script_path.",
                "nullable": True
            },
            "editor_id": {
                "type": "string",
                "description": "Optional target editor id",
                "nullable": True
            }
        }, metadata={
            "side_effect_level": "script_write",
            "requires_verification": True,
            "requires_read_before_write": False,
            "path_argument_names": ["filename", "editor_id"],
            "capability_tags": ["script_write", "editor"],
            "domain_tags": ["script"],
            "keywords": [
                "save script",
                "save python file",
                "write editor to disk",
                "save script as",
            ],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filename=None, editor_id=None):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}

        loop = QEventLoop()
        result = {"error": "execution failed"}

        def on_tool_executed(result_str):
            nonlocal result
            try:
                result = json.loads(result_str)
            except Exception as e:
                result = {"error": f"Failed to parse result: {e}"}
            finally:
                loop.quit()

        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_save_script.emit({"filename": filename, "editor_id": editor_id})

        loop.exec()

        return _attach_script_state(result, self.tool_executor, editor_id=result.get("editor_id") or editor_id, script_path=result.get("filepath") or filename)


@register_tool
class GetScriptStateTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_get_script_state", "Get structured state for an open script editor, including whether it is in AI preview mode, whether it has unsaved changes, and whether the current working copy should be run instead of creating a new file.", {
            "editor_id": {
                "type": "string",
                "description": "Optional target editor id.",
                "nullable": True
            },
            "script_path": {
                "type": "string",
                "description": "Optional script path to resolve an already-open editor.",
                "nullable": True
            }
        }, metadata={
            "capability_tags": ["editor", "inspection"],
            "domain_tags": ["script"],
            "keywords": [
                "script state",
                "editor state",
                "preview state",
                "unsaved changes",
                "script status",
            ],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, editor_id=None, script_path=None):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}

        loop = QEventLoop()
        result = {"error": "execution failed"}

        def on_tool_executed(result_str):
            nonlocal result
            try:
                result = json.loads(result_str)
            except Exception as e:
                result = {"error": f"Failed to parse result: {e}"}
            finally:
                loop.quit()

        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_get_script_state.emit({
            "editor_id": editor_id,
            "script_path": script_path,
        })

        loop.exec()

        return result

@register_tool
class ListScriptsTool(BaseTool):
    def __init__(self):
        super().__init__("tool_list_scripts", "List all user script files in the scripts_user directory", {}, metadata={
            "capability_tags": ["search", "script_inventory"],
            "domain_tags": ["script"],
            "keywords": [
                "list scripts",
                "show scripts",
                "script inventory",
                "available scripts",
            ],
        })

    def execute(self):
        d = "scripts_user"
        if not os.path.exists(d):
            return []
            
        scripts = []
        for root, dirs, files in os.walk(d):
            # 过滤掉 __pycache__ 和 隐藏文件夹
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != '__pycache__']
            
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.join(root, file)
                    # 返回相对于项目根目录的路径，或者相对于 scripts_user 的路径
                    # 考虑到 tool_open_script_file 的描述，通常使用 'scripts_user/folder/script.py'
                    rel_path = os.path.relpath(full_path, os.getcwd())
                    scripts.append(rel_path.replace('\\', '/'))
        return sorted(scripts)


@register_tool
class RunTerminalCommandTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_run_terminal_command", "Execute a Python command in the script editor's terminal. Use this to run Python code interactively or test commands.", {
            "command": {
                "type": "string",
                "description": "Python command to execute in the terminal"
            }
        }, metadata={
            "required_args": ["command"],
            "capability_tags": ["script_execution", "terminal"],
            "domain_tags": ["script"],
            "keywords": [
                "run terminal command",
                "python terminal",
                "interactive python command",
                "run python command",
            ],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, command=""):
        if not self.main_window or not self.tool_executor:
            return {"error": "no main window"}

        if not command or not command.strip():
            return {"error": "command is required"}

        loop = QEventLoop()
        result = {"error": "execution failed"}

        def on_tool_executed(result_str):
            nonlocal result
            try:
                result = json.loads(result_str)
            except Exception as e:
                result = {"error": f"Failed to parse result: {e}"}
            finally:
                loop.quit()

        self.tool_executor.tool_executed.connect(on_tool_executed)
        self.tool_executor.execute_run_terminal_command.emit(command.strip())

        loop.exec()

        return result
