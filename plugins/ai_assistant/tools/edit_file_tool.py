import os
import json

try:
    from .base_tool import BaseTool
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        from .base_tool import BaseTool
        from .registry import register_tool

import os
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


def _fetch_script_state(tool_executor, editor_id=None, script_path=None):
    if not tool_executor:
        return None

    from PySide6.QtCore import QEventLoop

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


def draft_change_in_open_editor(filepath, new_content, tool_executor):
    """
    Send code changes to an already-open editor draft/review session.

    This intentionally does not open script editors. If the target script is not
    already open, callers should write through the normal file-edit path.
    """
    if not filepath.endswith(".py") or not tool_executor:
        return None

    from PySide6.QtCore import QEventLoop

    state = _fetch_script_state(tool_executor, script_path=filepath)
    if not state or (not state.get("editor_id") and not state.get("script_path")):
        return None

    loop = QEventLoop()
    draft_result = None

    def on_draft_done(res):
        nonlocal draft_result
        try:
            res_dict = json.loads(res)
            if res_dict.get("ok"):
                draft_result = res_dict
        except Exception:
            draft_result = None
        finally:
            try:
                tool_executor.tool_executed.disconnect(on_draft_done)
            except Exception:
                pass
            loop.quit()

    tool_executor.tool_executed.connect(on_draft_done)
    tool_executor.execute_preview_script_code.emit({
        "editor_id": state.get("editor_id"),
        "script_path": state.get("script_path") or filepath,
    }, new_content)
    loop.exec()

    if not draft_result:
        return None

    draft_result.setdefault("editor_id", state.get("editor_id"))
    draft_result.setdefault("script_path", state.get("script_path") or filepath)
    draft_result["previewed"] = True
    return _attach_script_state(
        draft_result,
        tool_executor,
        editor_id=draft_result.get("editor_id"),
        script_path=filepath,
    )


@register_tool
class EditFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_edit_file", "Edit an existing file by replacing specific content. Use this for targeted, minor modifications. IMPORTANT: Always use tool_read_file first to understand the file content.", {
            "filepath": {
                "type": "string",
                "description": "Path to the file to edit"
            },
            "old_string": {
                "type": "string",
                "description": "The exact text to be replaced (search section)"
            },
            "new_string": {
                "type": "string",
                "description": "The new text to replace with (replace section)"
            }
        }, metadata={
            "side_effect_level": "write",
            "requires_verification": True,
            "requires_read_before_write": True,
            "required_args": ["filepath", "old_string", "new_string"],
            "path_argument_names": ["filepath"],
            "capability_tags": ["code_edit", "targeted_edit"],
            "domain_tags": ["code", "script"],
            "keywords": [
                "edit file",
                "replace text",
                "targeted edit",
                "modify file",
                "change code",
                "replace string",
            ],
            "usage_hint": "If the target path is unknown, call tool_find_files or tool_search_code first. Read the file before editing.",
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath=None, old_string=None, new_string=None):
        if not filepath or not filepath.strip():
            return {"error": "filepath is required"}
        
        if old_string is None:
            return {"error": "old_string is required"}
        
        if new_string is None:
            return {"error": "new_string is required"}
        
        try:
            filepath = filepath.strip()
            
            # Resolve relative paths against project root
            if not os.path.isabs(filepath):
                filepath = os.path.join(PathResolver.get_project_root(), filepath)
            
            if not os.path.exists(filepath):
                return {"error": f"File not found: {filepath}"}
            
            if not os.path.isfile(filepath):
                return {"error": f"Not a file: {filepath}"}
            
            # 读取文件内容 (若编辑器中有草稿，则从编辑器拿，否则从硬盘读)
            content = None
            if getattr(self, "tool_executor", None) and getattr(self, "main_window", None):
                target_abs = os.path.abspath(filepath).lower()
                for sub in self.main_window.mdi_area.subWindowList():
                    widget = sub.widget()
                    if hasattr(widget, "script_path") and widget.script_path:
                        if os.path.abspath(widget.script_path).lower() == target_abs:
                            if hasattr(widget, "get_code"):
                                content = widget.get_code()
                                break
                                
            if content is None:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            
            # 检查old_string是否存在
            if old_string not in content:
                return {"error": f"old_string not found in file. Make sure the text matches exactly."}
            
            # 替换内容
            new_content = content.replace(old_string, new_string, 1)
            
            # If the script is already open, update its draft review instead of writing immediately.
            preview_result = draft_change_in_open_editor(filepath, new_content, self.tool_executor)
            if preview_result:
                return _attach_script_state({
                    "ok": True,
                    "filepath": filepath,
                    "previewed": True,
                    "editor_id": preview_result.get("editor_id"),
                    "script_path": preview_result.get("script_path"),
                    "message": f"Draft review updated for open script {filepath}. Changes are NOT saved to disk yet."
                }, self.tool_executor, script_path=filepath)
            
            # Write to disk when no open editor can host a draft review.
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            return _attach_script_state({
                "ok": True,
                "filepath": filepath,
                "message": f"File edited successfully: {filepath}"
            }, self.tool_executor, script_path=filepath)
        except Exception as e:
            return {"error": str(e)}


