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
    MAX_RETRIEVED_CONTEXT_ITEMS = 6
    MAX_TOOL_FIELD_LENGTH = 180
    SECTION_POLICIES = {
        "selection": {"priority": 10, "max_lines": None, "drop_strategy": "keep"},
        "active_script_state": {"priority": 20, "max_lines": 12, "drop_strategy": "keep"},
        "plot_window_state": {"priority": 23, "max_lines": 12, "drop_strategy": "summarize"},
        "skills_summary": {"priority": 24, "max_lines": 10, "max_items": 8, "drop_strategy": "summarize"},
        "task_plan": {"priority": 25, "max_lines": 12, "drop_strategy": "summarize"},
        "recent_tool_results": {
            "priority": 30,
            "max_lines": 8,
            "max_items": MAX_RECENT_TOOL_RESULTS,
            "drop_strategy": "keep_failures",
        },
        "retrieved_context": {
            "priority": 40,
            "max_lines": 10,
            "max_items": MAX_RETRIEVED_CONTEXT_ITEMS,
            "drop_strategy": "relevance",
        },
        "conversation_summary": {"priority": 70, "max_lines": 10, "drop_strategy": "summarize"},
        "raw_outputs": {"priority": 90, "max_lines": 4, "drop_strategy": "truncate"},
    }

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
        plot_window_lines = []
        skills_summary_items = []
        skills_summary_meta = {}
        task_plan_lines = []
        tool_result_items = []
        retrieved_context_items = []
        conversation_summary_lines = []
        for item in context_data:
            if not isinstance(item, Mapping):
                continue
            line = self._format_context_item(item)
            if line:
                selection_lines.append(line)
            script_state = self._extract_script_state(item)
            if script_state:
                script_state_lines.extend(self._format_script_state(script_state))
            plot_window_state = self._extract_plot_window_state(item)
            if plot_window_state:
                plot_window_lines.extend(self._format_plot_window_state(plot_window_state))
            skills_summary = self._extract_skills_summary(item)
            if skills_summary:
                skills_summary_meta.update({
                    key: value
                    for key, value in skills_summary.items()
                    if key not in {"skills", "items"} and value not in (None, "", [], {})
                })
                for skill in skills_summary.get("skills") or skills_summary.get("items") or []:
                    if isinstance(skill, Mapping):
                        skills_summary_items.append(skill)
            task_plan = self._extract_task_plan(item)
            if task_plan:
                task_plan_lines.extend(self._format_task_plan(task_plan))
            tool_result_items.extend(self._extract_tool_result_items(item))
            retrieved_context_items.extend(self._extract_retrieved_context_items(item))
            conversation_summary = self._extract_conversation_summary(item)
            if conversation_summary:
                conversation_summary_lines.extend(self._format_conversation_summary(conversation_summary))

        sections = []
        if selection_lines:
            sections.append(self._make_section("selection", selection_lines))
        if script_state_lines:
            sections.append(self._make_section("active_script_state", script_state_lines))
        if plot_window_lines:
            sections.append(self._make_section("plot_window_state", plot_window_lines))
        skills_summary_lines = self._format_skills_summary(skills_summary_items, skills_summary_meta)
        if skills_summary_lines:
            sections.append(self._make_section("skills_summary", skills_summary_lines))
        if task_plan_lines:
            sections.append(self._make_section("task_plan", task_plan_lines))
        tool_result_lines = self._format_recent_tool_results(tool_result_items)
        if tool_result_lines:
            sections.append(self._make_section("recent_tool_results", tool_result_lines))
        retrieved_context_lines = self._format_retrieved_context(retrieved_context_items)
        if retrieved_context_lines:
            sections.append(self._make_section("retrieved_context", retrieved_context_lines))
        if conversation_summary_lines:
            sections.append(self._make_section("conversation_summary", conversation_summary_lines))
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

    def _extract_plot_window_state(self, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if isinstance(item.get("plot_window_state"), Mapping):
            return item.get("plot_window_state")
        item_type = item.get("type")
        if item_type in {"plot_window_state", "plot_state", "window_state", "active_plot"}:
            return item
        return None

    def _format_plot_window_state(self, state: Mapping[str, Any]) -> List[str]:
        lines = ["[Plot / Window State]"]
        active_window = state.get("active_window") if isinstance(state.get("active_window"), Mapping) else {}
        plot = state.get("plot") if isinstance(state.get("plot"), Mapping) else {}

        self._append_state_line(lines, "active_window_title", state.get("active_window_title") or active_window.get("title"))
        self._append_state_line(lines, "active_window_type", state.get("active_window_type") or active_window.get("type"))
        self._append_state_line(lines, "plot_title", state.get("plot_title") or plot.get("title") or state.get("title"))
        self._append_state_line(lines, "well", state.get("well") or state.get("well_name") or plot.get("well"))
        self._append_state_line(lines, "db_path", state.get("db_path") or plot.get("db_path"))
        self._append_state_line(lines, "depth_range", self._format_range(state.get("depth_range") or plot.get("depth_range")))
        self._append_state_line(lines, "track_count", state.get("track_count") or plot.get("track_count"))
        self._append_state_line(lines, "curve_count", state.get("curve_count") or plot.get("curve_count"))
        self._append_state_line(lines, "has_unsaved_changes", self._format_bool(state.get("has_unsaved_changes")))
        table = state.get("table") if isinstance(state.get("table"), Mapping) else {}
        self._append_state_line(lines, "table_rows", table.get("row_count"))
        self._append_state_line(lines, "table_columns", table.get("column_count"))
        if table.get("visible_columns"):
            self._append_state_line(lines, "visible_columns", self._format_name_list(table.get("visible_columns")))
        if table.get("selected_columns"):
            self._append_state_line(lines, "selected_columns", self._format_name_list(table.get("selected_columns")))
        if table.get("selected_rows"):
            self._append_state_line(lines, "selected_rows", self._format_name_list(table.get("selected_rows")))

        selected_curves = state.get("selected_curves") or plot.get("selected_curves")
        if selected_curves:
            self._append_state_line(lines, "selected_curves", self._format_name_list(selected_curves))

        tracks = state.get("tracks") or plot.get("tracks")
        if isinstance(tracks, list):
            for index, track in enumerate(tracks[:4], start=1):
                line = self._format_plot_track(index, track)
                if line:
                    lines.append(line)
            if len(tracks) > 4:
                lines.append(f"- omitted: {len(tracks) - 4} plot track(s)")

        return lines if len(lines) > 1 else []

    def _format_plot_track(self, index: int, track: Any) -> str:
        if isinstance(track, Mapping):
            name = track.get("name") or track.get("track_name") or f"Track {index}"
            curves = track.get("curves") or track.get("curve_names")
            depth_range = self._format_range(track.get("depth_range"))
            parts = [f"- track {index}: {self._truncate(name)}"]
            if curves:
                parts.append(f"curves: {self._format_name_list(curves)}")
            if depth_range:
                parts.append(f"depth_range: {depth_range}")
            return "; ".join(parts)
        return f"- track {index}: {self._truncate(track)}" if track else ""

    def _extract_skills_summary(self, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if isinstance(item.get("skills_summary"), Mapping):
            return item.get("skills_summary")
        if item.get("type") in {"skills_summary", "skill_summary", "enabled_skills"}:
            return item
        return None

    def _format_skills_summary(self, skills: List[Mapping[str, Any]], meta: Mapping[str, Any]) -> List[str]:
        if not skills and not meta:
            return []

        max_items = int(self._section_policy("skills_summary").get("max_items") or 8)
        lines = ["[Skills Summary]"]
        self._append_state_line(lines, "use_tool", "tool_read_skill(name='<skill_id>') before applying detailed skill guidance")
        total_count = meta.get("total_count") if meta.get("total_count") is not None else len(skills)
        self._append_state_line(lines, "enabled_count", total_count)

        disabled = meta.get("disabled_skills")
        if disabled:
            self._append_state_line(lines, "disabled_skills", self._format_name_list(disabled, max_items=6))

        for skill in skills[:max_items]:
            line = self._format_skill_summary_line(skill)
            if line:
                lines.append(line)
        if len(skills) > max_items:
            lines.append(f"- omitted: {len(skills) - max_items} skill summary item(s)")
        return lines if len(lines) > 1 else []

    def _format_skill_summary_line(self, skill: Mapping[str, Any]) -> str:
        skill_id = skill.get("id") or skill.get("name") or skill.get("skill")
        if not skill_id:
            return ""
        title = skill.get("title")
        description = self._first_text(skill.get("description"), skill.get("summary"))
        aliases = skill.get("aliases")
        parts = [f"- {self._truncate(skill_id)}"]
        if title and title != skill_id:
            parts.append(f"title: {self._truncate(title)}")
        if aliases:
            parts.append(f"aliases: {self._format_name_list(aliases, max_items=4)}")
        if description:
            parts.append(f"description: {self._truncate(description)}")
        return "; ".join(parts)

    def _extract_task_plan(self, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        item_type = item.get("type")
        if item_type == "task_plan":
            return item
        plan = item.get("task_plan") or item.get("plan")
        if isinstance(plan, Mapping):
            merged = dict(plan)
            for key in ("current_step_id", "plan_domain", "plan_source"):
                if item.get(key) is not None and key not in merged:
                    merged[key] = item.get(key)
            return merged
        return None

    def _format_task_plan(self, plan: Mapping[str, Any]) -> List[str]:
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            return []

        lines = ["[Task Plan]"]
        self._append_state_line(lines, "domain", plan.get("plan_domain") or plan.get("domain"))
        self._append_state_line(lines, "source", plan.get("plan_source") or plan.get("source"))
        current_step_id = plan.get("current_step_id")
        self._append_state_line(lines, "current_step_id", current_step_id)

        for index, step in enumerate(steps, start=1):
            if not isinstance(step, Mapping):
                continue
            lines.append(self._format_task_plan_step(index, step, current_step_id))
        return lines if len(lines) > 1 else []

    def _format_task_plan_step(self, index: int, step: Mapping[str, Any], current_step_id: Any) -> str:
        step_id = step.get("id") or step.get("kind") or f"step_{index}"
        status = step.get("status") or "pending"
        marker = " current" if current_step_id and str(step_id) == str(current_step_id) else ""
        title = self._truncate(step.get("title") or step.get("summary") or step_id)
        line = f"- {index}. [{status}{marker}] {step_id}: {title}"
        notes = self._first_text(step.get("notes"))
        if notes:
            line += f" (notes: {self._truncate(notes)})"
        return line

    def _extract_conversation_summary(self, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if isinstance(item.get("conversation_summary"), Mapping):
            return item.get("conversation_summary")
        if item.get("type") in {"conversation_summary", "history_summary"}:
            return item
        return None

    def _format_conversation_summary(self, summary: Mapping[str, Any]) -> List[str]:
        lines = ["[Conversation Summary]"]
        self._append_state_line(lines, "goal", self._first_text(summary.get("goal"), summary.get("current_goal")))
        for key, label in (
            ("decisions", "decisions"),
            ("completed", "completed"),
            ("user_preferences", "user_preferences"),
            ("open_items", "open_items"),
            ("notes", "notes"),
        ):
            value = summary.get(key)
            if value:
                self._append_state_line(lines, label, self._format_name_list(value, max_items=6))
        updated_at = summary.get("updated_at")
        if updated_at:
            self._append_state_line(lines, "updated_at", updated_at)
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

    def _extract_retrieved_context_items(self, item: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        item_type = item.get("type")
        if item_type == "retrieved_context":
            for key in ("items", "results", "contexts", "matches"):
                value = item.get(key)
                if isinstance(value, list):
                    return [entry for entry in value if isinstance(entry, Mapping)]
            return [item] if self._looks_like_retrieved_context(item) else []
        if item_type in {"search_result", "file_summary", "code_location"}:
            return [item]

        tool_name = item.get("tool_name") or item.get("tool") or item.get("command")
        result = item.get("result")
        if not tool_name or not isinstance(result, Mapping):
            return []
        return self._extract_retrieved_from_tool_result(str(tool_name), result)

    def _extract_retrieved_from_tool_result(self, tool_name: str, result: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        lowered = tool_name.lower()
        if not any(token in lowered for token in ("search", "grep", "find", "read_file", "symbol", "reference")):
            return []

        items = []
        for entry in self._iter_result_entries(result):
            items.extend(self._normalize_retrieved_entry(tool_name, entry))

        if not items and self._looks_like_retrieved_context(result):
            items.extend(self._normalize_retrieved_entry(tool_name, result))
        return items

    def _iter_result_entries(self, result: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        entries = []
        for key in ("results", "matches", "files", "items"):
            value = result.get(key)
            if isinstance(value, list):
                entries.extend(entry for entry in value if isinstance(entry, Mapping))
        return entries

    def _normalize_retrieved_entry(self, source: str, entry: Mapping[str, Any]) -> List[Mapping[str, Any]]:
        path = entry.get("path") or entry.get("filepath") or entry.get("file_path") or entry.get("filename")
        nested_matches = entry.get("matches")
        if isinstance(nested_matches, list) and nested_matches:
            normalized = []
            for match in nested_matches:
                if not isinstance(match, Mapping):
                    continue
                nested = dict(match)
                if path and not any(nested.get(key) for key in ("path", "filepath", "file_path", "filename")):
                    nested["path"] = path
                normalized.extend(self._normalize_retrieved_entry(source, nested))
            return normalized

        normalized = dict(entry)
        normalized.setdefault("source", source)
        if path:
            normalized["path"] = path
        return [normalized] if self._looks_like_retrieved_context(normalized) else []

    def _looks_like_retrieved_context(self, item: Mapping[str, Any]) -> bool:
        return any(
            item.get(key) is not None
            for key in ("path", "filepath", "file_path", "filename", "summary", "snippet", "line", "line_number", "symbol")
        )

    def _format_retrieved_context(self, items: List[Mapping[str, Any]]) -> List[str]:
        selected, omitted_count = self._select_retrieved_context(items)
        if not selected:
            return []

        lines = ["[Retrieved Context]"]
        for item in selected:
            line = self._format_retrieved_context_line(item)
            if line:
                lines.append(line)
        if omitted_count:
            lines.append(f"- omitted: {omitted_count} lower-priority retrieved item(s)")
        return lines if len(lines) > 1 else []

    def _select_retrieved_context(self, items: List[Mapping[str, Any]]) -> tuple[List[Mapping[str, Any]], int]:
        max_items = int(self._section_policy("retrieved_context").get("max_items") or self.MAX_RETRIEVED_CONTEXT_ITEMS)
        if len(items) <= max_items:
            return items, 0

        indexed = list(enumerate(items))
        indexed.sort(key=lambda pair: (-self._retrieved_context_rank(pair[1]), pair[0]))
        selected_indexes = sorted(index for index, _item in indexed[:max_items])
        return [items[index] for index in selected_indexes], len(items) - len(selected_indexes)

    def _retrieved_context_rank(self, item: Mapping[str, Any]) -> float:
        score = item.get("score")
        try:
            rank = float(score) if score is not None else 0.0
        except (TypeError, ValueError):
            rank = 0.0
        if item.get("path") or item.get("filepath") or item.get("file_path") or item.get("filename"):
            rank += 0.25
        if item.get("line") or item.get("line_number"):
            rank += 0.15
        if item.get("symbol"):
            rank += 0.1
        return rank

    def _format_retrieved_context_line(self, item: Mapping[str, Any]) -> str:
        source = item.get("source") or item.get("type") or "retrieved"
        path = item.get("path") or item.get("filepath") or item.get("file_path") or item.get("filename")
        line_number = item.get("line_number") or item.get("lineno")
        symbol = item.get("symbol") or item.get("name") or item.get("matched_symbol")
        score = item.get("score")
        summary = self._first_text(item.get("summary"), item.get("description"), item.get("content"))
        snippet = self._first_text(item.get("snippet"), item.get("line_text"), item.get("line"), item.get("context"))

        parts = [f"- {source}"]
        if path:
            location = self._truncate(path)
            if line_number and not isinstance(line_number, str):
                location += f":{line_number}"
            parts.append(f"path: {location}")
        elif line_number:
            parts.append(f"line: {line_number}")
        if symbol:
            parts.append(f"symbol: {self._truncate(symbol)}")
        if score is not None:
            parts.append(f"score: {score}")
        if summary:
            summary_text, was_truncated = self._truncate_with_flag(summary)
            parts.append(f"summary: {summary_text}")
            if was_truncated:
                parts.append("truncated: summary shortened")
        if snippet and snippet != summary:
            snippet_text, was_truncated = self._truncate_with_flag(snippet)
            parts.append(f"snippet: {snippet_text}")
            if was_truncated:
                parts.append("truncated: snippet shortened")
        return "; ".join(part for part in parts if part)

    def _format_recent_tool_results(self, items: List[Mapping[str, Any]]) -> List[str]:
        selected, omitted_count = self._select_recent_tool_results(items)
        if not selected:
            return []

        lines = ["[Recent Tool Results]"]
        for item in selected:
            line = self._format_tool_result_line(item)
            if line:
                lines.append(line)
        if omitted_count:
            lines.append(f"- omitted: {omitted_count} older tool result(s)")
        return lines if len(lines) > 1 else []

    def _select_recent_tool_results(self, items: List[Mapping[str, Any]]) -> tuple[List[Mapping[str, Any]], int]:
        max_items = int(self._section_policy("recent_tool_results").get("max_items") or self.MAX_RECENT_TOOL_RESULTS)
        if len(items) <= max_items:
            return items, 0

        selected_indexes = set()
        for index in range(len(items) - 1, -1, -1):
            if self._tool_result_failed(items[index]):
                selected_indexes.add(index)
            if len(selected_indexes) >= max_items:
                break

        for index in range(len(items) - 1, -1, -1):
            if len(selected_indexes) >= max_items:
                break
            selected_indexes.add(index)

        return [items[index] for index in sorted(selected_indexes)], len(items) - len(selected_indexes)

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
            summary_text, was_truncated = self._truncate_with_flag(summary)
            parts.append(summary_text)
            if was_truncated:
                parts.append("truncated: summary shortened")

        error = self._first_text(item.get("error"), result_map.get("error"), result_map.get("stderr"))
        if error and status != "ok":
            error_text, was_truncated = self._truncate_with_flag(error)
            parts.append(f"error: {error_text}")
            if was_truncated:
                parts.append("truncated: error shortened")

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

    def _format_range(self, value: Any) -> str:
        if value is None or value == "":
            return ""
        if isinstance(value, Mapping):
            start = value.get("min") if value.get("min") is not None else value.get("start")
            end = value.get("max") if value.get("max") is not None else value.get("end")
            unit = value.get("unit") or ""
            if start is not None and end is not None:
                return f"{start}~{end}{unit}"
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return f"{value[0]}~{value[1]}"
        return self._truncate(value)

    def _format_name_list(self, value: Any, max_items: int = 8) -> str:
        if isinstance(value, str):
            return self._truncate(value)
        if not isinstance(value, Iterable):
            return self._truncate(value)
        items = [str(item) for item in list(value)[:max_items]]
        text = ", ".join(items)
        try:
            total = len(value)
        except TypeError:
            total = len(items)
        if total > max_items:
            text += f", +{total - max_items} more"
        return self._truncate(text)

    def _truncate(self, value: Any) -> str:
        return self._truncate_with_flag(value)[0]

    def _truncate_with_flag(self, value: Any) -> tuple[str, bool]:
        text = " ".join(str(value).split())
        if len(text) <= self.MAX_TOOL_FIELD_LENGTH:
            return text, False
        return text[: self.MAX_TOOL_FIELD_LENGTH - 3].rstrip() + "...", True

    def _make_section(self, title: str, lines: List[str]) -> ContextSection:
        policy = self._section_policy(title)
        return ContextSection(
            title=title,
            lines=self._apply_section_budget(title, lines),
            priority=int(policy.get("priority", 100)),
        )

    def _section_policy(self, title: str) -> Mapping[str, Any]:
        return self.SECTION_POLICIES.get(title, {"priority": 100, "max_lines": None, "drop_strategy": "truncate"})

    def _apply_section_budget(self, title: str, lines: List[str]) -> List[str]:
        policy = self._section_policy(title)
        max_lines = policy.get("max_lines")
        if not max_lines or len(lines) <= int(max_lines):
            return lines

        limit = int(max_lines)
        omitted_count = len(lines) - limit + 1
        kept = list(lines[: max(limit - 1, 0)])
        if kept:
            kept.append(f"- omitted: {omitted_count} {title} line(s)")
        return kept

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
