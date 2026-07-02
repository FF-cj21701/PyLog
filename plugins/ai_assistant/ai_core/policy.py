from __future__ import annotations

import os
from typing import Any, Dict, Optional

from .tool_result import (
    tool_result_error,
    tool_result_ok,
    tool_result_summary,
    tool_result_to_dict,
)


WRITE_TOOLS = {
    "tool_apply_patch",
    "tool_edit_file",
    "tool_overwrite_file",
    "tool_insert_into_file",
    "tool_write_file",
    "tool_append_file",
    "tool_write_script_file",
    "tool_append_script_code",
    "tool_save_script",
}

CREATE_TOOLS = {
    "tool_write_script_file",
}

READ_TOOLS = {
    "tool_read_file",
}

VERIFICATION_TOOLS = {
    "tool_verify_target",
    "tool_run_python_file",
    "tool_run_test_command",
    "tool_run_lint_command",
    "tool_run_format_command",
    "tool_run_import_check",
}

def _get_filepath(args: Optional[Dict[str, Any]], tool=None) -> Optional[str]:
    args = args or {}
    candidate_names = ["filepath", "file_path"]
    if tool is not None:
        try:
            candidate_names = list(tool.path_argument_names) or candidate_names
        except Exception:
            pass

    for name in candidate_names:
        value = args.get(name)
        if value:
            return value
    return None


def _normalize_tracked_path(filepath: Optional[str]) -> Optional[str]:
    if not filepath:
        return None
    try:
        return os.path.normcase(os.path.normpath(os.path.abspath(str(filepath))))
    except Exception:
        return str(filepath)


def is_write_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            return tool.side_effect_level in {"write", "data_mutation", "script_write"}
        except Exception:
            pass
    return tool_name in WRITE_TOOLS


def is_create_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            return bool(tool.metadata.get("creates_file", False))
        except Exception:
            pass
    return tool_name in CREATE_TOOLS


def is_read_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            if tool.side_effect_level == "read":
                return True
        except Exception:
            pass
    return tool_name in READ_TOOLS


def is_verification_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            return bool(tool.is_verification_tool)
        except Exception:
            pass
    return tool_name in VERIFICATION_TOOLS


def is_external_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            if getattr(tool, "source", None) == "mcp":
                return True
            return "external_tool" in set(getattr(tool, "capability_tags", []) or [])
        except Exception:
            pass
    return tool_name.startswith("mcp_")


def is_high_risk_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            risk_level = getattr(tool, "risk_level", "low")
            capability_tags = set(getattr(tool, "capability_tags", []) or [])
            return risk_level == "high" or "destructive" in capability_tags
        except Exception:
            pass
    return False


def is_destructive_tool(tool_name: str, tool=None) -> bool:
    if tool is not None:
        try:
            capability_tags = set(getattr(tool, "capability_tags", []) or [])
            return "destructive" in capability_tags
        except Exception:
            pass
    return False


def has_meaningful_args(args: Optional[Dict[str, Any]]) -> bool:
    args = args or {}
    for value in args.values():
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, (list, tuple, dict, set)) and len(value) > 0:
            return True
        if isinstance(value, bool):
            if value:
                return True
            continue
        if isinstance(value, (int, float)):
            return True
    return False


