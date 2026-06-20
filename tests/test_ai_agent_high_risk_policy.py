from __future__ import annotations

import os
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plugins.ai_assistant.ai_core.agent_state import AgentState
from plugins.ai_assistant.ai_core.policy import ExecutionPolicy
from plugins.ai_assistant.ai_core.tool_selection import ToolSelectionStrategy
from plugins.ai_assistant.ai_core.tool_spec import ToolSpec


class DummyTool:
    def __init__(
        self,
        name: str,
        *,
        source: str = "mcp",
        risk_level: str = "high",
        capability_tags=None,
        side_effect_level: str = "write",
        is_verification_tool: bool = False,
    ):
        self.name = name
        self.source = source
        self.risk_level = risk_level
        self.capability_tags = list(capability_tags or [])
        self.side_effect_level = side_effect_level
        self.is_verification_tool = is_verification_tool
        self.requires_read_before_write = False
        self.metadata = {}


class HighRiskPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = ExecutionPolicy()
        self.state = AgentState()
        self.state.start_task("test high-risk gating")
        self.state.set_task_state("executing", "test setup")

    def test_blocks_high_risk_external_tool_without_meaningful_args(self):
        tool = DummyTool(
            "mcp_delete_remote_resource",
            capability_tags=["external_tool", "destructive"],
        )

        error = self.policy.before_tool_call(self.state, tool.name, {}, tool=tool)

        self.assertIsNotNone(error)
        self.assertIn("explicit target arguments", error)

    def test_blocks_high_risk_external_tool_during_verification(self):
        tool = DummyTool(
            "mcp_delete_remote_resource",
            capability_tags=["external_tool", "destructive"],
        )
        self.state.verification_required = True

        error = self.policy.before_tool_call(
            self.state,
            tool.name,
            {"target_id": "abc-123"},
            tool=tool,
        )

        self.assertIsNotNone(error)
        self.assertIn("require verification", error)

    def test_destructive_external_tool_requires_repeated_intent(self):
        tool = DummyTool(
            "mcp_delete_remote_resource",
            capability_tags=["external_tool", "destructive"],
        )

        first_error = self.policy.before_tool_call(
            self.state,
            tool.name,
            {"target_id": "abc-123"},
            tool=tool,
        )
        self.assertIsNotNone(first_error)
        self.assertIn("repeated intent", first_error)

        self.state.record_command(tool.name, {"target_id": "abc-123"})
        second_error = self.policy.before_tool_call(
            self.state,
            tool.name,
            {"target_id": "abc-123"},
            tool=tool,
        )
        self.assertIsNone(second_error)


class ToolSelectionStrategyTests(unittest.TestCase):
    def setUp(self):
        self.strategy = ToolSelectionStrategy()
        self.state = AgentState()
        self.state.start_task("test selection")
        self.state.set_task_state("repairing", "verification failed")
        self.state.verification_required = True

    def test_verification_tool_ranks_ahead_of_high_risk_external_tool(self):
        verification_spec = ToolSpec(
            name="tool_verify_target",
            description="verify",
            args_schema={},
            source="local",
            side_effect_level="execution",
            risk_level="medium",
            output_type="verification",
            is_verification_tool=True,
            capability_tags=["verification", "auto_strategy"],
            domain_tags=["code"],
        )
        risky_external_spec = ToolSpec(
            name="mcp_delete_remote_resource",
            description="delete remote resource",
            args_schema={},
            source="mcp",
            side_effect_level="write",
            risk_level="high",
            capability_tags=["external_tool", "destructive", "open_world"],
            domain_tags=["external"],
        )

        ranked = self.strategy.order_specs([risky_external_spec, verification_spec], state=self.state)

        self.assertEqual(ranked[0].name, "tool_verify_target")
        self.assertEqual(ranked[-1].name, "mcp_delete_remote_resource")


if __name__ == "__main__":
    unittest.main()
