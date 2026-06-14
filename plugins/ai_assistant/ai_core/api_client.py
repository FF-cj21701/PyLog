from PySide6.QtCore import QObject, Signal
import asyncio
import json

import sniffio

from .task_domain_router import TaskDomainRouter
from .tool_dispatcher import ToolDispatcher
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

try:
    import openai

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class AsyncAIWorker(QObject):
    """Async chat worker coordinating streaming, tools, planning, and verification."""

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
        self.tool_dispatcher = ToolDispatcher(self.tools)
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
        messages.append({"role": "user", "content": self.prompt})
        return messages

    def _build_tool_configs(self):
        """Build routed and ranked tool configs for the current task context."""
        tool_configs = []
        ranked_specs = self.tool_dispatcher.list_ranked_specs(
            state=self.agent_state,
            strategy=self.tool_selection,
        )
        routed_specs = self.domain_router.route_specs(
            ranked_specs,
            prompt=self.prompt,
            history=self.history,
            state=self.agent_state,
        )
        for spec in routed_specs:
            tool_configs.append(spec.to_openai_tool())
        return tool_configs

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
            if messages and messages[-1].get("role") == "system" and messages[-1].get("content") == guidance:
                continue
            messages.append({"role": "system", "content": guidance})

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
        return self.tool_dispatcher.find_tool(tool_name)

    @staticmethod
    def _extract_finish_visible_output(serialized_result, *, suppress_summary, has_visible_response):
        """Return visible text contributed by tool_finish, if any."""
        try:
            result_obj = json.loads(serialized_result)
            normalized = normalize_tool_result("tool_finish", result_obj)
            if normalized.ok:
                candidate = tool_result_content(normalized, fallback_to_summary=False)
                if candidate and (not suppress_summary or not has_visible_response):
                    return candidate
        except Exception:
            candidate = tool_result_content(serialized_result, fallback_to_summary=False)
            if candidate and (not suppress_summary or not has_visible_response):
                return candidate
        return None

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
                if self.task_state_machine and tool_name == "tool_finish":
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
            _tool, result = await self.tool_dispatcher.execute(tool_name, args)

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

        if self.execution_policy:
            tool = self._find_tool(tool_name)
            policy_error = self.execution_policy.before_tool_call(self.agent_state, tool_name, args, tool=tool)
            if policy_error:
                if tool_name == "tool_finish":
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
        }

        if use_tools and tool_configs:
            params["tools"] = tool_configs
            params["tool_choice"] = "auto"
        else:
            params["tool_choice"] = "none"

        return await self._client.chat.completions.create(**params)

    async def _handle_stream_with_tools(self, messages, tool_configs):
        """Stream one assistant turn that may emit tool calls."""
        self._reset_stream_parse_state()
        accumulator = {"reasoning": "", "content": ""}
        tool_calls_dict = {}

        response = await self._stream_response(messages, tool_configs, use_tools=True)
        try:
            async for chunk in response:
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
        """Run the streaming ReAct loop until tool_finish or max rounds."""
        from openai.types.chat import ChatCompletionMessageToolCall
        from openai.types.chat.chat_completion_message_tool_call import Function

        iteration = 0
        final_response = ""

        while iteration < self.max_rounds:
            iteration += 1
            self._reset_stream_parse_state()

            print(f"\n{'=' * 60}")
            print(f"=== ReAct Loop Iteration {iteration} ===")
            print(f"{'=' * 60}")

            tool_configs = self._build_tool_configs()
            self._maybe_append_tool_selection_guidance(messages)

            reasoning, content, tool_calls_dict = await self._handle_stream_with_tools(messages, tool_configs)
            if reasoning is None:
                return final_response

            if content:
                final_response = content

            if not tool_calls_dict:
                print("No tool calls, finishing...")
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

                if tool_name == "tool_finish":
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
                print("tool_finish called, exiting loop.")
                return finish_result if finish_result else final_response

            if self.execution_policy:
                guidance = self.execution_policy.finish_guidance(self.agent_state)
                if guidance:
                    messages.append({"role": "system", "content": guidance})

            self.round_finished.emit()

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
            if self._client:
                try:
                    await asyncio.shield(self._safe_aclose(self._client))
                except Exception:
                    pass
                self._client = None
