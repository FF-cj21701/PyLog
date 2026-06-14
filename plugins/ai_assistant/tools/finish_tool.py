import importlib
import os


# Try a few import paths so the tool still loads in different plugin contexts.
try:
    from .base_tool import BaseTool
except ImportError:
    try:
        from plugins.ai_assistant.tools.base_tool import BaseTool
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        BaseTool = importlib.import_module("base_tool").BaseTool

try:
    from .registry import register_tool
except ImportError:
    try:
        from plugins.ai_assistant.tools.registry import register_tool
    except ImportError:
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        register_tool = importlib.import_module("registry").register_tool


@register_tool
class FinishTool(BaseTool):
    """
    Explicitly signal the end of the task.
    Use this tool when all requested work is complete or when a final answer is ready.
    """

    def __init__(self):
        super().__init__(
            "tool_finish",
            "Signal that the task is complete. Prefer using this as a control signal, not a second full reply.",
            {
                "final_answer": {
                    "type": "string",
                    "description": "Optional final answer. Leave empty if the visible response was already provided.",
                    "nullable": True,
                },
                "summary": {
                    "type": "string",
                    "description": "A brief summary of the completed work.",
                    "nullable": True,
                },
            },
            metadata={
                "lifecycle_role": "finish",
                "side_effect_level": "none",
                "risk_level": "low",
                "output_type": "control_signal",
                "capability_tags": ["lifecycle", "finish"],
                "usage_hint": "Call only after the task is actually complete and required verification has passed.",
            },
        )

    def execute(self, final_answer=None, summary=None):
        visible_answer = (final_answer or "").strip()
        final_summary = summary or "Task finished successfully."
        return {
            "ok": True,
            "message": "Task finished successfully.",
            "final_answer": visible_answer,
            "content": visible_answer,
            "summary": final_summary,
        }
