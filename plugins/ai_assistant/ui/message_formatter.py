"""Message formatting utilities for AI responses."""

import json
import re

from ..ai_core.tool_result import tool_result_content, tool_result_error, tool_result_ok, tool_result_to_dict


class MessageFormatter:
    """Formats AI messages for better display in the UI."""

    @staticmethod
    def format_ai_response(text: str) -> str:
        """Format AI response for display."""
        if not text:
            return text

        text = MessageFormatter._format_tool_calls(text)
        text = MessageFormatter._format_code_in_tools(text)
        text = MessageFormatter._clean_escapes(text)
        return text

    @staticmethod
    def _format_tool_calls(text: str) -> str:
        """Format tool call markers into readable text."""
        tool_call_pattern = r"\[执行工具\]\s+(\w+)\((\{.*?\})\)"

        def replace_tool_call(match):
            tool_name = match.group(1)
            args = match.group(2)

            try:
                args_dict = json.loads(args)
                display_args = {k: v for k, v in args_dict.items() if k != "code"}
                if display_args:
                    args_str = json.dumps(display_args, ensure_ascii=False, indent=2)
                    return f"\nTool call: `{tool_name}`\n\nArguments:\n```json\n{args_str}\n```\n"
                return f"\nTool call: `{tool_name}`\n"
            except Exception:
                return f"\nTool call: `{tool_name}`\n"

        text = re.sub(tool_call_pattern, replace_tool_call, text, flags=re.DOTALL)

        tool_result_pattern = r"\[工具结果\]\s+(\{.*?\})"

        def replace_tool_result(match):
            result = match.group(1)
            try:
                parsed = json.loads(result)
            except Exception:
                return f"\nTool result: {result[:100]}...\n"

            payload = tool_result_to_dict(parsed)
            if tool_result_ok(payload):
                content = tool_result_content(payload, fallback_to_summary=False)
                summary = payload.get("summary") or ""
                if content and summary and content != summary:
                    return f"\nTool succeeded: {summary}\n{content}\n"
                if summary:
                    return f"\nTool succeeded: {summary}\n"
                return "\nTool succeeded.\n"

            error_text = tool_result_error(payload) or "Unknown error"
            return f"\nTool failed: {error_text}\n"

        text = re.sub(tool_result_pattern, replace_tool_result, text, flags=re.DOTALL)

        thought_pattern = r"\[思考\]\s*(.+?)(?=\n|$)"
        text = re.sub(thought_pattern, r"\nThought: \1", text)

        return text

    @staticmethod
    def _format_code_in_tools(text: str) -> str:
        """Extract and format code from tool arguments."""
        pattern = r'"code":\s*"((?:[^"\\]|\\.)*)"'

        def replace_code(match):
            code = match.group(1)
            code = code.replace("\\n", "\n").replace('\\"', '"').replace("\\\\", "\\")

            lines = code.split("\n")
            if len(lines) > 10:
                preview = "\n".join(lines[:10]) + "\n# ... (code written to editor)"
            else:
                preview = code

            return f"\n\nCode preview:\n```python\n{preview}\n```\n\n"

        if "[执行工具]" in text or "Tool call:" in text:
            text = re.sub(pattern, replace_code, text)

        return text

    @staticmethod
    def _clean_escapes(text: str) -> str:
        """Clean up escape sequences in the text."""
        code_blocks = []

        def save_code_block(match):
            code_blocks.append(match.group(0))
            return f"__CODE_BLOCK_{len(code_blocks) - 1}__"

        text = re.sub(r"```[\s\S]*?```", save_code_block, text)

        text = text.replace("\\n", "\n")
        text = text.replace("\\t", "    ")
        text = text.replace('\\"', '"')
        text = text.replace("\\'", "'")
        text = text.replace("\\\\", "\\")

        for i, block in enumerate(code_blocks):
            text = text.replace(f"__CODE_BLOCK_{i}__", block)

        return text

    @staticmethod
    def format_tool_summary(tool_name: str, success: bool, summary: str = "") -> str:
        """Format a summary of tool execution."""
        status = "succeeded" if success else "failed"
        if summary:
            return f"\n{tool_name} {status}: {summary}\n"
        return f"\n{tool_name} {status}\n"
