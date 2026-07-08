from __future__ import annotations

import os
import sys
import unittest


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from plugins.ai_assistant.ai_core.task_domain_router import TaskDomainRouter
from plugins.ai_assistant.ai_core.tool_spec import ToolSpec


class TaskDomainRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = TaskDomainRouter()

    @staticmethod
    def _spec(name, domain_tags=None, capability_tags=None, is_verification_tool=False, keywords=None):
        return ToolSpec(
            name=name,
            description=name,
            args_schema={},
            domain_tags=list(domain_tags or []),
            capability_tags=list(capability_tags or []),
            keywords=list(keywords or []),
            is_verification_tool=is_verification_tool,
        )

    def test_detects_geoscience_domain_from_chinese_prompt(self):
        detected = self.router.detect_domains(prompt="请列出井和曲线并作图")

        self.assertIn("geoscience", detected)

    def test_routes_code_task_toward_code_tools(self):
        specs = [
            self._spec("search_code", domain_tags=["code"]),
            self._spec("apply_patch", domain_tags=["code", "script"]),
            self._spec("list_curves", domain_tags=["geoscience", "pylog"]),
            self._spec("finish", capability_tags=["lifecycle"]),
            self._spec("verify_target", domain_tags=["code", "script"], capability_tags=["verification"], is_verification_tool=True),
        ]

        routed = self.router.route_specs(specs, prompt="修复 calculate_sum 函数并补测试")
        names = {spec.name for spec in routed}

        self.assertIn("search_code", names)
        self.assertIn("apply_patch", names)
        self.assertIn("finish", names)
        self.assertIn("verify_target", names)
        self.assertNotIn("list_curves", names)

    def test_routes_script_task_toward_script_tools(self):
        specs = [
            self._spec("open_script_file", domain_tags=["script"]),
            self._spec("run_script", domain_tags=["script"]),
            self._spec("search_code", domain_tags=["code"]),
            self._spec("plot", domain_tags=["geoscience", "pylog"]),
        ]

        routed = self.router.route_specs(specs, prompt="修改脚本并运行 python 脚本验证")
        names = {spec.name for spec in routed}

        self.assertIn("open_script_file", names)
        self.assertIn("run_script", names)
        self.assertIn("search_code", names)
        self.assertNotIn("plot", names)

    def test_routes_geoscience_task_toward_pylog_tools(self):
        specs = [
            self._spec("list_curves", domain_tags=["geoscience", "pylog"]),
            self._spec("plot", domain_tags=["geoscience", "pylog"]),
            self._spec("search_code", domain_tags=["code"]),
            self._spec("open_script_file", domain_tags=["script"]),
        ]

        routed = self.router.route_specs(specs, prompt="plot well Gangtan1_SL curves GR and DEN")
        names = {spec.name for spec in routed}

        self.assertIn("list_curves", names)
        self.assertIn("plot", names)
        self.assertNotIn("search_code", names)
        self.assertNotIn("open_script_file", names)

    def test_routes_mixed_task_to_multiple_domains(self):
        specs = [
            self._spec("plot", domain_tags=["geoscience", "pylog"]),
            self._spec("set_script_code", domain_tags=["script"]),
            self._spec("run_script", domain_tags=["script"]),
            self._spec("verify_target", domain_tags=["code", "script"], capability_tags=["verification"], is_verification_tool=True),
        ]

        routed = self.router.route_specs(specs, prompt="写一个 PyLog 脚本读取 well 曲线并作图，然后运行验证")
        names = {spec.name for spec in routed}

        self.assertIn("plot", names)
        self.assertIn("set_script_code", names)
        self.assertIn("run_script", names)
        self.assertIn("verify_target", names)

    def test_agent_page_tools_are_always_visible_across_domains(self):
        specs = [
            self._spec("open_agent_page", domain_tags=["agent"], capability_tags=["ui", "agent_page", "workspace"]),
            self._spec("update_agent_page", domain_tags=["agent"], capability_tags=["ui", "agent_page", "workspace"]),
            self._spec("close_agent_page", domain_tags=["agent"], capability_tags=["ui", "agent_page", "workspace"]),
            self._spec("plot", domain_tags=["geoscience", "pylog"]),
        ]

        routed = self.router.route_specs(specs, prompt="修复 Python 脚本并运行验证")
        names = {spec.name for spec in routed}

        self.assertIn("open_agent_page", names)
        self.assertIn("update_agent_page", names)
        self.assertIn("close_agent_page", names)

    def test_keyword_matched_tool_is_kept_even_when_domain_tags_do_not_match(self):
        specs = [
            self._spec("tool_plot", domain_tags=["geoscience", "pylog"]),
            self._spec("open_html_preview", domain_tags=["agent"], keywords=["html preview", "web page"]),
        ]

        routed = self.router.route_specs(specs, prompt="open this html preview in a web page")
        names = {spec.name for spec in routed}

        self.assertIn("open_html_preview", names)
        self.assertNotIn("tool_plot", names)


if __name__ == "__main__":
    unittest.main()
