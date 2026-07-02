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
from ..ai_core.context_manager import ContextManager
from ..ai_core.workspace_state_collector import WorkspaceStateCollector


class ChatService(QObject):
    finished = Signal(str)
    reasoning_received = Signal(str)
    content_received = Signal(str)
    error = Signal(str)
    script_generated = Signal(str)
    stopped = Signal()
    system_message = Signal(str)
    tool_call_started = Signal(str, dict)
    tool_call_finished = Signal(str, str, str)
    round_finished = Signal()
    task_progress = Signal(dict)

    def __init__(self, config: AIConfig, main_window=None, ui_bridge=None):
        super().__init__()
        self.config = config
        self.main_window = main_window
        self.ui_bridge = ui_bridge
        self.worker = None
        self.runtime = None
        self._current_chat_task = None
        self.mcp_tool_provider = MCPToolProvider(config)
        self.agent_state = AgentState()
        self.verification_coordinator = VerificationCoordinator()
        self.execution_policy = ExecutionPolicy(verification_coordinator=self.verification_coordinator)
        self.task_state_machine = TaskStateMachine(self.agent_state)
        self.context_manager = ContextManager()
        self.workspace_state_collector = WorkspaceStateCollector()
        self.tools = self._initialize_tools()
        self.tool_manager = ToolManager(self.tools)

        # Initialize SystemPrompts so the dynamic tool list is available.
        SystemPrompts()

    def _initialize_tools(self):
        """Initialize local tool instances."""
        whitelist = self.config.get_whitelist()

        from ..tools.tool_executor import ToolExecutor

        tool_executor = ToolExecutor(self.main_window)

        from ..tools.registry import tool_registry

        import os

        os.environ["PYLOG_TOOL_WHITELIST"] = ";".join(whitelist)

        tools_dir = os.path.dirname(os.path.abspath(__file__)) + "\\..\\tools"
        tool_registry.discover(tools_dir)

        return tool_registry.get_all_tools(
            self.main_window,
            tool_executor,
            self.ui_bridge,
            self.agent_state,
            self.execution_policy,
        )

    def start_chat(self, user_text, context_data, history, mode="chat"):
        prompt = self.compose_prompt(user_text, context_data)
        self.task_state_machine.start_task(user_text, mode=mode)

        # Run the worker start in an async context so MCP tools can be fetched.
        self._current_chat_task = asyncio.create_task(self._start_chat_async(prompt, history, mode))

    async def _start_chat_async(self, prompt, history, mode="chat"):
        """Start a chat turn after refreshing per-turn MCP tools."""
        turn_tool_manager = ToolManager(self.tools)

        if self.config.get_mcp_enabled():
            try:
                mcp_tools = await self.mcp_tool_provider.get_tools()
                turn_tool_manager.replace_tools_by_source("mcp", mcp_tools)
            except asyncio.CancelledError:
                return
            except Exception as e:
                print(f"Error fetching MCP tools: {e}")
                self.system_message.emit(f"Warning: Failed to fetch some MCP tools: {e}")

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
        """Stop the current worker and cancel its async task."""
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
        current_tools = all_tools if all_tools is not None else self.tools
        max_rounds = self.config.get_max_rounds() if hasattr(self.config, "get_max_rounds") else 5
        max_history = self.config.get_max_history() if hasattr(self.config, "get_max_history") else 10

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
        self.runtime.tool_call_started.connect(self.tool_call_started)
        self.runtime.tool_call_finished.connect(self._on_tool_call_finished)
        self.runtime.round_finished.connect(self.round_finished)
        self.runtime.task_progress.connect(self.task_progress)
        self.runtime.error.connect(self.error)
        self.runtime.stopped.connect(self.stopped)
        self.runtime.system_message.connect(self.handle_system_message)

        self._current_chat_task = asyncio.create_task(self.runtime.run_async())

    def _on_tool_call_finished(self, tool_name, status, result):
        """Handle a completed tool call."""
        self.tool_call_finished.emit(tool_name, status, result)

    def resolve_model(self, base_url, configured_model, mode="chat"):
        return configured_model

    def compose_prompt(self, user_text, context_data):
        return self.context_manager.compose_prompt(user_text, self._compose_runtime_context(context_data))

    def handle_system_message(self, message):
        """Handle system messages."""
        if hasattr(self, "system_message"):
            self.system_message.emit(message)
        else:
            self.error.emit(message)

    def build_context_block(self, context_data):
        return self.context_manager.build_context_block(self._compose_runtime_context(context_data))

    def build_effective_context_summary(self, context_data):
        """Build a compact UI summary for the same context that will enter the prompt."""
        runtime_context = self._compose_runtime_context(context_data)
        sections = self.context_manager.build_sections(runtime_context)
        groups = []
        for section in sorted(sections, key=lambda item: item.priority):
            section_has_header = bool(section.lines and str(section.lines[0]).startswith("["))
            source_lines = section.lines[1:] if section_has_header else section.lines
            body_lines = [str(line) for line in source_lines if str(line).strip()]
            if not body_lines:
                continue
            title = section.lines[0].strip("[]") if section_has_header else "Manual Context"
            groups.append({
                "id": section.title,
                "title": title,
                "lines": body_lines[:12],
            })

        return {
            "label": self._format_effective_context_label(groups),
            "groups": groups,
        }

    def _format_effective_context_label(self, groups):
        if not groups:
            return ""

        primary = ""
        extras = 0
        for group in groups:
            group_id = group.get("id")
            lines = group.get("lines") or []
            if group_id == "plot_window_state" and not primary:
                type_line = next((line for line in lines if line.startswith("- active_window_type:")), "")
                window_type = type_line.split(": ", 1)[1] if ": " in type_line else "workspace"
                primary = window_type.replace("_", " ").title()
            elif group_id == "active_script_state" and not primary:
                script_line = next((line for line in lines if line.startswith("- script_path:")), "")
                primary = script_line.split(": ", 1)[1] if ": " in script_line else "Script"
            else:
                extras += 1
        if not primary:
            first = groups[0]
            primary = first.get("title") or "Context"
            extras = max(0, len(groups) - 1)
        return f"{primary} +{extras}" if extras else primary

    def _compose_runtime_context(self, context_data):
        """Merge user-selected context with recent runtime state for the next turn."""
        merged = list(context_data or [])
        workspace_state = self._collect_workspace_state()
        if workspace_state:
            merged.append(workspace_state)

        agent_state = getattr(self, "agent_state", None)
        if not agent_state:
            return merged

        current_plan = list(getattr(agent_state, "current_plan", []) or [])
        if current_plan:
            merged.append({
                "type": "task_plan",
                "steps": current_plan,
                "current_step_id": getattr(agent_state, "current_plan_step_id", None),
                "plan_domain": getattr(agent_state, "current_plan_domain", None),
                "plan_source": getattr(agent_state, "current_plan_source", None),
            })

        tool_steps = list(getattr(agent_state, "tool_steps", []) or [])
        if tool_steps:
            merged.append({
                "type": "recent_tool_results",
                "items": tool_steps,
            })

        last_verification = getattr(agent_state, "last_verification", None)
        if last_verification:
            merged.append({
                "type": "tool_result",
                "tool_name": last_verification.get("tool_name") or "last_verification",
                "result": last_verification,
            })

        return merged

    def _collect_workspace_state(self):
        collector = getattr(self, "workspace_state_collector", None)
        if not collector:
            return None
        try:
            return collector.collect(getattr(self, "main_window", None))
        except Exception:
            return None