@register_tool
class OverwriteFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_overwrite_file", "Overwrite an existing file with new content. Use this when you need to completely replace a file's content. IMPORTANT: Always use tool_read_file first to backup or understand the existing content.", {
            "filepath": {
                "type": "string",
                "description": "Path to the file to overwrite"
            },
            "content": {
                "type": "string",
                "description": "New content to write to the file"
            }
        }, metadata={
            "side_effect_level": "write",
            "requires_verification": True,
            "requires_read_before_write": True,
            "required_args": ["filepath", "content"],
            "path_argument_names": ["filepath"],
            "capability_tags": ["code_edit", "overwrite"],
            "domain_tags": ["code", "script"],
            "keywords": [
                "overwrite file",
                "replace whole file",
                "rewrite file",
                "set file content",
                "replace full content",
            ],
            "usage_hint": "If the target path is unknown, call tool_find_files or tool_search_code first. Read the file before overwriting it.",
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath=None, content=None):
        if not filepath or not filepath.strip():
            return {"error": "filepath is required"}
        
        if content is None:
            return {"error": "content is required"}
        
        try:
            filepath = filepath.strip()
            
            # Resolve relative paths against project root
            if not os.path.isabs(filepath):
                filepath = os.path.join(PathResolver.get_project_root(), filepath)
            
            if not os.path.exists(filepath):
                return {"error": f"File not found: {filepath}"}
            
            if not os.path.isfile(filepath):
                return {"error": f"Not a file: {filepath}"}
            
            # If the script is already open, update its draft review instead of writing immediately.
            preview_result = draft_change_in_open_editor(filepath, content, self.tool_executor)
            if preview_result:
                return _attach_script_state({
                    "ok": True,
                    "filepath": filepath,
                    "previewed": True,
                    "editor_id": preview_result.get("editor_id"),
                    "script_path": preview_result.get("script_path"),
                    "message": f"Draft review updated for open script {filepath}. Changes are NOT saved to disk yet."
                }, self.tool_executor, script_path=filepath)
                
            # Write to disk when no open editor can host a draft review.
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return _attach_script_state({
                "ok": True,
                "filepath": filepath,
                "message": f"File overwritten successfully: {filepath}"
            }, self.tool_executor, script_path=filepath)
        except Exception as e:
            return {"error": str(e)}


