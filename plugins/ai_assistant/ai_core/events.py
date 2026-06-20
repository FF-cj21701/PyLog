from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class AgentEventType:
    MESSAGE_DELTA = "message_delta"
    REASONING_DELTA = "reasoning_delta"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    ROUND_FINISHED = "round_finished"
    TASK_PROGRESS = "task_progress"
    SYSTEM_MESSAGE = "system_message"
    FINISHED = "finished"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True)
class AgentEvent:
    """Provider-neutral event emitted by the native PyLog agent runtime."""

    type: str
    content: str = ""
    tool_name: Optional[str] = None
    status: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def message_delta(cls, content: str) -> "AgentEvent":
        return cls(type=AgentEventType.MESSAGE_DELTA, content=content or "")

    @classmethod
    def reasoning_delta(cls, content: str) -> "AgentEvent":
        return cls(type=AgentEventType.REASONING_DELTA, content=content or "")

    @classmethod
    def tool_started(cls, tool_name: str, args: Optional[Dict[str, Any]] = None) -> "AgentEvent":
        return cls(
            type=AgentEventType.TOOL_STARTED,
            tool_name=tool_name,
            payload={"args": dict(args or {})},
        )

    @classmethod
    def tool_finished(cls, tool_name: str, status: str, result: str) -> "AgentEvent":
        return cls(
            type=AgentEventType.TOOL_FINISHED,
            content=result or "",
            tool_name=tool_name,
            status=status,
        )

    @classmethod
    def task_progress(cls, payload: Optional[Dict[str, Any]] = None) -> "AgentEvent":
        return cls(type=AgentEventType.TASK_PROGRESS, payload=dict(payload or {}))

    @classmethod
    def simple(cls, event_type: str, content: str = "") -> "AgentEvent":
        return cls(type=event_type, content=content or "")
