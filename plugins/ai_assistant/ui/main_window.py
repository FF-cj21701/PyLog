
import sys
import os
import json
import html
import re
from html.parser import HTMLParser
from urllib.parse import unquote
from PySide6.QtWidgets import QWidget, QVBoxLayout, QApplication
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from datetime import datetime

from ..ai_core.config import AIConfig
from ..ai_core.memory import MemoryManager
from ..services.chat_service import ChatService
from .review_registry import get_review_record, open_review_page

try:
    from ..runtime.ui_action_executor import UiActionExecutor
except ImportError:
    UiActionExecutor = None
try:
    from .settings_page import open_ai_settings_page
except ImportError:
    open_ai_settings_page = None
from .widgets.web_chat_view import WebChatView
from PySide6.QtCore import QObject, Signal


class _MentionHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.contexts = []
        self._mention_stack = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_names = set(str(attrs_dict.get("class", "")).split())
        if tag.lower() == "span" and "mention-pill" in class_names:
            mention_type = attrs_dict.get("data-type") or "file"
            path = attrs_dict.get("data-path") or ""
            name = attrs_dict.get("data-name") or ""
            self.contexts.append(_mention_context(mention_type, path, name))
            self._mention_stack.append(tag.lower())
        elif tag.lower() in {"br"} and not self._mention_stack:
            self.parts.append("\n")
        elif tag.lower() in {"div", "p"} and not self._mention_stack:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if self._mention_stack and tag.lower() == self._mention_stack[-1]:
            self._mention_stack.pop()

    def handle_data(self, data):
        if not self._mention_stack:
            self.parts.append(data)


_MENTION_MARKER_RE = re.compile(r"@\[(?P<body>[^\]]+)\]")


def _mention_context(mention_type, path, name):
    context = {
        "type": str(mention_type or "file"),
        "name": str(name or ""),
    }
    if path:
        context["path"] = str(path)
    return context


def _extract_marker_contexts(text):
    contexts = []

    def replace(match):
        body = match.group("body")
        parts = body.split(":")
        if len(parts) >= 3:
            mention_type = parts[0]
            name = parts[-1]
            path = ":".join(parts[1:-1])
            contexts.append(_mention_context(mention_type, path, name))
        return ""

    cleaned = _MENTION_MARKER_RE.sub(replace, text)
    return cleaned, contexts


def normalize_chat_actual_text(text):
    """Remove UI-only mention markup from user text and return extracted contexts."""
    raw = str(text or "")
    contexts = []
    if "mention-pill" not in raw and "<span" not in raw:
        cleaned, marker_contexts = _extract_marker_contexts(raw)
        return cleaned.strip(), marker_contexts
    parser = _MentionHtmlParser()
    try:
        parser.feed(raw)
        parser.close()
        cleaned = "".join(parser.parts)
        contexts.extend(parser.contexts)
    except Exception:
        cleaned = re.sub(r"<[^>]+>", "", raw)
    cleaned, marker_contexts = _extract_marker_contexts(html.unescape(cleaned))
    contexts.extend(marker_contexts)
    return cleaned.strip(), contexts


def sanitize_chat_actual_text(text):
    """Return user text without leaked mention-pill HTML or inline markers."""
    return normalize_chat_actual_text(text)[0]


class UIBridge(QObject):
    """统一UI事件桥接器，用于工具与UI之间的通信"""
    
    show_plan = Signal(dict)
    show_message = Signal(str, str)
    
    def __init__(self, ai_widget):
        super().__init__()
        self.ai_widget = ai_widget
        
        # 连接信号到槽函数
        if ai_widget:
            self.show_plan.connect(self._on_show_plan)
            self.show_message.connect(self._on_show_message)
    
    def append_plan(self, plan_data):
        """显示计划卡片"""
        self.show_plan.emit(plan_data)
    
    def append_message(self, role, content):
        """添加消息"""
        self.show_message.emit(role, content)
    
    def get_chat_view(self):
        """获取聊天视图实例"""
        if self.ai_widget and hasattr(self.ai_widget, 'chat_view'):
            return self.ai_widget.chat_view
        return None
    
    def _on_show_plan(self, plan_data):
        """在主线程中显示计划卡片"""
        if self.ai_widget and hasattr(self.ai_widget, 'chat_view'):
            self.ai_widget.chat_view.append_plan(plan_data)
    
    def _on_show_message(self, role, content):
        """在主线程中添加消息"""
        if self.ai_widget and hasattr(self.ai_widget, 'chat_view'):
            self.ai_widget.chat_view.append_message(role, content)


class AIAssistantWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        self.selection_context = []
        self.chat_contexts = []  # 新增：接收来自JS的气泡上下文
        self._pending_mode = "chat"
        self.mode = "chat"
        
        self.config = AIConfig()
        self.memory = MemoryManager(limit=self.config.get_max_history())
        
        # 获取真正的主窗口实例
        main_window = self.parent()
        while main_window and not hasattr(main_window, "new_script_window"):
            main_window = main_window.parent()
        
        # 创建统一UI事件桥接器
        self.ui_bridge = UIBridge(self)
        
        self.chat_service = ChatService(self.config, main_window, self.ui_bridge)
        
        # State for streaming
        self._streaming_content = ""
        self._streaming_reasoning = ""
        self._previous_content_length = 0  # 用于检测重复内容

        self._pending_content_delta = ""
        self._pending_reasoning_delta = ""
        self._stream_flush_interval_ms = 80
        self._stream_flush_timer = QTimer(self)
        self._stream_flush_timer.setSingleShot(True)
        self._stream_flush_timer.timeout.connect(self._flush_stream_updates)
        self._context_refresh_timer = QTimer(self)
        self._context_refresh_timer.setSingleShot(True)
        self._context_refresh_timer.timeout.connect(self._refresh_effective_context_info_now)

        # Setup Web Chat View
        self.chat_view = WebChatView()
        self.layout.addWidget(self.chat_view)

        # Connect Python -> JS signals (via bridge)
        self.bridge = self.chat_view.bridge
        self.bridge.messageSent.connect(self.send_message)
        self.bridge.modeToggled.connect(self.toggle_mode)
        self.bridge.settingsRequested.connect(self.open_settings)
        self.bridge.chatCleared.connect(self.clear_chat_memory)
        self.bridge.updateChatContexts.connect(self.set_chat_contexts)
        self.bridge.messageCardActionRequested.connect(self.handle_message_card_action)
        
        # Connect Chat Service signals
        self.chat_service.finished.connect(self.handle_chat_finished)
        self.chat_service.reasoning_received.connect(self.handle_reasoning_update)
        self.chat_service.content_received.connect(self.handle_content_update)
        self.chat_service.error.connect(self.handle_error)
        self.chat_service.script_generated.connect(self.handle_script_generated)
        self.chat_service.stopped.connect(self.handle_stopped)
        self.chat_service.system_message.connect(self.append_system_message)
        # 连接工具调用信号
        self.chat_service.tool_call_started.connect(self.handle_tool_call_started)
        self.chat_service.tool_call_finished.connect(self.handle_tool_call_finished)
        self.chat_service.round_finished.connect(self.handle_round_finished)
        self.chat_service.task_progress.connect(self.handle_task_progress)

        # Initial UI State
        self.check_configuration()
        self.update_model_chip()
        self.chat_view.set_mode(self.mode)
        
        # State for sending/stopping
        self._is_sending = False
        
        # Ensure cleanup on widget destruction
        self.destroyed.connect(self.stop_generation)

    def toggle_mode(self):
        self.mode = "reason" if self.mode == "chat" else "chat"
        self.chat_view.set_mode(self.mode)
        self.update_model_chip()
    
    def check_configuration(self):
        if not self.config.is_configured():
            self.append_system_message("Welcome! Please click 'Settings' to configure your AI Model API key.")

    def open_settings(self):
        if open_ai_settings_page is None:
            self.append_system_message("AI settings page is unavailable.")
            return
        try:
            open_ai_settings_page(parent=self, on_saved=self._handle_settings_saved)
        except Exception as e:
            self.append_system_message(f"Failed to open AI settings page: {e}")

    def _handle_settings_saved(self):
        self.append_system_message("Settings updated.")
        self.update_model_chip()
        self.memory.update_limit(self.config.get_max_history())

    def update_model_chip(self):
        base_url = self.config.get_base_url()
        model = self.config.get_model()
        resolved = self.chat_service.resolve_model(base_url, model, self.mode) or "-"
        self.chat_view.set_model_name(resolved)

    def set_chat_contexts(self, contexts_json):
        """同步来自JS侧的上下文气泡数据"""
        try:
            import json
            self.chat_contexts = json.loads(contexts_json)
        except Exception:
            self.chat_contexts = []

    def set_selection_context(self, items_data):
        self.selection_context = items_data or []
        import json
        self.chat_view.set_context_info(json.dumps(self.selection_context) if self.selection_context else None)

    def _merged_chat_contexts(self):
        return self._merge_context_items(
            list(getattr(self, "chat_contexts", []) or []) + list(getattr(self, "selection_context", []) or [])
        )

    def _merge_context_items(self, items):
        merged = []
        seen = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            key = (
                item.get("type"),
                item.get("path") or item.get("db_path"),
                item.get("name") or item.get("display_name"),
                item.get("id") or item.get("curve_id"),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return merged

    def refresh_effective_context_info(self, delay_ms=80):
        if hasattr(self, "_context_refresh_timer"):
            self._context_refresh_timer.start(max(0, int(delay_ms)))
        else:
            self._refresh_effective_context_info_now()

    def _refresh_effective_context_info_now(self):
        if not hasattr(self, "chat_view") or not hasattr(self, "chat_service"):
            return
        effective_context = self._merged_chat_contexts()
        self.chat_view.set_effective_context_info(
            self.chat_service.build_effective_context_summary(effective_context)
        )

    def set_code_context(self, filename, lines, text):
        """Set code selection as context in the input box."""
        self.chat_view.set_selection_context(filename, lines, text)

    def send_message(self, text):
        text = text.strip()

        if self._is_sending:
            self.stop_generation()
            return

        if not text:
            return

        try:
            import json
            data = json.loads(text)
            full_text = data.get("actual", text)
            display_text = data.get("display", text)
            rendered_by_client = bool(data.get("rendered", False))
            message_contexts = data.get("contexts") if isinstance(data.get("contexts"), list) else []
        except Exception:
            full_text = text
            display_text = text
            rendered_by_client = False
            message_contexts = []

        full_text, extracted_contexts = normalize_chat_actual_text(full_text)
        message_contexts = self._merge_context_items(list(message_contexts or []) + list(extracted_contexts or []))

        if full_text in [
            "\u6267\u884c\u8ba1\u5212",
            "\u4fee\u6539\u8ba1\u5212",
            "\u53d6\u6d88\u8ba1\u5212",
            "Run Plan",
            "Edit Plan",
            "Cancel Plan",
        ]:
            self.handle_plan_action(full_text)
            return

        self._is_sending = True
        self.chat_view.set_sending_state(True)
        effective_context = self._merge_context_items(self._merged_chat_contexts() + message_contexts)
        self.chat_view.set_effective_context_info(
            self.chat_service.build_effective_context_summary(effective_context)
        )
        if not rendered_by_client:
            self.chat_view.append_message("user", display_text, is_html=True)
        self.chat_view.set_input_enabled(False)
        self.memory.add_user_message(full_text)

        self._streaming_content = ""
        self._streaming_reasoning = ""
        self._pending_content_delta = ""
        self._pending_reasoning_delta = ""
        self._stream_flush_timer.stop()
        self._previous_content_length = 0

        self.chat_view.clear_current_message_state()
        self.chat_view.clear_task_progress()

        def _start_chat_after_placeholder(_result=None):
            self._pending_mode = "chat"
            self.chat_service.start_chat(full_text, effective_context, self.memory.get_recent_history(), mode=self.mode)

        self.append_ai_message("", callback=_start_chat_after_placeholder)  # Placeholder

    def handle_plan_action(self, action):
        """Handle plan actions from the chat UI."""
        if action in ["\u6267\u884c\u8ba1\u5212", "Run Plan"]:
            self.append_system_message("Starting plan execution...")
        elif action in ["\u4fee\u6539\u8ba1\u5212", "Edit Plan"]:
            self.append_system_message("Update the plan parameters and run it again.")
        elif action in ["\u53d6\u6d88\u8ba1\u5212", "Cancel Plan"]:
            self.append_system_message("Plan cancelled.")
    
    def stop_generation(self):
        """停止生成"""
        self._flush_stream_updates()
        self.chat_service.stop()
    
    def handle_stopped(self):
        """处理停止事件"""
        self._flush_stream_updates()
        self._is_sending = False
        self.chat_view.set_sending_state(False)  # 切换回发送按钮
        self.chat_view.set_input_enabled(True)

    def handle_reasoning_update(self, chunk):
        """Handle streamed reasoning updates for the current AI request."""
        self._streaming_reasoning += chunk
        self._pending_reasoning_delta += chunk
        self._schedule_stream_flush()

    def handle_content_update(self, chunk):
        """处理内容更新 - 追加到当前消息"""
        self._streaming_content += chunk
        self._pending_content_delta += chunk
        self._schedule_stream_flush()
        
        # 检测并跳过重复的内容
        # 如果当前内容以之前的内容开头，只显示新增的部分
            # 使用追加模式更新消息，只显示新增内容

    def _stash_current_streaming_content(self):
        text = self._streaming_content or ""
        if not text.strip():
            self._streaming_content = ""
            self._previous_content_length = 0
            return

        # 立即追加到步骤历史，并清空当前UI打字区，使得正文块只负责当前轮的实时打字
        self.chat_view.append_process_log(text, preserve_current_content=False)
        self._streaming_content = ""
        self._previous_content_length = 0

    def handle_chat_finished(self, full_content):
        """处理完成状态，此时将正文区彻底裁剪为最终结果，让早前被 stash 的步骤自然暴露在 details 里"""
        self._flush_stream_updates()
        # 如果最后一步使用了 finish 且内容是琐碎的（如 "ok"），则优先使用之前流式积累的内容作为总结
        accumulated_content = self._streaming_content
        self._streaming_content = full_content

        current_tools = getattr(self.chat_view, "_current_message_tools", []) or []
        finish_used = any((t or {}).get("name") == "finish" for t in current_tools)
        normalized_full = (full_content or "").strip().lower()
        trivial_finish_texts = {"done", "finished", "complete", "completed", "ok", "success", "task finished successfully."}
        should_ignore_finish = finish_used and (normalized_full in trivial_finish_texts or not normalized_full)

        # 收尾：如果最后一句是无意义文本，我们尝试保留之前的流式内容，或者设为默认成功
        if should_ignore_finish:
            final_display = accumulated_content if accumulated_content.strip() else "Task completed successfully."
            self.chat_view.update_last_message(final_display, self._streaming_reasoning)
        else:
            self.chat_view.update_last_message(full_content, self._streaming_reasoning)

        self.memory.add_ai_message(full_content)
        def _complete_turn(_result=None):
            self.chat_view.set_input_enabled(True)
            self._pending_mode = "chat"
            self.update_model_chip()
            self._is_sending = False
            self.chat_view.set_sending_state(False)  # 切换回发送按钮

        self.chat_view.finalize_current_message(callback=_complete_turn)

    def handle_script_generated(self, code):
        self._flush_stream_updates()
        self.memory.add_ai_message("[Generated Script]")
        
        # Open script editor
        win = self.window()
        if not win or not hasattr(win, "new_script_window"):
            self.append_system_message("Script generated, but no main window found.")
            self.chat_view.update_last_message(code)
        else:
            win.new_script_window()
            active_sub = win.mdi_area.activeSubWindow() if hasattr(win, "mdi_area") else None
            if active_sub:
                editor = active_sub.widget()
                if hasattr(editor, "set_code"):
                    editor.set_code(code)
                    try: active_sub.setWindowTitle("Script: AI Generated")
                    except: pass
                    self.append_system_message("Script generated and opened in Script Editor.")
                else:
                    self.chat_view.update_last_message(code)
            else:
                self.chat_view.update_last_message(code)
        
        self.chat_view.set_input_enabled(True)
        self._pending_mode = "chat"
        self.update_model_chip()
        self._is_sending = False
        self.chat_view.set_sending_state(False)  # 切换回发送按钮

    def handle_error(self, error_msg):
        self._flush_stream_updates()
        self.append_system_message(f"Error: {error_msg}")
        self.chat_view.set_input_enabled(True)
        self.update_model_chip()
        self._is_sending = False
        self.chat_view.set_sending_state(False)  # 切换回发送按钮

    def handle_tool_call_started(self, tool_name, params):
        """Handle tool-call start and preserve text/tool chronological order."""
        self._flush_stream_updates()

        # Keep the final-answer draft in the main answer area when the agent is
        # transitioning into finish. Other tool transitions only stash
        # visible assistant text; details are populated after the full run ends.
        is_finish_tool = tool_name == "finish"
        if not is_finish_tool and self._streaming_content and self._streaming_content.strip():
            self._stash_current_streaming_content()

        code = params.get('code') if params and 'code' in params else None
        self.chat_view.add_tool_call(tool_name, status="pending", params=params, code=code)

    def handle_tool_call_finished(self, tool_name, status, result):
        """处理工具调用完成 - 在当前消息气泡中更新工具状态"""
        # 使用 update_tool_status 方法更新工具状态
        self.chat_view.update_tool_status(tool_name, status, result)

    def handle_round_finished(self):
        """Handle an intermediate agent round without creating a new AI message."""
        self._flush_stream_updates()
        # Keep round text out of details until the full conversation finishes.
        if self._streaming_content and self._streaming_content.strip():
            self._stash_current_streaming_content()

        self.chat_view.append_round_break()

        # Reset per-round streaming buffers but keep the same details container.
        self._streaming_content = ""
        self._streaming_reasoning = ""
        self._previous_content_length = 0

    def _schedule_stream_flush(self):
        if not self._stream_flush_timer.isActive():
            self._stream_flush_timer.start(self._stream_flush_interval_ms)

    def _flush_stream_updates(self):
        if self._stream_flush_timer.isActive():
            self._stream_flush_timer.stop()

        reasoning_delta = self._pending_reasoning_delta
        content_delta = self._pending_content_delta
        self._pending_reasoning_delta = ""
        self._pending_content_delta = ""

        if reasoning_delta:
            self.chat_view.append_reasoning_step(reasoning_delta)

        if content_delta:
            self._previous_content_length = len(self._streaming_content)

        if reasoning_delta or content_delta:
            self.chat_view.append_to_last_message(content_delta, reasoning_delta)

    def handle_task_progress(self, progress):
        """将后端任务计划进度同步到顶部任务清单区域。"""
        if not progress or not hasattr(self, "chat_view"):
            return
        self.chat_view.update_task_progress(progress)

    def handle_message_card_action(self, payload_json):
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            try:
                payload = json.loads(unquote(payload_json)) if payload_json else {}
            except Exception:
                payload = {}

        action_id = payload.get("action")
        card_payload = payload.get("payload") or {}
        if action_id in {"review_ui_actions", "replay_failed_ui_actions"}:
            self._handle_ui_action_card_action(action_id, card_payload)
            return

        script_path = card_payload.get("script_path") or payload.get("script_path")
        if action_id != "review" or not script_path:
            return

        win = self.window()
        if not win or not hasattr(win, "mdi_area"):
            self.append_system_message("Review is unavailable because no main window was found.")
            return

        review_record = get_review_record(script_path)
        if review_record:
            page = open_review_page(script_path, parent=win, payload=review_record)
            if page:
                return

        self.append_system_message(f"Review is unavailable because no saved review record was found for {script_path}.")

    def _handle_ui_action_card_action(self, action_id, card_payload):
        actions = card_payload.get("ui_actions") or []
        results = card_payload.get("ui_action_results") or []
        if action_id == "review_ui_actions":
            lines = [f"UI action review: {len(actions)} action(s)."]
            for index, action in enumerate(actions):
                result = results[index] if index < len(results) and isinstance(results[index], dict) else {}
                status = "ok" if result.get("ok") else "failed" if result else "pending"
                action_type = action.get("type") if isinstance(action, dict) else "invalid"
                detail = result.get("summary") or result.get("error") or ""
                lines.append(f"{index + 1}. {action_type}: {status}" + (f" - {detail}" if detail else ""))
            self.append_system_message("\n".join(lines))
            return

        if not UiActionExecutor:
            self.append_system_message("Replay is unavailable because the UI action executor could not be loaded.")
            return
        replay_results = UiActionExecutor(main_window=self.window()).execute_many(actions)
        succeeded = len([item for item in replay_results if item.get("ok")])
        failed = len(replay_results) - succeeded
        self.append_system_message(
            f"Replayed {len(replay_results)} UI action(s): {succeeded} succeeded"
            + (f", {failed} failed." if failed else ".")
        )

    def append_user_message(self, text):
        self.chat_view.append_message("user", text)

    def append_ai_message(self, text, callback=None):
        self.chat_view.append_message("ai", text, callback=callback)

    def append_system_message(self, text):
        self.chat_view.append_message("system", text)
        
    def clear_chat_memory(self):
        self.memory.clear()
        if hasattr(self.chat_service, "reset_active_tools"):
            self.chat_service.reset_active_tools()
        # UI is cleared in JS, just sync memory

    def set_theme(self, theme):
        """Update the AI assistant theme."""
        if hasattr(self, 'chat_view'):
            self.chat_view.set_theme(theme)
