import importlib
import os
import sys

from PySide6.QtCore import QEventLoop

try:
    from .base_tool import BaseTool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool

try:
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        register_tool = importlib.import_module("registry").register_tool


def _run_executor_signal(tool_executor, signal, payload):
    loop = QEventLoop()
    result = {"ok": False, "error": "execution failed"}

    def on_tool_executed(result_str):
        nonlocal result
        try:
            import json

            result = json.loads(result_str)
        except Exception as exc:
            result = {"ok": False, "error": f"Failed to parse result: {exc}"}
        finally:
            loop.quit()

    try:
        tool_executor.tool_executed.connect(on_tool_executed)
        signal.emit(payload)
        loop.exec()
    finally:
        try:
            tool_executor.tool_executed.disconnect(on_tool_executed)
        except Exception:
            pass

    return result


@register_tool
class OpenAgentPageTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "tool_open_agent_page",
            "Open or focus a reusable agent-owned local HTML/web workspace page. Use this to show reviews, reports, plans, summaries, diagrams, or any structured content in a dedicated rendered page inside the workspace.",
            {
                "page_id": {
                    "type": "string",
                    "description": "Stable page identifier used for later updates. Reusing the same id focuses the existing page instead of opening duplicates.",
                },
                "title": {
                    "type": "string",
                    "description": "Window title shown in the workspace tab.",
                },
                "content": {
                    "type": "string",
                    "description": "Main page content, rendered as text or HTML depending on format.",
                    "nullable": True,
                },
                "summary": {
                    "type": "string",
                    "description": "Short summary shown near the top of the page.",
                    "nullable": True,
                },
                "content_title": {
                    "type": "string",
                    "description": "Label for the main content section.",
                    "nullable": True,
                },
                "eyebrow": {
                    "type": "string",
                    "description": "Small heading above the page title.",
                    "nullable": True,
                },
                "format": {
                    "type": "string",
                    "description": "Main content format: text or html. Use html when you want a rendered web-style page.",
                    "nullable": True,
                },
                "meta": {
                    "type": "array",
                    "description": "Optional pill metadata shown near the top of the page.",
                    "items": {"type": "string"},
                    "nullable": True,
                },
                "sections": {
                    "type": "array",
                    "description": "Optional structured sections shown below the main content.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "format": {"type": "string", "nullable": True},
                        },
                        "required": ["title", "content"],
                    },
                    "nullable": True,
                },
                "mode": {
                    "type": "string",
                    "description": "dialog or mdi. Defaults to an mdi workspace page.",
                    "nullable": True,
                },
            },
            metadata={
                "required_args": ["page_id", "title"],
                "side_effect_level": "none",
                "capability_tags": ["ui", "agent_page", "workspace"],
                "domain_tags": ["agent"],
                "keywords": [
                    "agent page",
                    "html page",
                    "web page",
                    "workspace page",
                    "open page",
                    "report page",
                    "review page",
                    "rendered html",
                ],
                "usage_hint": "Use a stable page_id like report:well-summary or review:editor-1 so later updates reuse the same local HTML workspace page.",
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, page_id=None, title=None, **kwargs):
        if not self.main_window or not self.tool_executor:
            return {"ok": False, "error": "no main window"}
        if not page_id or not str(page_id).strip():
            return {"ok": False, "error": "page_id is required"}
        if not title or not str(title).strip():
            return {"ok": False, "error": "title is required"}

        payload = {"page_id": str(page_id).strip(), "title": str(title).strip(), **kwargs}
        return _run_executor_signal(self.tool_executor, self.tool_executor.execute_open_agent_page, payload)


@register_tool
class UpdateAgentPageTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "tool_update_agent_page",
            "Update the content of an existing agent-owned local HTML/web workspace page, or create it if it does not exist yet.",
            {
                "page_id": {
                    "type": "string",
                    "description": "Stable page identifier to update.",
                },
                "title": {
                    "type": "string",
                    "description": "Optional updated window title.",
                    "nullable": True,
                },
                "content": {
                    "type": "string",
                    "description": "Updated main page content, rendered as text or HTML depending on format.",
                    "nullable": True,
                },
                "summary": {
                    "type": "string",
                    "description": "Updated summary.",
                    "nullable": True,
                },
                "content_title": {
                    "type": "string",
                    "description": "Updated main content label.",
                    "nullable": True,
                },
                "eyebrow": {
                    "type": "string",
                    "description": "Updated small heading above the title.",
                    "nullable": True,
                },
                "format": {
                    "type": "string",
                    "description": "Main content format: text or html. Use html when you want a rendered web-style page.",
                    "nullable": True,
                },
                "meta": {
                    "type": "array",
                    "description": "Updated metadata pills.",
                    "items": {"type": "string"},
                    "nullable": True,
                },
                "sections": {
                    "type": "array",
                    "description": "Updated structured sections.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "content": {"type": "string"},
                            "format": {"type": "string", "nullable": True},
                        },
                        "required": ["title", "content"],
                    },
                    "nullable": True,
                },
                "mode": {
                    "type": "string",
                    "description": "dialog or mdi. Defaults to an mdi workspace page.",
                    "nullable": True,
                },
            },
            metadata={
                "required_args": ["page_id"],
                "side_effect_level": "none",
                "capability_tags": ["ui", "agent_page", "workspace"],
                "domain_tags": ["agent"],
                "keywords": [
                    "update page",
                    "update html page",
                    "update web page",
                    "workspace page",
                    "refresh page content",
                ],
                "usage_hint": "Call this repeatedly with the same page_id to keep a live local HTML workspace page updated as work progresses.",
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, page_id=None, **kwargs):
        if not self.main_window or not self.tool_executor:
            return {"ok": False, "error": "no main window"}
        if not page_id or not str(page_id).strip():
            return {"ok": False, "error": "page_id is required"}

        payload = {"page_id": str(page_id).strip(), **kwargs}
        return _run_executor_signal(self.tool_executor, self.tool_executor.execute_update_agent_page, payload)


@register_tool
class CloseAgentPageTool(BaseTool):
    def __init__(self, main_window=None, tool_executor=None):
        super().__init__(
            "tool_close_agent_page",
            "Close an existing agent-owned local HTML/web workspace page by page_id.",
            {
                "page_id": {
                    "type": "string",
                    "description": "Stable page identifier to close.",
                }
            },
            metadata={
                "required_args": ["page_id"],
                "side_effect_level": "none",
                "capability_tags": ["ui", "agent_page", "workspace"],
                "domain_tags": ["agent"],
                "keywords": [
                    "close page",
                    "close html page",
                    "close web page",
                    "close workspace page",
                ],
            },
        )
        self.main_window = main_window
        self.tool_executor = tool_executor

    def execute(self, page_id=None):
        if not self.main_window or not self.tool_executor:
            return {"ok": False, "error": "no main window"}
        if not page_id or not str(page_id).strip():
            return {"ok": False, "error": "page_id is required"}

        payload = {"page_id": str(page_id).strip()}
        return _run_executor_signal(self.tool_executor, self.tool_executor.execute_close_agent_page, payload)