class ExecutionPolicy:
    def __init__(self, verification_coordinator=None):
        self.verification_coordinator = verification_coordinator

    def before_tool_call(self, state, tool_name: str, args: Optional[Dict[str, Any]] = None, tool=None) -> Optional[str]:
        args = args or {}

        plan_error = self._active_task_plan_guard(state, tool_name, args, tool=tool)
        if plan_error:
            return plan_error

        risk_error = self._high_risk_tool_guard(state, tool_name, args, tool=tool)
        if risk_error:
            return risk_error

        if is_write_tool(tool_name, tool=tool):
            filepath = _normalize_tracked_path(_get_filepath(args, tool=tool))
            requires_read = tool.requires_read_before_write if tool is not None else True
            if is_create_tool(tool_name, tool=tool):
                return None
            if requires_read and filepath and filepath not in state.files_read:
                return (
                    f"Policy blocked `{tool_name}` for `{filepath}`. "
                    "Read the target file first with tool_read_file before modifying it."
                )

        if tool_name == "tool_finish" and not state.can_finish():
            if self.verification_coordinator:
                return self.verification_coordinator.get_finish_block_message(state)
            recommendation = self._verification_recommendation(state)
            return (
                "Policy blocked tool_finish because files were modified and no successful verification "
                f"has been recorded yet. {recommendation}"
            )

        return None

    def after_tool_call(self, state, tool_name: str, args: Optional[Dict[str, Any]], result: Any, tool=None) -> None:
        args = args or {}
        result_obj = tool_result_to_dict(result)

        if is_read_tool(tool_name, tool=tool):
            filepath = _normalize_tracked_path(_get_filepath(args, tool=tool))
            state.mark_file_read(filepath)

        if is_write_tool(tool_name, tool=tool):
            filepath = _normalize_tracked_path(_get_filepath(args, tool=tool))
            if tool_result_ok(result):
                summary = tool_result_summary(result)
                state.mark_file_modified(
                    filepath,
                    {
                        "tool": tool_name,
                        "filepath": filepath,
                        "summary": summary,
                    },
                )
            else:
                state.record_error(tool_result_error(result) or "Unknown error")

        if is_verification_tool(tool_name, tool=tool):
            verification = result_obj
            verification_target = self._verification_target(args, result_obj, tool=tool)
            if not verification:
                error_text = tool_result_error(result) or "Unknown verification error"
                verification = {
                    "ok": False,
                    "error": error_text,
                    "summary": error_text,
                }
            else:
                verification.setdefault("summary", tool_result_summary(result))
                if not verification.get("ok"):
                    verification.setdefault("error", tool_result_error(result))
            state.record_verification(verification, target=verification_target)

    def finish_guidance(self, state) -> Optional[str]:
        if state.dirty and state.verification_required:
            modified = ", ".join(sorted(state.files_modified)) or "unknown files"
            recommendation = (
                self.verification_coordinator.get_verification_recommendation(state)
                if self.verification_coordinator
                else self._verification_recommendation(state)
            )
            return (
                f"Files modified: {modified}. You must run at least one verification tool "
                f"and get a successful result before finishing. {recommendation}"
            )
        return None

    def get_auto_verification_request(self, state) -> Optional[Dict[str, Any]]:
        if self.verification_coordinator:
            return self.verification_coordinator.get_auto_verification_request(state)
        if not state or not state.dirty or not state.verification_required:
            return None

        modified_files = sorted(state.files_modified)
        script_targets = [path for path in modified_files if self._is_script_target(path)]
        if script_targets:
            target = script_targets[0].replace("\\", "/")
            return {
                "tool_name": "tool_verify_target",
                "args": {
                    "filepath": target,
                },
                "reason": f"auto-verify script target `{target}` before finish",
            }

        target = modified_files[0].replace("\\", "/") if modified_files else None
        return {
            "tool_name": "tool_verify_target",
            "args": {"filepath": target} if target else {},
            "reason": "auto-verify modified project target before finish",
        }

    @staticmethod
    def _is_script_target(filepath: str) -> bool:
        normalized = str(filepath or "").replace("\\", "/").lower()
        if not normalized:
            return False
        return (
            "/scripts_user/" in normalized
            or normalized.startswith("scripts_user/")
            or "/scripts/" in normalized
            or normalized.startswith("scripts/")
        ) and normalized.endswith(".py")

    def _verification_recommendation(self, state) -> str:
        modified_files = sorted(state.files_modified)
        script_targets = [path for path in modified_files if self._is_script_target(path)]
        if script_targets:
            target = script_targets[0].replace("\\", "/")
            return (
                "For AI/user script changes, prefer script-level verification first: "
                f"run `tool_verify_target(filepath='{target}')`, then if needed "
                f"`tool_verify_target(filepath='{target}', run_execution=true)`."
            )

        return (
            "For source-code changes, prefer running a detected project verification command, "
            "starting with `tool_verify_target`, then fall back to "
            "`tool_run_test_command`, `tool_run_lint_command`, or `tool_run_format_command` if needed."
        )

    def _verification_target(self, args: Optional[Dict[str, Any]], result: Dict[str, Any], tool=None) -> Optional[str]:
        args = args or {}
        result = result or {}
        for payload in (args, result):
            for key in ("filepath", "file_path", "target", "path", "script_path"):
                value = payload.get(key)
                if value:
                    return _normalize_tracked_path(value)
        return _normalize_tracked_path(_get_filepath(args, tool=tool))

    def _high_risk_tool_guard(self, state, tool_name: str, args: Optional[Dict[str, Any]], tool=None) -> Optional[str]:
        if not is_high_risk_tool(tool_name, tool=tool):
            return None

        if not is_external_tool(tool_name, tool=tool):
            return None

        if not has_meaningful_args(args):
            return (
                f"Policy blocked `{tool_name}` because high-risk external tools require explicit target arguments "
                "or a concrete action scope before execution."
            )

        if state and getattr(state, "verification_required", False) and not is_verification_tool(tool_name, tool=tool):
            return (
                f"Policy blocked `{tool_name}` because modified files still require verification. "
                "Complete verification first, then retry the external high-risk tool if it is still necessary."
            )

        if state and getattr(state, "task_state", "") == "repairing" and not is_verification_tool(tool_name, tool=tool):
            return (
                f"Policy blocked `{tool_name}` during repairing. "
                "Prefer local read, patch, and verification tools until the current failure is understood and fixed."
            )

        if is_destructive_tool(tool_name, tool=tool):
            last_command = getattr(state, "last_command", None) if state else None
            if not last_command or last_command.get("command") != tool_name:
                return (
                    f"Policy blocked `{tool_name}` because destructive external tools require an explicit, repeated intent. "
                    "Retry the same tool call after confirming the exact target and purpose in the current task flow."
                )

        return None

    def _active_task_plan_guard(self, state, tool_name: str, args: Optional[Dict[str, Any]] = None, tool=None) -> Optional[str]:
        if not state or not getattr(state, "has_active_task_plan", lambda: False)():
            return None

        if tool_name in {"tool_create_task_plan", "tool_get_task_plan", "tool_update_task_plan"}:
            return None

        if tool_name == "tool_finish":
            incomplete = getattr(state, "get_incomplete_plan_steps", lambda: [])()
            blocking = incomplete[:-1] if len(incomplete) > 1 else []
            if blocking:
                labels = ", ".join(
                    str(step.get("title") or step.get("id") or "unnamed step")
                    for step in blocking[:3]
                )
                return (
                    "Policy blocked tool_finish because the active task plan still has incomplete steps: "
                    f"{labels}. Finish the remaining steps in order before finishing."
                )

        return None

