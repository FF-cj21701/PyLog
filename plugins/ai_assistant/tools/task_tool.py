import os
import importlib
from typing import Any, Dict, List, Optional

try:
    from .base_tool import BaseTool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool

try:
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        register_tool = importlib.import_module("registry").register_tool

try:
    from ..ai_core.task_plan import TaskPlan, TaskPlanStep, TaskPlanner
except ImportError:
    try:
        from plugins.ai_assistant.ai_core.task_plan import TaskPlan, TaskPlanStep, TaskPlanner
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        task_plan_module = importlib.import_module("ai_core.task_plan")
        TaskPlan = task_plan_module.TaskPlan
        TaskPlanStep = task_plan_module.TaskPlanStep
        TaskPlanner = task_plan_module.TaskPlanner

TASK_PLAN_MUTABLE_STATUSES = {"pending", "in_progress", "completed", "failed", "skipped"}


def _build_task_plan(
    agent_state,
    task_planner: TaskPlanner,
    steps: List[Dict[str, Any]],
) -> TaskPlan:
    current_task = getattr(agent_state, "current_task", "") or ""
    fallback_plan = task_planner.create_plan(current_task, state=agent_state)
    inferred_domain = fallback_plan.domain
    normalized_steps: List[TaskPlanStep] = []

    for index, item in enumerate(steps):
        if not isinstance(item, dict):
            raise ValueError(f"Step {index + 1} must be an object")

        title = str(item.get("title") or "").strip()
        if not title:
            raise ValueError(f"Step {index + 1} requires title")

        fallback_kind = fallback_plan.steps[index].kind if index < len(fallback_plan.steps) else f"step_{index + 1}"
        step_kind = str(item.get("kind") or "").strip() or fallback_kind
        step_id = str(item.get("id") or "").strip() or step_kind

        step = TaskPlanStep(
            id=step_id,
            kind=step_kind,
            title=title,
            notes=str(item.get("notes") or "").strip() or None,
        )
        normalized_steps.append(step)

    return TaskPlan(domain=inferred_domain, steps=normalized_steps)


def _current_plan_payload(agent_state) -> Dict[str, Any]:
    return {
        "task": agent_state.current_task,
        "task_state": agent_state.task_state,
        "current_step_id": agent_state.current_plan_step_id,
        "steps": list(agent_state.current_plan),
    }


@register_tool
class CreateTaskPlanTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None, ui_bridge=None, agent_state=None):
        super().__init__(
            "tool_create_task_plan",
            "Create the agent's short-lived execution plan for the current task. Use this as the default structured tracker for tasks that need 3 or more execution steps.",
            {
                "steps": {
                    "type": "array",
                    "description": "Ordered execution steps for the current task plan",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Stable step identifier", "nullable": True},
                            "title": {"type": "string", "description": "Short user-visible step title"},
                            "notes": {"type": "string", "description": "Optional notes for this step", "nullable": True},
                        },
                        "required": ["title"],
                    },
                },
            },
            metadata={
                "required_args": ["steps"],
                "side_effect_level": "none",
                "capability_tags": ["planning", "task_planning"],
                "domain_tags": ["agent"],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor
        self.ui_bridge = ui_bridge
        self.agent_state = agent_state
        self.task_planner = TaskPlanner()

    def execute(self, steps):
        if not self.agent_state:
            return {"error": "Agent state is unavailable for task planning"}

        if not isinstance(steps, list) or not steps:
            return {"error": "steps must be a non-empty list"}

        if len(steps) < 3:
            return {"error": "Task plan requires at least 3 steps"}

        if len(steps) > 8:
            return {"error": "Task plan cannot exceed 8 steps"}

        plan = self._build_task_plan(steps)
        self.agent_state.set_task_plan(plan, source="tool")

        return {
            "ok": True,
            "summary": f"Created task plan with {len(plan.steps)} steps",
            "data": {
                "steps": [step.to_dict() for step in plan.steps],
            },
        }

    def _build_task_plan(self, steps: List[Dict[str, Any]]) -> TaskPlan:
        return _build_task_plan(self.agent_state, self.task_planner, steps)


@register_tool
class GetTaskPlanTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None, ui_bridge=None, agent_state=None):
        super().__init__(
            "tool_get_task_plan",
            "Get the current agent execution plan and its live step statuses.",
            {},
            metadata={
                "side_effect_level": "read",
                "capability_tags": ["planning", "task_planning", "inspection"],
                "domain_tags": ["agent"],
            },
        )
        self.agent_state = agent_state

    def execute(self):
        if not self.agent_state or not self.agent_state.current_plan:
            return {
                "ok": True,
                "summary": "No active task plan",
                "data": {"steps": []},
            }

        return {
            "ok": True,
            "summary": f"Current task plan has {len(self.agent_state.current_plan)} steps",
            "data": _current_plan_payload(self.agent_state),
        }


