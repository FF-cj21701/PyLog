from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plugins.ai_assistant.ai_core.agent_state import AgentState
from plugins.ai_assistant.ai_core.api_client import AsyncAIWorker
from plugins.ai_assistant.ai_core.context_manager import ContextManager
from plugins.ai_assistant.ai_core.policy import ExecutionPolicy
from plugins.ai_assistant.ai_core.state_machine import TaskStateMachine
from plugins.ai_assistant.ai_core.task_plan import TaskPlanner
from plugins.ai_assistant.ai_core.tool_dispatcher import ToolDispatcher
from plugins.ai_assistant.ai_core.tool_manager import ToolManager
from plugins.ai_assistant.ai_core.tool_result import (
    ToolResult,
    normalize_tool_result,
    tool_result_content,
    tool_result_error,
    tool_result_ok,
    tool_result_summary,
    tool_result_to_dict,
)
from plugins.ai_assistant.ai_core.verification_coordinator import VerificationCoordinator
from plugins.ai_assistant.services.chat_service import ChatService
from plugins.ai_assistant.ui.main_window import AIAssistantWidget
from plugins.ai_assistant.ui.message_formatter import MessageFormatter
from plugins.ai_assistant.ui.widgets.web_chat_view import WebChatView


class DummyTool:
    def __init__(
        self,
        *,
        name: str,
        side_effect_level: str = "none",
        is_verification_tool: bool = False,
        path_argument_names=None,
        domain_tags=None,
        capability_tags=None,
        keywords=None,
        source: str = "local",
    ):
        self.name = name
        self.side_effect_level = side_effect_level
        self.is_verification_tool = is_verification_tool
        self.path_argument_names = list(path_argument_names or ["filepath", "file_path"])
        self.requires_read_before_write = side_effect_level in {"write", "data_mutation", "script_write"}
        self.metadata = {}
        self.domain_tags = list(domain_tags or [])
        self.capability_tags = list(capability_tags or [])
        self.keywords = list(keywords or [])
        self.source = source

    @property
    def spec(self):
        from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

        return ToolSpec(
            name=self.name,
            description=f"dummy tool {self.name}",
            args_schema={},
            source=self.source,
            side_effect_level=self.side_effect_level,
            is_verification_tool=self.is_verification_tool,
            path_argument_names=self.path_argument_names,
            domain_tags=self.domain_tags,
            capability_tags=self.capability_tags,
            keywords=self.keywords,
        )


