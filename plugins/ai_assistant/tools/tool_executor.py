import os
import sys
import json
from PySide6.QtCore import QObject, Signal, Slot

# 动态注入插件根目录，确保内部模块导入的健壮性
_plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

try:
    from ..common.paths import PathResolver
except ImportError:
    # 极端情况下的分级回退适配
    try:
        from plugins.ai_assistant.common.paths import PathResolver
    except ImportError:
        PathResolver = None

class ToolExecutor(QObject):
    """工具执行器，用于在主线程中执行UI相关的工具操作"""
    
    # 信号定义
    execute_open_script = Signal(str)
    execute_open_script_file = Signal(str)
    execute_set_script_code = Signal(object)
    execute_append_script_code = Signal(object)
    execute_preview_script_code = Signal(object, str) # payload(filepath/editor_id), code
    execute_run_script = Signal(object, object)  # (code, script_path)
    execute_save_script = Signal(object)
    execute_get_script_state = Signal(object)
    execute_get_terminal = Signal()
    execute_run_terminal_command = Signal(str)
    execute_plot_from_db = Signal(str)  # 传递JSON字符串
    execute_plot_data = Signal(str)     # 传递JSON字符串
    execute_plot = Signal(str)          # 统一绘图信号
    execute_save_curve = Signal(str)    # 曲线保存信号
    execute_get_plot_details = Signal(str) # 传递窗口标题
    
    # 结果信号
    tool_executed = Signal(str)
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        # 连接信号和槽
        self.execute_open_script.connect(self._open_script)
        self.execute_open_script_file.connect(self._open_script_file)
        self.execute_set_script_code.connect(self._set_script_code)
        self.execute_append_script_code.connect(self._append_script_code)
        self.execute_preview_script_code.connect(self._preview_script_code)
        self.execute_run_script.connect(self._run_script)
        self.execute_save_script.connect(self._save_script)
        self.execute_get_script_state.connect(self._get_script_state)
        self.execute_get_terminal.connect(self._get_terminal)
        self.execute_run_terminal_command.connect(self._run_terminal_command)
        self.execute_plot_from_db.connect(self._plot_from_db)
        self.execute_plot_data.connect(self._plot_data)
        self.execute_plot.connect(self._plot)
        self.execute_save_curve.connect(self._save_curve)
        self.execute_get_plot_details.connect(self._get_plot_details)
        self.execution_context = {}
        self.terminal_history = []
        self._last_script_editor_id = None
        self._init_ai_context()
    
    def _init_ai_context(self):
        """初始化 AI 专用的执行上下环境"""
        import numpy as np
        from scripts.data.db_manager import DBManager as DBClass
        
        # 尝试获取数据库路径和实例
        db_path = ""
        db = None
        well_info = []
        if self.main_window:
            if hasattr(self.main_window, 'db_path') and self.main_window.db_path:
                db_path = self.main_window.db_path
            elif hasattr(self.main_window, 'db') and self.main_window.db and hasattr(self.main_window.db, 'db_path'):
                db_path = self.main_window.db.db_path
            elif hasattr(self.main_window, 'get_active_db'):
                try:
                    db_obj = self.main_window.get_active_db()
                    if db_obj and hasattr(db_obj, 'db_path'):
                        db_path = db_obj.db_path
                        db = db_obj
                except:
                    pass
            
            if not db and hasattr(self.main_window, 'db'):
                db = self.main_window.db

            if hasattr(self.main_window, 'get_all_well_info'):
                well_info = self.main_window.get_all_well_info()

        root = PathResolver.get_project_root()
        self.execution_context = {
            "__name__": "__main__",
            "__file__": os.path.join(root, "ai_terminal.py"),
            "db_path": db_path,
            "db": db,
            "app": self.main_window,
            "np": np,
            "DBManager": DBClass,
            "wells": well_info,
        }

    def _remember_editor(self, editor):
        if editor and hasattr(editor, "editor_id"):
            self._last_script_editor_id = editor.editor_id

    @staticmethod
    def _build_terminal_result(command, output, *, ok=True, stderr="", exit_code=0, mode="python"):
        stdout = output if ok else ""
        err_text = stderr or (output if not ok else "")
        combined = stdout.strip()
        if err_text.strip():
            combined = f"{combined}\n{err_text}".strip() if combined else err_text.strip()
        return {
            "ok": ok,
            "executed": True,
            "display_type": "terminal",
            "terminal_mode": mode,
            "command": command,
            "terminal": combined or "Done (No Output)",
            "stdout": stdout,
            "stderr": err_text,
            "exit_code": exit_code,
        }

    def _find_script_editor(self, editor_id=None, script_path=None, create_if_missing=False):
        if not self.main_window or not hasattr(self.main_window, "mdi_area"):
            return None, None

        normalized_path = os.path.abspath(script_path).lower() if script_path else None
        for sub in self.main_window.mdi_area.subWindowList():
            widget = sub.widget()
            if editor_id and getattr(widget, "editor_id", None) == editor_id:
                self.main_window.mdi_area.setActiveSubWindow(sub)
                return sub, widget
            if normalized_path and getattr(widget, "script_path", None):
                if os.path.abspath(widget.script_path).lower() == normalized_path:
                    self.main_window.mdi_area.setActiveSubWindow(sub)
                    return sub, widget

        if self._last_script_editor_id:
            for sub in self.main_window.mdi_area.subWindowList():
                widget = sub.widget()
                if getattr(widget, "editor_id", None) == self._last_script_editor_id:
                    self.main_window.mdi_area.setActiveSubWindow(sub)
                    return sub, widget

        sub = self.main_window.mdi_area.activeSubWindow()
        if sub and hasattr(sub.widget(), "set_code"):
            return sub, sub.widget()

        if create_if_missing and hasattr(self.main_window, "new_script_window"):
            self.main_window.new_script_window()
            sub = self.main_window.mdi_area.activeSubWindow()
            if sub and hasattr(sub.widget(), "set_code"):
                self._remember_editor(sub.widget())
                return sub, sub.widget()
        return None, None

    def _resolve_script_editor(self, editor_id=None, script_path=None):
        sub, editor = self._find_script_editor(
            editor_id=editor_id,
            script_path=script_path,
            create_if_missing=False,
        )
        if sub and editor:
            return sub, editor, None

        target_hint = editor_id or script_path or "current script editor"
        return None, None, (
            f"Unable to locate the target script editor for {target_hint}. "
            "If this is an existing script, open it first and reuse its editor_id instead of creating a new file."
        )
    
    @Slot(str)
    def _open_script(self, title):
        """在主线程中打开脚本编辑器"""
        try:
            if not self.main_window or not hasattr(self.main_window, "new_script_window"):
                result = {"error": "no main window"}
            else:
                self.main_window.new_script_window()
                sub = self.main_window.mdi_area.activeSubWindow() if hasattr(self.main_window, "mdi_area") else None
                if sub and title:
                    try:
                        sub.setWindowTitle(str(title))
                    except:
                        pass
                editor = sub.widget() if sub else None
                self._remember_editor(editor)
                result = {
                    "ok": True,
                    "editor_id": getattr(editor, "editor_id", None),
                    "window_title": sub.windowTitle() if sub else (title or "")
                }
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(str)
    def _open_script_file(self, filepath):
        """在主线程中打开已有的脚本文件"""
        try:
            if not self.main_window or not hasattr(self.main_window, "new_script_window"):
                result = {"error": "no main window"}
            else:
                # 处理相对路径，尝试在scripts_user目录下查找
                if not os.path.exists(filepath):
                    # 尝试在scripts_user目录下查找
                    alt_path = os.path.join("scripts_user", filepath)
                    if os.path.exists(alt_path):
                        filepath = alt_path
                    else:
                        result = {"error": f"File not found: {filepath} (also tried {alt_path})"}
                        self.tool_executed.emit(json.dumps(result))
                        return
                
                # 读取文件内容
                with open(filepath, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                
                # 检查是否已经打开了该文件
                target_abs = os.path.abspath(filepath).lower()
                if hasattr(self.main_window, "mdi_area"):
                    for sub in self.main_window.mdi_area.subWindowList():
                        widget = sub.widget()
                        # 检查 widget 是否有 script_path 属性且匹配
                        if hasattr(widget, "script_path") and widget.script_path:
                            existing_abs = os.path.abspath(widget.script_path).lower()
                            if existing_abs == target_abs:
                                # 已经打开，激活并刷新内容
                                self.main_window.mdi_area.setActiveSubWindow(sub)
                                self._remember_editor(widget)
                                if hasattr(widget, "set_code"):
                                    widget.set_code(script_content)
                                result = {"ok": True, "filepath": filepath, "editor_id": getattr(widget, "editor_id", None), "message": "Existing tab activated and updated"}
                                self.tool_executed.emit(json.dumps(result))
                                return

                # 创建新的脚本编辑器窗口
                self.main_window.new_script_window()
                sub = self.main_window.mdi_area.activeSubWindow() if hasattr(self.main_window, "mdi_area") else None
                
                if sub and hasattr(sub.widget(), "set_code"):
                    ed = sub.widget()
                    ed.set_code(script_content)
                    ed.script_path = filepath # 记录路径以便下次识别
                    sub.setWindowTitle(f"Script: {os.path.basename(filepath)}")
                    self._remember_editor(ed)
                    result = {"ok": True, "filepath": filepath, "editor_id": getattr(ed, "editor_id", None)}
                else:
                    result = {"error": "no script editor"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(object)
    def _set_script_code(self, payload):
        """在主线程中设置脚本代码"""
        try:
            if not self.main_window or not hasattr(self.main_window, "mdi_area"):
                result = {"error": "no main window"}
            else:
                if isinstance(payload, dict):
                    code = payload.get("code", "")
                    editor_id = payload.get("editor_id")
                else:
                    code = payload or ""
                    editor_id = None

                sub, ed, error = self._resolve_script_editor(editor_id=editor_id)
                if sub and hasattr(ed, "set_code"):
                    ed.set_code(code or "")
                    self._remember_editor(ed)
                    result = {"ok": True, "editor_id": getattr(ed, "editor_id", None)}
                else:
                    result = {"ok": False, "error": error or "no script editor"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(object)
    def _append_script_code(self, payload):
        """在主线程中追加脚本代码"""
        try:
            if not self.main_window or not hasattr(self.main_window, "mdi_area"):
                result = {"error": "no main window"}
            else:
                if isinstance(payload, dict):
                    code = payload.get("code", "")
                    editor_id = payload.get("editor_id")
                else:
                    code = payload or ""
                    editor_id = None

                sub, ed, error = self._resolve_script_editor(editor_id=editor_id)
                if sub and hasattr(ed, "get_code") and hasattr(ed, "set_code"):
                    current = ed.get_code()
                    add = code or ""
                    ed.set_code(current + ("\n" if current and add else "") + add)
                    self._remember_editor(ed)
                    result = {"ok": True, "editor_id": getattr(ed, "editor_id", None)}
                else:
                    result = {"ok": False, "error": error or "no script editor"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))

    @Slot(object, str)
    def _preview_script_code(self, payload, code):
        """主线程中触发代码预览"""
        try:
            if not self.main_window or not hasattr(self.main_window, "mdi_area"):
                result = {"error": "no main window"}
            else:
                if isinstance(payload, dict):
                    editor_id = payload.get("editor_id")
                    script_path = payload.get("script_path")
                else:
                    editor_id = None
                    script_path = payload

                found_sub = None
                widget = None
                if editor_id or script_path:
                    found_sub, widget = self._find_script_editor(
                        editor_id=editor_id,
                        script_path=script_path,
                        create_if_missing=False,
                    )
                            
                if found_sub:
                    self.main_window.mdi_area.setActiveSubWindow(found_sub)
                    widget = widget or found_sub.widget()
                    if hasattr(widget, "set_preview_code"):
                        widget.set_preview_code(code)
                        result = {
                            "ok": True,
                            "message": "Preview shown in editor",
                            "editor_id": getattr(widget, "editor_id", None),
                            "script_path": getattr(widget, "script_path", None),
                        }
                    else:
                        result = {"error": "Editor does not support preview"}
                else:
                    hint = script_path or editor_id or "target script editor"
                    result = {"ok": False, "error": f"{hint} is not currently open in an editor tab. Open it first to preview."}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))

    @Slot(object, object)
    def _run_script(self, code=None, script_path=None):
        """在主线程中运行 AI 专用终端中的代码 (支持直接传入代码或路径)"""
        try:
            import io
            import contextlib
            
            # 捕获输出
            f = io.StringIO()
            
            # 确定执行的代码
            exec_code = ""
            
            editor_id = None
            raw_code = code
            if isinstance(code, dict):
                editor_id = code.get("editor_id")
                raw_code = code.get("code")
                script_path = code.get("script_path") or script_path

            if raw_code:
                exec_code = raw_code
            elif editor_id:
                sub, editor = self._find_script_editor(editor_id=editor_id, create_if_missing=False)
                if editor and hasattr(editor, "get_code"):
                    exec_code = editor.get_code()
                    self._remember_editor(editor)
            elif script_path:
                # 优先从编辑器中读取代码 (为了支持预览模式下的运行)
                target_abs = os.path.abspath(script_path).lower()
                found_code = None
                if self.main_window and hasattr(self.main_window, "mdi_area"):
                    for sub in self.main_window.mdi_area.subWindowList():
                        widget = sub.widget()
                        if hasattr(widget, "script_path") and widget.script_path:
                            if os.path.abspath(widget.script_path).lower() == target_abs:
                                if hasattr(widget, "get_code"):
                                    found_code = widget.get_code()
                                    break
                
                if found_code is not None:
                    exec_code = found_code
                elif os.path.exists(script_path):
                    with open(script_path, "r", encoding="utf-8") as file:
                        exec_code = file.read()
                else:
                    exec_code = f"print('Error: Script file not found: {script_path}')"
            else:
                # 默认从 MDI 中读取代码 (兼容旧行为)
                if self.main_window and hasattr(self.main_window, "mdi_area"):
                    sub = self.main_window.mdi_area.activeSubWindow()
                    if sub and hasattr(sub.widget(), "get_code"):
                        exec_code = sub.widget().get_code()
            
            if not exec_code:
                result = {"error": "No active script code or path to run"}
            else:
                # 注入当前的 db_path 等状态（防止主窗口状态变化）
                if self.main_window:
                    if hasattr(self.main_window, 'db_path'):
                        self.execution_context["db_path"] = self.main_window.db_path
                    if hasattr(self.main_window, 'db'):
                        self.execution_context["db"] = self.main_window.db
                
                # 运行前清理 Matplotlib，防止图形窗口堆积导致崩溃
                try:
                    import matplotlib.pyplot as plt
                    plt.close('all')
                except:
                    pass
                
                # 设置 print 重定向
                self.execution_context["print"] = lambda *args, **kwargs: print(*args, file=f, **kwargs)
                
                try:
                    # 拦截脚本中的 sys.exit() 以防止其关闭整个 PyLog 进程
                    import sys
                    _orig_exit = sys.exit
                    def _intercepted_exit(*args, **kwargs):
                        msg = f"INFO: Script called sys.exit({args}) - Intercepted to keep PyLog alive."
                        print(msg, file=f)
                    sys.exit = _intercepted_exit
                    
                    try:
                        with contextlib.redirect_stdout(f):
                            exec(exec_code, self.execution_context)
                    finally:
                        sys.exit = _orig_exit
                        
                    output = f.getvalue()
                    status = "ok"
                except Exception as cmd_error:
                    output = f"{f.getvalue()}\nError: {cmd_error}"
                    status = "error"
                
                # 记录到历史
                hist_header = f">>> [Run Script: {script_path if script_path else 'Direct Code' if code else 'MDI'}]\n"
                self.terminal_history.append(f"{hist_header}{output}")
                
                # 限制历史大小
                if len(self.terminal_history) > 100:
                    self.terminal_history = self.terminal_history[-100:]
                    
                command_label = f"Run Script: {script_path if script_path else 'Direct Code' if code else 'MDI'}"
                result = self._build_terminal_result(
                    command_label,
                    output if status == "ok" else "",
                    ok=status == "ok",
                    stderr=output if status == "error" else "",
                    exit_code=0 if status == "ok" else 1,
                    mode="python",
                )
                result["summary"] = "Script executed successfully" if status == "ok" else "Script execution failed"
                if status == "error":
                    result["error"] = "Script execution failed"
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(object)
    def _save_script(self, payload):
        """在主线程中保存脚本"""
        try:
            if not self.main_window or not hasattr(self.main_window, "mdi_area"):
                result = {"error": "no main window"}
            else:
                if isinstance(payload, dict):
                    filename = payload.get("filename")
                    editor_id = payload.get("editor_id")
                else:
                    filename = payload
                    editor_id = None
                sub, ed = self._find_script_editor(editor_id=editor_id, create_if_missing=False)
                if not sub or not hasattr(ed, "save_code"):
                    result = {"error": "no active script editor"}
                else:
                    success = ed.save_code(filename)
                    if success:
                        self._remember_editor(ed)
                        result = {"ok": True, "filepath": success if isinstance(success, str) else getattr(ed, "script_path", None), "editor_id": getattr(ed, "editor_id", None)}
                    else:
                        result = {"error": "save failed"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))

    @Slot(object)
    def _get_script_state(self, payload):
        try:
            if isinstance(payload, dict):
                editor_id = payload.get("editor_id")
                script_path = payload.get("script_path")
            else:
                editor_id = None
                script_path = payload

            sub, editor, error = self._resolve_script_editor(editor_id=editor_id, script_path=script_path)
            if not editor or not hasattr(editor, "get_script_state"):
                result = {"ok": False, "error": error or "no script editor"}
            else:
                self._remember_editor(editor)
                state = editor.get_script_state()
                result = {"ok": True, **state}
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        self.tool_executed.emit(json.dumps(result))
    
    @Slot()
    def _get_terminal(self):
        """在主线程中获取 AI 专用终端内容"""
        try:
            # 返回最近的输出记录
            content = "\n".join(self.terminal_history[-20:]) if self.terminal_history else "Terminal is empty."
            result = {
                "ok": True,
                "display_type": "terminal",
                "terminal_mode": "history",
                "terminal": content,
                "summary": "Current terminal history",
            }
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(str)
    def _run_terminal_command(self, command):
        """在主线程中执行 AI 专用终端命令（解耦 MDI）"""
        try:
            import io
            import contextlib
            
            # 捕获输出
            f = io.StringIO()
            
            # 注入当前的 db_path 等状态（防止主窗口状态变化）
            if self.main_window:
                if hasattr(self.main_window, 'db_path'):
                    self.execution_context["db_path"] = self.main_window.db_path
                if hasattr(self.main_window, 'db'):
                    self.execution_context["db"] = self.main_window.db
            
            # 设置 print 重定向
            self.execution_context["print"] = lambda *args, **kwargs: print(*args, file=f, **kwargs)
            
            try:
                with contextlib.redirect_stdout(f):
                    exec(command, self.execution_context)
                output = f.getvalue()
                status = "ok"
            except Exception as cmd_error:
                output = f"{f.getvalue()}\nError: {cmd_error}"
                status = "error"
            
            # 记录到历史
            self.terminal_history.append(f">>> {command}\n{output}")
            
            # 限制历史大小
            if len(self.terminal_history) > 100:
                self.terminal_history = self.terminal_history[-100:]
                
            result = self._build_terminal_result(
                command,
                output if status == "ok" else "",
                ok=status == "ok",
                stderr=output if status == "error" else "",
                exit_code=0 if status == "ok" else 1,
                mode="python",
            )
            result["summary"] = "Terminal command executed successfully" if status == "ok" else "Command execution failed"
            if status == "error":
                result["error"] = "Command execution failed"

        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(str)
    def _plot_from_db(self, plot_data_json):
        """在主线程中执行从数据库绘图操作"""
        try:
            import json
            plot_data = json.loads(plot_data_json)
            
            from pylog_api import plot_from_db
            result = plot_from_db(
                well=plot_data.get("well"),
                curves=plot_data.get("curves") or plot_data.get("curve_names"),
                db_path=plot_data.get("db_path"),
                title=plot_data.get("title", "AI Generated Plot"),
                colors=plot_data.get("colors"),
                line_widths=plot_data.get("line_widths"),
                line_styles=plot_data.get("line_styles"),
                v_mins=plot_data.get("v_mins"),
                v_maxs=plot_data.get("v_maxs"),
                track=plot_data.get("track"),
                fill_to=plot_data.get("fill_to"),
                fill_colors=plot_data.get("fill_colors"),
                fill_alphas=plot_data.get("fill_alphas"),
                titles=plot_data.get("titles"),
                colormap=plot_data.get("colormap", "thermal"),
                invert_colormap=plot_data.get("invert_colormap", False),
                accum_fill=plot_data.get("accum_fill", False),
                show_ai_chat=False,
                show_scripts=False,
                block=False
            )
            
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"error": str(e)}))
    
    @Slot(str)
    def _plot_data(self, plot_data_json):
        """在主线程中执行数据绘图操作"""
        try:
            import json
            plot_data = json.loads(plot_data_json)
            
            from pylog_api import plot_log_curves
            result = plot_log_curves(
                plot_data["data_list"],
                title=plot_data.get("title", "AI Generated Plot"),
                accum_fill=plot_data.get("accum_fill", False),
                fill_to=plot_data.get("fill_to"),
                fill_colors=plot_data.get("fill_colors"),
                fill_alphas=plot_data.get("fill_alphas"),
                titles=plot_data.get("titles"),
                show_ai_chat=False,
                show_scripts=False,
                block=False
            )
            
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"error": str(e)}))

    @Slot(str)
    def _plot(self, plot_data_json):
        """统一绘图入口"""
        try:
            plot_data = json.loads(plot_data_json)
            from pylog_api import plot
            
            # 移除 None 值以使用 API 默认值
            clean_params = {k: v for k, v in plot_data.items() if v is not None}
            clean_params['show_ai_chat'] = False
            clean_params['show_scripts'] = False
            clean_params['block'] = False
            
            result = plot(**clean_params)
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _save_curve(self, save_data_json):
        """保存曲线并刷新 UI"""
        try:
            save_data = json.loads(save_data_json)
            from pylog_api import save_curve
            
            result = save_curve(
                well=save_data.get("well"),
                curve_name=save_data.get("curve_name"),
                values=save_data.get("values"),
                unit=save_data.get("unit", ""),
                folder=save_data.get("folder"),
                db_path=save_data.get("db_path")
            )
            
            # 如果保存成功，尝试刷新主界面井目录树
            if result.get("ok") and self.main_window:
                if hasattr(self.main_window, "tree_controller"):
                    self.main_window.tree_controller.refresh_tree()
                elif hasattr(self.main_window, "refresh_well_list"):
                    self.main_window.refresh_well_list()
            
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _get_plot_details(self, title):
        """在主线程中获取指定绘图窗口的详细信息"""
        try:
            if not self.main_window or not hasattr(self.main_window, "mdi_area"):
                result = {"error": "no main window or mdi area"}
            else:
                found = False
                for sub in self.main_window.mdi_area.subWindowList():
                    curr_title = sub.windowTitle()
                    # Support both exact match and prefix-less match
                    if curr_title == title or curr_title == f"Plot: {title}" or curr_title == f"Log Plot {title}":
                        widget = sub.widget()
                        if hasattr(widget, "get_plot_details"):
                            result = {"ok": True, "details": widget.get_plot_details()}
                        else:
                            result = {"error": f"Window '{curr_title}' exists but is not a valid plot window"}
                        found = True
                        break
                
                if not found:
                    result = {"error": f"Plot window with title '{title}' not found"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))
