import os
import json
import datetime
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtCore import QUrl, QObject, Slot, Signal
from PySide6.QtWidgets import QMenu
from scripts.data.db_manager import DBManager

from ...ai_core.tool_result import tool_result_content, tool_result_summary, tool_result_to_dict

class WebChatBridge(QObject):
    """Bridge for JavaScript to call Python."""
    
    # Signals to notify Python widget
    messageSent = Signal(str)
    modeToggled = Signal()
    settingsRequested = Signal()
    chatCleared = Signal()
    messageCardActionRequested = Signal(str)
    updateChatContexts = Signal(str)  # 新增：同步JS侧的气泡上下文
    webReady = Signal() # New signal to indicate page is loaded
    
    def __init__(self, parent=None):
        super().__init__(parent)
    
    @Slot(str)
    def log(self, msg):
        if msg == "Web interface ready":
            self.webReady.emit()
        pass

    @Slot(str)
    def sendMessage(self, text):
        self.messageSent.emit(text)

    @Slot()
    def toggleMode(self):
        self.modeToggled.emit()

    @Slot()
    def openSettings(self):
        self.settingsRequested.emit()

    @Slot()
    def clearChat(self):
        self.chatCleared.emit()

    @Slot(str)
    def onUpdateChatContexts(self, contexts_json):
        """接收来自JS的上下文同步请求"""
        self.updateChatContexts.emit(contexts_json)

    @Slot(str)
    def onMessageCardAction(self, payload_json):
        self.messageCardActionRequested.emit(payload_json)

    @Slot(result=list)
    def getProjectFiles(self):
        """获取项目文件列表 (限制在白名单内)"""
        # 从环境变量获取白名单
        whitelist_str = os.environ.get('PYLOG_TOOL_WHITELIST', '')
        if not whitelist_str:
            return []
            
        whitelist = whitelist_str.split(';')
        
        # 获取项目根目录，假设它是插件目录向上三级
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        project_root = os.path.dirname(os.path.dirname(plugin_dir))
        
        file_list = []
        exclude_dirs = {'.git', '.venv', '__pycache__', '.pytest_cache', '.idea', '.vscode', 'build', 'dist'}
        exclude_exts = {'.pyc', '.pyo', '.exe', '.dll', '.so', '.pyd', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar', '.gz'}

        for w in whitelist:
            if not w: continue
            w_path = os.path.normpath(os.path.abspath(w))
            
            # 如果路径不存在则跳过
            if not os.path.exists(w_path):
                continue
                
            # 如果是具体文件
            if os.path.isfile(w_path):
                rel_path = os.path.relpath(w_path, project_root)
                file_list.append(rel_path.replace('\\', '/'))
                continue
                
            # 如果是目录，递归扫描
            for root, dirs, files in os.walk(w_path):
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                for file in files:
                    ext = os.path.splitext(file)[1].lower()
                    if ext not in exclude_exts:
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, project_root)
                        file_list.append(rel_path.replace('\\', '/'))
        
        return sorted(list(set(file_list)))

    @Slot(str, result=str)
    def readFileContent(self, rel_path):
        """读取文件内容 (增加白名单检查)"""
        # 获取项目根目录
        plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        project_root = os.path.dirname(os.path.dirname(plugin_dir))
        abs_path = os.path.normpath(os.path.abspath(os.path.join(project_root, rel_path)))
        
        # 安全性检查：白名单
        whitelist_str = os.environ.get('PYLOG_TOOL_WHITELIST', '')
        whitelist = whitelist_str.split(';')
        
        allowed = False
        abs_path_lower = abs_path.lower()
        for w in whitelist:
            if not w: continue
            w_norm = os.path.normpath(os.path.abspath(w)).lower()
            if abs_path_lower.startswith(w_norm + os.sep) or abs_path_lower == w_norm:
                allowed = True
                break
                
        if not allowed:
            return f"Error: Access denied (Security). File '{rel_path}' is not in whitelist."
        
        if not os.path.exists(abs_path):
            return f"Error: File not found - {rel_path}"
            
        try:
            with open(abs_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file {rel_path}: {str(e)}"

    @Slot(result=str)
    def getOpenedWindowsInfo(self):
        """获取所有已打开的窗口信息"""
        main_window = None
        widget = self.parent()
        while widget:
            if hasattr(widget, "mdi_area") and hasattr(widget, "new_script_window"):
                main_window = widget
                break
            if hasattr(widget, "parentWidget") and widget.parentWidget():
                widget = widget.parentWidget()
            else:
                widget = widget.parent()
                
        if not main_window:
            from PySide6.QtWidgets import QApplication
            for widget in QApplication.topLevelWidgets():
                if hasattr(widget, "mdi_area") and hasattr(widget, "new_script_window"):
                    main_window = widget
                    break
            
        if not main_window:
            return json.dumps({"ok": False, "error": "Main window not found"})
            
        sub_windows = main_window.mdi_area.subWindowList()
        active_sub = main_window.mdi_area.activeSubWindow()
        
        results = []
        for sub in sub_windows:
            widget = sub.widget()
            class_name = widget.__class__.__name__
            title = sub.windowTitle()
            is_active = (sub == active_sub)
            
            item = {
                "name": title,
                "is_active": is_active,
                "type": "unknown"
            }
            
            try:
                if "WebScriptEditor" in class_name:
                    item["type"] = "file"
                    item["name"] = title.replace("Script: ", "")
                    item["path"] = getattr(widget, "path", getattr(widget, "script_path", ""))
                elif "LogWidget" in class_name:
                    item["type"] = "plot"
                    if hasattr(widget, "get_plot_details"):
                        try:
                            plot_details = widget.get_plot_details()
                            item["well_name"] = plot_details.get("well_name")
                            item["tracks"] = plot_details.get("tracks")
                            # Still provide flat curves list for backward compatibility or quick display
                            curves = []
                            for t in plot_details.get("tracks", []):
                                for c in t.get("curves", []):
                                    if c["name"] not in curves:
                                        curves.append(c["name"])
                            item["curves"] = curves
                        except Exception as inner_e:
                            item["error"] = f"Plot details error: {str(inner_e)}"
                    else:
                        # Fallback
                        curves = []
                        if hasattr(widget, "track_containers"):
                            for track in widget.track_containers:
                                try:
                                    if hasattr(track, "plot_widget") and hasattr(track.plot_widget, "curves"):
                                        for c_obj in track.plot_widget.curves:
                                            c_info = c_obj.get("info", {})
                                            c_name = c_info.get("name", "Unknown")
                                            if c_name not in curves:
                                                curves.append(c_name)
                                except: pass
                        item["curves"] = curves
                
                results.append(item)
            except Exception as e:
                print(f"Error gathering info for window {title}: {e}")
                item["error"] = str(e)
                results.append(item)
            
        # Sort so active is at the top
        results.sort(key=lambda x: x["is_active"], reverse=True)
            
        return json.dumps({"ok": True, "data": results})

    @Slot(result=str)
    def getWellsForMention(self):
        """获取所有数据库中的井信息"""
        data_dir = "data"
        all_wells = []
        if os.path.exists(data_dir):
            db_files = [f for f in os.listdir(data_dir) if f.endswith(".db")]
            for db_file in db_files:
                db_path = os.path.join(data_dir, db_file)
                try:
                    temp_db = DBManager(db_path)
                    wells = temp_db.get_wells()
                    for wid, wname in wells:
                        all_wells.append({
                            'id': wid,
                            'name': wname,
                            'db_path': os.path.abspath(db_path).replace('\\', '/')
                        })
                except Exception:
                    pass
        return json.dumps(all_wells)

    @Slot(int, str, result=str)
    def getCurvesForWell(self, well_id, db_path):
        """获取指定井的所有曲线，按1D优先排序"""
        try:
            db = DBManager(db_path)
            curves = db.get_curves(well_id)
            
            # 获取文件夹映射，用于关联 folder_id -> folder_name
            folders = db.get_folders(well_id)
            folder_map = {f[0]: f[1] for f in folders}
            
            # 分离 1D 和 2D
            curves_1d = []
            curves_2d = []
            for c in curves:
                # curve structure: (id, name, unit, shape, folder_id, ...)
                shape = str(c[3])
                is_2d = "," in shape and len(shape.split(',')) > 1 and shape.split(',')[1].strip()
                folder_id = c[4]
                folder_name = folder_map.get(folder_id)
                
                item = {
                    'id': c[0],
                    'name': c[1],
                    'folder': folder_name,
                    'unit': c[2] or "",
                    'is_2d': bool(is_2d),
                    'well_id': well_id,
                    'db_path': db_path,
                    'well_name': os.path.basename(db_path).replace('.db', '')
                }
                if is_2d:
                    curves_2d.append(item)
                else:
                    curves_1d.append(item)
            
            # 合并排序：1D在前，2D在后，组内按名称排序
            curves_1d.sort(key=lambda x: x['name'].lower())
            curves_2d.sort(key=lambda x: x['name'].lower())
            
            return json.dumps(curves_1d + curves_2d)
        except Exception as e:
            return json.dumps({"error": str(e)})

    @Slot(result=str)
    def getActiveContextBubbles(self):
        """获取当前活跃的上下文气泡信息"""
        main_window = None
        widget = self.parent()
        while widget:
            if hasattr(widget, "selection_context"):
                return json.dumps({"ok": True, "data": widget.selection_context})
            if hasattr(widget, "parentWidget") and widget.parentWidget():
                widget = widget.parentWidget()
            else:
                widget = widget.parent()
        return json.dumps({"ok": False, "error": "Context not found"})

class WebChatView(QWebEngineView):
    web_ready = Signal()

    def __init__(self, parent=None):
        from core.app_config import app_config
        super().__init__(parent)
        
        # Prevent black/white flash by setting solid theme background color early
        bg_color = app_config.get_theme_qcolor("bg_pure")
        self.page().setBackgroundColor(bg_color)
        self.setStyleSheet(f"background-color: {bg_color.name()};")
        
        self.bridge = WebChatBridge(self)
        self.channel = QWebChannel()
        self.channel.registerObject("pyBridge", self.bridge)
        self.bridge.webReady.connect(self.on_web_ready)
        
        self.page().setWebChannel(self.channel)
        
        # Load the HTML template
        self.template_path = os.path.join(os.path.dirname(__file__), "..", "resources", "chat_template.html")
        self.template_path = os.path.abspath(self.template_path)
        
        with open(self.template_path, "r", encoding="utf-8") as f:
            html_content = f.read()
            
        self.setHtml(html_content, baseUrl=QUrl.fromLocalFile(os.path.dirname(self.template_path) + "/"))
        self._is_ready = False
        self._pending_scripts = []
        
        # 存储当前消息的组件
        self._current_message_tools = []
        self._current_message_reasoning = ""
        self._current_message_content = ""
        self._current_message_process_logs = []
        self._current_message_steps = []
        self._current_message_cards = []
        self._current_message_pending_cards = []
        self._current_reasoning_step_index = None
        self._current_live_text_step_index = None
        self._has_active_ai_message = False  # 标记是否有正在进行的AI消息
        
        # 待办清单状态
        self._current_task_progress = None
        
        # Apply initial theme
        self.update_theme()

    def _build_context_menu_stylesheet(self):
        from core.app_config import app_config

        bg = app_config.get_theme_color("bg_pure", "#FFFFFF")
        text = app_config.get_theme_color("text_main", "#333333")
        text_dim = app_config.get_theme_color("text_dim", "#777777")
        border = app_config.get_theme_color("border_std", "#E0E0E0")
        border_dark = app_config.get_theme_color("border_dark", border)
        hover_bg = app_config.get_theme_color("accent_light", "#EBF3FF")
        hover_text = app_config.get_theme_color("accent", "#0078D7")

        return f"""
            QMenu {{
                background-color: {bg};
                color: {text};
                border: 1px solid {border_dark};
                padding: 6px;
            }}
            QMenu::item {{
                background-color: transparent;
                color: {text};
                padding: 7px 24px 7px 30px;
                margin: 1px 0;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background-color: {hover_bg};
                color: {hover_text};
            }}
            QMenu::item:disabled {{
                color: {text_dim};
                background-color: transparent;
            }}
            QMenu::separator {{
                height: 1px;
                background: {border};
                margin: 6px 10px;
            }}
            QMenu::icon {{
                padding-left: 8px;
            }}
        """

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet(self._build_context_menu_stylesheet())
        web_action = QWebEnginePage.WebAction
        copy_action = self.page().action(web_action.Copy)
        cut_action = self.page().action(web_action.Cut)
        paste_action = self.page().action(web_action.Paste)

        added_any = False

        if copy_action is not None:
            menu.addAction(copy_action)
            added_any = True

        editable_actions = []
        if cut_action is not None and cut_action.isEnabled():
            editable_actions.append(cut_action)
        if paste_action is not None and paste_action.isEnabled():
            editable_actions.append(paste_action)

        if editable_actions:
            if added_any:
                menu.addSeparator()
            for action in editable_actions:
                menu.addAction(action)
            added_any = True

        if not added_any:
            return

        menu.exec(event.globalPos())
        menu.deleteLater()

    @staticmethod
    def _normalize_tool_result_payload(result):
        if result is None:
            return None

        parsed_result = result
        if isinstance(result, str):
            try:
                parsed_result = json.loads(result)
            except Exception:
                parsed_result = result

        payload = tool_result_to_dict(parsed_result)
        normalized = dict(payload)

        content = tool_result_content(payload, fallback_to_summary=False)
        summary = tool_result_summary(payload)

        if content:
            normalized["content"] = content
        if summary:
            normalized["summary"] = summary
        cards = WebChatView._extract_message_cards(normalized)
        if cards:
            normalized["cards"] = cards

        return normalized

    @staticmethod
    def _extract_message_cards(result):
        if not isinstance(result, dict):
            return []

        explicit_cards = result.get("cards")
        if isinstance(explicit_cards, list) and explicit_cards:
            return explicit_cards

        if not result.get("ok", True):
            return []

        if result.get("open_only"):
            return []

        state = result.get("script_state") or {}
        script_path = result.get("script_path") or result.get("filepath") or state.get("script_path")
        review_stats = state.get("last_review_diff_stats") or {}
        if not script_path:
            return []

        has_mutation_signal = bool(
            result.get("previewed")
            or result.get("saved_to_disk")
            or result.get("applied_hunks")
            or (
                isinstance(review_stats, dict)
                and (
                    int(review_stats.get("added") or 0) > 0
                    or int(review_stats.get("removed") or 0) > 0
                )
            )
        )
        if not has_mutation_signal:
            return []

        normalized_path = str(script_path).replace("\\", "/")
        card = {
            "type": "file_change",
            "title": f"Edited {os.path.basename(normalized_path)}",
            "path": normalized_path,
            "subtitle": os.path.dirname(normalized_path) or "workspace file",
            "added": int(review_stats.get("added") or 0),
            "removed": int(review_stats.get("removed") or 0),
            "review_available": True,
            "actions": [],
        }
        card["actions"].append({
            "id": "review",
            "label": "Review",
            "payload": {"script_path": normalized_path},
        })
        return [card]

    def _is_finish_stage_active(self):
        return any((tool or {}).get("name") == "tool_finish" for tool in self._current_message_tools)

    def _sync_current_message_to_ui(self, summary=None):
        safe_content = json.dumps(self._current_message_content)
        safe_reasoning = json.dumps(self._current_message_reasoning) if self._current_message_reasoning else "null"
        safe_tools = json.dumps(self._current_message_tools) if self._current_message_tools else "null"
        safe_steps = json.dumps(self._current_message_steps) if self._current_message_steps else "null"
        safe_cards = json.dumps(self._current_message_cards) if self._current_message_cards else "null"
        safe_summary = json.dumps(summary) if summary else "null"
        js = f"updateLastMessage({safe_content}, {safe_reasoning}, {safe_tools}, {safe_summary}, null, {safe_steps}, {safe_cards});"
        self._run_js(js)

    def on_web_ready(self):
        self._is_ready = True
        self.web_ready.emit()
        for js in self._pending_scripts:
            self.page().runJavaScript(js)
        self._pending_scripts = []

    def _run_js(self, js, callback=None):
        if self._is_ready:
            if callback:
                self.page().runJavaScript(js, callback)
            else:
                self.page().runJavaScript(js)
        else:
            self._pending_scripts.append(js)

    def append_message(self, role, content, reasoning=None, tools=None, summary=None, is_html=False, callback=None, cards=None):
        """添加消息到聊天界面。
        
        Args:
            role: 'user', 'ai', 或 'system'
            content: 消息内容
            reasoning: 思考过程（仅AI消息）
            tools: 工具调用列表，每个工具是dict包含name, status, params, code, result
            summary: 总结信息dict包含content和sections
            is_html: 内容是否已经是HTML格式（通常用于绘制了药丸的用户消息）
        """
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        safe_content = json.dumps(content)
        safe_role = json.dumps(role)
        safe_ts = json.dumps(ts)
        safe_reasoning = json.dumps(reasoning) if reasoning else "null"
        safe_tools = json.dumps(tools) if tools else "null"
        safe_steps = json.dumps(self._current_message_steps) if role == 'ai' and self._current_message_steps else "null"
        safe_cards = json.dumps(cards) if cards else "null"
        safe_summary = json.dumps(summary) if summary else "null"
        safe_is_html = "true" if is_html else "false"
        
        js = f"appendMessage({safe_role}, {safe_content}, {safe_ts}, {safe_reasoning}, {safe_tools}, {safe_summary}, null, {safe_steps}, {safe_is_html}, {safe_cards});"
        self._run_js(js, callback=callback)
        
        # 如果是AI消息，标记为活跃状态
        if role == 'ai':
            self._has_active_ai_message = True

    def start_new_ai_message(self):
        """开始一个新的AI消息气泡。
        
        用于多轮对话，每一轮创建独立的消息气泡。
        """
        # 重置当前消息状态
        self._current_message_tools = []
        self._current_message_reasoning = ""
        self._current_message_content = ""
        self._current_message_process_logs = []
        self._current_message_steps = []
        self._current_message_cards = []
        self._current_message_pending_cards = []
        self._current_reasoning_step_index = None
        self._current_live_text_step_index = None
        self._has_active_ai_message = False

    def append_to_last_message(self, content_delta, reasoning_delta=None):
        """Append streamed content to the current AI message.

        Streamed assistant text is treated as the current final-answer candidate.
        Only explicit process-log flushes are persisted into the details timeline.
        """
        self._current_message_content += content_delta

        if reasoning_delta:
            self._current_message_reasoning += reasoning_delta

        self._sync_current_message_to_ui()

    def update_last_message(self, content, reasoning=None, tools=None, summary=None):
        """更新最后一条AI消息（完全替换）。
        
        用于非流式响应或最终更新。
        """
        self._current_message_content = content
        if reasoning:
            self._current_message_reasoning = reasoning
        if tools:
            self._current_message_tools = tools
        
        self._sync_current_message_to_ui(summary=summary)

    def add_tool_call(self, tool_name, status="pending", params=None, code=None, result=None):
        """添加工具调用到当前消息。
        
        Args:
            tool_name: 工具名称
            status: 'pending', 'success', 或 'error'
            params: 工具参数字典
            code: 代码内容（如果有）
            result: 执行结果
        """
        if (
            self._current_live_text_step_index is not None
            and self._current_live_text_step_index < len(self._current_message_steps)
            and self._current_message_steps[self._current_live_text_step_index].get("kind") == "live_text"
        ):
            self._current_message_steps[self._current_live_text_step_index]["kind"] = "text"
            self._current_live_text_step_index = None

        tool = {
            "name": tool_name,
            "status": status,
            "params": params or {},
        }
        if code:
            tool["code"] = code
        if result:
            tool["result"] = self._normalize_tool_result_payload(result)
            self._merge_pending_cards_from_result(tool["result"])
            
        self._current_message_tools.append(tool)
        self._current_message_steps.append({
            "kind": "tool",
            "name": tool_name,
            "status": status,
            "params": params or {},
            "code": code,
            "result": tool.get("result"),
        })
        self._sync_current_message_to_ui()

    def update_tool_status(self, tool_name, status, result=None):
        """更新工具调用状态。
        
        Args:
            tool_name: 工具名称
            status: 'success' 或 'error'
            result: 执行结果（可选）
        """
        for tool in self._current_message_tools:
            if tool["name"] == tool_name:
                tool["status"] = status
                if result:
                    tool["result"] = self._normalize_tool_result_payload(result)
                    self._merge_pending_cards_from_result(tool["result"])
                break

        for step in reversed(self._current_message_steps):
            if step.get("kind") == "tool" and step.get("name") == tool_name and step.get("status") == "pending":
                step["status"] = status
                if result:
                    step["result"] = self._normalize_tool_result_payload(result)
                    self._merge_pending_cards_from_result(step["result"])
                break

        self._sync_current_message_to_ui()

    @staticmethod
    def _merge_card_collections(existing_cards, incoming_cards):
        merged = {}
        for card in existing_cards or []:
            key = f"{card.get('type')}::{card.get('path')}::{card.get('title')}"
            merged[key] = dict(card)
        for card in incoming_cards or []:
            key = f"{card.get('type')}::{card.get('path')}::{card.get('title')}"
            incoming = dict(card)
            existing = merged.get(key)
            if existing:
                existing["added"] = max(int(existing.get("added") or 0), int(incoming.get("added") or 0))
                existing["removed"] = max(int(existing.get("removed") or 0), int(incoming.get("removed") or 0))
                existing["review_available"] = bool(existing.get("review_available")) or bool(incoming.get("review_available"))
                existing_actions = existing.get("actions") or []
                incoming_actions = incoming.get("actions") or []
                seen = {
                    f"{action.get('id')}::{json.dumps(action.get('payload') or {}, sort_keys=True, ensure_ascii=False)}"
                    for action in existing_actions
                }
                for action in incoming_actions:
                    action_key = f"{action.get('id')}::{json.dumps(action.get('payload') or {}, sort_keys=True, ensure_ascii=False)}"
                    if action_key not in seen:
                        existing_actions.append(action)
                        seen.add(action_key)
                existing["actions"] = existing_actions
                merged[key] = existing
            else:
                merged[key] = incoming
        return list(merged.values())

    def _merge_pending_cards_from_result(self, result):
        cards = result.get("cards") if isinstance(result, dict) else None
        if not cards:
            return
        self._current_message_pending_cards = self._merge_card_collections(
            self._current_message_pending_cards,
            cards,
        )

    def _publish_pending_cards(self):
        if not getattr(self, "_current_message_pending_cards", None):
            return
        self._current_message_cards = self._merge_card_collections(
            self._current_message_cards,
            self._current_message_pending_cards,
        )
        self._current_message_pending_cards = []
        self._sync_current_message_to_ui()

    def add_summary(self, content, sections=None):
        """添加总结卡片到当前消息。
        
        Args:
            content: 总结内容
            sections: 分节列表，每个节是dict包含title和content
        """
        summary = {
            "content": content,
            "sections": sections or []
        }
        
        self._sync_current_message_to_ui(summary=summary)

    def finalize_current_message(self):
        """完成当前消息，准备下一轮对话。"""
        self._publish_pending_cards()
        self._run_js("setLastAiMessageState('finalized');")
        self._has_active_ai_message = False

    def clear_current_message_state(self):
        """清除当前消息状态，用于开始新消息。"""
        self._current_message_tools = []
        self._current_message_reasoning = ""
        self._current_message_content = ""
        self._current_message_process_logs = []
        self._current_message_steps = []
        self._current_message_cards = []
        self._current_message_pending_cards = []
        self._current_reasoning_step_index = None
        self._current_live_text_step_index = None
        self._has_active_ai_message = False

    def append_process_log(self, content, preserve_current_content=False):
        """Append one intermediate visible assistant chunk into the current details timeline."""
        if content and content.strip():
            if (
                self._current_live_text_step_index is not None
                and self._current_live_text_step_index < len(self._current_message_steps)
                and self._current_message_steps[self._current_live_text_step_index].get("kind") == "live_text"
            ):
                self._current_message_steps[self._current_live_text_step_index]["kind"] = "text"
                self._current_message_steps[self._current_live_text_step_index]["content"] = content
            else:
                self._current_message_steps.append({
                    "kind": "text",
                    "content": content,
                })
        if not preserve_current_content:
            self._current_message_content = ""
        self._current_reasoning_step_index = None
        self._current_live_text_step_index = None
        self._sync_current_message_to_ui()

    def append_round_break(self):
        """Insert a visible React round boundary between archived steps and the next live round."""
        if not self._current_message_steps:
            return
        if self._current_message_steps[-1].get("kind") == "round_break":
            return

        self._current_message_steps.append({
            "kind": "round_break",
        })
        self._current_reasoning_step_index = None
        self._current_live_text_step_index = None
        self._sync_current_message_to_ui()

    def append_reasoning_step(self, reasoning_delta):
        """Accumulate reasoning into a dedicated step so it is not overwritten by later rounds."""
        if not reasoning_delta:
            return

        if (
            self._current_reasoning_step_index is None
            or self._current_reasoning_step_index >= len(self._current_message_steps)
            or self._current_message_steps[self._current_reasoning_step_index].get("kind") != "reasoning"
        ):
            self._current_message_steps.append({
                "kind": "reasoning",
                "content": reasoning_delta,
            })
            self._current_reasoning_step_index = len(self._current_message_steps) - 1
        else:
            self._current_message_steps[self._current_reasoning_step_index]["content"] += reasoning_delta

        self._sync_current_message_to_ui()

    def set_model_name(self, name):
        """设置显示的模型名称。"""
        safe_name = json.dumps(name)
        js = f"setModelName({safe_name});"
        self._run_js(js)

    def set_mode(self, mode):
        """设置思考模式。"""
        safe_mode = json.dumps(mode)
        js = f"setMode({safe_mode});"
        self._run_js(js)

    def set_input_enabled(self, enabled):
        """设置输入框状态。"""
        js = f"setInputEnabled({str(enabled).lower()});"
        self._run_js(js)

    def set_sending_state(self, is_sending):
        """设置发送/停止按钮状态。"""
        js = f"setSendingState({str(is_sending).lower()});"
        self._run_js(js)

    def clear_chat(self):
        """清空聊天记录。"""
        js = "clearChat();"
        self._run_js(js)
        self.clear_current_message_state()
        self.clear_task_progress()

    def set_context_info(self, context_text):
        """设置上下文信息显示。
        
        Args:
            context_text: 上下文信息文本，None表示清空
        """
        safe_text = json.dumps(context_text) if context_text else "null"
        js = f"setContextInfo({safe_text});"
        self._run_js(js)

    def set_effective_context_info(self, summary):
        """Show the effective prompt context summary in the toolbar bubble."""
        safe_summary = json.dumps(summary or {})
        js = f"setEffectiveContextInfo({safe_summary});"
        self._run_js(js)

    def append_plan(self, plan_data):
        """兼容旧接口；默认计划展示已迁移到顶部任务计划进度卡。"""
        return

    def update_task_progress(self, progress):
        """更新顶部显式任务计划进度卡片。"""
        if not progress:
            return

        self._current_task_progress = progress
        safe_progress = json.dumps(progress)
        js = f"updateTopPlanProgress({safe_progress});"
        self._run_js(js)

    def clear_task_progress(self):
        """清除显式任务计划进度卡片。"""
        self._current_task_progress = None
        self._run_js("clearTaskPlanProgress();")

    def set_selection_context(self, filename, lines, text):
        """设置代码选区内容到输入框上下文。"""
        safe_file = json.dumps(filename)
        safe_lines = json.dumps(lines)
        safe_text = json.dumps(text)
        js = f"setSelectionContext({safe_file}, {safe_lines}, {safe_text});"
        self._run_js(js)

    def update_theme(self):
        """ThemeManager compatibility method."""
        from core.app_config import app_config
        self.set_theme(app_config.get_theme_name())

    def set_theme(self, theme):
        """更新Web视图主题 (light/dark) 并注入动态CSS变量。"""
        theme = theme.lower() if theme else "light"
        
        # 1. Toggle dark-mode class
        self._run_js(f"setTheme('{theme}');")
        
        # 2. Inject centralized CSS variables from ThemeManager
        from scripts.ui.theme_manager import ThemeManager
        css_vars = ThemeManager.get_web_theme_css(theme)
        
        # Escaping for JS string
        css_content = css_vars.replace("\n", "\\n").replace("'", "\\'")
        js_inject = f"""
            var styleTag = document.getElementById('dynamic-theme-vars');
            if (styleTag) {{
                styleTag.innerHTML = '{css_content}';
            }}
        """
        self._run_js(js_inject)

    def closeEvent(self, event):
        """Cleanup resources on close to prevent handle leaks."""
        self._pending_scripts = []
        self._current_message_tools = []
        
        if hasattr(self, 'channel'):
            self.channel.deregisterObject(self.bridge)
        
        if self.page():
            self.page().setWebChannel(None)
            self.page().deleteLater()
            
        super().closeEvent(event)
