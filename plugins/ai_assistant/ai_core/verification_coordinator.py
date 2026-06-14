from __future__ import annotations

from typing import Dict, Optional


class VerificationCoordinator:
    """Selects verification actions for changed targets without enforcing policy."""

    def get_finish_block_message(self, state) -> str:
        recommendation = self.get_verification_recommendation(state)
        return (
            "Policy blocked tool_finish because files were modified and no successful verification "
            f"has been recorded yet. {recommendation}"
        )

    def get_verification_recommendation(self, state) -> str:
        modified_files = sorted(getattr(state, "files_modified", set()))
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

    def get_auto_verification_request(self, state) -> Optional[Dict[str, object]]:
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
