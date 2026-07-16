from __future__ import annotations

from typing import Callable, Iterable

from .base_tool import BaseTool


class SearchToolsTool(BaseTool):
    """Search the current AI tool catalog without exposing full schemas."""

    is_abstract = True

    def __init__(self, search_callback: Callable[..., list[dict]]):
        super().__init__(
            "search_tools",
            "Search the available AI tool catalog by task, capability, domain, or keyword before loading tools.",
            {
                "query": {
                    "type": "string",
                    "description": "Task or capability to search for, such as run script, plot curve, edit file, or verify tests.",
                },
                "domain": {
                    "type": "string",
                    "description": "Optional exact domain tag filter.",
                    "nullable": True,
                },
                "capability": {
                    "type": "string",
                    "description": "Optional exact capability tag filter.",
                    "nullable": True,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of matching tools to return. Defaults to 5.",
                    "minimum": 1,
                    "maximum": 5,
                    "nullable": True,
                },
            },
            metadata={
                "required_args": ["query"],
                "side_effect_level": "read",
                "risk_level": "low",
                "output_type": "structured_data",
                "capability_tags": ["tool_discovery", "search", "inspection"],
                "domain_tags": ["agent"],
                "keywords": ["search tools", "find tools", "tool catalog", "tool index", "discover tools"],
            },
        )
        self._search_callback = search_callback

    def execute(self, query, domain=None, capability=None, limit=5):
        results = self._search_callback(query=query, domain=domain, capability=capability, limit=limit)
        return {
            "ok": True,
            "summary": f"Found {len(results)} matching tools",
            "tools": results,
        }


class LoadToolsTool(BaseTool):
    """Activate selected tool schemas for the current AI worker/session."""

    is_abstract = True

    def __init__(self, load_callback: Callable[[Iterable[str]], dict]):
        super().__init__(
            "load_tools",
            "Load selected tool definitions into the current session after search_tools identifies relevant tools.",
            {
                "names": {
                    "type": "array",
                    "description": "Tool names to load into the current session.",
                    "items": {"type": "string"},
                },
            },
            metadata={
                "required_args": ["names"],
                "side_effect_level": "none",
                "risk_level": "low",
                "output_type": "structured_data",
                "capability_tags": ["tool_discovery", "tool_loading"],
                "domain_tags": ["agent"],
                "keywords": ["load tools", "activate tools", "tool schema", "enable tools"],
            },
        )
        self._load_callback = load_callback

    def execute(self, names):
        if isinstance(names, str):
            names = [names]
        if not isinstance(names, list):
            return {"ok": False, "error": "names must be a list of tool names"}

        result = self._load_callback(names)
        loaded = result.get("loaded", [])
        return {
            "ok": bool(result.get("ok", True)),
            "summary": result.get("summary") or f"Loaded {len(loaded)} tools",
            **result,
        }
