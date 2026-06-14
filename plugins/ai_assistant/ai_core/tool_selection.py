from __future__ import annotations

from typing import Iterable, List, Optional


PLAN_TOOL_NAMES = {"tool_create_task_plan", "tool_get_task_plan", "tool_update_task_plan"}
WRITE_SIDE_EFFECTS = {"write", "data_mutation", "script_write"}


class ToolSelectionStrategy:
    """Keep tool ordering simple and step-driven instead of score-heavy."""

    def order_specs(self, specs: Iterable[object], state=None) -> List[object]:
        return sorted(list(specs), key=lambda spec: self._sort_key(spec, state))

    def build_guidance(self, state=None) -> Optional[str]:
        if not state:
            return None

        if getattr(state, "verification_required", False):
            return "Verification is still required. Prefer verification tools and avoid finishing early."

        current_step = getattr(state, "get_current_plan_step", lambda: None)()
        current_title = str((current_step or {}).get("title") or "").strip()
        if current_title:
            return f"Follow the current task-plan step: `{current_title}`."

        return None

    def _sort_key(self, spec, state=None):
        bucket = self._bucket(spec, state)
        name = getattr(spec, "name", "")
        return (bucket, name)

    def _bucket(self, spec, state=None) -> int:
        name = getattr(spec, "name", "")
        side_effect_level = getattr(spec, "side_effect_level", "none")
        lifecycle_role = getattr(spec, "lifecycle_role", "normal")
        is_verification = bool(getattr(spec, "is_verification_tool", False))
        capability_tags = set(getattr(spec, "capability_tags", []) or [])
        source = getattr(spec, "source", "local")

        # Default ordering: local read tools first, risky finish/write tools later.
        bucket = 50

        if name in PLAN_TOOL_NAMES:
            bucket = 10
        elif side_effect_level == "read":
            bucket = 20
        elif side_effect_level == "none":
            bucket = 25
        elif side_effect_level == "execution":
            bucket = 40
        elif side_effect_level in WRITE_SIDE_EFFECTS:
            bucket = 60

        if is_verification:
            bucket = min(bucket, 30)

        if lifecycle_role == "finish":
            bucket = 90

        if source == "mcp":
            bucket += 5

        if "destructive" in capability_tags:
            bucket += 15
        if "open_world" in capability_tags:
            bucket += 10

        if not state:
            return bucket

        if getattr(state, "verification_required", False):
            if is_verification:
                return 0
            if lifecycle_role == "finish":
                return 100
            if side_effect_level in WRITE_SIDE_EFFECTS:
                return 80
            return min(bucket, 35)

        task_state = getattr(state, "task_state", "")
        if task_state == "repairing":
            if is_verification:
                return 5
            if side_effect_level == "read":
                return 10
            if side_effect_level in WRITE_SIDE_EFFECTS:
                return 20
            if lifecycle_role == "finish":
                return 100

        current_index = getattr(state, "get_current_plan_step_index", lambda: None)()
        if current_index is None:
            return bucket

        if name in PLAN_TOOL_NAMES:
            return 8

        if current_index == 0:
            if side_effect_level == "read" or capability_tags & {"inspection", "search", "navigation"}:
                return 10
            if is_verification:
                return 45
            if side_effect_level in WRITE_SIDE_EFFECTS:
                return 70
            if lifecycle_role == "finish":
                return 100

        if current_index == 1:
            if side_effect_level in WRITE_SIDE_EFFECTS:
                return 15
            if capability_tags & {"script_execution", "python_execution"} or side_effect_level == "execution":
                return 18
            if side_effect_level == "read":
                return 25
            if is_verification:
                return 55
            if lifecycle_role == "finish":
                return 100

        if current_index == 2:
            if is_verification:
                return 0
            if side_effect_level == "read":
                return 20
            if side_effect_level in WRITE_SIDE_EFFECTS:
                return 75
            if lifecycle_role == "finish":
                return 100

        if state and current_index == max(len(getattr(state, "current_plan", []) or []) - 1, 0):
            if lifecycle_role == "finish":
                return 0
            if is_verification:
                return 40
            if side_effect_level in WRITE_SIDE_EFFECTS:
                return 85

        return bucket
