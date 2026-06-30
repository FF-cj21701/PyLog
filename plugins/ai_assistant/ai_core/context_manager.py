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
        for item in context_data:
            if not isinstance(item, Mapping):
                continue
            line = self._format_context_item(item)
            if line:
                selection_lines.append(line)
            script_state = self._extract_script_state(item)
            if script_state:
                script_state_lines.extend(self._format_script_state(script_state))

        sections = []
        if not selection_lines:
            selection_lines = []
        else:
            sections.append(ContextSection(title="selection", lines=selection_lines, priority=10))
        if script_state_lines:
            sections.append(ContextSection(title="active_script_state", lines=script_state_lines, priority=20))
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
