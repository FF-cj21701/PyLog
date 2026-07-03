from __future__ import annotations

from typing import Dict, List, Optional


class VerificationCoordinator:
    """Selects verification actions for changed targets without enforcing policy."""

    def get_finish_block_message(self, state) -> str:
        recommendation = self.get_verification_recommendation(state)
        coverage_note = self._verification_coverage_note(state)
        return (
            "Policy blocked tool_finish because files were modified and no successful verification "
            f"has been recorded yet. {coverage_note}{recommendation}"
        )

    def get_verification_recommendation(self, state) -> str:
        strategy = self.get_verification_strategy(state)
        return strategy["message"]

    def get_verification_strategy(self, state) -> Dict[str, object]:
        """Return a structured verification strategy for the current modified files."""
        modified_files = sorted(getattr(state, "files_modified", set()))
        normalized_files = [path.replace("\\", "/") for path in modified_files]
        script_targets = [path for path in normalized_files if self._is_script_target(path)]
        ui_targets = [path for path in normalized_files if self._is_ui_target(path)]
        python_targets = [path for path in normalized_files if self._is_python_source_target(path)]

        if len(normalized_files) > 1:
            return self._project_strategy(
                category="mixed" if self._has_mixed_categories(normalized_files) else "multi_file",
                modified_files=normalized_files,
                reason="multiple modified files require project-level coverage before finish",
            )

        if script_targets:
            target = script_targets[0]
            return {
                "scope": "file",
                "category": "script",
                "tool_name": "tool_verify_target",
                "args": {"filepath": target},
                "reason": f"verify changed PyLog script `{target}` before finish",
                "message": (
                    "For AI/user script changes, prefer script-level verification first: "
                    f"run `tool_verify_target(filepath='{target}')`, then if needed "
                    f"`tool_verify_target(filepath='{target}', run_execution=true)`."
                ),
            }

        if ui_targets:
            target = ui_targets[0]
            return {
                "scope": "project",
                "category": "ui",
                "tool_name": "tool_run_test_command",
                "args": {"command": "pytest tests/test_chat_ui_template_regressions.py -q"},
                "reason": f"verify UI/template regression coverage for `{target}` before finish",
                "message": (
                    "For AI UI/template changes, prefer the chat UI regression suite: "
                    "`tool_run_test_command(command='pytest tests/test_chat_ui_template_regressions.py -q')`. "
                    f"If the change is isolated, also inspect `{target}` with `tool_verify_target`."
                ),
            }

        if python_targets:
            target = python_targets[0]
            return {
                "scope": "file",
                "category": "python_source",
                "tool_name": "tool_verify_target",
                "args": {"filepath": target},
                "reason": f"verify changed Python source `{target}` before finish",
                "message": (
                    "For Python source changes, start with "
                    f"`tool_verify_target(filepath='{target}')` for syntax/import checks, "
                    "then run the nearest focused pytest command if behavior changed."
                ),
            }

        if normalized_files:
            return self._project_strategy(
                category="project",
                modified_files=normalized_files,
                reason="verify modified project files before finish",
            )

        return self._project_strategy(
            category="none",
            modified_files=[],
            reason="verify project state before finish",
        )

    def get_auto_verification_request(self, state) -> Optional[Dict[str, object]]:
        if not state or not state.dirty or not state.verification_required:
            return None

        strategy = self.get_verification_strategy(state)
        tool_name = strategy.get("tool_name")
        if not tool_name:
            return None
        return {
            "tool_name": tool_name,
            "args": dict(strategy.get("args") or {}),
            "reason": strategy.get("reason") or "auto-verify modified project target before finish",
        }

    def _project_strategy(self, *, category: str, modified_files: List[str], reason: str) -> Dict[str, object]:
        files = ", ".join(modified_files) if modified_files else "modified files"
        return {
            "scope": "project",
            "category": category,
            "tool_name": "tool_run_test_command",
            "args": {},
            "reason": reason,
            "message": (
                f"For {category.replace('_', ' ')} changes ({files}), prefer project-level verification "
                "so all modified files are covered: run `tool_run_test_command` with the focused pytest "
                "command when known, otherwise run `tool_verify_target` without a filepath or use "
                "`tool_run_lint_command` / `tool_run_format_command` if tests are not applicable."
            ),
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

    @staticmethod
    def _is_ui_target(filepath: str) -> bool:
        normalized = str(filepath or "").replace("\\", "/").lower()
        return (
            normalized.endswith((".html", ".js", ".css"))
            or "/ui/resources/" in normalized
            or normalized.startswith("plugins/ai_assistant/ui/resources/")
            or "chat_ui_template" in normalized
        )

    @classmethod
    def _is_python_source_target(cls, filepath: str) -> bool:
        normalized = str(filepath or "").replace("\\", "/").lower()
        return normalized.endswith(".py") and not cls._is_script_target(normalized)

    @classmethod
    def _has_mixed_categories(cls, filepaths: List[str]) -> bool:
        categories = set()
        for filepath in filepaths:
            if cls._is_script_target(filepath):
                categories.add("script")
            elif cls._is_ui_target(filepath):
                categories.add("ui")
            elif cls._is_python_source_target(filepath):
                categories.add("python_source")
            else:
                categories.add("other")
        return len(categories) > 1

    @staticmethod
    def _verification_coverage_note(state) -> str:
        last_verification = getattr(state, "last_verification", None) or {}
        if last_verification.get("ok") and last_verification.get("covers_modified_files") is False:
            target = last_verification.get("target") or "unknown target"
            return f"The last successful verification targeted `{target}`, but it did not cover the modified files. "
        return ""
