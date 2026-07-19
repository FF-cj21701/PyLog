import os
import sys
import json
import base64
from PySide6.QtCore import QObject, Signal, Slot, Qt

# Add the plugin root dynamically so internal imports remain robust.
_plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

try:
    from ..common.paths import PathResolver
except ImportError:
    # Fallback for unusual import layouts.
    try:
        from plugins.ai_assistant.common.paths import PathResolver
    except ImportError:
        PathResolver = None

try:
    from ..ui.widgets.agent_page_host import close_agent_page, open_agent_page
except ImportError:
    try:
        from plugins.ai_assistant.ui.widgets.agent_page_host import close_agent_page, open_agent_page
    except ImportError:
        close_agent_page = None
        open_agent_page = None

try:
    from ..runtime.script_job_manager import get_script_job_manager
except ImportError:
    try:
        from plugins.ai_assistant.runtime.script_job_manager import get_script_job_manager
    except ImportError:
        get_script_job_manager = None

try:
    from ..runtime.ui_action_executor import UiActionExecutor
except ImportError:
    try:
        from plugins.ai_assistant.runtime.ui_action_executor import UiActionExecutor
    except ImportError:
        UiActionExecutor = None

try:
    from scripts.ui.widgets.html_preview_widget import HtmlPreviewWidget, is_html_previewable
except ImportError:
    HtmlPreviewWidget = None
    is_html_previewable = None

