from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Signal

from .events import AgentEvent, AgentEventType


class AgentRuntime(QObject):
    """Thin runtime boundary around the current worker implementation.

    Phase 1 keeps behavior unchanged while giving future agent-loop, context,
    tool, and policy work a stable integration seam.
    """

    event = Signal(object)
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

    def __init__(self, worker: Any):
        super().__init__()
        self.worker = worker
        self._connect_worker_signals()

    async def run_async(self):
        return await self.worker.run_async()

    def stop(self) -> None:
        if hasattr(self.worker, "stop"):
            self.worker.stop()

    def get_tool_inventory_payload(self) -> dict:
        if hasattr(self.worker, "get_tool_inventory_payload"):
            return self.worker.get_tool_inventory_payload()
        return {"summary": {"total": 0}, "tools": []}

    def _connect_worker_signals(self) -> None:
        self.worker.finished.connect(self._on_finished)
        self.worker.reasoning_update.connect(self._on_reasoning_update)
        self.worker.content_update.connect(self._on_content_update)
        self.worker.error.connect(self._on_error)
        self.worker.stopped.connect(self._on_stopped)
        self.worker.tool_call_started.connect(self._on_tool_call_started)
        self.worker.tool_call_finished.connect(self._on_tool_call_finished)
        self.worker.round_finished.connect(self._on_round_finished)
        self.worker.task_progress.connect(self._on_task_progress)
        if hasattr(self.worker, "system_message"):
            self.worker.system_message.connect(self._on_system_message)

    def _emit_event(self, event: AgentEvent) -> None:
        self.event.emit(event)

    def _on_finished(self, content: str) -> None:
        self._emit_event(AgentEvent.simple(AgentEventType.FINISHED, content))
        self.finished.emit(content)

    def _on_reasoning_update(self, content: str) -> None:
        self._emit_event(AgentEvent.reasoning_delta(content))
        self.reasoning_update.emit(content)

    def _on_content_update(self, content: str) -> None:
        self._emit_event(AgentEvent.message_delta(content))
        self.content_update.emit(content)

    def _on_error(self, message: str) -> None:
        self._emit_event(AgentEvent.simple(AgentEventType.ERROR, message))
        self.error.emit(message)

    def _on_stopped(self) -> None:
        self._emit_event(AgentEvent.simple(AgentEventType.STOPPED))
        self.stopped.emit()

    def _on_system_message(self, message: str) -> None:
        self._emit_event(AgentEvent.simple(AgentEventType.SYSTEM_MESSAGE, message))
        self.system_message.emit(message)

    def _on_tool_call_started(self, tool_name: str, args: dict) -> None:
        self._emit_event(AgentEvent.tool_started(tool_name, args))
        self.tool_call_started.emit(tool_name, args)

    def _on_tool_call_finished(self, tool_name: str, status: str, result: str) -> None:
        self._emit_event(AgentEvent.finished(tool_name, status, result))
        self.tool_call_finished.emit(tool_name, status, result)

    def _on_round_finished(self) -> None:
        self._emit_event(AgentEvent.simple(AgentEventType.ROUND_FINISHED))
        self.round_finished.emit()

    def _on_task_progress(self, payload: dict) -> None:
        self._emit_event(AgentEvent.task_progress(payload))
        self.task_progress.emit(payload)
