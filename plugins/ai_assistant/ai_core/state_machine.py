from __future__ import annotations

from typing import Any, Dict, Optional

from .policy import is_verification_tool, is_write_tool
from .task_plan import TaskPlanner, find_plan_step_id_for_tool
from .tool_result import tool_result_error, tool_result_ok


FINAL_TASK_STATES = {"completed", "failed", "cancelled"}


class TaskStateMachine:
    """Task lifecycle controller coordinating AI-authored plan progress and verification gates."""

    def __init__(self, agent_state):
        self.agent_state = agent_state
        self.task_planner = TaskPlanner()

    def start_task(self, task: str, mode: str = "chat") -> None:
        self.agent_state.start_task(task, mode=mode)
        if self.task_planner.should_enable_task_plan(task):
            fallback_plan = self.task_planner.create_plan(task, state=self.agent_state)
            self.agent_state.set_task_plan(fallback_plan, source="fallback")
        self.transition("planning", reason="task accepted")

    def apply_model_plan(self, payload: Any) -> bool:
        """Install a model-authored plan when it is rich enough to drive the task card."""
        if not self.agent_state.current_task:
            return False

        normalized = self.task_planner.parse_model_plan_payload(payload)
        if not normalized or len(normalized.get("steps") or []) < 3:
            return False

        plan = self.task_planner.build_model_plan(
            self.agent_state.current_task,
            normalized,
            state=self.agent_state,
        )
        if not plan.steps:
            return False

        self.agent_state.update_task_plan(plan, preserve_progress=True, source="model")
        return True

    def mark_execution_started(self) -> None:
        if self.agent_state.task_state in {"idle", "planning"}:
            self.transition("executing", reason="worker started")

    def before_tool_call(self, tool_name: str, args: Optional[Dict[str, Any]] = None, tool=None) -> None:
        """Advance task state before a tool runs."""
        if self.agent_state.task_state in FINAL_TASK_STATES:
            return

        if tool_name == "finish":
            self.agent_state.finish_requested = True
            if self.agent_state.verification_required:
                self.transition("awaiting_verification", reason="finish requested before verification")
            return

        if self.agent_state.task_state in {"planning", "idle"}:
            self.transition("executing", reason=f"calling {tool_name}")
            return

        if self.agent_state.task_state == "repairing" and not is_verification_tool(tool_name, tool=tool):
            self.transition("executing", reason=f"repair step via {tool_name}")

    def after_tool_call(self, tool_name: str, args: Optional[Dict[str, Any]], result: Any, tool=None) -> None:
        """Advance task state after a successful or failed tool call."""
        if self.agent_state.task_state in FINAL_TASK_STATES:
            return

        ok = tool_result_ok(result)

        if not ok:
            self.on_tool_error(tool_name, tool_result_error(result), tool=tool)
            return

        if is_write_tool(tool_name, tool=tool):
            self._advance_plan_for_success(tool_name, tool=tool)
            self.agent_state.record_side_effect(tool_name, args=args, result=result)
            self.transition("awaiting_verification", reason=f"{tool_name} modified state")
            return

        if is_verification_tool(tool_name, tool=tool):
            if self.agent_state.verification_required:
                verify_step = self.agent_state.get_plan_step("verify")
                if verify_step:
                    self.agent_state.mark_plan_step_failed(str(verify_step.get("id")), notes=tool_result_error(result))
                implement_step = self.agent_state.get_plan_step("implement")
                if implement_step:
                    self.agent_state.mark_plan_step_in_progress(str(implement_step.get("id")), force=True)
                self.transition("repairing", reason=f"{tool_name} requires follow-up repair")
            else:
                self._advance_plan_for_success(tool_name, tool=tool)
                self.transition("executing", reason=f"{tool_name} passed")
            return

        if tool_name == "finish":
            complete_step = self.agent_state.get_plan_step("complete")
            if complete_step:
                self.agent_state.mark_plan_step_completed(str(complete_step.get("id")))
            self.transition("completed", reason="finish tool succeeded")
            return

        self._advance_plan_for_success(tool_name, tool=tool)

        if self.agent_state.task_state in {"idle", "planning"}:
            self.transition("executing", reason=f"{tool_name} succeeded")

    def on_tool_error(self, tool_name: str, error: Optional[str] = None, tool=None) -> None:
        """Route tool failures back into the plan and repair flow."""
        if self.agent_state.task_state in FINAL_TASK_STATES:
            return

        if is_verification_tool(tool_name, tool=tool):
            verify_step = self.agent_state.get_plan_step("verify")
            if verify_step:
                self.agent_state.mark_plan_step_failed(str(verify_step.get("id")), notes=error)
            implement_step = self.agent_state.get_plan_step("implement")
            if implement_step:
                self.agent_state.mark_plan_step_in_progress(str(implement_step.get("id")), notes=error, force=True)
            self.transition("repairing", reason=error or f"{tool_name} failed")
            return

        if self.agent_state.task_state == "planning":
            self.transition("executing", reason=error or f"{tool_name} failed during startup")

    def on_finish_blocked(self, reason: str) -> None:
        self.agent_state.finish_requested = True
        if self.agent_state.verification_required:
            self.transition("awaiting_verification", reason=reason)

    def complete_task(self, reason: str = "task completed") -> None:
        self.transition("completed", reason=reason)

    def fail_task(self, reason: str) -> None:
        self.transition("failed", reason=reason)

    def cancel_task(self, reason: str = "task cancelled") -> None:
        self.transition("cancelled", reason=reason)

    def transition(self, new_state: str, reason: Optional[str] = None) -> None:
        """Apply a guarded task-state transition."""
        current = self.agent_state.task_state
        if current == new_state:
            self.agent_state.set_task_state(new_state, reason)
            return

        if new_state == "completed" and self.agent_state.verification_required:
            self.agent_state.set_task_state("awaiting_verification", reason or "verification still required")
            return

        self.agent_state.set_task_state(new_state, reason)

    def _advance_plan_for_success(self, tool_name: str, tool=None) -> None:
        if not self.agent_state.current_plan:
            return

        step_id = find_plan_step_id_for_tool(self.agent_state.current_plan, tool_name, tool=tool)
        if not step_id:
            return

        step = self.agent_state.get_plan_step_by_id(step_id)
        if not step:
            return

        self._complete_prior_open_steps(step_id, tool_name)
        self.agent_state.mark_plan_step_completed(str(step.get("id")))

        if step.get("kind") in {"implement", "script_edit", "run"}:
            verify_step = self.agent_state.get_plan_step("verify")
            if verify_step and verify_step.get("status") == "pending":
                self.agent_state.mark_plan_step_in_progress(str(verify_step.get("id")), force=True)

    def _complete_prior_open_steps(self, target_step_id: str, tool_name: str) -> None:
        for step in self.agent_state.current_plan:
            if step.get("id") == target_step_id:
                return
            if step.get("status") in {"pending", "in_progress"}:
                self.agent_state.mark_plan_step_completed(
                    str(step.get("id")),
                    notes=f"Auto-advanced after {tool_name} succeeded",
                )
