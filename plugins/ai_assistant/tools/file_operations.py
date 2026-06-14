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


def _check_whitelist(file_path, whitelist):
    """检查文件路径是否在白名单中（支持文件夹授权和单个文件授权）"""
    file_path = os.path.normcase(os.path.normpath(os.path.abspath(file_path)))
    for w in whitelist:
        if not w:
            continue
        w_norm = os.path.normcase(os.path.normpath(os.path.abspath(w)))
        
        # 1. 精确路径匹配 (支持文件授权)
        if file_path == w_norm:
            return True, file_path
            
        # 2. 目录前缀匹配 (支持文件夹授权)
        try:
            if os.path.commonpath([file_path, w_norm]) == w_norm:
                return True, file_path
        except (ValueError, Exception):
            continue
            
    return False, file_path

@register_tool
class ReadFileTool(BaseTool):
    def __init__(self):
        super().__init__("tool_read_file", "Read content from a file with optional offset and limit", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to read"
            },
            "offset": {
                "type": "integer",
                "description": "Character offset to start reading from (default: 0)"
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of characters to read (default: 10000, max: 50000)"
            },
            "line_start": {
                "type": "integer",
                "description": "Start reading from this line number (1-based, optional)"
            },
            "line_end": {
                "type": "integer",
                "description": "Stop reading at this line number (inclusive, optional)"
            }
        }, metadata={
            "side_effect_level": "read",
            "required_args": ["file_path"],
            "path_argument_names": ["file_path"],
        })

    def execute(self, file_path, offset=0, limit=10000, line_start=None, line_end=None):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 使用助手函数进行白名单检查（统一逻辑）
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            if not os.path.exists(file_path):
                return {"error": f"File not found: {file_path}"}

            if not os.path.isfile(file_path):
                return {"error": f"Not a file: {file_path}"}

            # 限制最大读取长度
            limit = min(limit, 50000)
            
            # 尝试从编辑器读取
            editor_content = None
            if file_path.endswith('.py'):
                from PySide6.QtWidgets import QApplication
                for w in QApplication.topLevelWidgets():
                    if hasattr(w, 'mdi_area'):
                        target_abs = os.path.abspath(file_path).lower()
                        for sub in w.mdi_area.subWindowList():
                            widget = sub.widget()
                            if hasattr(widget, "script_path") and widget.script_path:
                                if os.path.abspath(widget.script_path).lower() == target_abs and hasattr(widget, "get_code"):
                                    editor_content = widget.get_code()
                                    break
                        break

            # 获取文件信息 (如果是编辑器则计算字符串长度，否则从os获取)
            total_size = len(editor_content.encode('utf-8')) if editor_content is not None else os.path.getsize(file_path)

            # 如果指定了行范围，按行读取
            if line_start is not None or line_end is not None:
                if editor_content is not None:
                    lines = [line + '\n' for line in editor_content.split('\n')]
                    if lines: lines[-1] = lines[-1].replace('\n', '')
                else:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        lines = f.readlines()

                total_lines = len(lines)
                start_idx = (line_start - 1) if line_start else 0
                end_idx = line_end if line_end else total_lines

                # 确保索引有效
                start_idx = max(0, start_idx)
                end_idx = min(total_lines, end_idx)

                selected_lines = lines[start_idx:end_idx]
                content = ''.join(selected_lines)

                # 如果内容超过限制，截断
                if len(content) > limit:
                    content = content[:limit]
                    truncated = True
                else:
                    truncated = False

                return {
                    "ok": True,
                    "message": f"Read {len(selected_lines)} lines ({len(content)} chars) from {os.path.basename(file_path)} (Line {start_idx + 1}-{end_idx})",
                    "content": content,
                    "total_lines": total_lines,
                    "read_lines": len(selected_lines),
                    "line_range": [start_idx + 1, end_idx],
                    "has_more": end_idx < total_lines or truncated,
                    "next_line": end_idx + 1 if end_idx < total_lines else None
                }
            else:
                # 按字符偏移读取
                if editor_content is not None:
                    content = editor_content[offset:offset+limit]
                else:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        f.seek(offset)
                        content = f.read(limit)

                has_more = offset + len(content) < total_size

                return {
                    "ok": True,
                    "message": f"Read {len(content)} bytes from {os.path.basename(file_path)} at offset {offset}",
                    "content": content,
                    "total_size": total_size,
                    "offset": offset,
                    "read_size": len(content),
                    "has_more": has_more,
                    "next_offset": offset + len(content) if has_more else None
                }
        except Exception as e:
            return {"error": str(e)}

