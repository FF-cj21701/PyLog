from __future__ import annotations

import asyncio
from typing import Any, Dict, Iterable, Optional

from .tool_result import error_tool_result, normalize_tool_result
from .tool_selection import ToolSelectionStrategy


class ToolDispatcher:
    """Unified execution entrypoint for local and MCP-backed tools."""

    def __init__(self, tools: Optional[Iterable[Any]] = None):
        self.set_tools(tools or [])

    def set_tools(self, tools: Iterable[Any]) -> None:
        self.tools = list(tools)
        self._tool_map = {tool.name: tool for tool in self.tools if getattr(tool, "name", None)}

    def find_tool(self, tool_name: str):
        return self._tool_map.get(tool_name)

    def get_spec(self, tool_name: str):
        tool = self.find_tool(tool_name)
        if not tool:
            return None
        return getattr(tool, "spec", None)

    def list_specs(self):
        specs = []
        for tool in self.tools:
            spec = getattr(tool, "spec", None)
            if spec is not None:
                specs.append(spec)
        return specs

    def list_specs_by_source(self, source: Optional[str] = None):
        specs = self.list_specs()
        if source is None:
            return specs
        return [spec for spec in specs if getattr(spec, "source", None) == source]

    def list_ranked_specs(self, state=None, strategy: Optional[ToolSelectionStrategy] = None):
        strategy = strategy or ToolSelectionStrategy()
        return strategy.order_specs(self.list_specs(), state=state)

    async def execute(self, tool_name: str, args: Optional[Dict[str, Any]] = None):
        tool = self.find_tool(tool_name)
        if tool is None:
            raise KeyError(f"Tool not found: {tool_name}")

        call_args = args or {}
        spec = getattr(tool, "spec", None)
        missing_args = self._get_missing_required_args(spec, call_args)
        if missing_args:
            source = "mcp" if tool_name.startswith("mcp_") else "local"
            return tool, error_tool_result(
                tool_name,
                f"Missing required arguments for {tool_name}: {', '.join(missing_args)}",
                source=source,
                missing_required_args=missing_args,
            )

        argument_rule_error = self._validate_argument_rules(spec, call_args)
        if argument_rule_error:
            source = "mcp" if tool_name.startswith("mcp_") else "local"
            return tool, error_tool_result(
                tool_name,
                argument_rule_error["message"],
                source=source,
                argument_rule_violation=argument_rule_error,
            )

        if asyncio.iscoroutinefunction(tool.execute):
            raw_result = await tool.execute(**call_args)
        else:
            raw_result = await asyncio.to_thread(tool.execute, **call_args)

        source = "mcp" if tool_name.startswith("mcp_") else "local"
        return tool, normalize_tool_result(tool_name, raw_result, source=source)

    @staticmethod
    def _get_missing_required_args(spec, args: Optional[Dict[str, Any]]) -> list[str]:
        if spec is None or not hasattr(spec, "get_required_args"):
            return []

        args = args or {}
        missing = []
        for name in spec.get_required_args():
            value = args.get(name)
            if value is None:
                missing.append(name)
                continue
            if isinstance(value, str) and not value.strip():
                missing.append(name)
        return missing

    @classmethod
    def _validate_argument_rules(cls, spec, args: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if spec is None or not hasattr(spec, "get_argument_rules"):
            return None

        args = args or {}
        for rule in spec.get_argument_rules():
            rule_type = str(rule.get("type") or "").strip()
            if rule_type == "exactly_one_of":
                error = cls._validate_exactly_one_of_rule(rule, args)
                if error:
                    return error
            elif rule_type == "at_least_one_of":
                error = cls._validate_at_least_one_of_rule(rule, args)
                if error:
                    return error
            elif rule_type == "requires_when":
                error = cls._validate_requires_when_rule(rule, args)
                if error:
                    return error
        return None

    @classmethod
    def _validate_exactly_one_of_rule(cls, rule: Dict[str, Any], args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fields = [str(name) for name in rule.get("fields", []) if str(name).strip()]
        provided = [name for name in fields if cls._has_meaningful_value(args.get(name))]
        if len(provided) == 1:
            return None
        message = (
            f"Exactly one of {', '.join(fields)} must be provided"
            if fields
            else "Invalid argument rule"
        )
        return {
            "type": "exactly_one_of",
            "fields": fields,
            "provided": provided,
            "message": message,
        }

    @classmethod
    def _validate_at_least_one_of_rule(cls, rule: Dict[str, Any], args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        fields = [str(name) for name in rule.get("fields", []) if str(name).strip()]
        provided = [name for name in fields if cls._has_meaningful_value(args.get(name))]
        if provided:
            return None
        message = (
            f"At least one of {', '.join(fields)} must be provided"
            if fields
            else "Invalid argument rule"
        )
        return {
            "type": "at_least_one_of",
            "fields": fields,
            "provided": provided,
            "message": message,
        }

    @classmethod
    def _validate_requires_when_rule(cls, rule: Dict[str, Any], args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        trigger_arg = str(rule.get("arg") or "").strip()
        required_arg = str(rule.get("requires") or "").strip()
        expected_value = rule.get("equals")
        if not trigger_arg or not required_arg:
            return None
        trigger_value = args.get(trigger_arg)
        if expected_value == "__non_empty__":
            if not cls._has_meaningful_value(trigger_value):
                return None
        elif trigger_value != expected_value:
            return None
        if cls._has_meaningful_value(args.get(required_arg)):
            return None
        if expected_value == "__non_empty__":
            expectation_text = "provided"
        else:
            expectation_text = repr(expected_value)
        return {
            "type": "requires_when",
            "arg": trigger_arg,
            "equals": expected_value,
            "requires": required_arg,
            "message": (
                f"{required_arg} is required when {trigger_arg} is "
                f"{expectation_text}"
            ),
        }

    @staticmethod
    def _has_meaningful_value(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        return True
