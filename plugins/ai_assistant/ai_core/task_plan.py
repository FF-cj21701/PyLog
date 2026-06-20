from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence


PLAN_STATUS_PENDING = "pending"
PLAN_STATUS_IN_PROGRESS = "in_progress"
PLAN_STATUS_COMPLETED = "completed"
PLAN_STATUS_FAILED = "failed"
PLAN_STATUS_SKIPPED = "skipped"
PLAN_TOOL_NAMES = {"tool_create_task_plan", "tool_get_task_plan", "tool_update_task_plan"}


@dataclass
class TaskPlanStep:
    """One canonical plan step used for UI progress and tool-to-step mapping."""

    id: str
    kind: str
    title: str
    status: str = PLAN_STATUS_PENDING
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "status": self.status,
            "notes": self.notes,
        }


@dataclass
class TaskPlan:
    """A lightweight ordered task plan."""

    domain: str
    steps: List[TaskPlanStep]

    def to_dict_list(self) -> List[Dict[str, object]]:
        return [step.to_dict() for step in self.steps]

    def get_step(self, kind: str) -> Optional[TaskPlanStep]:
        for step in self.steps:
            if step.kind == kind:
                return step
        return None


class TaskPlanner:
    """Build canonical task plans and normalize model-provided plan payloads."""

    def create_plan(
        self,
        task: str,
        history: Optional[Sequence[Sequence[str]]] = None,
        state=None,
    ) -> TaskPlan:
        """Create a lightweight default plan matched to the task domain."""
        text = str(task or "").lower()
        if self._looks_like_geoscience_script_task(text):
            return self._build_plan(
                "geoscience_script",
                [
                    ("inspect", "Inspect PyLog context and relevant APIs"),
                    ("script_edit", "Write or update the PyLog script"),
                    ("run", "Run the script or preview execution"),
                    ("verify", "Verify results and outputs"),
                    ("complete", "Wrap up"),
                ],
            )
        if self._looks_like_code_task(text):
            return self._build_plan(
                "code",
                [
                    ("inspect", "Inspect the relevant code"),
                    ("implement", "Make the code change"),
                    ("verify", "Verify the change"),
                    ("complete", "Wrap up"),
                ],
            )
        return self._build_plan(
            "task_plan",
            [
                ("inspect", "Review the task"),
                ("implement", "Make the change"),
                ("verify", "Check the result"),
                ("complete", "Wrap up"),
            ],
        )

    def build_model_plan(
        self,
        task: str,
        payload,
        history: Optional[Sequence[Sequence[str]]] = None,
        state=None,
    ) -> TaskPlan:
        """Normalize a model-authored plan while preserving canonical kinds when possible."""
        base_plan = self.create_plan(task, history=history, state=state)
        normalized = self.parse_model_plan_payload(payload)
        if not normalized:
            return base_plan

        payload_steps = normalized.get("steps") or []
        if not payload_steps:
            return base_plan

        model_steps: List[TaskPlanStep] = []
        for index, item in enumerate(payload_steps):
            if not isinstance(item, dict):
                continue

            title = str(item.get("title") or "").strip()
            notes = str(item.get("notes") or item.get("summary") or "").strip()
            kind = str(item.get("kind") or "").strip() or (
                base_plan.steps[index].kind if index < len(base_plan.steps) else f"step_{index + 1}"
            )

            step_id = str(item.get("id") or f"step_{index + 1}")
            fallback_title = base_plan.steps[index].title if index < len(base_plan.steps) else f"Step {index + 1}"

            model_steps.append(
                TaskPlanStep(
                    id=step_id,
                    kind=kind,
                    title=title or fallback_title,
                    status=PLAN_STATUS_PENDING,
                    notes=notes,
                )
            )

        return TaskPlan(domain=base_plan.domain, steps=model_steps)

    def parse_model_plan_payload(self, payload) -> Optional[Dict[str, object]]:
        """Normalize a task-plan payload into an object containing a non-empty steps list."""
        if payload is None:
            return None

        if isinstance(payload, str):
            raw = payload.strip()
            if not raw:
                return None
            try:
                payload = json.loads(raw)
            except Exception:
                return None

        if isinstance(payload, list):
            payload = {"steps": payload}

        if not isinstance(payload, dict):
            return None

        nested = payload.get("plan")
        if isinstance(nested, dict):
            payload = nested

        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            return None

        return payload

    def should_enable_task_plan(self, task: str) -> bool:
        text = str(task or "").strip().lower()
        if not text:
            return False
        smalltalk = {"hello", "hi", "who are you?", "thanks", "thank you"}
        if text in smalltalk:
            return False
        return any(
            token in text
            for token in (
                "inspect",
                "fix",
                "write",
                "script",
                "plot",
                "curve",
                "well",
                "analyze",
                "modify",
                "change",
                "render",
                "code",
                "verify",
                "file",
            )
        )

    def build_model_aware_plan(
        self,
        task: str,
        payload,
        history: Optional[Sequence[Sequence[str]]] = None,
        state=None,
        fallback_plan: Optional[TaskPlan] = None,
    ) -> TaskPlan:
        base_plan = fallback_plan or self.create_plan(task, history=history, state=state)
        normalized = self.parse_model_plan_payload(payload)
        if not normalized:
            return base_plan
        return self.build_model_plan(task, normalized, history=history, state=state)

    def _build_plan(self, domain: str, step_defs: Sequence[Sequence[str]]) -> TaskPlan:
        """Construct a plan from static step definitions."""
        steps = [
            TaskPlanStep(
                id=kind,
                kind=kind,
                title=title,
            )
            for index, (kind, title) in enumerate(step_defs)
        ]
        return TaskPlan(domain=domain, steps=steps)

    @staticmethod
    def _looks_like_geoscience_script_task(text: str) -> bool:
        if "script" not in text and "python" not in text:
            return False
        return any(token in text for token in ("pylog", "well", "curve", "plot", "log"))

    @staticmethod
    def _looks_like_code_task(text: str) -> bool:
        return any(token in text for token in ("code", "bug", "fix", "parser", "render", "refactor"))


def find_plan_step_id_for_tool(plan_steps: Iterable[Dict[str, object]], tool_name: str, tool=None) -> Optional[str]:
    """Map a tool call to the most relevant lightweight plan-step id."""
    steps = list(plan_steps)
    if not steps:
        return None

    if tool_name in PLAN_TOOL_NAMES:
        return None

    def step_id_at(index: int) -> Optional[str]:
        if 0 <= index < len(steps):
            return str(steps[index].get("id") or "")
        return None

    if tool_name == "tool_finish":
        return step_id_at(len(steps) - 1)

    capability_tags = set(getattr(tool, "capability_tags", []) or [])
    is_verification = bool(getattr(tool, "is_verification_tool", False))
    side_effect_level = getattr(tool, "side_effect_level", "none")

    if is_verification:
        return step_id_at(min(2, len(steps) - 1))

    if side_effect_level == "read" or capability_tags & {"inspection", "search", "navigation"}:
        return step_id_at(0)

    if side_effect_level in {"write", "data_mutation", "script_write", "execution"}:
        return step_id_at(min(1, len(steps) - 1))

    if capability_tags & {"python_execution", "script_execution", "numeric_analysis", "curve_analysis", "plotting", "curve_visualization"}:
        return step_id_at(min(1, len(steps) - 1))

    return step_id_at(0)