@register_tool
class WriteFileTool(BaseTool):
    def __init__(self):
        super().__init__("tool_write_file", "Write content to a file", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to write"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        }, metadata={
            "required_args": ["file_path", "content"],
            "path_argument_names": ["file_path"],
        })
    
    def execute(self, file_path, content):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查文件路径是否在白名单中
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)

            return {"ok": True, "message": f"File written successfully: {file_path}"}
        except Exception as e:
            return {"error": str(e)}

@register_tool
class ListDirectoryTool(BaseTool):
    def __init__(self):
        super().__init__("tool_list_directory", "List files and directories in a directory", {
            "directory": {
                "type": "string",
                "description": "Path to the directory to list"
            }
        }, metadata={
            "required_args": ["directory"],
            "path_argument_names": ["directory"],
        })
    
    def execute(self, directory):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')
            
            # 使用助手函数进行白名单检查
            allowed, resolved_path = _check_whitelist(directory, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            directory = resolved_path

            items = []
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                items.append({
                    "name": item,
                    "type": "directory" if os.path.isdir(item_path) else "file",
                    "size": os.path.getsize(item_path) if os.path.isfile(item_path) else 0
                })

            return {
                "ok": True, 
                "message": f"Listed {len(items)} items in {os.path.basename(directory) or directory}",
                "items": items
            }
        except Exception as e:
            return {"error": str(e)}

@register_tool
class AppendFileTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__("tool_append_file", "Append content to a file", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to append to"
            },
            "content": {
                "type": "string",
                "description": "Content to append to the file"
            }
        }, metadata={
            "required_args": ["file_path", "content"],
            "path_argument_names": ["file_path"],
        })
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, file_path, content):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查文件路径是否在白名单中
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            with open(file_path, 'a', encoding='utf-8') as f:
                f.write(content)

            # 如果是Python脚本，自动重新打开
            if file_path.endswith('.py') and self.tool_executor:
                from PySide6.QtCore import QEventLoop
                import json
                loop = QEventLoop()
                
                def on_done(res):
                    loop.quit()
                
                self.tool_executor.tool_executed.connect(on_done)
                self.tool_executor.execute_open_script_file.emit(file_path)
                loop.exec()
                self.tool_executor.tool_executed.disconnect(on_done)

            return {"ok": True, "message": f"Content appended successfully: {file_path}"}
        except Exception as e:
            return {"error": str(e)}

@register_tool
class FileExistsTool(BaseTool):
    def __init__(self):
        super().__init__("tool_file_exists", "Check if a file exists", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to check"
            }
        }, metadata={
            "required_args": ["file_path"],
            "path_argument_names": ["file_path"],
        })
    
    def execute(self, file_path):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查文件路径是否在白名单中
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            exists = os.path.exists(file_path)
            is_file = os.path.isfile(file_path) if exists else False
            status = "exists" if exists else "does not exist"
            type_str = " (File)" if is_file else " (Directory)" if exists else ""
            return {
                "ok": True, 
                "message": f"File {status}{type_str}: {os.path.basename(file_path)}",
                "exists": exists, 
                "is_file": is_file
            }
        except Exception as e:
            return {"error": str(e)}

@register_tool
class DeleteFileTool(BaseTool):
    def __init__(self):
        super().__init__("tool_delete_file", "Delete a file", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to delete"
            }
        }, metadata={
            "required_args": ["file_path"],
            "path_argument_names": ["file_path"],
        })

    def execute(self, file_path):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查文件路径是否在白名单中
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            if os.path.exists(file_path):
                os.remove(file_path)
                return {"ok": True, "message": f"File deleted successfully: {file_path}"}
            else:
                return {"error": f"File does not exist: {file_path}"}
        except Exception as e:
            return {"error": str(e)}

