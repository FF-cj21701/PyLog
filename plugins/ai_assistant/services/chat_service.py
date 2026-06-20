from PySide6.QtCore import QObject, Signal
import asyncio
import qasync
import numpy as np
from scripts.data.db_manager import DBManager

from ..ai_core.api_client import AsyncAIWorker
from ..ai_core.agent_runtime import AgentRuntime
from ..ai_core.mcp_integration import MCPToolProvider
from ..ai_core.config import AIConfig
from ..ai_core.utils import extract_code
from ..ai_core.prompts import SystemPrompts
from ..ai_core.agent_state import AgentState
from ..ai_core.policy import ExecutionPolicy
from ..ai_core.state_machine import TaskStateMachine
from ..ai_core.tool_manager import ToolManager
from ..ai_core.verification_coordinator import VerificationCoordinator

class ChatService(QObject):
    finished = Signal(str)
    reasoning_received = Signal(str)
    content_received = Signal(str)
    error = Signal(str)
    script_generated = Signal(str)
    stopped = Signal()
    system_message = Signal(str)  # 系统消息信号
    # 新增工具调用信号
    tool_call_started = Signal(str, dict)  # tool_name, params
    tool_call_finished = Signal(str, str, str)  # tool_name, status, result
    round_finished = Signal()  # 一轮完整回复完成，准备下一轮
    task_progress = Signal(dict)

    def __init__(self, config: AIConfig, main_window=None, ui_bridge=None):
        super().__init__()
        self.config = config
        self.main_window = main_window
        self.ui_bridge = ui_bridge
        self.worker = None
        self.runtime = None
        self._current_chat_task = None  # Track the current chat task for cancellation
        self.mcp_tool_provider = MCPToolProvider(config)
        self.agent_state = AgentState()
        self.verification_coordinator = VerificationCoordinator()
        self.execution_policy = ExecutionPolicy(verification_coordinator=self.verification_coordinator)
        self.task_state_machine = TaskStateMachine(self.agent_state)
        self.tools = self._initialize_tools()
        self.tool_manager = ToolManager(self.tools)
        
        # 初始化 SystemPrompts 以生成动态工具列表
        from ..ai_core.prompts import SystemPrompts
        SystemPrompts()

    def _initialize_tools(self):
        """初始化工具"""
        # 获取路径白名单（文件+文件夹）
        whitelist = self.config.get_whitelist()
        
        # 创建全局 ToolExecutor 实例
        from ..tools.tool_executor import ToolExecutor
        tool_executor = ToolExecutor(self.main_window)
        
        # 使用工具注册表
        from ..tools.registry import tool_registry
        
        # 设置白名单环境变量，供文件工具使用
        import os
        os.environ['PYLOG_TOOL_WHITELIST'] = ';'.join(whitelist)
        
        # 自动发现工具
        tools_dir = os.path.dirname(os.path.abspath(__file__)) + '\\..\\tools'
        tool_registry.discover(tools_dir)
        
        # 获取所有工具实例，传递 ui_bridge
        tools = tool_registry.get_all_tools(
            self.main_window,
            tool_executor,
            self.ui_bridge,
            self.agent_state,
            self.execution_policy,
        )
        
        return tools

    def start_chat(self, user_text, context_data, history, mode="chat"):
        prompt = self.compose_prompt(user_text, context_data)
        self.task_state_machine.start_task(user_text, mode=mode)
        
        # We need to run the worker start in an async context to fetch MCP tools
        self._current_chat_task = asyncio.create_task(self._start_chat_async(prompt, history, mode))

    async def _start_chat_async(self, prompt, history, mode="chat"):
        """Async version of start_chat to handle MCP tool fetching."""
        # 1. Build a per-turn tool manager so external tools can refresh safely.
        turn_tool_manager = ToolManager(self.tools)
        
        # 2. Get MCP tools
        if self.config.get_mcp_enabled():
            try:
                mcp_tools = await self.mcp_tool_provider.get_tools()
                turn_tool_manager.replace_tools_by_source("mcp", mcp_tools)
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"Error fetching MCP tools: {e}")
                self.system_message.emit(f"Warning: Failed to fetch some MCP tools: {e}")

        # 3. Start worker with all tools, using the reactive prompt getter
        SystemPrompts.clear_cache()
        system_prompt = SystemPrompts.get_prompt()
        self._start_worker(
            prompt,
            history,
            system_prompt=system_prompt,
            mode=mode,
            all_tools=turn_tool_manager.tools,
        )

    def stop(self):
        """停止当前的worker并取消异步任务"""
        if self._current_chat_task and not self._current_chat_task.done():
            self._current_chat_task.cancel()
            self._current_chat_task = None
            
        if self.runtime:
            self.runtime.stop()
        elif self.worker:
            self.worker.stop()

    def get_tool_inventory_payload(self):
        """Return current runtime tools, falling back to initialized local tools."""
        if self.runtime and hasattr(self.runtime, "get_tool_inventory_payload"):
            return self.runtime.get_tool_inventory_payload()
        return self.tool_manager.get_inventory_payload()

    def _start_worker(self, prompt, history, system_prompt=None, mode="chat", all_tools=None):
        api_key = self.config.get_api_key()
        base_url = self.config.get_base_url()
        model = self.config.get_model()
        use_model = self.resolve_model(base_url, model, mode)
        
        stream = True
        
        # Use provided tools or fallback to initialized local tools
        current_tools = all_tools if all_tools is not None else self.tools
        
        max_rounds = self.config.get_max_rounds() if hasattr(self.config, 'get_max_rounds') else 5
        max_history = self.config.get_max_history() if hasattr(self.config, 'get_max_history') else 10
        self.worker = AsyncAIWorker(
            api_key,
            base_url,
            use_model,
            prompt,
            history,
            system_prompt=system_prompt,
            stream=stream,
            tools=current_tools,
            max_rounds=max_rounds,
            max_history=max_history,
            agent_state=self.agent_state,
            execution_policy=self.execution_policy,
            task_state_machine=self.task_state_machine,
            verification_coordinator=self.verification_coordinator,
        )
        
        self.runtime = AgentRuntime(self.worker)

        self.runtime.finished.connect(self.finished)
        self.runtime.reasoning_update.connect(self.reasoning_received)
        self.runtime.content_update.connect(self.content_received)
        # 连接工具调用信号
        self.runtime.tool_call_started.connect(self.tool_call_started)
        self.runtime.tool_call_finished.connect(self._on_tool_call_finished)
        self.runtime.round_finished.connect(self.round_finished)
        self.runtime.task_progress.connect(self.task_progress)
            
        self.runtime.error.connect(self.error)
        self.runtime.stopped.connect(self.stopped)
        # 连接系统消息信号
        self.runtime.system_message.connect(self.handle_system_message)
        
        # Start the async worker and track the task
        self._current_chat_task = asyncio.create_task(self.runtime.run_async())

    def _on_tool_call_finished(self, tool_name, status, result):
        """Handle a completed tool call."""
        self.tool_call_finished.emit(tool_name, status, result)

    def resolve_model(self, base_url, configured_model, mode="chat"):
        return configured_model

    def compose_prompt(self, user_text, context_data):
        ctx = self.build_context_block(context_data)
        if not ctx:
            return user_text
        return ctx + "\n\n[User Message]\n" + user_text

    def handle_system_message(self, message):
        """处理系统消息"""
        # 直接发送系统消息，不添加 Error 前缀
        if hasattr(self, 'system_message'):
            self.system_message.emit(message)
        else:
            # 回退到 error 信号
            self.error.emit(message)

    def build_context_block(self, context_data):
        if not context_data:
            return ""
        
        parts = []
        for item in context_data:
            t = item.get("type")
            if t == "well":
                name = item.get("name") or item.get("display_name") or ""
                db = item.get("db_path")
                parts.append(f"Well: {name} (db={db})")
            elif t == "curve":
                name = item.get("name") or item.get("display_name") or ""
                wid = item.get("well_id")
                db = item.get("db_path")
                # 尝试获取井名
                well_name = ""
                if db and wid:
                    try:
                        import sqlite3
                        conn = sqlite3.connect(db)
                        cursor = conn.cursor()
                        cursor.execute("SELECT name FROM wells WHERE id=?", (wid,))
                        row = cursor.fetchone()
                        if row:
                            well_name = row[0]
                        conn.close()
                    except Exception:
                        pass
                if well_name:
                    parts.append(f"Curve: {name} (well={well_name}, db={db})")
                else:
                    parts.append(f"Curve: {name} (db={db})")
        
        if not parts:
            return ""
        
        return "[ALIVE Context]\n" + "\n".join(parts)
