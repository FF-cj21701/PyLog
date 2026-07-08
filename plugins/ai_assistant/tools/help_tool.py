import importlib
import os
import sys


def _robust_import():
    try:
        from .base_tool import BaseTool
        from .registry import register_tool, tool_registry
        from ..ai_core.api_docs import APIDocumentation
        return BaseTool, register_tool, tool_registry, APIDocumentation
    except (ImportError, ValueError):
        pass

    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
        from plugins.ai_assistant.tools.registry import register_tool, tool_registry
        from plugins.ai_assistant.ai_core.api_docs import APIDocumentation
        return BaseTool, register_tool, tool_registry, APIDocumentation
    except ImportError:
        pass

    tools_dir = os.path.dirname(os.path.abspath(__file__))
    assistant_dir = os.path.dirname(tools_dir)
    if assistant_dir not in sys.path:
        sys.path.insert(0, assistant_dir)

    BaseTool = importlib.import_module("base_tool").BaseTool
    registry_module = importlib.import_module("registry")
    register_tool = registry_module.register_tool
    tool_registry = registry_module.tool_registry
    from plugins.ai_assistant.ai_core.api_docs import APIDocumentation

    return BaseTool, register_tool, tool_registry, APIDocumentation


BaseTool, register_tool, tool_registry, APIDocumentation = _robust_import()


def _instantiate_tool(tool_class, main_window=None):
    try:
        return tool_class(main_window=main_window)
    except TypeError:
        pass
    try:
        return tool_class()
    except Exception:
        return None


@register_tool
class HelpTool(BaseTool):
    def __init__(self, main_window=None):
        super().__init__(
            "get_help",
            "Get detailed documentation for AI tools or PyLog API functions",
            {
                "query": {
                    "type": "string",
                    "description": "A tool name, API function name, or keyword such as plotting or analysis",
                }
            },
            metadata={
                "required_args": ["query"],
                "side_effect_level": "read",
                "capability_tags": ["inspection", "search"],
                "keywords": [
                    "help",
                    "tool help",
                    "api help",
                    "documentation",
                    "docs",
                    "how to use tool",
                ],
            },
        )
        self.main_window = main_window

    def execute(self, query=None):
        if not query:
            return {"error": "query is required"}

        query = str(query).strip().lower()
        results = {}

        for tool_class in tool_registry.tools:
            try:
                tool = _instantiate_tool(tool_class, main_window=self.main_window)
                if tool is None:
                    continue
                tool_name = str(getattr(tool, "name", "") or "").lower()
                if tool_name == query or query in tool_name:
                    results[f"Tool: {tool.name}"] = {
                        "description": getattr(tool, "description", ""),
                        "parameters": getattr(tool, "args_schema", {}),
                        "required_args": getattr(tool, "required_args", []),
                    }
            except Exception:
                approx_name = tool_class.__name__.replace("Tool", "").lower()
                if query in approx_name:
                    results[f"Tool (approx): {approx_name}"] = tool_class.__doc__ or "No detailed description available"

        for topic, content in APIDocumentation.DOCS_BY_TOPIC.items():
            topic_key = str(topic).lower()
            body = str(content).lower()
            if query in topic_key or query in body:
                results[f"API Topic: {topic}"] = content

        if not results:
            topics = list(APIDocumentation.DOCS_BY_TOPIC.keys())
            tool_names = []
            for tool_class in tool_registry.tools:
                tool = _instantiate_tool(tool_class, main_window=self.main_window)
                tool_names.append(tool.name if tool is not None else tool_class.__name__)

            return {
                "message": f"No direct match for '{query}'.",
                "available_topics": topics,
                "available_tools": tool_names,
                "suggestion": "Try a more specific tool name or one of the listed topics.",
            }

        return {"ok": True, "results": results}
