from __future__ import annotations

from typing import Dict, List, Optional


class VerificationCoordinator:
    """Selects verification actions for changed targets without enforcing policy."""

    UNRESOLVED_FAILURE_THRESHOLD = 2

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

    def get_repair_guidance(self, state) -> Optional[Dict[str, object]]:
        """Describe the next repair step after a failed or incomplete verification."""
        if not state:
            return None
        last_verification = getattr(state, "last_verification", None) or {}
        if not last_verification:
            return None

        failed = last_verification.get("ok") is False
        incomplete_coverage = (
            last_verification.get("ok") is True
            and last_verification.get("covers_modified_files") is False
        )
        if not failed and not incomplete_coverage:
            return None

        strategy = self.get_verification_strategy(state)
        modified_files = [path.replace("\\", "/") for path in sorted(getattr(state, "files_modified", set()))]
        failed_tool = last_verification.get("tool_name") or last_verification.get("tool")
        if not failed_tool or failed_tool == "unknown_tool":
            failed_tool = "last_verification"
        target = last_verification.get("target") or last_verification.get("filepath") or last_verification.get("file_path")
        summary = last_verification.get("summary") or last_verification.get("message")
        error = last_verification.get("error") or last_verification.get("stderr")

        if incomplete_coverage:
            action = (
                "The last verification passed but did not cover every modified file. "
                "Run project-level verification or verify the full modified-file scope before finishing."
            )
        else:
            action = (
                "Inspect the failed verification output, patch the relevant modified file(s), "
                "then rerun the recommended verification before finishing."
            )

        return {
            "type": "verification_repair",
            "status": "coverage_incomplete" if incomplete_coverage else "failed",
            "failed_tool": failed_tool,
            "target": target,
            "summary": summary,
            "error": error,
            "modified_files": modified_files,
            "recommended_tool": strategy.get("tool_name"),
            "recommended_args": strategy.get("args") or {},
            "recommended_action": action,
        }

    def should_report_unresolved_failure(self, state) -> bool:
        if not state:
            return False
        if not getattr(state, "dirty", False) or not getattr(state, "verification_required", False):
            return False
        last_verification = getattr(state, "last_verification", None) or {}
        has_failed_verification = (
            last_verification.get("ok") is False
            or (
                last_verification.get("ok") is True
                and last_verification.get("covers_modified_files") is False
            )
        )
        if not has_failed_verification:
            return False
        return int(getattr(state, "failure_count", 0) or 0) >= self.UNRESOLVED_FAILURE_THRESHOLD

    def get_unresolved_failure_report(self, state) -> Optional[str]:
        """Build a final report when verification remains unresolved after repair attempts."""
        if not self.should_report_unresolved_failure(state):
            return None

        repair = self.get_repair_guidance(state) or {}
        last_verification = getattr(state, "last_verification", None) or {}
        modified_files = repair.get("modified_files") or [
            path.replace("\\", "/")
            for path in sorted(getattr(state, "files_modified", set()))
        ]
        failed_tool = repair.get("failed_tool") or last_verification.get("tool_name") or "last_verification"
        summary = repair.get("summary") or last_verification.get("summary") or "Verification did not pass."
        error = repair.get("error") or last_verification.get("error") or getattr(state, "last_error", None)
        recommended_tool = repair.get("recommended_tool")
        recommended_args = repair.get("recommended_args") or {}
        recommended_action = repair.get("recommended_action") or self.get_verification_recommendation(state)

        lines = [
            "Unresolved verification failure.",
            "",
            "I could not safely mark this task complete because verification is still failing or incomplete.",
            f"- failed_tool: {failed_tool}",
            f"- failure_count: {getattr(state, 'failure_count', 0)}",
        ]
        if modified_files:
            lines.append(f"- modified_files: {', '.join(str(path) for path in modified_files[:6])}")
            if len(modified_files) > 6:
                lines.append(f"- omitted_modified_files: {len(modified_files) - 6}")
        if summary:
            lines.append(f"- summary: {summary}")
        if error:
            lines.append(f"- error: {error}")
        if recommended_tool:
            lines.append(f"- recommended_tool: {recommended_tool}")
        if recommended_args:
            args_text = ", ".join(f"{key}={value}" for key, value in sorted(recommended_args.items()))
            lines.append(f"- recommended_args: {args_text}")
        lines.append(f"- next_step: {recommended_action}")
        return "\n".join(lines)

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