@register_tool
class InsertIntoFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_insert_into_file", "Insert content into a file at a specific location. Use this to add code at a specific line or after/before a specific marker.", {
            "filepath": {
                "type": "string",
                "description": "Path to the file to edit"
            },
            "content": {
                "type": "string",
                "description": "Content to insert"
            },
            "after": {
                "type": "string",
                "description": "Insert after this text (optional, use either after or before)",
                "nullable": True
            },
            "before": {
                "type": "string",
                "description": "Insert before this text (optional, use either after or before)",
                "nullable": True
            },
            "line_number": {
                "type": "integer",
                "description": "Insert at this line number (1-indexed, optional)",
                "nullable": True
            }
        }, metadata={
            "side_effect_level": "write",
            "requires_verification": True,
            "requires_read_before_write": True,
            "required_args": ["filepath", "content"],
            "argument_rules": [
                {
                    "type": "exactly_one_of",
                    "fields": ["after", "before", "line_number"],
                }
            ],
            "path_argument_names": ["filepath"],
            "capability_tags": ["code_edit", "insert"],
            "domain_tags": ["code", "script"],
            "keywords": [
                "insert into file",
                "insert code",
                "add code",
                "insert after",
                "insert before",
                "insert at line",
            ],
            "usage_hint": "If the target path is unknown, call tool_find_files or tool_search_code first. Then provide exactly one insertion anchor.",
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, filepath=None, content=None, after=None, before=None, line_number=None):
        if not filepath or not filepath.strip():
            return {"error": "filepath is required"}
        
        if content is None:
            return {"error": "content is required"}
        
        if sum(x is not None for x in [after, before, line_number]) != 1:
            return {"error": "Must specify exactly one of: after, before, or line_number"}
        
        try:
            filepath = filepath.strip()
            
            # Resolve relative paths against project root
            if not os.path.isabs(filepath):
                filepath = os.path.join(PathResolver.get_project_root(), filepath)
            
            if not os.path.exists(filepath):
                return {"error": f"File not found: {filepath}"}
            
            if not os.path.isfile(filepath):
                return {"error": f"Not a file: {filepath}"}
            
            # 读取文件内容 (优先从编辑器获取)
            content_str = None
            if getattr(self, "main_window", None):
                target_abs = os.path.abspath(filepath).lower()
                for sub in getattr(self.main_window, "mdi_area").subWindowList() if hasattr(self.main_window, "mdi_area") else []:
                    widget = sub.widget()
                    if hasattr(widget, "script_path") and widget.script_path:
                        if os.path.abspath(widget.script_path).lower() == target_abs:
                            if hasattr(widget, "get_code"):
                                content_str = widget.get_code()
                                break
                                
            if content_str is None:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            else:
                lines = [line + '\n' for line in content_str.split('\n')]
                # remove the extra newline added to the last item
                if lines:
                    lines[-1] = lines[-1].replace('\n', '')
            
            if line_number is not None:
                # 在指定行号插入
                if line_number < 1:
                    line_number = 1
                if line_number > len(lines) + 1:
                    line_number = len(lines) + 1
                lines.insert(line_number - 1, content + '\n')
            
            elif after is not None:
                # 在指定文本后插入
                content_str = ''.join(lines)
                if after not in content_str:
                    return {"error": f"'after' text not found in file"}
                new_content = content_str.replace(after, after + content, 1)
                lines = new_content.split('\n')
                lines = [line + '\n' for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
            
            elif before is not None:
                # 在指定文本前插入
                content_str = ''.join(lines)
                if before not in content_str:
                    return {"error": f"'before' text not found in file"}
                new_content = content_str.replace(before, content + before, 1)
                lines = new_content.split('\n')
                lines = [line + '\n' for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])
            
            new_content_str = ''.join(lines)
            
            # Try applying dynamically to preview
            preview_result = None
            if getattr(self, "tool_executor", None):
                preview_result = draft_change_in_open_editor(filepath, new_content_str, self.tool_executor)
            if preview_result:
                return _attach_script_state({
                    "ok": True,
                    "filepath": filepath,
                    "previewed": True,
                    "editor_id": preview_result.get("editor_id"),
                    "script_path": preview_result.get("script_path"),
                    "message": f"Draft review updated for open script {filepath}. Changes are NOT saved to disk yet."
                }, self.tool_executor, script_path=filepath)
            
            # Write to disk when no open editor can host a draft review.
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            
            return _attach_script_state({
                "ok": True,
                "filepath": filepath,
                "message": f"Content inserted successfully into: {filepath}"
            }, self.tool_executor, script_path=filepath)
        except Exception as e:
            return {"error": str(e)}