class ToolExecutor(QObject):
    """Execute UI-bound tool operations on the main thread."""
    
    # Command signals.
    execute_open_script = Signal(str)
    execute_open_script_file = Signal(str)
    execute_open_html_preview = Signal(str)
    execute_set_script_code = Signal(object)
    execute_append_script_code = Signal(object)
    execute_preview_script_code = Signal(object, str) # payload(filepath/editor_id), code
    execute_run_script = Signal(object, object)  # (code, script_path)
    execute_get_script_job = Signal(object)
    execute_save_script = Signal(object)
    execute_get_script_state = Signal(object)
    execute_open_agent_page = Signal(object)
    execute_update_agent_page = Signal(object)
    execute_close_agent_page = Signal(object)
    execute_get_terminal = Signal()
    execute_run_terminal_command = Signal(str)
    execute_plot_from_db = Signal(str)  # JSON payload.
    execute_plot_data = Signal(str)     # JSON payload.
    execute_plot = Signal(str)          # Unified plotting signal.
    execute_create_plot = Signal(str)
    execute_update_plot = Signal(str)
    execute_apply_curve_style = Signal(str)
    execute_apply_track_style = Signal(str)
    execute_save_curve = Signal(str)    # Curve save signal.
    execute_get_plot_details = Signal(str) # Window title payload.
    execute_render_analysis_tracks = Signal(str)  # JSON render request.
    execute_apply_fracture_detection_results = Signal(str)  # JSON result batch.
    
    # Result signals.
    tool_executed = Signal(str)
    
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        
        # Connect signals and slots.
        self.execute_open_script.connect(self._open_script)
        self.execute_open_script_file.connect(self._open_script_file)
        self.execute_open_html_preview.connect(self._open_html_preview)
        self.execute_set_script_code.connect(self._set_script_code)
        self.execute_append_script_code.connect(self._append_script_code)
        self.execute_preview_script_code.connect(self._preview_script_code)
        self.execute_run_script.connect(self._run_script)
        self.execute_get_script_job.connect(self._get_script_job)
        self.execute_save_script.connect(self._save_script)
        self.execute_get_script_state.connect(self._get_script_state)
        self.execute_open_agent_page.connect(self._open_agent_page)
        self.execute_update_agent_page.connect(self._update_agent_page)
        self.execute_close_agent_page.connect(self._close_agent_page)
        self.execute_get_terminal.connect(self._get_terminal)
        self.execute_run_terminal_command.connect(self._run_terminal_command)
        self.execute_plot_from_db.connect(self._plot_from_db)
        self.execute_plot_data.connect(self._plot_data)
        self.execute_plot.connect(self._plot)
        self.execute_create_plot.connect(self._create_plot)
        self.execute_update_plot.connect(self._update_plot)
        self.execute_apply_curve_style.connect(self._apply_curve_style)
        self.execute_apply_track_style.connect(self._apply_track_style)
        self.execute_save_curve.connect(self._save_curve)
        self.execute_get_plot_details.connect(self._get_plot_details)
        self.execute_render_analysis_tracks.connect(self._render_analysis_tracks)
        self.execute_apply_fracture_detection_results.connect(self._apply_fracture_detection_results)
        self.execution_context = {}
        self.terminal_history = []
        self._last_script_editor_id = None
        self._init_ai_context()
    
    def _init_ai_context(self):
        """Initialize the dedicated AI execution context."""
        import numpy as np
        from scripts.data.db_manager import DBManager as DBClass
        
        # Try to capture the current database path and instance.
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
        """Open the script editor on the main thread."""
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
        """Open an existing script file on the main thread."""
        try:
            if not self.main_window or not hasattr(self.main_window, "new_script_window"):
                result = {"error": "no main window"}
            else:
                # Resolve relative paths, preferring scripts_user when applicable.
                if not os.path.exists(filepath):
                    # Try scripts_user as a convenience lookup root.
                    alt_path = os.path.join("scripts_user", filepath)
                    if os.path.exists(alt_path):
                        filepath = alt_path
                    else:
                        result = {"error": f"File not found: {filepath} (also tried {alt_path})"}
                        self.tool_executed.emit(json.dumps(result))
                        return
                
                # Read file content.
                with open(filepath, 'r', encoding='utf-8') as f:
                    script_content = f.read()
                
                # Reuse an existing editor if the file is already open.
                target_abs = os.path.abspath(filepath).lower()
                if hasattr(self.main_window, "mdi_area"):
                    for sub in self.main_window.mdi_area.subWindowList():
                        widget = sub.widget()
                        # Match widgets by script_path when available.
                        if hasattr(widget, "script_path") and widget.script_path:
                            existing_abs = os.path.abspath(widget.script_path).lower()
                            if existing_abs == target_abs:
                                # Activate the existing editor and refresh its content.
                                self.main_window.mdi_area.setActiveSubWindow(sub)
                                self._remember_editor(widget)
                                if hasattr(widget, "set_code"):
                                    widget.set_code(script_content)
                                result = {"ok": True, "filepath": filepath, "editor_id": getattr(widget, "editor_id", None), "message": "Existing tab activated and updated"}
                                self.tool_executed.emit(json.dumps(result))
                                return

                # Create a new script editor window.
                self.main_window.new_script_window()
                sub = self.main_window.mdi_area.activeSubWindow() if hasattr(self.main_window, "mdi_area") else None
                
                if sub and hasattr(sub.widget(), "set_code"):
                    ed = sub.widget()
                    ed.set_code(script_content)
                    ed.script_path = filepath # Store the path for later matching.
                    sub.setWindowTitle(f"Script: {os.path.basename(filepath)}")
                    self._remember_editor(ed)
                    result = {"ok": True, "filepath": filepath, "editor_id": getattr(ed, "editor_id", None)}
                else:
                    result = {"error": "no script editor"}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))

    @Slot(str)
    def _open_html_preview(self, filepath):
        """Open a local HTML file in the workspace preview surface."""
        try:
            if not self.main_window or not hasattr(self.main_window, "mdi_area"):
                result = {"ok": False, "error": "no main window"}
            elif not HtmlPreviewWidget or not is_html_previewable:
                result = {"ok": False, "error": "html preview widget is unavailable"}
            else:
                resolved_path = filepath
                if not os.path.exists(resolved_path):
                    if PathResolver and not os.path.isabs(resolved_path):
                        alt_path = os.path.join(PathResolver.get_project_root(), resolved_path)
                        if os.path.exists(alt_path):
                            resolved_path = alt_path
                    if not os.path.exists(resolved_path):
                        result = {"ok": False, "error": f"File not found: {filepath}"}
                        self.tool_executed.emit(json.dumps(result))
                        return

                resolved_path = os.path.abspath(resolved_path)
                if not is_html_previewable(resolved_path):
                    result = {
                        "ok": False,
                        "error": f"Unsupported HTML preview file type: {resolved_path}",
                    }
                    self.tool_executed.emit(json.dumps(result))
                    return

                target_abs = resolved_path.lower()
                for sub in self.main_window.mdi_area.subWindowList():
                    widget = sub.widget()
                    if isinstance(widget, HtmlPreviewWidget) and getattr(widget, "file_path", None):
                        existing_abs = os.path.abspath(widget.file_path).lower()
                        if existing_abs == target_abs:
                            widget.load_file(resolved_path)
                            self.main_window.mdi_area.setActiveSubWindow(sub)
                            sub.setWindowTitle(f"HTML: {os.path.basename(resolved_path)}")
                            sub.show()
                            result = {
                                "ok": True,
                                "filepath": resolved_path,
                                "window_title": sub.windowTitle(),
                                "view": "html_preview",
                                "message": "Existing HTML preview focused",
                            }
                            self.tool_executed.emit(json.dumps(result))
                            return

                widget = HtmlPreviewWidget(resolved_path, parent=self.main_window)
                widget.openSourceRequested.connect(self.execute_open_script_file.emit)
                sub = self.main_window.mdi_area.addSubWindow(widget)
                if hasattr(sub, "setAttribute"):
                    sub.setAttribute(Qt.WA_DeleteOnClose)
                sub.setWindowTitle(f"HTML: {os.path.basename(resolved_path)}")
                sub.show()
                self.main_window.mdi_area.setActiveSubWindow(sub)
                if hasattr(self.main_window, "_update_workspace_launchpad_visibility"):
                    self.main_window._update_workspace_launchpad_visibility()
                result = {
                    "ok": True,
                    "filepath": resolved_path,
                    "window_title": sub.windowTitle(),
                    "view": "html_preview",
                    "message": "HTML preview opened",
                }
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        self.tool_executed.emit(json.dumps(result))
    
    @Slot(object)
    def _set_script_code(self, payload):
        """Set script code on the main thread."""
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
        """Append script code on the main thread."""
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
        """Trigger script draft/review handling on the main thread."""
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
                    if hasattr(widget, "start_preview_session"):
                        widget.start_preview_session(code, source="ai_preview")
                    elif hasattr(widget, "set_preview_code"):
                        widget.set_preview_code(code)
                    else:
                        result = {"error": "Editor does not support preview"}
                        self.tool_executed.emit(json.dumps(result))
                        return
                    result = {
                        "ok": True,
                        "message": "Draft applied to editor; review is available",
                        "editor_id": getattr(widget, "editor_id", None),
                        "script_path": getattr(widget, "script_path", None),
                    }
                else:
                    hint = script_path or editor_id or "target script editor"
                    result = {"ok": False, "error": f"{hint} is not currently open in an editor tab. Open it first to preview."}
        except Exception as e:
            result = {"error": str(e)}
        
        self.tool_executed.emit(json.dumps(result))

    @Slot(object, object)
    def _run_script(self, code=None, script_path=None):
        """Run code in the dedicated AI terminal on the main thread."""
        try:
            import io
            import contextlib
            
            # Capture output.
            f = io.StringIO()
            
            # Determine the code to execute.
            exec_code = ""
            
            editor_id = None
            raw_code = code
            if isinstance(code, dict):
                editor_id = code.get("editor_id")
                raw_code = code.get("code")
                script_path = code.get("script_path") or script_path
                execution_mode = code.get("execution_mode") or "quick"
                timeout_seconds = code.get("timeout_seconds")
            else:
                execution_mode = "quick"
                timeout_seconds = None

            if raw_code:
                exec_code = raw_code
            elif editor_id:
                sub, editor = self._find_script_editor(editor_id=editor_id, create_if_missing=False)
                if editor and hasattr(editor, "get_code"):
                    exec_code = editor.get_code()
                    self._remember_editor(editor)
            elif script_path:
                # Prefer editor code so draft/review execution uses the current workspace.
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
                # Fall back to reading code from the MDI editor for legacy behavior.
                if self.main_window and hasattr(self.main_window, "mdi_area"):
                    sub = self.main_window.mdi_area.activeSubWindow()
                    if sub and hasattr(sub.widget(), "get_code"):
                        exec_code = sub.widget().get_code()
            
            if not exec_code:
                result = {"error": "No active script code or path to run"}
            elif execution_mode != "legacy_in_process":
                if not get_script_job_manager:
                    result = {"ok": False, "error": "ScriptJobManager is unavailable"}
                else:
                    db_path = ""
                    wells = []
                    if self.main_window:
                        if hasattr(self.main_window, "db_path") and self.main_window.db_path:
                            db_path = self.main_window.db_path
                        elif hasattr(self.main_window, "db") and self.main_window.db and hasattr(self.main_window.db, "db_path"):
                            db_path = self.main_window.db.db_path
                        if hasattr(self.main_window, "get_all_well_info"):
                            try:
                                wells = self.main_window.get_all_well_info()
                            except Exception:
                                wells = []
                    manager = get_script_job_manager(PathResolver.get_project_root() if PathResolver else None)
                    if UiActionExecutor:
                        manager.set_ui_action_executor(UiActionExecutor(main_window=self.main_window))
                    result = manager.run_script(
                        code=exec_code,
                        script_path=script_path,
                        db_path=db_path,
                        wells=wells,
                        execution_mode=execution_mode,
                        timeout_seconds=timeout_seconds,
                    )
                    output = result.get("stdout") or result.get("terminal") or ""
                    hist_header = f">>> [Run Script: {script_path if script_path else 'Direct Code' if code else 'MDI'}]\n"
                    self.terminal_history.append(f"{hist_header}{output}")
                    if len(self.terminal_history) > 100:
                        self.terminal_history = self.terminal_history[-100:]
                    result.setdefault("executed", True)
                    result.setdefault("display_type", "terminal")
                    result.setdefault("terminal_mode", "python")
                    result.setdefault("terminal", (result.get("stdout") or result.get("stderr") or "").strip() or result.get("summary"))
            else:
                # Inject current db_path state to avoid main-window state drift.
                if self.main_window:
                    if hasattr(self.main_window, 'db_path'):
                        self.execution_context["db_path"] = self.main_window.db_path
                    if hasattr(self.main_window, 'db'):
                        self.execution_context["db"] = self.main_window.db
                
                # Clear Matplotlib state before running to avoid accumulated GUI figures.
                try:
                    import matplotlib.pyplot as plt
                    plt.close('all')
                except:
                    pass
                
                # Redirect print output.
                self.execution_context["print"] = lambda *args, **kwargs: print(*args, file=f, **kwargs)
                
                try:
                    # Intercept sys.exit() so user scripts cannot close the PyLog process.
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
                
                # Record output history.
                hist_header = f">>> [Run Script: {script_path if script_path else 'Direct Code' if code else 'MDI'}]\n"
                self.terminal_history.append(f"{hist_header}{output}")
                
                # Limit history size.
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
    def _get_script_job(self, payload):
        try:
            if not get_script_job_manager:
                result = {"ok": False, "error": "ScriptJobManager is unavailable"}
            else:
                job_id = payload.get("job_id") if isinstance(payload, dict) else payload
                manager = get_script_job_manager(PathResolver.get_project_root() if PathResolver else None)
                if UiActionExecutor:
                    manager.set_ui_action_executor(UiActionExecutor(main_window=self.main_window))
                result = manager.get_job(job_id)
        except Exception as e:
            result = {"ok": False, "error": str(e)}
        self.tool_executed.emit(json.dumps(result))
    
    @Slot(object)
    def _save_script(self, payload):
        """Save a script on the main thread."""
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

    @Slot(object)
    def _open_agent_page(self, payload):
        self._show_agent_page(payload, create_mode=True)

    @Slot(object)
    def _update_agent_page(self, payload):
        self._show_agent_page(payload, create_mode=False)

    def _show_agent_page(self, payload, create_mode):
        try:
            if not open_agent_page or not self.main_window:
                result = {"ok": False, "error": "agent page host is unavailable"}
            elif not isinstance(payload, dict):
                result = {"ok": False, "error": "payload must be an object"}
            else:
                page_id = str(payload.get("page_id") or "").strip()
                if not page_id:
                    result = {"ok": False, "error": "page_id is required"}
                else:
                    mode = str(payload.get("mode") or "mdi").strip().lower()
                    title = str(payload.get("title") or page_id).strip() or page_id
                    template = str(payload.get("template") or "agent_page_template.html").strip()
                    size = payload.get("size") or (980, 720)
                    page_payload = payload.get("payload")
                    if not isinstance(page_payload, dict):
                        page_payload = {
                            "title": payload.get("headline") or title,
                            "summary": payload.get("summary") or "",
                            "content_title": payload.get("content_title") or "Content",
                            "content": payload.get("content") or "",
                            "format": payload.get("format") or "text",
                            "eyebrow": payload.get("eyebrow") or "Agent Workspace",
                            "meta": payload.get("meta") or [],
                            "sections": payload.get("sections") or [],
                        }
                    page = open_agent_page(
                        page_id=page_id,
                        title=title,
                        template=template,
                        payload=page_payload,
                        mode=mode,
                        size=tuple(size) if isinstance(size, (list, tuple)) and len(size) == 2 else (980, 720),
                        parent=self.main_window,
                    )
                    result = {
                        "ok": True,
                        "page_id": page_id,
                        "title": title,
                        "mode": mode,
                        "template": template,
                        "message": "Agent page opened" if create_mode else "Agent page updated",
                        "page_mode": getattr(page, "page_mode", mode),
                    }
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        self.tool_executed.emit(json.dumps(result))

    @Slot(object)
    def _close_agent_page(self, payload):
        try:
            if not close_agent_page or not self.main_window:
                result = {"ok": False, "error": "agent page host is unavailable"}
            elif not isinstance(payload, dict):
                result = {"ok": False, "error": "payload must be an object"}
            else:
                page_id = str(payload.get("page_id") or "").strip()
                if not page_id:
                    result = {"ok": False, "error": "page_id is required"}
                else:
                    closed = close_agent_page(page_id, parent=self.main_window)
                    result = {
                        "ok": bool(closed),
                        "page_id": page_id,
                        "message": "Agent page closed" if closed else "Agent page not found",
                    }
        except Exception as e:
            result = {"ok": False, "error": str(e)}

        self.tool_executed.emit(json.dumps(result))
    
    @Slot()
    def _get_terminal(self):
        """Return dedicated AI terminal content from the main thread."""
        try:
            # Return recent output history.
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
        """Execute a dedicated AI terminal command on the main thread."""
        try:
            import io
            import contextlib
            
            # Capture output.
            f = io.StringIO()
            
            # Inject current db_path state to avoid main-window state drift.
            if self.main_window:
                if hasattr(self.main_window, 'db_path'):
                    self.execution_context["db_path"] = self.main_window.db_path
                if hasattr(self.main_window, 'db'):
                    self.execution_context["db"] = self.main_window.db
            
            # Redirect print output.
            self.execution_context["print"] = lambda *args, **kwargs: print(*args, file=f, **kwargs)
            
            try:
                with contextlib.redirect_stdout(f):
                    exec(command, self.execution_context)
                output = f.getvalue()
                status = "ok"
            except Exception as cmd_error:
                output = f"{f.getvalue()}\nError: {cmd_error}"
                status = "error"
            
            # Record output history.
            self.terminal_history.append(f">>> {command}\n{output}")
            
            # Limit history size.
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
        """Execute database-backed plotting on the main thread."""
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
        """Execute data plotting on the main thread."""
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
        """Unified plotting entry point."""
        try:
            plot_data = json.loads(plot_data_json)
            from pylog_api import plot
            
            # Drop None values so API defaults can apply.
            clean_params = {k: v for k, v in plot_data.items() if v is not None}
            clean_params['show_ai_chat'] = False
            clean_params['show_scripts'] = False
            clean_params['block'] = False
            
            result = plot(**clean_params)
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _create_plot(self, payload_json):
        try:
            payload = json.loads(payload_json)
            from pylog_api import create_plot

            result = create_plot(payload.get("plot_spec"))
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _update_plot(self, payload_json):
        try:
            payload = json.loads(payload_json)
            from pylog_api import update_plot

            result = update_plot(
                window_id=payload.get("window_id"),
                commands=payload.get("commands"),
            )
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _apply_curve_style(self, payload_json):
        try:
            payload = json.loads(payload_json)
            from pylog_api import apply_curve_style

            result = apply_curve_style(
                payload.get("window_id"),
                payload.get("track"),
                payload.get("curve"),
                payload.get("settings"),
            )
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _apply_track_style(self, payload_json):
        try:
            payload = json.loads(payload_json)
            from pylog_api import apply_track_style

            result = apply_track_style(
                payload.get("window_id"),
                payload.get("track"),
                payload.get("settings"),
            )
            self.tool_executed.emit(json.dumps(result))
        except Exception as e:
            self.tool_executed.emit(json.dumps({"ok": False, "error": str(e)}))

    @Slot(str)
    def _save_curve(self, save_data_json):
        """Save a curve and refresh the UI."""
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
            
            # Refresh the main well tree after a successful save.
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
        """Get details for a plotting window on the main thread."""
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

    def _find_plot_widget(self, title):
        if not self.main_window or not hasattr(self.main_window, "mdi_area"):
            return None
        for sub in self.main_window.mdi_area.subWindowList():
            current = sub.windowTitle()
            if current == title or current == f"Plot: {title}" or current == f"Log Plot {title}":
                return sub.widget()
        return None

    @Slot(str)
    def _render_analysis_tracks(self, payload_json):
        try:
            payload = json.loads(payload_json)
            widget = self._find_plot_widget(payload.get("window_id"))
            if widget is None or not hasattr(widget, "render_analysis_tracks"):
                result = {"ok": False, "error": f"Plot window '{payload.get('window_id')}' was not found"}
            else:
                rendered = widget.render_analysis_tracks(
                    payload.get("tracks"),
                    payload.get("depth_start"),
                    payload.get("depth_end"),
                    width=payload.get("width", 1600),
                    height=payload.get("height", 1600),
                      include_depth_track=bool(payload.get("include_depth_track", False)),
                      preserve_aspect=bool(payload.get("preserve_aspect", False)),
                      respect_current_vertical_scale=bool(payload.get("respect_current_vertical_scale", False)),
                      vertical_scale=float(payload.get("vertical_scale", 1.0)),
                  )
                result = {
                    "ok": True,
                    "metadata": rendered["metadata"],
                    "data_url": "data:image/png;base64," + base64.b64encode(rendered["png_bytes"]).decode("ascii"),
                }
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self.tool_executed.emit(json.dumps(result))

    @Slot(str)
    def _apply_fracture_detection_results(self, payload_json):
        try:
            payload = json.loads(payload_json)
            widget = self._find_plot_widget(payload.get("window_id"))
            if widget is None or not hasattr(widget, "start_ai_fracture_playback"):
                result = {"ok": False, "error": f"Plot window '{payload.get('window_id')}' was not found"}
            else:
                result = widget.start_ai_fracture_playback(
                    payload.get("run_id"),
                    payload.get("target_image_track"),
                    payload.get("annotations") or [],
                )
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        self.tool_executed.emit(json.dumps(result))