class ContextManagerTests(unittest.TestCase):
    def test_empty_context_returns_user_message_unchanged(self):
        manager = ContextManager()

        self.assertEqual(manager.build_context_block([]), "")
        self.assertEqual(manager.compose_prompt("hello", []), "hello")

    def test_well_context_matches_existing_alive_context_format(self):
        manager = ContextManager()

        context = manager.build_context_block([
            {"type": "well", "name": "Well-A", "db_path": "demo.db"},
        ])

        self.assertEqual(context, "[ALIVE Context]\nWell: Well-A (db=demo.db)")

    def test_curve_context_resolves_well_name_from_database(self):
        import sqlite3
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "demo.db")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE wells (id TEXT PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO wells (id, name) VALUES (?, ?)", ("well-1", "Alpha"))
            conn.commit()
            conn.close()

            context = ContextManager().build_context_block([
                {"type": "curve", "name": "GR", "well_id": "well-1", "db_path": db_path},
            ])

        self.assertIn("Curve: GR (well=Alpha, db=", context)

    def test_chat_service_delegates_prompt_composition_to_context_manager(self):
        service = ChatService.__new__(ChatService)
        service.context_manager = ContextManager()

        prompt = service.compose_prompt("plot it", [
            {"type": "well", "display_name": "Well-B", "db_path": "demo.db"},
        ])

        self.assertEqual(prompt, "[ALIVE Context]\nWell: Well-B (db=demo.db)\n\n[User Message]\nplot it")

    def test_chat_service_injects_recent_runtime_tool_results(self):
        service = ChatService.__new__(ChatService)
        service.context_manager = ContextManager()
        service.agent_state = AgentState()
        service.agent_state.record_tool_result(
            "tool_run_test_command",
            "failed",
            result={"stdout": "1 failed", "exit_code": 1},
            error="AssertionError",
        )

        prompt = service.compose_prompt("fix it", [
            {"type": "well", "name": "Well-B", "db_path": "demo.db"},
        ])

        self.assertIn("Well: Well-B (db=demo.db)", prompt)
        self.assertIn("[Recent Tool Results]", prompt)
        self.assertIn("- tool_run_test_command: failed; 1 failed; error: AssertionError", prompt)
        self.assertIn("[User Message]\nfix it", prompt)

    def test_chat_service_injects_last_verification_without_mutating_input_context(self):
        service = ChatService.__new__(ChatService)
        service.context_manager = ContextManager()
        service.agent_state = AgentState()
        service.agent_state.record_verification({
            "ok": False,
            "tool_name": "tool_verify_target",
            "summary": "Verification failed",
            "error": "missing import",
        })
        context_data = [{"type": "active_script", "script_path": "scripts_user/demo.py"}]

        prompt = service.compose_prompt("continue", context_data)

        self.assertEqual(context_data, [{"type": "active_script", "script_path": "scripts_user/demo.py"}])
        self.assertIn("[Active Script State]", prompt)
        self.assertIn("- tool_verify_target: failed; Verification failed; error: missing import", prompt)

    def test_chat_service_injects_current_task_plan(self):
        service = ChatService.__new__(ChatService)
        service.context_manager = ContextManager()
        service.agent_state = AgentState()
        plan = TaskPlanner().create_plan("fix code bug")
        service.agent_state.set_task_plan(plan, source="model")
        service.agent_state.mark_plan_step_in_progress("implement")

        prompt = service.compose_prompt("continue", [])

        self.assertIn("[Task Plan]", prompt)
        self.assertIn("- domain: code", prompt)
        self.assertIn("- source: model", prompt)
        self.assertIn("- current_step_id: implement", prompt)
        self.assertIn("[in_progress current] implement: Make the code change", prompt)

    def test_active_script_state_section_formats_editor_draft_state(self):
        context = ContextManager().build_context_block([
            {
                "type": "active_script",
                "editor_id": "editor-1",
                "script_path": "scripts_user/demo.py",
                "has_unsaved_changes": True,
                "is_preview_active": True,
                "preview_session_id": "session-1",
                "base_hash": "base123",
                "draft_hash": "draft456",
                "working_hash": "work789",
                "should_run_from": "editor",
                "should_save_to": "scripts_user/demo.py",
            }
        ])

        self.assertIn("[Active Script State]", context)
        self.assertIn("- editor_id: editor-1", context)
        self.assertIn("- script_path: scripts_user/demo.py", context)
        self.assertIn("- has_unsaved_changes: yes", context)
        self.assertIn("- ai_draft_active: yes", context)
        self.assertIn("- should_run_from: editor", context)

    def test_script_state_can_be_extracted_from_tool_result_payload(self):
        context = ContextManager().build_context_block([
            {
                "tool_name": "tool_edit_file",
                "script_state": {
                    "editor_id": "editor-2",
                    "script_path": "scripts_user/tool_demo.py",
                    "has_unsaved_changes": False,
                    "is_preview_active": False,
                    "should_run_from": "editor",
                    "should_save_to": "scripts_user/tool_demo.py",
                },
            }
        ])

        self.assertIn("- editor_id: editor-2", context)
        self.assertIn("- has_unsaved_changes: no", context)
        self.assertIn("- ai_draft_active: no", context)

    def test_active_script_state_follows_selection_context(self):
        context = ContextManager().build_context_block([
            {"type": "well", "name": "Well-A", "db_path": "demo.db"},
            {"type": "active_script", "script_path": "scripts_user/demo.py"},
        ])

        self.assertLess(context.index("Well: Well-A"), context.index("[Active Script State]"))

    def test_task_plan_section_formats_current_step_and_notes(self):
        context = ContextManager().build_context_block([
            {
                "type": "task_plan",
                "plan_domain": "code",
                "plan_source": "model",
                "current_step_id": "implement",
                "steps": [
                    {"id": "inspect", "title": "Inspect relevant files", "status": "completed"},
                    {
                        "id": "implement",
                        "title": "Make the change",
                        "status": "in_progress",
                        "notes": "Editing context manager",
                    },
                    {"id": "verify", "title": "Run tests", "status": "pending"},
                ],
            }
        ])

        self.assertIn("[Task Plan]", context)
        self.assertIn("- domain: code", context)
        self.assertIn("- source: model", context)
        self.assertIn("- current_step_id: implement", context)
        self.assertIn("- 1. [completed] inspect: Inspect relevant files", context)
        self.assertIn("- 2. [in_progress current] implement: Make the change", context)
        self.assertIn("notes: Editing context manager", context)

    def test_task_plan_section_follows_active_script_before_recent_results(self):
        context = ContextManager().build_context_block([
            {"type": "well", "name": "Well-A", "db_path": "demo.db"},
            {"type": "active_script", "script_path": "scripts_user/demo.py"},
            {
                "type": "task_plan",
                "current_step_id": "verify",
                "steps": [{"id": "verify", "title": "Verify", "status": "in_progress"}],
            },
            {"type": "tool_result", "tool_name": "tool_read_file", "ok": True, "message": "read"},
        ])

        self.assertLess(context.index("Well: Well-A"), context.index("[Active Script State]"))
        self.assertLess(context.index("[Active Script State]"), context.index("[Task Plan]"))
        self.assertLess(context.index("[Task Plan]"), context.index("[Recent Tool Results]"))

    def test_task_plan_budget_reports_omitted_steps(self):
        steps = [
            {"id": f"step_{index}", "title": f"Step {index}", "status": "pending"}
            for index in range(15)
        ]

        context = ContextManager().build_context_block([
            {"type": "task_plan", "steps": steps, "current_step_id": "step_2"},
        ])

        self.assertIn("[Task Plan]", context)
        self.assertIn("- 1. [pending] step_0: Step 0", context)
        self.assertIn("- omitted: 6 task_plan line(s)", context)
        self.assertNotIn("step_14", context)

    def test_recent_tool_results_section_formats_high_signal_fields(self):
        context = ContextManager().build_context_block([
            {
                "type": "tool_result",
                "tool_name": "tool_edit_file",
                "status": "completed",
                "result": {
                    "message": "File edited successfully",
                    "filepath": "plugins/demo.py",
                    "previewed": False,
                    "script_state": {
                        "script_path": "plugins/demo.py",
                        "is_preview_active": False,
                    },
                },
            },
            {
                "type": "tool_result",
                "tool_name": "tool_run_test_command",
                "ok": False,
                "error": "AssertionError: expected 1 got 2",
                "exit_code": 1,
            },
        ])

        self.assertIn("[Recent Tool Results]", context)
        self.assertIn("- tool_edit_file: ok; File edited successfully; filepath: plugins/demo.py", context)
        self.assertIn("previewed: no", context)
        self.assertIn("ai_draft_active: no", context)
        self.assertIn("- tool_run_test_command: failed; error: AssertionError: expected 1 got 2; exit_code: 1", context)

    def test_recent_tool_results_can_be_extracted_from_agent_tool_steps(self):
        context = ContextManager().build_context_block([
            {
                "tool_steps": [
                    {
                        "command": "tool_read_file",
                        "status": "completed",
                        "result": {"summary": "Read 20 lines", "file_path": "demo.py"},
                    }
                ]
            }
        ])

        self.assertIn("[Recent Tool Results]", context)
        self.assertIn("- tool_read_file: ok; Read 20 lines; file_path: demo.py", context)

    def test_recent_tool_results_use_stdout_fallback_and_truncate_long_text(self):
        long_stdout = "x" * (ContextManager.MAX_TOOL_FIELD_LENGTH + 20)

        context = ContextManager().build_context_block([
            {
                "type": "tool_result",
                "tool_name": "tool_run_test_command",
                "ok": True,
                "result": {"stdout": long_stdout},
            }
        ])

        expected = "x" * (ContextManager.MAX_TOOL_FIELD_LENGTH - 3) + "..."
        self.assertIn(expected, context)
        self.assertIn("truncated: summary shortened", context)
        self.assertNotIn(long_stdout, context)

    def test_recent_tool_results_are_limited_but_keep_failures(self):
        context = ContextManager().build_context_block([
            {
                "type": "recent_tool_results",
                "items": [
                    {"tool_name": "tool_1", "ok": True, "message": "one"},
                    {"tool_name": "tool_2", "ok": False, "error": "important failure"},
                    {"tool_name": "tool_3", "ok": True, "message": "three"},
                    {"tool_name": "tool_4", "ok": True, "message": "four"},
                    {"tool_name": "tool_5", "ok": True, "message": "five"},
                    {"tool_name": "tool_6", "ok": True, "message": "six"},
                    {"tool_name": "tool_7", "ok": True, "message": "seven"},
                ],
            }
        ])

        self.assertIn("tool_2: failed", context)
        self.assertNotIn("tool_1: ok", context)
        self.assertIn("tool_7: ok", context)
        self.assertIn("- omitted: 2 older tool result(s)", context)
        self.assertEqual(context.count("- tool_"), ContextManager.MAX_RECENT_TOOL_RESULTS)

    def test_recent_tool_results_follow_active_script_state(self):
        context = ContextManager().build_context_block([
            {"type": "well", "name": "Well-A", "db_path": "demo.db"},
            {"type": "active_script", "script_path": "scripts_user/demo.py"},
            {"type": "tool_result", "tool_name": "tool_read_file", "ok": True, "message": "read"},
        ])

        self.assertLess(context.index("Well: Well-A"), context.index("[Active Script State]"))
        self.assertLess(context.index("[Active Script State]"), context.index("[Recent Tool Results]"))

    def test_context_section_policies_control_priority_and_budget(self):
        manager = ContextManager()

        sections = manager.build_sections([
            {"type": "well", "name": "Well-A", "db_path": "demo.db"},
            {"type": "active_script", "script_path": "scripts_user/demo.py"},
            {"type": "task_plan", "steps": [{"id": "verify", "title": "Verify", "status": "pending"}]},
            {"type": "tool_result", "tool_name": "tool_read_file", "ok": True, "message": "read"},
        ])
        priorities = {section.title: section.priority for section in sections}

        self.assertEqual(priorities["selection"], ContextManager.SECTION_POLICIES["selection"]["priority"])
        self.assertEqual(
            priorities["active_script_state"],
            ContextManager.SECTION_POLICIES["active_script_state"]["priority"],
        )
        self.assertEqual(priorities["task_plan"], ContextManager.SECTION_POLICIES["task_plan"]["priority"])
        self.assertEqual(
            priorities["recent_tool_results"],
            ContextManager.SECTION_POLICIES["recent_tool_results"]["priority"],
        )

    def test_section_budget_preserves_high_priority_sections_before_truncating_recent_results(self):
        items = [{"tool_name": f"tool_{index}", "ok": True, "message": str(index)} for index in range(10)]

        context = ContextManager().build_context_block([
            {"type": "well", "name": "Well-A", "db_path": "demo.db"},
            {
                "type": "active_script",
                "editor_id": "editor-1",
                "script_path": "scripts_user/demo.py",
                "has_unsaved_changes": True,
            },
            {"type": "recent_tool_results", "items": items},
        ])

        self.assertIn("Well: Well-A (db=demo.db)", context)
        self.assertIn("[Active Script State]", context)
        self.assertIn("- script_path: scripts_user/demo.py", context)
        self.assertIn("[Recent Tool Results]", context)
        self.assertIn("- omitted: 5 older tool result(s)", context)
        self.assertEqual(context.count("- tool_"), ContextManager.SECTION_POLICIES["recent_tool_results"]["max_items"])


class ToolResultNormalizationTests(unittest.TestCase):
    def test_normalize_dict_result_preserves_metadata_and_summary(self):
        result = normalize_tool_result(
            "tool_demo",
            {
                "ok": True,
                "message": "done",
                "custom_field": 123,
            },
        )

        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.ok)
        self.assertEqual(result.tool_name, "tool_demo")
        self.assertEqual(result.summary, "done")
        self.assertEqual(result.metadata["message"], "done")
        self.assertEqual(result.metadata["custom_field"], 123)

    def test_normalize_string_error_result(self):
        result = normalize_tool_result("tool_demo", "Error: failed to execute")

        self.assertFalse(result.ok)
        self.assertEqual(result.error, "Error: failed to execute")
        self.assertEqual(tool_result_error(result), "Error: failed to execute")
        self.assertFalse(tool_result_ok(result))

    def test_tool_result_to_dict_handles_plain_string(self):
        payload = tool_result_to_dict("done")

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tool_name"], "unknown_tool")
        self.assertEqual(payload["summary"], "done")

    def test_tool_result_to_dict_normalizes_mapping_shape(self):
        payload = tool_result_to_dict(
            {
                "ok": True,
                "message": "saved",
                "final_answer": "visible text",
            }
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"], "saved")
        self.assertEqual(payload["content"], "visible text")
        self.assertEqual(payload["final_answer"], "visible text")

    def test_tool_result_content_prefers_explicit_visible_body(self):
        result = normalize_tool_result(
            "tool_demo",
            {
                "ok": True,
                "message": "summary text",
                "final_answer": "visible body",
            },
        )

        self.assertEqual(tool_result_content(result), "visible body")
        self.assertEqual(tool_result_summary(result), "summary text")


class ToolDispatcherValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatcher_returns_standard_error_for_missing_required_args(self):
        class RequiredArgTool(DummyTool):
            @property
            def spec(self):
                from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

                return ToolSpec(
                    name=self.name,
                    description="needs filepath",
                    args_schema={
                        "filepath": {"type": "string", "description": "Path to file"},
                        "content": {"type": "string", "description": "content", "nullable": True},
                    },
                    required_args=["filepath"],
                    side_effect_level="write",
                    path_argument_names=["filepath"],
                )

            def execute(self, **kwargs):
                return {"ok": True, "message": "should not execute when filepath is missing"}

        dispatcher = ToolDispatcher([RequiredArgTool(name="tool_required_demo", side_effect_level="write")])

        _tool, result = await dispatcher.execute("tool_required_demo", {"filepath": "   "})

        self.assertFalse(result.ok)
        self.assertIn("Missing required arguments", result.error or "")
        self.assertEqual(result.metadata["missing_required_args"], ["filepath"])

    async def test_dispatcher_does_not_require_optional_db_path_for_list_wells(self):
        class OptionalDbPathTool(DummyTool):
            @property
            def spec(self):
                from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

                return ToolSpec(
                    name="list_wells",
                    description="list wells with optional db path",
                    args_schema={
                        "db_path": {
                            "type": "string",
                            "description": "Optional database file path",
                            "nullable": True,
                        }
                    },
                    required_args=[],
                    side_effect_level="none",
                )

            def execute(self, **kwargs):
                return {"ok": True, "message": "executed without requiring db_path"}

        dispatcher = ToolDispatcher([OptionalDbPathTool(name="list_wells")])

        _tool, result = await dispatcher.execute("list_wells", {})

        self.assertTrue(result.ok)
        self.assertNotIn("Missing required arguments", (result.error or ""))

    async def test_dispatcher_validates_exactly_one_of_argument_rule(self):
        class InsertRuleTool(DummyTool):
            @property
            def spec(self):
                from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

                return ToolSpec(
                    name="tool_insert_rule_demo",
                    description="needs exactly one insertion anchor",
                    args_schema={
                        "filepath": {"type": "string", "description": "Path"},
                        "content": {"type": "string", "description": "Content"},
                        "after": {"type": "string", "description": "After", "nullable": True},
                        "before": {"type": "string", "description": "Before", "nullable": True},
                        "line_number": {"type": "integer", "description": "Line", "nullable": True},
                    },
                    required_args=["filepath", "content"],
                    metadata={
                        "argument_rules": [
                            {"type": "exactly_one_of", "fields": ["after", "before", "line_number"]}
                        ]
                    },
                )

            def execute(self, **kwargs):
                return {"ok": True, "message": "should not execute with invalid anchors"}

        dispatcher = ToolDispatcher([InsertRuleTool(name="tool_insert_rule_demo")])

        _tool, result = await dispatcher.execute(
            "tool_insert_rule_demo",
            {"filepath": "demo.py", "content": "x", "after": "a", "before": "b"},
        )

        self.assertFalse(result.ok)
        self.assertIn("Exactly one of after, before, line_number must be provided", result.error or "")
        self.assertEqual(result.metadata["argument_rule_violation"]["type"], "exactly_one_of")

    async def test_dispatcher_validates_requires_when_argument_rule(self):
        class ConditionalTargetTool(DummyTool):
            @property
            def spec(self):
                from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

                return ToolSpec(
                    name="tool_conditional_target_demo",
                    description="target required for py_compile",
                    args_schema={
                        "command": {"type": "string", "description": "Command", "nullable": True},
                        "target": {"type": "string", "description": "Target", "nullable": True},
                    },
                    metadata={
                        "argument_rules": [
                            {
                                "type": "requires_when",
                                "arg": "command",
                                "equals": "python -m py_compile",
                                "requires": "target",
                            }
                        ]
                    },
                )

            def execute(self, **kwargs):
                return {"ok": True, "message": "should not execute without target"}

        dispatcher = ToolDispatcher([ConditionalTargetTool(name="tool_conditional_target_demo")])

        _tool, result = await dispatcher.execute(
            "tool_conditional_target_demo",
            {"command": "python -m py_compile"},
        )

        self.assertFalse(result.ok)
        self.assertIn("target is required when command is 'python -m py_compile'", result.error or "")
        self.assertEqual(result.metadata["argument_rule_violation"]["type"], "requires_when")

    async def test_dispatcher_validates_at_least_one_of_argument_rule(self):
        class RunModeTool(DummyTool):
            @property
            def spec(self):
                from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

                return ToolSpec(
                    name="tool_run_mode_demo",
                    description="requires at least one execution target",
                    args_schema={
                        "code": {"type": "string", "description": "Code", "nullable": True},
                        "script_path": {"type": "string", "description": "Path", "nullable": True},
                        "editor_id": {"type": "string", "description": "Editor", "nullable": True},
                    },
                    metadata={
                        "argument_rules": [
                            {
                                "type": "at_least_one_of",
                                "fields": ["code", "script_path", "editor_id"],
                            }
                        ]
                    },
                )

            def execute(self, **kwargs):
                return {"ok": True, "message": "should not execute without any execution target"}

        dispatcher = ToolDispatcher([RunModeTool(name="tool_run_mode_demo")])

        _tool, result = await dispatcher.execute("tool_run_mode_demo", {})

        self.assertFalse(result.ok)
        self.assertIn("At least one of code, script_path, editor_id must be provided", result.error or "")
        self.assertEqual(result.metadata["argument_rule_violation"]["type"], "at_least_one_of")

    async def test_dispatcher_validates_requires_when_for_non_empty_trigger(self):
        class PlotModeTool(DummyTool):
            @property
            def spec(self):
                from plugins.ai_assistant.ai_core.tool_spec import ToolSpec

                return ToolSpec(
                    name="tool_plot_mode_demo",
                    description="well required when curves are provided",
                    args_schema={
                        "well": {"type": "string", "description": "Well", "nullable": True},
                        "curves": {"type": "array", "description": "Curves", "nullable": True},
                        "data_list": {"type": "array", "description": "Data", "nullable": True},
                    },
                    metadata={
                        "argument_rules": [
                            {"type": "at_least_one_of", "fields": ["curves", "data_list"]},
                            {"type": "requires_when", "arg": "curves", "equals": "__non_empty__", "requires": "well"},
                        ]
                    },
                )

            def execute(self, **kwargs):
                return {"ok": True, "message": "should not execute without well when curves are present"}

        dispatcher = ToolDispatcher([PlotModeTool(name="tool_plot_mode_demo")])

        _tool, result = await dispatcher.execute("tool_plot_mode_demo", {"curves": ["GR"]})

        self.assertFalse(result.ok)
        self.assertIn("well is required when curves is provided", result.error or "")
        self.assertEqual(result.metadata["argument_rule_violation"]["type"], "requires_when")


class ToolManagerBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_delegates_execution_and_preserves_normalized_result(self):
        class ExecutableTool(DummyTool):
            def execute(self, **kwargs):
                return {"ok": True, "message": f"ran {kwargs['value']}"}

        manager = ToolManager([ExecutableTool(name="tool_manager_demo")])

        tool, result = await manager.execute("tool_manager_demo", {"value": "input"})

        self.assertEqual(tool.name, "tool_manager_demo")
        self.assertTrue(result.ok)
        self.assertEqual(result.summary, "ran input")

    def test_manager_builds_routed_tool_configs(self):
        manager = ToolManager(
            [
                DummyTool(name="list_curves", domain_tags=["geoscience"]),
                DummyTool(name="tool_edit_file", side_effect_level="write", capability_tags=["file_edit"]),
            ]
        )

        configs = manager.build_tool_configs(prompt="inspect well curves and plot GR")
        names = [item["function"]["name"] for item in configs]

        self.assertEqual(names, ["list_curves", "tool_edit_file"])

    def test_manager_builds_keyword_ranked_tool_configs(self):
        manager = ToolManager(
            [
                DummyTool(name="tool_open_agent_page", keywords=["agent page"]),
                DummyTool(name="tool_open_html_preview", keywords=["html preview", "web page"]),
            ]
        )

        configs = manager.build_tool_configs(prompt="please open this html preview in a web page")
        names = [item["function"]["name"] for item in configs]

        self.assertEqual(names[0], "tool_open_html_preview")

    def test_manager_exposes_lightweight_inventory(self):
        manager = ToolManager(
            [
                DummyTool(
                    name="tool_edit_file",
                    side_effect_level="write",
                    domain_tags=["code"],
                    capability_tags=["file_edit"],
                    keywords=["edit file", "patch code"],
                )
            ]
        )

        inventory = manager.describe_inventory()

        self.assertEqual(inventory[0]["name"], "tool_edit_file")
        self.assertEqual(inventory[0]["side_effect_level"], "write")
        self.assertEqual(inventory[0]["capability_tags"], ["file_edit"])
        self.assertEqual(inventory[0]["domain_tags"], ["code"])
        self.assertEqual(inventory[0]["keywords"], ["edit file", "patch code"])

    def test_manager_replaces_registered_tool_by_name(self):
        manager = ToolManager([DummyTool(name="tool_demo", capability_tags=["old"])])

        manager.register_tool(DummyTool(name="tool_demo", capability_tags=["new"]))

        self.assertEqual(len(manager.tools), 1)
        self.assertEqual(manager.get_spec("tool_demo").capability_tags, ["new"])

    def test_manager_rejects_duplicate_when_replace_is_disabled(self):
        manager = ToolManager([DummyTool(name="tool_demo")])

        with self.assertRaises(ValueError):
            manager.register_tool(DummyTool(name="tool_demo"), replace_existing=False)

    def test_manager_replaces_tools_by_source(self):
        manager = ToolManager(
            [
                DummyTool(name="list_curves", source="local"),
                DummyTool(name="mcp_old", source="mcp"),
            ]
        )

        manager.replace_tools_by_source("mcp", [DummyTool(name="mcp_new", source="mcp")])

        self.assertIsNotNone(manager.find_tool("list_curves"))
        self.assertIsNone(manager.find_tool("mcp_old"))
        self.assertIsNotNone(manager.find_tool("mcp_new"))

    def test_manager_lists_specs_by_domain_and_capability(self):
        manager = ToolManager(
            [
                DummyTool(name="list_curves", domain_tags=["geoscience"], capability_tags=["curve_lookup"]),
                DummyTool(name="tool_edit_file", domain_tags=["code"], capability_tags=["file_edit"]),
            ]
        )

        self.assertEqual([spec.name for spec in manager.list_specs_by_domain("geoscience")], ["list_curves"])
        self.assertEqual([spec.name for spec in manager.list_specs_by_capability("file_edit")], ["tool_edit_file"])

    def test_manager_inventory_payload_includes_summary(self):
        manager = ToolManager(
            [
                DummyTool(name="list_curves", source="local", domain_tags=["geoscience"], keywords=["curve lookup"]),
                DummyTool(name="mcp_lookup", source="mcp", side_effect_level="execution"),
            ]
        )

        payload = manager.get_inventory_payload()

        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual(payload["summary"]["by_source"], {"local": 1, "mcp": 1})
        self.assertEqual(payload["summary"]["by_side_effect"]["execution"], 1)
        self.assertEqual(payload["summary"]["domain_tags"], ["geoscience"])
        self.assertEqual(payload["summary"]["keywords"], ["curve lookup"])
        self.assertEqual([tool["name"] for tool in payload["tools"]], ["list_curves", "mcp_lookup"])


class TaskStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.state = AgentState()
        self.machine = TaskStateMachine(self.state)

    def test_write_tool_moves_to_awaiting_verification(self):
        self.machine.start_task("modify a file")
        tool = DummyTool(name="tool_edit_file", side_effect_level="write")

        self.machine.after_tool_call(
            tool.name,
            {"filepath": "demo.py"},
            {"ok": True, "message": "patched"},
            tool=tool,
        )

        self.assertEqual(self.state.task_state, "awaiting_verification")
        self.assertEqual(self.state.side_effects[-1]["tool"], "tool_edit_file")
        self.assertEqual(self.state.get_plan_step("implement")["status"], "completed")
        self.assertEqual(self.state.get_plan_step("verify")["status"], "in_progress")

    def test_failed_verification_moves_to_repairing(self):
        self.machine.start_task("verify a file")
        verify_tool = DummyTool(
            name="tool_verify_target",
            side_effect_level="execution",
            is_verification_tool=True,
        )

        self.machine.after_tool_call(
            verify_tool.name,
            {"filepath": "demo.py"},
            {"ok": False, "error": "compile failed"},
            tool=verify_tool,
        )

        self.assertEqual(self.state.task_state, "repairing")
        self.assertEqual(self.state.task_state_reason, "compile failed")
        self.assertEqual(self.state.get_plan_step("verify")["status"], "failed")
        self.assertEqual(self.state.get_plan_step("implement")["status"], "in_progress")

    def test_completed_is_blocked_while_verification_required(self):
        self.machine.start_task("finish later")
        self.state.verification_required = True

        self.machine.complete_task("should not complete")

        self.assertEqual(self.state.task_state, "awaiting_verification")

    def test_start_task_creates_code_plan(self):
        self.machine.start_task("fix parser bug in code")

        self.assertEqual(self.state.current_plan_domain, "code")
        self.assertEqual(
            [step["kind"] for step in self.state.current_plan],
            ["inspect", "implement", "verify", "complete"],
        )

    def test_geoscience_lookup_tool_maps_to_inspect_not_analyze(self):
        self.machine.start_task("Inspect well curves and analyze them")
        self.state.update_task_plan(
            self.machine.task_planner.build_model_aware_plan(
                "Inspect well curves and analyze them",
                {
                    "steps": [
                        {"kind": "inspect", "title": "Fetch available curves"},
                        {"kind": "analyze", "title": "Choose cross-plot curves"},
                        {"kind": "complete", "title": "Return the result"},
                    ]
                },
                state=self.state,
                fallback_plan=self.machine.task_planner.create_plan("Inspect well curves and analyze them", state=self.state),
            ),
            source="model",
        )
        tool = DummyTool(
            name="list_curves",
            side_effect_level="none",
            domain_tags=["geoscience", "pylog"],
            capability_tags=["curve_lookup"],
        )

        self.machine.after_tool_call(
            tool.name,
            {"well": "MaJiaGou"},
            {"ok": True, "message": "listed"},
            tool=tool,
        )

        self.assertEqual(self.state.get_plan_step("inspect")["status"], "completed")
        self.assertEqual(self.state.get_plan_step("analyze")["status"], "pending")
        self.assertEqual(self.state.current_plan_step_id, self.state.get_plan_step("analyze")["id"])

    def test_out_of_order_step_completion_does_not_skip_earlier_pending_step(self):
        self.machine.start_task("Inspect well curves and analyze them")
        self.state.update_task_plan(
            self.machine.task_planner.build_model_aware_plan(
                "Inspect well curves and analyze them",
                {
                    "steps": [
                        {"kind": "inspect", "title": "Fetch available curves"},
                        {"kind": "analyze", "title": "Choose cross-plot curves"},
                        {"kind": "complete", "title": "Return the result"},
                    ]
                },
                state=self.state,
                fallback_plan=self.machine.task_planner.create_plan("Inspect well curves and analyze them", state=self.state),
            ),
            source="model",
        )

        self.state.mark_plan_step_completed("analyze", notes="should not advance to complete first")

        self.assertEqual(self.state.get_plan_step("analyze")["status"], "completed")
        self.assertEqual(self.state.current_plan_step_id, self.state.get_plan_step("inspect")["id"])


class TaskPlannerTests(unittest.TestCase):
    def test_planner_creates_script_geoscience_plan(self):
        planner = TaskPlanner()

        plan = planner.create_plan("Write a PyLog script to load well curves and plot them")

        self.assertEqual(plan.domain, "geoscience_script")
        self.assertEqual(
            [step.kind for step in plan.steps],
            ["inspect", "script_edit", "run", "verify", "complete"],
        )

    def test_model_plan_overrides_default_titles(self):
        planner = TaskPlanner()
        fallback = planner.create_plan("Fix duplicate task-card rendering")

        plan = planner.build_model_aware_plan(
            "Fix duplicate task-card rendering",
            {
                "steps": [
                    {
                        "kind": "inspect",
                        "title": "Locate the duplicate render entry points",
                        "acceptance": "The duplicate entry path can be explained clearly.",
                    },
                    {
                        "kind": "implement",
                        "title": "Unify task-plan rendering into the top progress card",
                        "notes": "Keep explicit task-plan support and disable the legacy default card.",
                    },
                ]
            },
            fallback_plan=fallback,
        )

        self.assertEqual(len(plan.steps), 2)
        self.assertEqual(plan.get_step("inspect").title, "Locate the duplicate render entry points")
        self.assertEqual(plan.get_step("implement").title, "Unify task-plan rendering into the top progress card")
        self.assertIsNone(plan.get_step("verify"))

    def test_smalltalk_does_not_enable_task_plan(self):
        planner = TaskPlanner()

        self.assertFalse(planner.should_enable_task_plan("hello"))
        self.assertFalse(planner.should_enable_task_plan("who are you?"))
        self.assertTrue(planner.should_enable_task_plan("inspect this well's curves and plot them"))


class HiddenTaskPlanProtocolTests(unittest.TestCase):
    def test_worker_applies_hidden_task_plan_without_leaking_to_visible_content(self):
        state = AgentState()
        machine = TaskStateMachine(state)
        machine.start_task("Fix duplicate task-card rendering")
        worker = AsyncAIWorker(
            api_key="test",
            base_url="http://example.com",
            model="dummy",
            prompt="Fix duplicate task-card rendering",
            history=[],
            system_prompt="test",
            stream=True,
            tools=[],
            agent_state=state,
            execution_policy=None,
            task_state_machine=machine,
            verification_coordinator=None,
        )

        class Delta:
            content = '<task_plan>{"steps":[{"kind":"inspect","title":"Locate duplicate render entry points"},{"kind":"implement","title":"Unify the task-card entry point"},{"kind":"verify","title":"Verify the task card only appears for 3-step tasks"}]}</task_plan>Starting work'

        accumulator = {"reasoning": "", "content": ""}
        worker._process_stream_chunk(Delta(), accumulator)

        self.assertEqual(accumulator["content"], "Starting work")
        self.assertEqual(state.current_plan_source, "model")
        self.assertEqual(state.get_plan_step("inspect")["title"], "Locate duplicate render entry points")


class TaskPlanVisibilityTests(unittest.TestCase):
    def test_fallback_plan_is_hidden_before_model_plan(self):
        state = AgentState()
        machine = TaskStateMachine(state)
        machine.start_task("Inspect the well curves and plot them")

        payload = state.get_task_progress_payload()

        self.assertTrue(payload["plan_enabled"])
        self.assertFalse(payload["plan_should_display"])
        self.assertEqual(payload["plan_source"], "fallback")

    def test_fallback_plan_remains_hidden_even_after_tool_activity(self):
        state = AgentState()
        machine = TaskStateMachine(state)
        machine.start_task("Inspect the well curves and plot them")
        tool = DummyTool(
            name="list_curves",
            side_effect_level="none",
            domain_tags=["geoscience", "pylog"],
            capability_tags=["curve_lookup"],
        )

        machine.before_tool_call(tool.name, {"well": "MaJiaGou"}, tool=tool)
        machine.after_tool_call(tool.name, {"well": "MaJiaGou"}, {"ok": True, "message": "listed"}, tool=tool)

        payload = state.get_task_progress_payload()

        self.assertTrue(payload["plan_enabled"])
        self.assertFalse(payload["plan_should_display"])
        self.assertEqual(payload["plan_source"], "fallback")

    def test_model_plan_becomes_visible_immediately(self):
        state = AgentState()
        machine = TaskStateMachine(state)
        machine.start_task("Inspect the well curves and plot them")

        applied = machine.apply_model_plan({
            "steps": [
                {"kind": "inspect", "title": "Confirm well and curve scope"},
                {"kind": "analyze", "title": "Choose cross-plot curves"},
                {"kind": "complete", "title": "Return the result"},
            ]
        })

        payload = state.get_task_progress_payload()

        self.assertTrue(applied)
        self.assertTrue(payload["plan_enabled"])
        self.assertTrue(payload["plan_should_display"])
        self.assertEqual(payload["plan_source"], "model")

    def test_two_step_plan_does_not_display_task_card(self):
        state = AgentState()
        machine = TaskStateMachine(state)
        machine.start_task("List all wells")

        applied = machine.apply_model_plan({
            "steps": [
                {"kind": "inspect", "title": "Fetch the well list"},
                {"kind": "complete", "title": "Return the result"},
            ]
        })

        payload = state.get_task_progress_payload()

        self.assertFalse(applied)
        self.assertTrue(payload["plan_enabled"])
        self.assertFalse(payload["plan_should_display"])
        self.assertEqual(payload["plan_source"], "fallback")

    def test_smalltalk_task_has_no_plan(self):
        state = AgentState()
        machine = TaskStateMachine(state)
        machine.start_task("hello")

        payload = state.get_task_progress_payload()

        self.assertFalse(payload["plan_enabled"])
        self.assertFalse(payload["plan_should_display"])
        self.assertEqual(payload["steps"], [])


class FinishAndVerificationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.coordinator = VerificationCoordinator()
        self.policy = ExecutionPolicy(verification_coordinator=self.coordinator)
        self.state = AgentState()
        self.state.start_task("change code")
        self.state.set_task_state("executing", "test setup")

    def test_finish_is_blocked_when_verification_required(self):
        self.state.mark_file_modified("scripts/example.py")

        error = self.policy.before_tool_call(self.state, "tool_finish", {}, tool=None)

        self.assertIsNotNone(error)
        self.assertIn("Policy blocked tool_finish", error)
        self.assertIn("tool_verify_target", error)

    def test_auto_verification_request_prefers_script_target(self):
        self.state.mark_file_modified("scripts_user/ai_example.py")

        request = self.policy.get_auto_verification_request(self.state)

        self.assertIsNotNone(request)
        self.assertEqual(request["tool_name"], "tool_verify_target")
        self.assertEqual(request["args"]["filepath"], "scripts_user/ai_example.py")

    def test_successful_verification_clears_finish_block(self):
        verify_tool = DummyTool(
            name="tool_verify_target",
            side_effect_level="execution",
            is_verification_tool=True,
        )
        self.state.mark_file_modified("scripts/example.py")

        self.policy.after_tool_call(
            self.state,
            verify_tool.name,
            {"filepath": "scripts/example.py"},
            {"ok": True, "summary": "verified"},
            tool=verify_tool,
        )

        self.assertFalse(self.state.verification_required)
        self.assertTrue(self.state.can_finish())

    def test_read_tool_marks_file_as_read_even_when_tool_object_is_present(self):
        read_tool = DummyTool(
            name="tool_read_file",
            side_effect_level="none",
            path_argument_names=["file_path"],
        )

        self.policy.after_tool_call(
            self.state,
            read_tool.name,
            {"file_path": "scripts/example.py"},
            {"ok": True, "content": "print('ok')"},
            tool=read_tool,
        )

        self.assertIn(os.path.abspath("scripts/example.py").lower(), self.state.files_read)

    def test_write_policy_accepts_normalized_path_after_relative_read(self):
        read_tool = DummyTool(
            name="tool_read_file",
            side_effect_level="none",
            path_argument_names=["file_path"],
        )
        write_tool = DummyTool(
            name="tool_edit_file",
            side_effect_level="write",
            path_argument_names=["filepath"],
        )

        self.policy.after_tool_call(
            self.state,
            read_tool.name,
            {"file_path": "scripts/example.py"},
            {"ok": True, "content": "print('ok')"},
            tool=read_tool,
        )

        error = self.policy.before_tool_call(
            self.state,
            write_tool.name,
            {"filepath": os.path.abspath("scripts/example.py")},
            tool=write_tool,
        )

        self.assertIsNone(error)

    def test_write_tracking_uses_normalized_summary_not_message_only(self):
        write_tool = DummyTool(
            name="tool_edit_file",
            side_effect_level="write",
            path_argument_names=["filepath"],
        )

        self.policy.after_tool_call(
            self.state,
            write_tool.name,
            {"filepath": "scripts/example.py"},
            {"ok": True, "summary": "normalized summary", "content": "visible body"},
            tool=write_tool,
        )

        self.assertEqual(self.state.pending_patches[-1]["summary"], "normalized summary")


class FinishOutputBehaviorTests(unittest.TestCase):
    def test_finish_final_answer_is_not_suppressed_when_no_visible_response_exists(self):
        output = AsyncAIWorker._extract_finish_visible_output(
            '{"ok": true, "final_answer": "Visible final response"}',
            suppress_summary=True,
            has_visible_response=False,
        )

        self.assertEqual(output, "Visible final response")

    def test_finish_final_answer_is_suppressed_when_visible_response_already_exists_in_early_round(self):
        output = AsyncAIWorker._extract_finish_visible_output(
            '{"ok": true, "final_answer": "Repeated tool_finish summary"}',
            suppress_summary=True,
            has_visible_response=True,
        )

        self.assertIsNone(output)

    def test_finish_prefers_unified_content_field(self):
        output = AsyncAIWorker._extract_finish_visible_output(
            '{"ok": true, "summary": "done", "content": "Unified visible response"}',
            suppress_summary=True,
            has_visible_response=False,
        )

        self.assertEqual(output, "Unified visible response")


class WebChatViewResultConsumptionTests(unittest.TestCase):
    def test_normalize_tool_result_payload_promotes_summary_and_content(self):
        payload = WebChatView._normalize_tool_result_payload(
            '{"ok": true, "summary": "Saved file", "content": "Patched /tmp/demo.py"}'
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"], "Saved file")
        self.assertEqual(payload["content"], "Patched /tmp/demo.py")

    def test_normalize_tool_result_payload_handles_legacy_message_shape(self):
        payload = WebChatView._normalize_tool_result_payload(
            {"ok": True, "message": "Legacy success"}
        )

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"], "Legacy success")
        self.assertEqual(payload["content"], "Legacy success")

    def test_file_change_cards_are_deferred_until_message_finalization(self):
        view = WebChatView.__new__(WebChatView)
        js_calls = []
        view._run_js = lambda js, callback=None: js_calls.append(js)
        view._current_message_tools = []
        view._current_message_reasoning = ""
        view._current_message_content = ""
        view._current_message_process_logs = []
        view._current_message_steps = []
        view._current_message_cards = []
        view._current_message_pending_cards = []
        view._current_reasoning_step_index = None
        view._current_live_text_step_index = None
        view._has_active_ai_message = False

        result = {
            "ok": True,
            "script_path": "scripts_user/demo.py",
            "script_state": {
                "last_review_diff_stats": {"added": 3, "removed": 1},
            },
        }

        view.add_tool_call("tool_edit_file", status="success", result=result)

        self.assertEqual(view._current_message_cards, [])
        self.assertEqual(len(view._current_message_pending_cards), 1)
        self.assertEqual(view._current_message_pending_cards[0]["path"], "scripts_user/demo.py")

        view.finalize_current_message()

        self.assertEqual(view._current_message_pending_cards, [])
        self.assertEqual(len(view._current_message_cards), 1)
        self.assertEqual(view._current_message_cards[0]["title"], "Edited demo.py")
        self.assertEqual(view._current_message_cards[0]["added"], 3)
        self.assertEqual(view._current_message_cards[0]["removed"], 1)
        self.assertEqual(view._current_message_cards[0]["actions"][0]["label"], "Review")
        self.assertIn("setLastAiMessageState('finalized');", js_calls[-1])

    def test_file_change_cards_merge_multiple_tool_updates_before_finalization(self):
        view = WebChatView.__new__(WebChatView)
        view._run_js = lambda js, callback=None: None
        view._current_message_tools = []
        view._current_message_reasoning = ""
        view._current_message_content = ""
        view._current_message_process_logs = []
        view._current_message_steps = []
        view._current_message_cards = []
        view._current_message_pending_cards = []
        view._current_reasoning_step_index = None
        view._current_live_text_step_index = None
        view._has_active_ai_message = False

        first = {
            "ok": True,
            "script_path": "scripts_user/demo.py",
            "script_state": {
                "last_review_diff_stats": {"added": 1, "removed": 0},
            },
        }
        second = {
            "ok": True,
            "script_path": "scripts_user/demo.py",
            "script_state": {
                "last_review_diff_stats": {"added": 2, "removed": 1},
            },
        }

        view.add_tool_call("tool_edit_file", status="success", result=first)
        view.update_tool_status("tool_edit_file", "success", result=second)
        view.finalize_current_message()

        self.assertEqual(len(view._current_message_cards), 1)
        self.assertEqual(view._current_message_cards[0]["added"], 2)
        self.assertEqual(view._current_message_cards[0]["removed"], 1)

    def test_open_only_html_result_does_not_generate_file_change_card(self):
        view = WebChatView.__new__(WebChatView)
        view._run_js = lambda js, callback=None: None
        view._current_message_tools = []
        view._current_message_reasoning = ""
        view._current_message_content = ""
        view._current_message_process_logs = []
        view._current_message_steps = []
        view._current_message_cards = []
        view._current_message_pending_cards = []
        view._current_reasoning_step_index = None
        view._current_live_text_step_index = None
        view._has_active_ai_message = False

        result = {
            "ok": True,
            "filepath": "scripts_user/demo.html",
            "document_kind": "html",
            "open_only": True,
            "message": "HTML preview opened",
        }

        view.add_tool_call("tool_open_html_preview", status="success", result=result)
        view.finalize_current_message()

        self.assertEqual(view._current_message_pending_cards, [])
        self.assertEqual(view._current_message_cards, [])


class MessageCardActionRoutingTests(unittest.TestCase):
    def tearDown(self):
        from plugins.ai_assistant.ui import review_registry

        review_registry._REVIEW_RECORDS.clear()

    def test_review_action_reports_missing_saved_record_without_falling_back_to_editor(self):
        widget = AIAssistantWidget.__new__(AIAssistantWidget)
        system_messages = []
        widget.append_system_message = system_messages.append

        class DummyEditor:
            def __init__(self, script_path):
                self.script_path = script_path
                self.opened = False

            def open_review_dialog(self):
                self.opened = True

        class DummySubWindow:
            def __init__(self, editor):
                self._editor = editor

            def widget(self):
                return self._editor

        class DummyMdiArea:
            def __init__(self, sub):
                self._sub = sub
                self.active = None

            def subWindowList(self):
                return [self._sub]

            def setActiveSubWindow(self, sub):
                self.active = sub

        class DummyMainWindow:
            def __init__(self, mdi_area):
                self.mdi_area = mdi_area

        editor = DummyEditor(os.path.join(PROJECT_ROOT, "scripts_user", "demo.py"))
        sub = DummySubWindow(editor)
        mdi_area = DummyMdiArea(sub)
        main_win = DummyMainWindow(mdi_area)
        widget.window = lambda: main_win

        payload = '{"action":"review","payload":{"script_path":"scripts_user/demo.py"}}'
        widget.handle_message_card_action(payload)

        self.assertFalse(editor.opened)
        self.assertIsNone(mdi_area.active)
        self.assertEqual(
            system_messages,
            ["Review is unavailable because no saved review record was found for scripts_user/demo.py."],
        )

    def test_review_action_opens_saved_review_without_script_editor(self):
        from plugins.ai_assistant.ui import review_registry

        widget = AIAssistantWidget.__new__(AIAssistantWidget)
        system_messages = []
        widget.append_system_message = system_messages.append

        class DummyMdiArea:
            def subWindowList(self):
                return []

        class DummyMainWindow:
            def __init__(self):
                self.mdi_area = DummyMdiArea()

        main_win = DummyMainWindow()
        widget.window = lambda: main_win

        review_registry.register_review_record({
            "session_id": "session-1",
            "script_path": os.path.join(PROJECT_ROOT, "scripts_user", "demo.py"),
            "base_code": "print('old')\n",
            "draft_code": "print('new')\n",
            "diff_blocks": [],
            "diff_text": "",
            "source": "ai_preview",
            "created_at": "2026-06-29T00:00:00+00:00",
            "review_mode": "saved",
            "saved_to_disk": True,
        })

        with patch("plugins.ai_assistant.ui.main_window.open_review_page", return_value=object()) as mock_open:
            payload = '{"action":"review","payload":{"script_path":"scripts_user/demo.py"}}'
            widget.handle_message_card_action(payload)

        mock_open.assert_called_once()
        self.assertEqual(system_messages, [])


class MessageFormatterResultConsumptionTests(unittest.TestCase):
    def test_formatter_prefers_unified_summary_and_content(self):
        formatted = MessageFormatter.format_ai_response(
            '[工具结果] {"ok": true, "summary": "Saved file", "content": "Patched demo.py"}'
        )

        self.assertIn("Tool succeeded: Saved file", formatted)
        self.assertIn("Patched demo.py", formatted)

    def test_formatter_supports_legacy_error_shape(self):
        formatted = MessageFormatter.format_ai_response(
            '[工具结果] {"ok": false, "message": "compile failed"}'
        )

        self.assertIn("Tool failed: compile failed", formatted)


if __name__ == "__main__":
    unittest.main()
