from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional


@dataclass
class ContextSection:
    title: str
    lines: List[str]
    priority: int = 100

    def is_empty(self) -> bool:
        return not any(str(line).strip() for line in self.lines)


class ContextManager:
    """Build structured prompt context for the PyLog agent runtime."""

    HEADER = "[ALIVE Context]"
    MAX_RECENT_TOOL_RESULTS = 5
    MAX_TOOL_FIELD_LENGTH = 180

    def build_context_block(self, context_data: Optional[Iterable[Mapping[str, Any]]]) -> str:
        sections = self.build_sections(context_data)
        lines = []
        for section in sorted(sections, key=lambda item: item.priority):
            lines.extend(section.lines)
        if not lines:
            return ""
        return self.HEADER + "\n" + "\n".join(lines)

    def build_sections(self, context_data: Optional[Iterable[Mapping[str, Any]]]) -> List[ContextSection]:
        if not context_data:
            return []

        selection_lines = []
        script_state_lines = []
        tool_result_items = []
        for item in context_data:
            if not isinstance(item, Mapping):
                continue
            line = self._format_context_item(item)
            if line:
                selection_lines.append(line)
            script_state = self._extract_script_state(item)
            if script_state:
                script_state_lines.extend(self._format_script_state(script_state))
            tool_result_items.extend(self._extract_tool_result_items(item))

        sections = []
        if not selection_lines:
            selection_lines = []
        else:
            sections.append(ContextSection(title="selection", lines=selection_lines, priority=10))
        if script_state_lines:
            sections.append(ContextSection(title="active_script_state", lines=script_state_lines, priority=20))
        tool_result_lines = self._format_recent_tool_results(tool_result_items)
        if tool_result_lines:
            sections.append(ContextSection(title="recent_tool_results", lines=tool_result_lines, priority=30))
        return sections

    def compose_prompt(self, user_text: str, context_data: Optional[Iterable[Mapping[str, Any]]]) -> str:
        context_block = self.build_context_block(context_data)
        if not context_block:
            return user_text
        return context_block + "\n\n[User Message]\n" + user_text

    def _format_context_item(self, item: Mapping[str, Any]) -> str:
        item_type = item.get("type")
        if item_type == "well":
            name = item.get("name") or item.get("display_name") or ""
            db_path = item.get("db_path")
            return f"Well: {name} (db={db_path})"
        if item_type == "curve":
            name = item.get("name") or item.get("display_name") or ""
            well_id = item.get("well_id")
            db_path = item.get("db_path")
            well_name = self._lookup_well_name(db_path, well_id)
            if well_name:
                return f"Curve: {name} (well={well_name}, db={db_path})"
            return f"Curve: {name} (db={db_path})"
        return ""

    def _extract_script_state(self, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if isinstance(item.get("script_state"), Mapping):
            return item.get("script_state")
        item_type = item.get("type")
        if item_type in {"script_state", "active_script", "script"}:
            return item
        return None

    def _format_script_state(self, state: Mapping[str, Any]) -> List[str]:
        lines = ["[Active Script State]"]
        self._append_state_line(lines, "editor_id", state.get("editor_id"))
        self._append_state_line(lines, "script_path", state.get("script_path"))
        self._append_state_line(lines, "has_unsaved_changes", self._format_bool(state.get("has_unsaved_changes")))
        self._append_state_line(lines, "ai_draft_active", self._format_bool(state.get("is_preview_active")))
        self._append_state_line(lines, "preview_session_id", state.get("preview_session_id"))
        self._append_state_line(lines, "preview_source", state.get("preview_source"))
        self._append_state_line(lines, "base_hash", state.get("base_hash"))
        self._append_state_line(lines, "draft_hash", state.get("draft_hash"))
        self._append_state_line(lines, "working_hash", state.get("working_hash"))
        self._append_state_line(lines, "should_run_from", state.get("should_run_from"))
        self._append_state_line(lines, "should_save_to", state.get("should_save_to"))
        return lines if len(lines) > 1 else []

    def _extract_tool_result_items(self, item: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        item_type = item.get("type")
        if item_type == "recent_tool_results":
            for key in ("items", "results", "tool_results", "steps"):
                value = item.get(key)
                if isinstance(value, list):
                    return [entry for entry in value if isinstance(entry, Mapping)]
            return []
        if isinstance(item.get("tool_steps"), list):
            return [entry for entry in item.get("tool_steps", []) if isinstance(entry, Mapping)]
        if item_type in {"tool_result", "tool_step"}:
            return [item]
        if any(key in item for key in ("tool_name", "tool", "command")) and any(
            key in item for key in ("result", "error", "status", "ok")
        ):
            return [item]
        return []

    def _format_recent_tool_results(self, items: List[Mapping[str, Any]]) -> List[str]:
        selected = self._select_recent_tool_results(items)
        if not selected:
            return []

        lines = ["[Recent Tool Results]"]
        for item in selected:
            line = self._format_tool_result_line(item)
            if line:
                lines.append(line)
        return lines if len(lines) > 1 else []

    def _select_recent_tool_results(self, items: List[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        if len(items) <= self.MAX_RECENT_TOOL_RESULTS:
            return items

        selected_indexes = set()
        for index in range(len(items) - 1, -1, -1):
            if self._tool_result_failed(items[index]):
                selected_indexes.add(index)
            if len(selected_indexes) >= self.MAX_RECENT_TOOL_RESULTS:
                break

        for index in range(len(items) - 1, -1, -1):
            if len(selected_indexes) >= self.MAX_RECENT_TOOL_RESULTS:
                break
            selected_indexes.add(index)

        return [items[index] for index in sorted(selected_indexes)]

    def _format_tool_result_line(self, item: Mapping[str, Any]) -> str:
        result = item.get("result")
        result_map = result if isinstance(result, Mapping) else {}
        tool_name = (
            item.get("tool_name")
            or item.get("tool")
            or item.get("command")
            or result_map.get("tool_name")
            or "unknown_tool"
        )
        status = self._format_tool_status(item, result_map)
        parts = [f"- {tool_name}: {status}"]

        summary = self._first_text(
            item.get("summary"),
            item.get("message"),
            result_map.get("summary"),
            result_map.get("message"),
            result_map.get("content"),
            result_map.get("stdout"),
            result if isinstance(result, str) else None,
        )
        if summary:
            parts.append(self._truncate(summary))

        error = self._first_text(item.get("error"), result_map.get("error"), result_map.get("stderr"))
        if error and status != "ok":
            parts.append(f"error: {self._truncate(error)}")

        for key in ("filepath", "file_path", "script_path"):
            value = item.get(key) or result_map.get(key)
            if value:
                parts.append(f"{key}: {self._truncate(value)}")
                break

        exit_code = item.get("exit_code", result_map.get("exit_code"))
        if exit_code is not None:
            parts.append(f"exit_code: {exit_code}")

        previewed = item.get("previewed", result_map.get("previewed"))
        if previewed is not None:
            parts.append(f"previewed: {self._format_bool(previewed)}")

        script_state = item.get("script_state") or result_map.get("script_state")
        if isinstance(script_state, Mapping):
            state_path = script_state.get("script_path")
            if state_path and "script_path:" not in " ".join(parts):
                parts.append(f"script_path: {self._truncate(state_path)}")
            if script_state.get("is_preview_active") is not None:
                parts.append(f"ai_draft_active: {self._format_bool(script_state.get('is_preview_active'))}")

        return "; ".join(part for part in parts if part)

    def _format_tool_status(self, item: Mapping[str, Any], result_map: Mapping[str, Any]) -> str:
        status = item.get("status")
        if status:
            normalized = str(status).lower()
            if normalized in {"completed", "success", "succeeded"}:
                return "ok"
            if normalized in {"failed", "failure", "error"}:
                return "failed"
            return normalized
        ok = item.get("ok", result_map.get("ok"))
        if ok is True:
            return "ok"
        if ok is False:
            return "failed"
        if item.get("error") or result_map.get("error"):
            return "failed"
        return "unknown"

    def _tool_result_failed(self, item: Mapping[str, Any]) -> bool:
        result = item.get("result")
        result_map = result if isinstance(result, Mapping) else {}
        return self._format_tool_status(item, result_map) == "failed"

    def _first_text(self, *values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return ""

    def _truncate(self, value: Any) -> str:
        text = " ".join(str(value).split())
        if len(text) <= self.MAX_TOOL_FIELD_LENGTH:
            return text
        return text[: self.MAX_TOOL_FIELD_LENGTH - 3].rstrip() + "..."

    @staticmethod
    def _append_state_line(lines: List[str], label: str, value: Any) -> None:
        if value is None or value == "":
            return
        lines.append(f"- {label}: {value}")

    @staticmethod
    def _format_bool(value: Any) -> str:
        if value is True:
            return "yes"
        if value is False:
            return "no"
        return ""

    @staticmethod
    def _lookup_well_name(db_path: Any, well_id: Any) -> str:
        if not db_path or not well_id:
            return ""
        try:
            conn = sqlite3.connect(db_path)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM wells WHERE id=?", (well_id,))
                row = cursor.fetchone()
                return row[0] if row else ""
            finally:
                conn.close()
        except Exception:
            return ""
