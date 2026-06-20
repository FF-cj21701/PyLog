from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .task_plan import (
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_IN_PROGRESS,
    TaskPlan,
)
from .tool_result import tool_result_error, tool_result_ok, tool_result_to_dict


@dataclass
class AgentState:
    """Runtime state shared across planning, tool execution, and verification."""

    current_task: str = ""
    current_plan: List[Dict[str, Any]] = field(default_factory=list)
    current_plan_step_id: Optional[str] = None
    current_plan_source: Optional[str] = None
    current_plan_domain: Optional[str] = None
    task_plan_enabled: bool = False
    task_state: str = "idle"
    task_state_reason: Optional[str] = None
    files_read: Set[str] = field(default_factory=set)
    files_modified: Set[str] = field(default_factory=set)
    pending_patches: List[Dict[str, Any]] = field(default_factory=list)
    tool_steps: List[Dict[str, Any]] = field(default_factory=list)
    side_effects: List[Dict[str, Any]] = field(default_factory=list)
    state_transitions: List[Dict[str, Any]] = field(default_factory=list)
    last_command: Optional[Dict[str, Any]] = None
    last_verification: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None
    failure_count: int = 0
    mode: str = "chat"
    dirty: bool = False
    verification_required: bool = False
    finish_requested: bool = False

    def start_task(self, task: str, mode: str = "chat") -> None:
        """Reset runtime state for a newly accepted task."""
        self.current_task = task or ""
        self.mode = mode or "chat"
        self.current_plan = []
        self.current_plan_step_id = None
        self.current_plan_source = None
        self.current_plan_domain = None
        self.task_plan_enabled = False
        self.task_state = "idle"
        self.task_state_reason = None
        self.files_read.clear()
        self.files_modified.clear()
        self.pending_patches.clear()
        self.tool_steps.clear()
        self.side_effects.clear()
        self.state_transitions.clear()
        self.last_command = None
        self.last_verification = None
        self.last_error = None
        self.failure_count = 0
        self.dirty = False
        self.verification_required = False
        self.finish_requested = False

    def set_task_state(self, state: str, reason: Optional[str] = None) -> None:
        """Record a task-state transition if it changes visible state."""
        if self.task_state == state and self.task_state_reason == reason:
            return
        self.task_state = state
        self.task_state_reason = reason
        self.state_transitions.append({
            "state": state,
            "reason": reason,
        })

    def set_task_plan(self, plan: TaskPlan, source: str = "model") -> None:
        """Install a fresh task plan and point at its first step."""
        self.current_plan = plan.to_dict_list()
        self.current_plan_step_id = self.current_plan[0]["id"] if self.current_plan else None
        self.current_plan_source = source
        self.current_plan_domain = plan.domain
        self.task_plan_enabled = True

    def update_task_plan(self, plan: TaskPlan, preserve_progress: bool = True, source: Optional[str] = None) -> None:
        """Replace the current plan while optionally preserving step progress by position."""
        old_steps = list(self.current_plan)
        current_index = self.get_current_plan_step_index()

        self.current_plan = plan.to_dict_list()
        self.current_plan_domain = plan.domain
        if source:
            self.current_plan_source = source
        self.task_plan_enabled = True

        if preserve_progress:
            for index, step in enumerate(self.current_plan):
                if index >= len(old_steps):
                    continue
                old = old_steps[index]
                if old.get("status") not in {None, "pending"}:
                    step["status"] = old.get("status")
                if old.get("notes") and not step.get("notes"):
                    step["notes"] = old.get("notes")

        if current_index is not None and current_index < len(self.current_plan):
            self.current_plan_step_id = self.current_plan[current_index].get("id")
            return

        next_step = self._next_open_plan_step()
        self.current_plan_step_id = next_step.get("id") if next_step else (self.current_plan[0]["id"] if self.current_plan else None)

    def get_plan_step_by_id(self, step_id: str) -> Optional[Dict[str, Any]]:
        for step in self.current_plan:
            if step.get("id") == step_id:
                return step
        return None

    def get_plan_step(self, kind: str) -> Optional[Dict[str, Any]]:
        for step in self.current_plan:
            if step.get("kind") == kind or step.get("id") == kind:
                return step
        return None

    def get_plan_step_by_index(self, step_index: int) -> Optional[Dict[str, Any]]:
        if 0 <= step_index < len(self.current_plan):
            return self.current_plan[step_index]
        return None

    def get_current_plan_step_index(self) -> Optional[int]:
        if not self.current_plan_step_id:
            return None
        for index, step in enumerate(self.current_plan):
            if step.get("id") == self.current_plan_step_id:
                return index
        return None

    def update_plan_step(
        self,
        *,
        step_id: Optional[str] = None,
        step_index: Optional[int] = None,
        status: Optional[str] = None,
        title: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update one plan step by id or index."""
        step = self.get_plan_step_by_id(step_id) if step_id else None
        if step is None and step_index is not None:
            step = self.get_plan_step_by_index(step_index)
        if not step:
            return None

        if title is not None:
            step["title"] = title
        if notes is not None:
            step["notes"] = notes

        if status is not None:
            if status == PLAN_STATUS_IN_PROGRESS:
                self.mark_plan_step_in_progress(str(step.get("id")), notes=notes, force=True)
                step = self.get_plan_step_by_id(str(step.get("id"))) or step
            elif status == PLAN_STATUS_COMPLETED:
                self.mark_plan_step_completed(str(step.get("id")), notes=notes)
                step = self.get_plan_step_by_id(str(step.get("id"))) or step
            elif status == PLAN_STATUS_FAILED:
                self.mark_plan_step_failed(str(step.get("id")), notes=notes)
                step = self.get_plan_step_by_id(str(step.get("id"))) or step
            else:
                step["status"] = status
        return step

    def mark_plan_step_in_progress(self, step_id: str, notes: Optional[str] = None, force: bool = False) -> None:
        """Mark one plan step active and clear other in-progress markers."""
        step = self.get_plan_step_by_id(step_id) or self.get_plan_step(step_id)
        if not step:
            return
        for item in self.current_plan:
            if item.get("status") == PLAN_STATUS_IN_PROGRESS and item.get("id") != step.get("id"):
                item["status"] = "pending"
        if force or step.get("status") not in {PLAN_STATUS_COMPLETED, PLAN_STATUS_FAILED}:
            step["status"] = PLAN_STATUS_IN_PROGRESS
        if notes:
            step["notes"] = notes
        self.current_plan_step_id = step.get("id")

    def mark_plan_step_completed(self, step_id: str, notes: Optional[str] = None) -> None:
        """Mark a plan step complete and advance focus to the next open step."""
        step = self.get_plan_step_by_id(step_id) or self.get_plan_step(step_id)
        if not step:
            return
        step["status"] = PLAN_STATUS_COMPLETED
        if notes:
            step["notes"] = notes

        next_step = self._next_open_plan_step()
        if next_step:
            self.current_plan_step_id = next_step.get("id")
        elif self.current_plan and step.get("id") == self.current_plan[-1].get("id"):
            self.current_plan_step_id = step.get("id")

    def mark_plan_step_failed(self, step_id: str, notes: Optional[str] = None) -> None:
        """Mark a plan step as failed and keep focus on that failed step."""
        step = self.get_plan_step_by_id(step_id) or self.get_plan_step(step_id)
        if not step:
            return
        step["status"] = PLAN_STATUS_FAILED
        if notes:
            step["notes"] = notes
        self.current_plan_step_id = step.get("id")

    def fallback_plan_step(self, failed_step_id: str, fallback_step_id: str, notes: Optional[str] = None) -> None:
        """Fail one step and immediately move focus to its repair step."""
        self.mark_plan_step_failed(failed_step_id, notes=notes)
        self.mark_plan_step_in_progress(fallback_step_id, notes=notes, force=True)

    def get_task_progress_payload(self) -> Dict[str, Any]:
        """Return the UI-facing task-progress payload."""
        completed = len([step for step in self.current_plan if step.get("status") == PLAN_STATUS_COMPLETED])
        total = len(self.current_plan)
        current = None
        for step in self.current_plan:
            if step.get("id") == self.current_plan_step_id:
                current = step
                break
        visible_plan = bool(
            self.task_plan_enabled
            and self.current_plan_source != "fallback"
            and len(self.current_plan) >= 3
        )
        return {
            "task": self.current_task,
            "task_state": self.task_state,
            "task_state_reason": self.task_state_reason,
            "plan_enabled": self.task_plan_enabled,
            "plan_should_display": visible_plan,
            "plan_source": self.current_plan_source,
            "plan_domain": self.current_plan_domain,
            "current_step": current,
            "steps": list(self.current_plan),
            "completed_steps": completed,
            "total_steps": total,
        }

    def has_active_task_plan(self) -> bool:
        return bool(self.task_plan_enabled and len(self.current_plan) >= 3)

    def get_current_plan_step(self) -> Optional[Dict[str, Any]]:
        if not self.current_plan_step_id:
            return None
        return self.get_plan_step_by_id(self.current_plan_step_id)

    def get_incomplete_plan_steps(self) -> List[Dict[str, Any]]:
        return [
            step
            for step in self.current_plan
            if step.get("status") not in {PLAN_STATUS_COMPLETED, "skipped"}
        ]

    def _next_open_plan_step(self) -> Optional[Dict[str, Any]]:
        """Return the next step that is neither completed, failed, nor skipped."""
        for step in self.current_plan:
            if step.get("status") not in {PLAN_STATUS_COMPLETED, PLAN_STATUS_FAILED, "skipped"}:
                return step
        return None

    def mark_file_read(self, filepath: Optional[str]) -> None:
        if filepath:
            self.files_read.add(filepath)

    def mark_file_modified(self, filepath: Optional[str], patch_meta: Optional[Dict[str, Any]] = None) -> None:
        """Record a file mutation and require verification before finishing."""
        if filepath:
            self.files_modified.add(filepath)
        if patch_meta:
            self.pending_patches.append(patch_meta)
        self.dirty = True
        self.verification_required = True

    def record_side_effect(self, tool_name: str, args: Optional[Dict[str, Any]] = None, result: Any = None) -> None:
        """Store successful state-changing tool calls for later inspection."""
        self.side_effects.append({
            "tool": tool_name,
            "args": args or {},
            "result": result,
        })

    def record_command(self, command: str, args: Optional[Dict[str, Any]] = None) -> None:
        self.last_command = {
            "command": command,
            "args": args or {},
        }

    def record_tool_attempt(self, command: str, args: Optional[Dict[str, Any]] = None) -> None:
        self.tool_steps.append({
            "command": command,
            "args": args or {},
            "status": "in_progress",
        })

    def record_tool_result(
        self,
        command: str,
        status: str,
        result: Any = None,
        error: Optional[str] = None,
    ) -> None:
        for step in reversed(self.tool_steps):
            if step.get("command") == command and step.get("status") == "in_progress":
                step["status"] = status
                step["result"] = result
                step["error"] = error
                return

        self.tool_steps.append({
            "command": command,
            "args": {},
            "status": status,
            "result": result,
            "error": error,
        })

    def record_verification(self, result: Any) -> None:
        """Persist the latest verification outcome and update finish eligibility."""
        normalized = tool_result_to_dict(result)
        self.last_verification = normalized
        ok = tool_result_ok(result)
        self.last_error = None if ok else tool_result_error(result)
        if ok:
            self.failure_count = 0
            self.verification_required = False
            self.finish_requested = False
        else:
            self.failure_count += 1

    def record_error(self, message: str) -> None:
        self.last_error = message
        self.failure_count += 1

    def can_finish(self) -> bool:
        """Return whether the task may legally terminate now."""
        if not self.dirty:
            return True
        if self.verification_required:
            return False
        if not self.last_verification:
            return False
        return bool(self.last_verification.get("ok"))
