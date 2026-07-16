from PySide6.QtCore import QObject, Signal
import asyncio
import json

import sniffio

from .task_domain_router import TaskDomainRouter
from .tool_manager import ToolManager
from .tool_result import (
    error_tool_result,
    normalize_tool_result,
    serialize_tool_result,
    tool_result_content,
    tool_result_error,
    tool_result_ok,
    tool_result_summary,
    tool_result_to_dict,
)
from .tool_selection import ToolSelectionStrategy
from ..tools.tool_discovery_tool import LoadToolsTool, SearchToolsTool

try:
    import openai

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class AsyncAIWorker(QObject):
    """Async chat worker coordinating streaming, tools, planning, and verification."""

    BASE_ACTIVE_TOOL_NAMES = {
        "finish",
        "get_help",
        "search_tools",
        "load_tools",
        "create_task_plan",
        "get_task_plan",
        "update_task_plan",
    }

    finished = Signal(str)
    reasoning_update = Signal(str)
    content_update = Signal(str)
    error = Signal(str)
    stopped = Signal()
    system_message = Signal(str)
    tool_call_started = Signal(str, dict)
    tool_call_finished = Signal(str, str, str)
    round_finished = Signal()
    task_progress = Signal(dict)

    def __init__(
        self,
        api_key,
        base_url,
        model,
        prompt,
        history=None,
        system_prompt=None,
        stream=True,
        tools=None,
        max_rounds=5,
        max_history=10,
        agent_state=None,
        execution_policy=None,
        task_state_machine=None,
        verification_coordinator=None,
        initial_active_tool_names=None,
        on_tools_loaded=None,
        images=None,
    ):
        super().__init__()
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.prompt = prompt if prompt is not None else ""
        self.history = history or []
        self.system_prompt = system_prompt if system_prompt is not None else "You are a helpful assistant."
        self.stream = stream
        self.tools = tools or []
        self._is_stopped = False
        self.max_rounds = max_rounds
        self.max_history = max_history
        self._client = None
        self.agent_state = agent_state
        self.execution_policy = execution_policy
        self.task_state_machine = task_state_machine
        self.verification_coordinator = verification_coordinator
        self.tool_manager = ToolManager(self.tools)
        self.active_tool_names = set(self.BASE_ACTIVE_TOOL_NAMES)
        self.active_tool_names.update(str(name) for name in (initial_active_tool_names or []) if str(name).strip())
        self.on_tools_loaded = on_tools_loaded
        self.images = list(images or [])
        self.token_usage_events = []
        self._install_runtime_discovery_tools()
        self.tool_dispatcher = self.tool_manager
        self.tool_selection = ToolSelectionStrategy()
        self.domain_router = TaskDomainRouter()
        self._in_thought_tag = False
        self._in_task_plan_tag = False
        self._task_plan_buffer = ""
        self._buffer = ""

    def _reset_stream_parse_state(self):
        """Reset transient parsing state for a fresh streamed assistant turn."""
        self._in_thought_tag = False
        self._in_task_plan_tag = False
        self._task_plan_buffer = ""
        self._buffer = ""

    def _emit_task_progress(self):
        """Emit the latest task-progress payload when state tracking is active."""
        if not self.agent_state:
            return
        try:
            self.task_progress.emit(self.agent_state.get_task_progress_payload())
        except Exception:
            pass

    @staticmethod
    async def list_models(api_key, base_url):
        """Fetch available models from the provider."""
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI library not installed.")
        async with openai.AsyncOpenAI(api_key=api_key, base_url=base_url) as client:
            response = await client.models.list()
            names = [m.id for m in response.data]
            names.sort()
            return names

    def stop(self):
        self._is_stopped = True
        if self.task_state_machine:
            self.task_state_machine.cancel_task("worker stopped")
        self.stopped.emit()

    def _init_client(self):
        if not OPENAI_AVAILABLE:
            raise ImportError("OpenAI library not installed. Please run: pip install openai")
        return openai.AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    def _build_messages(self):
        """Build the provider message list from system prompt, history, and current task."""
        messages = [{"role": "system", "content": self.system_prompt}]
        history_to_use = self.history[-self.max_history :] if len(self.history) > self.max_history else self.history
        for role, content in history_to_use:
            safe_content = content if content is not None else ""
            messages.append({"role": role, "content": safe_content})
        user_content = self.prompt
        if self.images:
            user_content = [{"type": "text", "text": self.prompt or "Analyze the attached image(s)."}]
            for image in self.images:
                user_content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": image.get("data_url"),
                        "detail": image.get("detail", "auto"),
                    },
                })
        messages.append({"role": "user", "content": user_content})
        return messages

    def _build_tool_configs(self):
        """Build routed and ranked tool configs for the current task context."""
        return self.tool_manager.build_tool_configs(
            state=self.agent_state,
            strategy=self.tool_selection,
            router=self.domain_router,
            prompt=self.prompt,
            history=self.history,
            active_tool_names=self.active_tool_names,
        )

    def get_tool_inventory_payload(self):
        """Expose the current worker tool inventory for diagnostics and UI consumers."""
        return self.tool_manager.get_inventory_payload()

    def _install_runtime_discovery_tools(self):
        self.tool_manager.register_tool(SearchToolsTool(self._search_tools), replace_existing=True)
        self.tool_manager.register_tool(LoadToolsTool(self._load_tools), replace_existing=True)
        self.tools = self.tool_manager.tools

    def _search_tools(self, query="", domain=None, capability=None, limit=5):
        try:
            compact_limit = max(1, min(int(limit or 5), 5))
        except (TypeError, ValueError):
            compact_limit = 5
        results = self.tool_manager.search_specs(
            query=query,
            domain=domain,
            capability=capability,
            limit=compact_limit,
        )
        compact_results = []
        for item in results:
            name = item.get("name")
            compact_results.append({
                "name": name,
                "description": str(item.get("description") or "")[:240],
                "category": item.get("category"),
                "domain_tags": list(item.get("domain_tags") or [])[:4],
                "capability_tags": list(item.get("capability_tags") or [])[:6],
                "already_loaded": name in self.active_tool_names,
                "can_call_now": name in self.active_tool_names,
            })
        return compact_results

    def _load_tools(self, names):
        requested = [str(name).strip() for name in (names or []) if str(name).strip()]
        loaded = []
        missing = []
        already_loaded = []
        for name in requested:
            spec = self.tool_manager.get_spec(name)
            if spec is None:
                missing.append(name)
                continue
            if name in self.active_tool_names:
                already_loaded.append(name)
            else:
                self.active_tool_names.add(name)
                loaded.append(spec.to_index_entry())

        if callable(self.on_tools_loaded):
            try:
                self.on_tools_loaded(sorted(self.active_tool_names))
            except Exception:
                pass

        if loaded and already_loaded:
            summary = f"Loaded {len(loaded)} tools, {len(already_loaded)} already active"
        elif loaded:
            summary = f"Loaded {len(loaded)} tools"
        elif already_loaded and not missing:
            summary = "No new tools loaded; all requested tools are already active"
        elif missing:
            summary = f"Loaded {len(loaded)} tools; {len(missing)} missing"
        else:
            summary = "No tools requested"

        return {
            "ok": not missing,
            "summary": summary,
            "loaded": loaded,
            "missing": missing,
            "already_loaded": already_loaded,
            "active_tool_names": sorted(self.active_tool_names),
        }

    def _is_tool_active(self, tool_name: str) -> bool:
        return str(tool_name or "") in self.active_tool_names

    def _inactive_tool_result(self, tool_name: str):
        return error_tool_result(
            tool_name,
            (
                f"Tool '{tool_name}' is not loaded in the current session. "
                "Call search_tools to find relevant tools, then load_tools with the selected tool names."
            ),
            source="local",
            tool_not_loaded=True,
            active_tool_names=sorted(self.active_tool_names),
        )

    def _maybe_append_tool_selection_guidance(self, messages):
        """Append dynamic system guidance about tool choice when available."""
        guidance_messages = []
        selection_guidance = self.tool_selection.build_guidance(self.agent_state)
        if selection_guidance:
            guidance_messages.append(selection_guidance)

        domain_guidance = self.domain_router.build_guidance(
            prompt=self.prompt,
            history=self.history,
            state=self.agent_state,
        )
        if domain_guidance:
            guidance_messages.append(domain_guidance)

        for guidance in guidance_messages:
            existing = sum(
                1
                for msg in messages
                if msg.get("role") == "system" and msg.get("content") == guidance
            )
            if existing:
                continue
            if messages and messages[-1].get("role") == "system" and messages[-1].get("content") == guidance:
                continue
            messages.append({"role": "system", "content": guidance})

    def _json_char_count(self, value):
        try:
            return len(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return len(str(value))

    def _print_prompt_debug(self, messages, tool_configs, iteration=None):
        role_counts = {}
        role_chars = {}
        tool_result_chars = 0
        assistant_tool_call_chars = 0

        for message in messages or []:
            role = str(message.get("role") or "unknown")
            chars = self._json_char_count(message)
            role_counts[role] = role_counts.get(role, 0) + 1
            role_chars[role] = role_chars.get(role, 0) + chars
            if role == "tool":
                tool_result_chars += chars
            if role == "assistant" and message.get("tool_calls"):
                assistant_tool_call_chars += self._json_char_count(message.get("tool_calls"))

        system_chars = role_chars.get("system", 0)
        user_chars = role_chars.get("user", 0)
        assistant_chars = role_chars.get("assistant", 0)
        tool_chars = role_chars.get("tool", 0)
        message_chars = sum(role_chars.values())
        tool_schema_chars = self._json_char_count(tool_configs or [])
        active_tool_count = len(tool_configs or [])
        round_label = f"round={iteration} " if iteration is not None else ""
        print(
            "[Prompt Debug] "
            f"{round_label}"
            f"messages={len(messages or [])} "
            f"system={role_counts.get('system', 0)}/{system_chars} "
            f"user={role_counts.get('user', 0)}/{user_chars} "
            f"assistant={role_counts.get('assistant', 0)}/{assistant_chars} "
            f"tool={role_counts.get('tool', 0)}/{tool_chars} "
            f"tool_results={tool_result_chars} "
            f"assistant_tool_calls={assistant_tool_call_chars} "
            f"tool_schemas={active_tool_count}/{tool_schema_chars} "
            f"total_chars={message_chars + tool_schema_chars}"
        )

    def _process_stream_chunk(self, delta, accumulator):
        """Parse streamed content, separating reasoning, visible text, and hidden task plans."""
        reasoning_chunk = getattr(delta, "reasoning_content", None)
        if reasoning_chunk:
            accumulator["reasoning"] += reasoning_chunk
            self.reasoning_update.emit(reasoning_chunk)

        content_chunk = delta.content
        if not content_chunk:
            return reasoning_chunk, content_chunk

        self._buffer += content_chunk

        while True:
            if self._in_thought_tag:
                end_idx = self._buffer.find("</thought>")
                if end_idx != -1:
                    thought_content = self._buffer[:end_idx]
                    if thought_content:
                        accumulator["reasoning"] += thought_content
                        self.reasoning_update.emit(thought_content)

                    self._in_thought_tag = False
                    self._buffer = self._buffer[end_idx + 10 :]
                    continue

                safe_idx = self._buffer.rfind("<")
                if safe_idx != -1 and len(self._buffer) - safe_idx < 10:
                    to_send = self._buffer[:safe_idx]
                    self._buffer = self._buffer[safe_idx:]
                else:
                    to_send = self._buffer
                    self._buffer = ""

                if to_send:
                    accumulator["reasoning"] += to_send
                    self.reasoning_update.emit(to_send)
                break

            if self._in_task_plan_tag:
                end_idx = self._buffer.find("</task_plan>")
                if end_idx != -1:
                    plan_content = self._buffer[:end_idx]
                    if plan_content:
                        self._task_plan_buffer += plan_content
                    self._apply_task_plan_payload(self._task_plan_buffer)
                    self._task_plan_buffer = ""
                    self._in_task_plan_tag = False
                    self._buffer = self._buffer[end_idx + 12 :]
                    continue

                safe_idx = self._buffer.rfind("<")
                if safe_idx != -1 and len(self._buffer) - safe_idx < 12:
                    plan_content = self._buffer[:safe_idx]
                    self._buffer = self._buffer[safe_idx:]
                else:
                    plan_content = self._buffer
                    self._buffer = ""
                if plan_content:
                    self._task_plan_buffer += plan_content
                break

            thought_idx = self._buffer.find("<thought>")
            plan_idx = self._buffer.find("<task_plan>")
            tag_candidates = [
                ("thought", thought_idx, 9),
                ("task_plan", plan_idx, 11),
            ]
            tag_candidates = [item for item in tag_candidates if item[1] != -1]

            if tag_candidates:
                tag_type, start_idx, tag_len = min(tag_candidates, key=lambda item: item[1])
                pre_content = self._buffer[:start_idx]
                if pre_content:
                    accumulator["content"] += pre_content
                    self.content_update.emit(pre_content)
                self._buffer = self._buffer[start_idx + tag_len :]
                if tag_type == "thought":
                    self._in_thought_tag = True
                else:
                    self._in_task_plan_tag = True
                    self._task_plan_buffer = ""
                continue

            safe_idx = self._buffer.rfind("<")
            if safe_idx != -1 and len(self._buffer) - safe_idx < 12:
                to_send = self._buffer[:safe_idx]
                self._buffer = self._buffer[safe_idx:]
            else:
                to_send = self._buffer
                self._buffer = ""

            if to_send:
                accumulator["content"] += to_send
                self.content_update.emit(to_send)
            break

        return reasoning_chunk, content_chunk

    def _apply_task_plan_payload(self, raw_payload):
        """Apply a streamed hidden task plan and emit updated progress when accepted."""
        if not raw_payload or not self.task_state_machine:
            return
        try:
            applied = self.task_state_machine.apply_model_plan(raw_payload)
            if applied:
                self._emit_task_progress()
        except Exception:
            pass

    def _process_tool_calls_stream(self, delta, tool_calls_dict):
        """Accumulate partial streamed tool-call chunks into complete tool calls."""
        if not (hasattr(delta, "tool_calls") and delta.tool_calls):
            return

        for tool_call in delta.tool_calls:
            tool_id = tool_call.id

            if tool_id is None and tool_calls_dict:
                last_id = list(tool_calls_dict.keys())[-1]
                existing = tool_calls_dict[last_id]

                if hasattr(tool_call, "function") and tool_call.function:
                    if hasattr(tool_call.function, "name") and tool_call.function.name:
                        existing["function"]["name"] = tool_call.function.name
                    if hasattr(tool_call.function, "arguments") and tool_call.function.arguments:
                        existing["function"]["arguments"] += tool_call.function.arguments
            elif tool_id:
                if tool_id not in tool_calls_dict:
                    tool_calls_dict[tool_id] = {
                        "id": tool_id,
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }

                if hasattr(tool_call, "function") and tool_call.function:
                    if hasattr(tool_call.function, "name") and tool_call.function.name:
                        tool_calls_dict[tool_id]["function"]["name"] = tool_call.function.name
                    if hasattr(tool_call.function, "arguments") and tool_call.function.arguments:
                        tool_calls_dict[tool_id]["function"]["arguments"] += tool_call.function.arguments

    def _find_tool(self, tool_name):
        return self.tool_manager.find_tool(tool_name)

    @staticmethod
    def _extract_finish_visible_output(serialized_result, *, suppress_summary, has_visible_response):
        """Return visible text contributed by finish, if any."""
        try:
            result_obj = json.loads(serialized_result)
            normalized = normalize_tool_result("finish", result_obj)
            if normalized.ok:
                candidate = AsyncAIWorker._finish_answer_from_payload(normalized.to_dict())
                if candidate and (not suppress_summary or not has_visible_response):
                    return candidate
        except Exception:
            candidate = ""
            if candidate and (not suppress_summary or not has_visible_response):
                return candidate
        return None

    @staticmethod
    def _finish_answer_from_payload(payload) -> str:
        """Extract only explicit final-answer text from finish payloads."""
        if not isinstance(payload, dict):
            return ""
        for key in ("final_answer", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                text = value.strip()
                if text.lower() not in {"done", "finished", "complete", "completed", "ok", "success"}:
                    return text
        return ""

    @staticmethod
    def _summarize_external_tool_result(tool_name, serialized_result) -> str:
        """Create a concise user-facing fallback from the latest meaningful tool result."""
        if tool_name in {"finish", "update_task_plan", "get_task_plan"}:
            return ""
        try:
            payload = json.loads(serialized_result) if isinstance(serialized_result, str) else serialized_result
        except Exception:
            payload = serialized_result
        if not isinstance(payload, dict):
            return ""

        ok = bool(payload.get("ok", True)) and not payload.get("error")
        if tool_name in {"run_script", "get_script_job", "run_python_file"}:
            return AsyncAIWorker._summarize_script_result(payload, ok=ok)

        content = tool_result_content(payload, fallback_to_summary=False)
        summary = tool_result_summary(payload)
        if content and content != summary:
            return f"{summary}\n\n{content}" if summary else content
        return summary or ""

    @staticmethod
    def _summarize_script_result(payload, *, ok: bool) -> str:
        script_path = payload.get("script_path") or payload.get("filepath")
        script_name = script_path.split("/")[-1].split("\\")[-1] if script_path else "script"
        stdout = (payload.get("stdout") or payload.get("terminal") or "").strip()
        stderr = (payload.get("stderr") or "").strip()
        exit_code = payload.get("exit_code")
        duration = payload.get("duration_seconds")

        lines = []
        if ok:
            lines.append(f"脚本 `{script_name}` 已成功运行。")
        else:
            lines.append(f"脚本 `{script_name}` 运行失败。")
        if stdout:
            lines.append(f"输出结果:\n```text\n{stdout}\n```")
        if stderr:
            lines.append(f"错误输出:\n```text\n{stderr}\n```")
        meta = []
        if exit_code is not None:
            meta.append(f"退出码: {exit_code}")
        if duration is not None:
            meta.append(f"耗时: {duration} 秒")
        if meta:
            lines.append("，".join(meta) + "。")
        return "\n\n".join(lines)

    @staticmethod
    def _is_low_value_final_response(text: str) -> bool:
        normalized = " ".join((text or "").strip().lower().split())
        if not normalized:
            return True
        low_value_markers = (
            "task completed successfully",
            "task finished successfully",
            "all steps are completed",
            "let me now finish",
            "now i can mark",
            "i need to mark",
            "the task is done",
        )
        return any(marker in normalized for marker in low_value_markers)


    @staticmethod
    def _tool_result_succeeded(serialized_result) -> bool:
        try:
            result_obj = json.loads(serialized_result) if isinstance(serialized_result, str) else serialized_result
            return bool(normalize_tool_result("finish", result_obj).ok)
        except Exception:
            return False

    def _unresolved_failure_report(self):
        if not self.verification_coordinator or not self.agent_state:
            return None
        return self.verification_coordinator.get_unresolved_failure_report(self.agent_state)

    async def _run_tool(self, tool_name, args, apply_policy=True):
        """Execute a single tool with policy checks and task-progress bookkeeping."""
        if self.agent_state:
            self.agent_state.record_command(tool_name, args)
            self.agent_state.record_tool_attempt(tool_name, args)
        tool = self._find_tool(tool_name)
        if self.task_state_machine:
            self.task_state_machine.before_tool_call(tool_name, args, tool=tool)
        self._emit_task_progress()

        if apply_policy and self.execution_policy:
            policy_error = self.execution_policy.before_tool_call(self.agent_state, tool_name, args, tool=tool)
            if policy_error:
                if self.agent_state:
                    self.agent_state.record_error(policy_error)
                    self.agent_state.record_tool_result(tool_name, "failed", error=policy_error)
                if self.task_state_machine and tool_name == "finish":
                    self.task_state_machine.on_finish_blocked(policy_error)
                error_result = error_tool_result(tool_name, policy_error)
                self.tool_call_finished.emit(tool_name, "error", serialize_tool_result(error_result))
                self._emit_task_progress()
                return error_result

        if not tool:
            error_msg = f"Tool not found: {tool_name}"
            if self.agent_state:
                self.agent_state.record_error(error_msg)
                self.agent_state.record_tool_result(tool_name, "failed", error=error_msg)
            if self.task_state_machine:
                self.task_state_machine.on_tool_error(tool_name, error_msg, tool=tool)
            error_result = error_tool_result(tool_name, error_msg)
            self.tool_call_finished.emit(tool_name, "error", serialize_tool_result(error_result))
            self._emit_task_progress()
            return error_result

        try:
            self.tool_call_started.emit(tool_name, args)
            _tool, result = await self.tool_manager.execute(tool_name, args)

            if self.execution_policy:
                self.execution_policy.after_tool_call(self.agent_state, tool_name, args, result, tool=tool)
            if self.agent_state:
                self.agent_state.record_tool_result(tool_name, "completed", result=result)
            if self.task_state_machine:
                self.task_state_machine.after_tool_call(tool_name, args, result, tool=tool)

            result_str = serialize_tool_result(result)
            self.tool_call_finished.emit(tool_name, "success", result_str)
            self._emit_task_progress()
            return result
        except Exception as e:
            error_msg = f"Error executing tool: {str(e)}"
            if self.agent_state:
                self.agent_state.record_error(error_msg)
                self.agent_state.record_tool_result(tool_name, "failed", error=error_msg)
            if self.task_state_machine:
                self.task_state_machine.on_tool_error(tool_name, error_msg, tool=tool)
            error_result = error_tool_result(tool_name, error_msg)
            self.tool_call_finished.emit(tool_name, "error", serialize_tool_result(error_result))
            self._emit_task_progress()
            return error_result

    async def _execute_tool(self, tool_call):
        """Execute one OpenAI-format tool call and return a serialized tool result."""
        tool_name = tool_call.function.name
        arguments = tool_call.function.arguments

        try:
            args = json.loads(arguments) if arguments else {}
        except Exception as e:
            return serialize_tool_result(error_tool_result(tool_name, f"Error parsing tool arguments: {str(e)}"))

        if not self._is_tool_active(tool_name):
            result = self._inactive_tool_result(tool_name)
            if self.agent_state:
                self.agent_state.record_error(result.error)
                self.agent_state.record_tool_result(tool_name, "failed", error=result.error)
            if self.task_state_machine:
                self.task_state_machine.on_tool_error(tool_name, result.error, tool=self._find_tool(tool_name))
            self.tool_call_finished.emit(tool_name, "error", serialize_tool_result(result))
            return serialize_tool_result(result)

        if self.execution_policy:
            tool = self._find_tool(tool_name)
            policy_error = self.execution_policy.before_tool_call(self.agent_state, tool_name, args, tool=tool)
            if policy_error:
                if tool_name == "finish":
                    if self.task_state_machine:
                        self.task_state_machine.on_finish_blocked(policy_error)
                    auto_request = (
                        self.verification_coordinator.get_auto_verification_request(self.agent_state)
                        if self.verification_coordinator
                        else self.execution_policy.get_auto_verification_request(self.agent_state)
                    )
                    if auto_request:
                        auto_result = await self._run_tool(
                            auto_request["tool_name"],
                            auto_request["args"],
                            apply_policy=True,
                        )
                        if tool_result_ok(auto_result):
                            finish_result = await self._run_tool(tool_name, args, apply_policy=True)
                            return serialize_tool_result(finish_result)

                        failure_summary = policy_error
                        if auto_result is not None:
                            failure_summary = tool_result_summary(auto_result) or tool_result_error(auto_result) or failure_summary
                        wrapped = error_tool_result(
                            tool_name,
                            policy_error,
                            auto_verification_attempted=auto_request,
                            auto_verification_result=tool_result_to_dict(auto_result) if auto_result is not None else None,
                            summary=failure_summary,
                        )
                        self.tool_call_finished.emit(tool_name, "error", serialize_tool_result(wrapped))
                        return serialize_tool_result(wrapped)

                if self.agent_state:
                    self.agent_state.record_error(policy_error)
                    self.agent_state.record_tool_result(tool_name, "failed", error=policy_error)
                if self.task_state_machine:
                    self.task_state_machine.on_tool_error(tool_name, policy_error, tool=tool)
                error_result = error_tool_result(tool_name, policy_error)
                self.tool_call_finished.emit(tool_name, "error", serialize_tool_result(error_result))
                return serialize_tool_result(error_result)

        result = await self._run_tool(tool_name, args, apply_policy=False)
        return serialize_tool_result(result)

    async def _stream_response(self, messages, tool_configs=None, use_tools=True):
        """Create one streamed provider response with or without tool calling enabled."""
        params = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        if use_tools and tool_configs:
            params["tools"] = tool_configs
            params["tool_choice"] = "auto"
        else:
            params["tool_choice"] = "none"

        try:
            return await self._client.chat.completions.create(**params)
        except Exception as exc:
            if "stream_options" not in str(exc):
                raise
            params.pop("stream_options", None)
            print("[Token Usage] provider rejected stream_options.include_usage; retrying stream without usage.")
            return await self._client.chat.completions.create(**params)

    def _usage_to_dict(self, usage):
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        for method_name in ("model_dump", "dict"):
            method = getattr(usage, method_name, None)
            if callable(method):
                try:
                    return method()
                except Exception:
                    pass
        result = {}
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_tokens_details",
            "completion_tokens_details",
        ):
            value = getattr(usage, key, None)
            if value is not None:
                result[key] = value
        return result

    def _extract_usage(self, response_or_chunk):
        if response_or_chunk is None:
            return {}
        if isinstance(response_or_chunk, dict):
            return self._usage_to_dict(response_or_chunk.get("usage"))
        return self._usage_to_dict(getattr(response_or_chunk, "usage", None))

    def _nested_usage_value(self, usage, parent_key, child_key):
        details = usage.get(parent_key) if isinstance(usage, dict) else None
        details = self._usage_to_dict(details)
        value = details.get(child_key)
        try:
            return int(value or 0)
        except Exception:
            return 0

    def _record_token_usage(self, usage, source):
        usage = self._usage_to_dict(usage)
        if not usage:
            return

        def as_int(key):
            try:
                return int(usage.get(key) or 0)
            except Exception:
                return 0

        event = {
            "source": source,
            "prompt_tokens": as_int("prompt_tokens"),
            "completion_tokens": as_int("completion_tokens"),
            "total_tokens": as_int("total_tokens"),
            "cached_tokens": self._nested_usage_value(usage, "prompt_tokens_details", "cached_tokens"),
            "reasoning_tokens": self._nested_usage_value(usage, "completion_tokens_details", "reasoning_tokens"),
        }
        self.token_usage_events.append(event)
        cached = f", cached={event['cached_tokens']}" if event["cached_tokens"] else ""
        reasoning = f", reasoning={event['reasoning_tokens']}" if event["reasoning_tokens"] else ""
        print(
            "[Token Usage] "
            f"{source}: input={event['prompt_tokens']}, "
            f"output={event['completion_tokens']}, "
            f"total={event['total_tokens']}"
            f"{cached}{reasoning}"
        )

    def _print_token_usage_summary(self):
        if not self.token_usage_events:
            print("[Token Usage] No usage data returned by provider.")
            return
        prompt_tokens = sum(event.get("prompt_tokens", 0) for event in self.token_usage_events)
        completion_tokens = sum(event.get("completion_tokens", 0) for event in self.token_usage_events)
        total_tokens = sum(event.get("total_tokens", 0) for event in self.token_usage_events)
        cached_tokens = sum(event.get("cached_tokens", 0) for event in self.token_usage_events)
        reasoning_tokens = sum(event.get("reasoning_tokens", 0) for event in self.token_usage_events)
        cached = f", cached={cached_tokens}" if cached_tokens else ""
        reasoning = f", reasoning={reasoning_tokens}" if reasoning_tokens else ""
        print(
            "[Token Usage] total: "
            f"input={prompt_tokens}, output={completion_tokens}, total={total_tokens}"
            f"{cached}{reasoning}, rounds={len(self.token_usage_events)}"
        )

    async def _handle_stream_with_tools(self, messages, tool_configs, iteration=None):
        """Stream one assistant turn that may emit tool calls."""
        self._reset_stream_parse_state()
        accumulator = {"reasoning": "", "content": ""}
        tool_calls_dict = {}

        response = await self._stream_response(messages, tool_configs, use_tools=True)
        try:
            async for chunk in response:
                usage = self._extract_usage(chunk)
                if usage:
                    source = f"react_round_{iteration}" if iteration is not None else "react_round"
                    self._record_token_usage(usage, source)

                if self._is_stopped:
                    try:
                        await response.aclose()
                    except Exception:
                        pass
                    self.stopped.emit()
                    return None, None, None

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                self._process_stream_chunk(delta, accumulator)
                self._process_tool_calls_stream(delta, tool_calls_dict)
        finally:
            if response:
                try:
                    await asyncio.shield(self._safe_aclose(response))
                except Exception:
                    pass

        return accumulator["reasoning"], accumulator["content"], tool_calls_dict

    async def _safe_aclose(self, obj):
        """Safely close an async resource, checking if the event loop is still running."""
        if not obj:
            return

        try:
            loop = asyncio.get_running_loop()
            if not loop.is_running():
                return
        except RuntimeError:
            return

        try:
            await obj.aclose()
        except Exception:
            pass

    async def _handle_stream_no_tools(self, messages):
        """Stream one assistant turn without tool calling."""
        self._reset_stream_parse_state()
        accumulator = {"reasoning": "", "content": ""}

        response = await self._stream_response(messages, use_tools=False)
        try:
            async for chunk in response:
                usage = self._extract_usage(chunk)
                if usage:
                    self._record_token_usage(usage, "stream_no_tools")

                if self._is_stopped:
                    try:
                        await response.aclose()
                    except Exception:
                        pass
                    self.stopped.emit()
                    return None, None

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                self._process_stream_chunk(delta, accumulator)
        finally:
            if response:
                try:
                    await asyncio.shield(self._safe_aclose(response))
                except Exception:
                    pass

        return accumulator["reasoning"], accumulator["content"]

    def _build_assistant_message(self, content, reasoning=None, tool_calls=None):
        """Build an assistant message payload compatible with the next provider turn."""
        message = {"role": "assistant"}
        if content:
            message["content"] = content
        if reasoning:
            message["reasoning_content"] = reasoning
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    def _convert_tool_calls_to_openai_format(self, tool_calls_dict):
        """Convert streamed tool-call fragments into typed OpenAI tool-call objects."""
        from openai.types.chat import ChatCompletionMessageToolCall
        from openai.types.chat.chat_completion_message_tool_call import Function

        tool_calls = []
        for tool_id, tool_data in tool_calls_dict.items():
            tool_call = ChatCompletionMessageToolCall(
                id=tool_id,
                type=tool_data["type"],
                function=Function(
                    name=tool_data["function"]["name"],
                    arguments=tool_data["function"]["arguments"],
                ),
            )
            tool_calls.append(tool_call)
        return tool_calls

    async def _run_react_loop(self, messages, tool_configs):
        """Run the streaming ReAct loop until finish or max rounds."""
        from openai.types.chat import ChatCompletionMessageToolCall
        from openai.types.chat.chat_completion_message_tool_call import Function

        iteration = 0
        final_response = ""
        latest_external_tool_summary = ""

        while iteration < self.max_rounds:
            iteration += 1
            self._reset_stream_parse_state()

            print(f"\n{'=' * 60}")
            print(f"=== ReAct Loop Iteration {iteration} ===")
            print(f"{'=' * 60}")

            tool_configs = self._build_tool_configs()
            self._maybe_append_tool_selection_guidance(messages)
            self._print_prompt_debug(messages, tool_configs, iteration=iteration)

            reasoning, content, tool_calls_dict = await self._handle_stream_with_tools(
                messages,
                tool_configs,
                iteration=iteration,
            )
            if reasoning is None:
                return final_response

            if content:
                final_response = content

            if not tool_calls_dict:
                print("No tool calls, finishing...")
                unresolved_report = self._unresolved_failure_report()
                if unresolved_report:
                    return unresolved_report
                return final_response

            print(f"Tool calls detected: {list(tool_calls_dict.keys())}")

            tool_calls = self._convert_tool_calls_to_openai_format(tool_calls_dict)
            assistant_message = self._build_assistant_message(content, reasoning, tool_calls)
            messages.append(assistant_message)

            finish_called = False
            finish_result = None
            suppress_finish_summary = iteration <= 2
            has_visible_response = bool((final_response or "").strip())

            for tool_id, tool_data in tool_calls_dict.items():
                if self._is_stopped:
                    self.stopped.emit()
                    return final_response

                tool_name = tool_data["function"]["name"]
                tool_args_str = tool_data["function"]["arguments"]
                mock_tool_call = ChatCompletionMessageToolCall(
                    id=tool_id,
                    type="function",
                    function=Function(name=tool_name, arguments=tool_args_str),
                )

                result = await self._execute_tool(mock_tool_call)
                external_summary = self._summarize_external_tool_result(tool_name, result)
                if external_summary:
                    latest_external_tool_summary = external_summary

                if tool_name == "finish":
                    if self._tool_result_succeeded(result):
                        finish_called = True
                        finish_result = self._extract_finish_visible_output(
                            result,
                            suppress_summary=suppress_finish_summary,
                            has_visible_response=has_visible_response,
                        )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": result,
                    }
                )

            if finish_called:
                print("finish called, exiting loop.")
                if finish_result:
                    return finish_result
                if final_response and not self._is_low_value_final_response(final_response):
                    return final_response
                if latest_external_tool_summary:
                    return latest_external_tool_summary
                return final_response

            if self.execution_policy:
                guidance = self.execution_policy.finish_guidance(self.agent_state)
                if guidance:
                    messages.append({"role": "system", "content": guidance})

            self.round_finished.emit()

        unresolved_report = self._unresolved_failure_report()
        if unresolved_report:
            return unresolved_report
        return final_response

    async def run_async(self):
        """Run the worker end-to-end and emit the final visible response."""
        sniffio.current_async_library_cvar.set("asyncio")

        try:
            self._client = self._init_client()
            if self.task_state_machine:
                self.task_state_machine.mark_execution_started()
            self._emit_task_progress()
            messages = self._build_messages()
            tool_configs = self._build_tool_configs()

            if self.stream:
                if tool_configs:
                    result = await self._run_react_loop(messages, tool_configs)
                else:
                    _reasoning, content = await self._handle_stream_no_tools(messages)
                    result = content if content else ""

                if not self._is_stopped:
                    if self.task_state_machine and self.agent_state and self.agent_state.can_finish():
                        self.task_state_machine.complete_task("response emitted")
                    self._emit_task_progress()
                    self.finished.emit(result)
            else:
                response = await self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    stream=False,
                )
                self._record_token_usage(self._extract_usage(response), "non_stream")
                if response.choices:
                    if self.task_state_machine and self.agent_state and self.agent_state.can_finish():
                        self.task_state_machine.complete_task("non-stream response emitted")
                    self._emit_task_progress()
                    self.finished.emit(response.choices[0].message.content)
                else:
                    self.error.emit("Received empty response choices from provider.")

        except Exception as e:
            if self.task_state_machine:
                self.task_state_machine.fail_task(str(e))
            self._emit_task_progress()
            self.error.emit(str(e))
        finally:
            self._print_token_usage_summary()
            if self._client:
                try:
                    await asyncio.shield(self._safe_aclose(self._client))
                except Exception:
                    pass
                self._client = None
