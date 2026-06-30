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
        for section in sections:
            lines.extend(section.lines)
        if not lines:
            return ""
        return self.HEADER + "\n" + "\n".join(lines)

    def build_sections(self, context_data: Optional[Iterable[Mapping[str, Any]]]) -> List[ContextSection]:
        if not context_data:
            return []

        selection_lines = []
        for item in context_data:
            if not isinstance(item, Mapping):
                continue
            line = self._format_context_item(item)
            if line:
                selection_lines.append(line)

        if not selection_lines:
            return []
        return [ContextSection(title="selection", lines=selection_lines, priority=10)]

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