@register_tool
class CreateDirectoryTool(BaseTool):
    def __init__(self):
        super().__init__("tool_create_directory", "Create a directory", {
            "directory_path": {
                "type": "string",
                "description": "Path to the directory to create"
            }
        }, metadata={
            "required_args": ["directory_path"],
            "path_argument_names": ["directory_path"],
        })
    
    def execute(self, directory_path):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查目录路径是否在白名单中
            allowed, resolved_path = _check_whitelist(directory_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            directory_path = resolved_path

            if not os.path.exists(directory_path):
                os.makedirs(directory_path, exist_ok=True)
                return {"ok": True, "message": f"Directory created successfully: {directory_path}"}
            else:
                return {"ok": True, "message": f"Directory already exists: {directory_path}"}
        except Exception as e:
            return {"error": str(e)}

@register_tool
class GetFileInfoTool(BaseTool):
    def __init__(self):
        super().__init__("tool_get_file_info", "Get information about a file", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to get info for"
            }
        }, metadata={
            "required_args": ["file_path"],
            "path_argument_names": ["file_path"],
        })

    def execute(self, file_path):
        try:
            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查文件路径是否在白名单中
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            if os.path.exists(file_path):
                info = {
                    "exists": True,
                    "is_file": os.path.isfile(file_path),
                    "is_directory": os.path.isdir(file_path),
                    "size": os.path.getsize(file_path) if os.path.isfile(file_path) else 0,
                    "modification_time": os.path.getmtime(file_path),
                    "absolute_path": file_path
                }
                size_str = f"{info['size']:,} bytes" if info['is_file'] else "N/A"
                import datetime
                mtime_str = datetime.datetime.fromtimestamp(info['modification_time']).strftime('%Y-%m-%d %H:%M:%S')
                return {
                    "ok": True, 
                    "message": f"File info for {os.path.basename(file_path)}: {size_str}, Modified: {mtime_str}",
                    "info": info
                }
            else:
                return {
                    "ok": True, 
                    "message": f"File not found: {os.path.basename(file_path)}",
                    "info": {"exists": False}
                }
        except Exception as e:
            return {"error": str(e)}

@register_tool
class SearchInFileTool(BaseTool):
    def __init__(self):
        super().__init__("tool_search_in_file", "Search for text patterns in a file", {
            "file_path": {
                "type": "string",
                "description": "Path to the file to search in"
            },
            "pattern": {
                "type": "string",
                "description": "Text pattern or regular expression to search for"
            },
            "use_regex": {
                "type": "boolean",
                "description": "Whether to treat pattern as a regular expression (default: false)"
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether the search is case-sensitive (default: false)"
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default: 100)"
            }
        }, metadata={
            "required_args": ["file_path", "pattern"],
            "path_argument_names": ["file_path"],
        })
    
    def execute(self, file_path, pattern, use_regex=False, case_sensitive=False, max_results=100):
        try:
            import re

            # 从环境变量获取白名单
            whitelist = os.environ.get('PYLOG_TOOL_WHITELIST', '').split(';')

            # 检查文件路径是否在白名单中
            allowed, resolved_path = _check_whitelist(file_path, whitelist)
            if not allowed:
                return {"error": f"Access denied: {resolved_path} is not in whitelist"}
            file_path = resolved_path

            if not os.path.exists(file_path):
                return {"error": f"File not found: {file_path}"}

            if not os.path.isfile(file_path):
                return {"error": f"Not a file: {file_path}"}
            
            # 读取文件内容: 优先从编辑器拿草稿
            editor_content = None
            if file_path.endswith('.py'):
                from PySide6.QtWidgets import QApplication
                for w in QApplication.topLevelWidgets():
                    if hasattr(w, 'mdi_area'):
                        target_abs = os.path.abspath(file_path).lower()
                        for sub in w.mdi_area.subWindowList():
                            widget = sub.widget()
                            if hasattr(widget, "script_path") and widget.script_path:
                                if os.path.abspath(widget.script_path).lower() == target_abs and hasattr(widget, "get_code"):
                                    editor_content = widget.get_code()
                                    break
                        break
                        
            if editor_content is not None:
                lines = [line + '\n' for line in editor_content.split('\n')]
                if lines: lines[-1] = lines[-1].replace('\n', '')
            else:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            
            results = []
            
            if use_regex:
                # 使用正则表达式搜索
                flags = 0 if case_sensitive else re.IGNORECASE
                try:
                    regex = re.compile(pattern, flags)
                except re.error as e:
                    return {"error": f"Invalid regex pattern: {e}"}
                
                for line_num, line in enumerate(lines, 1):
                    if regex.search(line):
                        results.append({
                            "line_number": line_num,
                            "line_content": line.rstrip('\n\r')
                        })
                        if len(results) >= max_results:
                            break
            else:
                # 普通文本搜索
                if case_sensitive:
                    for line_num, line in enumerate(lines, 1):
                        if pattern in line:
                            results.append({
                                "line_number": line_num,
                                "line_content": line.rstrip('\n\r')
                            })
                            if len(results) >= max_results:
                                break
                else:
                    pattern_lower = pattern.lower()
                    for line_num, line in enumerate(lines, 1):
                        if pattern_lower in line.lower():
                            results.append({
                                "line_number": line_num,
                                "line_content": line.rstrip('\n\r')
                            })
                            if len(results) >= max_results:
                                break
            
            return {
                "ok": True,
                "message": f"Found {len(results)} matches for '{pattern}' in {os.path.basename(file_path)}",
                "total_matches": len(results),
                "truncated": len(results) >= max_results,
                "matches": results
            }
        except Exception as e:
            return {"error": str(e)}