@register_tool
class UpdateTaskPlanTool(BaseTool):
    VALID_STATUSES = {"pending", "in_progress", "completed", "failed", "skipped"}

    def __init__(self, main_window=None, tool_executor=None, ui_bridge=None, agent_state=None):
        super().__init__(
            "tool_update_task_plan",
            "Update the current agent task plan by marking an existing step as pending, in progress, completed, failed, or skipped.",
            {
                "step_id": {
                    "type": "string",
                    "description": "Target step id",
                    "nullable": True,
                },
                "step_index": {
                    "type": "integer",
                    "description": "Zero-based target step index when step_id is unknown",
                    "nullable": True,
                },
                "kind": {
                    "type": "string",
                    "description": "Legacy alias for the target step. Values like inspect/implement/verify/complete are mapped to step indexes.",
                    "nullable": True,
                },
                "mode": {
                    "type": "string",
                    "description": "Legacy compatibility field. Ignored by the current lightweight task plan.",
                    "nullable": True,
                },
                "status": {
                    "type": "string",
                    "description": "New status for the target step. Defaults to in_progress when omitted.",
                    "nullable": True,
                },
                "title": {
                    "type": "string",
                    "description": "Optional updated title",
                    "nullable": True,
                },
                "notes": {
                    "type": "string",
                    "description": "Optional execution note",
                    "nullable": True,
                },
            },
            metadata={
                "argument_rules": [
                    {
                        "type": "at_least_one_of",
                        "fields": ["step_id", "step_index", "kind"],
                    }
                ],
                "side_effect_level": "none",
                "capability_tags": ["planning", "task_planning"],
                "domain_tags": ["agent"],
            },
        )
        self.agent_state = agent_state
        self.task_planner = TaskPlanner()

    def execute(
        self,
        step_id=None,
        step_index=None,
        kind=None,
        mode=None,
        status=None,
        title=None,
        notes=None,
        **_kwargs,
    ):
        if not self.agent_state:
            return {"error": "Agent state is unavailable for task-plan updates"}
        return self._update_step(
            step_id=step_id,
            step_index=step_index,
            kind=kind,
            status=status,
            title=title,
            notes=notes,
        )

    def _update_step(
        self,
        *,
        step_id: Optional[str],
        step_index: Optional[int],
        kind: Optional[str],
        status: Optional[str],
        title: Optional[str],
        notes: Optional[str],
    ):
        if not self.agent_state.current_plan:
            return {"error": "No active task plan"}

        resolved_index = self._resolve_step_index(step_index=step_index, kind=kind)
        if step_id is None and resolved_index is None:
            return {"error": "step_id, step_index, or kind is required"}

        if status is None:
            status = "in_progress"

        if status is not None and str(status) not in self.VALID_STATUSES:
            return {"error": f"Invalid task-plan status: {status}"}

        updated = self.agent_state.update_plan_step(
            step_id=str(step_id).strip() if step_id else None,
            step_index=resolved_index,
            status=str(status).strip() if status else None,
            title=title,
            notes=notes,
        )
        if not updated:
            return {"error": "Target task-plan step was not found"}

        return {
            "ok": True,
            "summary": f"Updated task-plan step {updated.get('id')}",
            "data": self._current_plan_payload(),
        }

    @staticmethod
    def _resolve_step_index(step_index: Optional[int], kind: Optional[str]) -> Optional[int]:
        if step_index is not None:
            return int(step_index)

        legacy_kind = str(kind or "").strip().lower()
        if not legacy_kind:
            return None

        kind_to_index = {
            "inspect": 0,
            "implement": 1,
            "verify": 2,
            "complete": 3,
        }
        return kind_to_index.get(legacy_kind)

    def _current_plan_payload(self) -> Dict[str, Any]:
        return _current_plan_payload(self.agent_state)
