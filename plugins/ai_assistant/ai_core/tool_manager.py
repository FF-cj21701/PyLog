from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from .tool_dispatcher import ToolDispatcher
from .tool_selection import ToolSelectionStrategy


class ToolManager:
    """Stable tool boundary for inventory, selection, routing, and execution."""

    def __init__(self, tools: Optional[Iterable[Any]] = None, dispatcher: Optional[ToolDispatcher] = None):
        self.dispatcher = dispatcher or ToolDispatcher(tools or [])

    @property
    def tools(self):
        return self.dispatcher.tools

    def set_tools(self, tools: Iterable[Any]) -> None:
        self.dispatcher.set_tools(tools)

    def register_tool(self, tool: Any, *, replace_existing: bool = True) -> None:
        """Register one tool instance by name."""
        tool_name = getattr(tool, "name", None)
        if not tool_name:
            raise ValueError("Tool must expose a non-empty name")

        current_tools = list(self.tools)
        existing_index = self._find_tool_index(tool_name, current_tools)
        if existing_index is not None:
            if not replace_existing:
                raise ValueError(f"Tool already registered: {tool_name}")
            current_tools[existing_index] = tool
        else:
            current_tools.append(tool)
        self.set_tools(current_tools)

    def register_tools(self, tools: Iterable[Any], *, replace_existing: bool = True) -> None:
        for tool in tools:
            self.register_tool(tool, replace_existing=replace_existing)

    def remove_tool(self, tool_name: str) -> bool:
        current_tools = list(self.tools)
        next_tools = [tool for tool in current_tools if getattr(tool, "name", None) != tool_name]
        if len(next_tools) == len(current_tools):
            return False
        self.set_tools(next_tools)
        return True

    def replace_tools_by_source(self, source: str, tools: Iterable[Any]) -> None:
        remaining_tools = []
        for tool in self.tools:
            spec = getattr(tool, "spec", None)
            tool_source = getattr(spec, "source", getattr(tool, "source", None))
            if tool_source != source:
                remaining_tools.append(tool)
        self.set_tools(remaining_tools)
        self.register_tools(tools, replace_existing=True)

    def find_tool(self, tool_name: str):
        return self.dispatcher.find_tool(tool_name)

    def get_spec(self, tool_name: str):
        return self.dispatcher.get_spec(tool_name)

    def list_specs(self):
        return self.dispatcher.list_specs()

    def list_specs_by_source(self, source: Optional[str] = None):
        return self.dispatcher.list_specs_by_source(source)

    def list_specs_by_domain(self, domain_tag: str):
        return [spec for spec in self.list_specs() if domain_tag in set(spec.domain_tags)]

    def list_specs_by_capability(self, capability_tag: str):
        return [spec for spec in self.list_specs() if capability_tag in set(spec.capability_tags)]

    def list_ranked_specs(self, state=None, strategy: Optional[ToolSelectionStrategy] = None, prompt: str = "", history=None):
        return self.dispatcher.list_ranked_specs(state=state, strategy=strategy, prompt=prompt, history=history)

    def build_tool_configs(
        self,
        *,
        state=None,
        strategy: Optional[ToolSelectionStrategy] = None,
        router=None,
        prompt: str = "",
        history=None,
        active_tool_names: Optional[Iterable[str]] = None,
    ):
        """Return model-ready tool configs after selection and optional domain routing."""
        ranked_specs = self.list_ranked_specs(state=state, strategy=strategy, prompt=prompt, history=history)
        active = None
        if active_tool_names is not None:
            active = {str(name) for name in active_tool_names if str(name).strip()}
        routed_specs = ranked_specs
        if router is not None:
            routed_specs = router.route_specs(
                ranked_specs,
                prompt=prompt,
                history=history or [],
                state=state,
            )
        if active is not None:
            routed_names = {spec.name for spec in routed_specs}
            routed_specs = list(routed_specs)
            routed_specs.extend(spec for spec in ranked_specs if spec.name in active and spec.name not in routed_names)
            routed_specs = [spec for spec in routed_specs if spec.name in active]
        return [spec.to_openai_tool() for spec in routed_specs]

    def search_specs(self, query: str = "", domain: Optional[str] = None, capability: Optional[str] = None, limit: int = 5):
        """Search tool specs and return compact index entries ordered by relevance."""
        query_terms = self._tokenize(query)
        domain_filter = str(domain or "").strip().lower()
        capability_filter = str(capability or "").strip().lower()
        try:
            safe_limit = max(1, min(int(limit or 5), 20))
        except Exception:
            safe_limit = 5

        scored = []
        for spec in self.list_specs():
            if domain_filter and domain_filter not in {str(tag).lower() for tag in spec.domain_tags}:
                continue
            if capability_filter and capability_filter not in {str(tag).lower() for tag in spec.capability_tags}:
                continue
            score = self._score_spec(spec, query_terms)
            if query_terms and score <= 0:
                continue
            entry = spec.to_index_entry()
            entry["score"] = score
            scored.append((score, spec.name, entry))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _score, _name, entry in scored[:safe_limit]]

    def describe_inventory(self):
        """Return lightweight metadata for UI/debugging without exposing tool objects."""
        inventory = []
        for spec in self.list_specs():
            entry = spec.to_index_entry()
            entry.update(
                {
                    "risk_level": spec.risk_level,
                    "output_type": spec.output_type,
                    "requires_verification": spec.requires_verification,
                    "requires_read_before_write": spec.requires_read_before_write,
                    "is_verification_tool": spec.is_verification_tool,
                    "lifecycle_role": spec.lifecycle_role,
                }
            )
            inventory.append(entry)
        return inventory

    def summarize_inventory(self):
        """Return compact inventory stats for context and diagnostics."""
        summary = {
            "total": 0,
            "by_source": {},
            "by_risk": {},
            "by_side_effect": {},
            "domain_tags": [],
            "capability_tags": [],
            "keywords": [],
        }
        domain_tags = set()
        capability_tags = set()
        keywords = set()
        for spec in self.list_specs():
            summary["total"] += 1
            self._increment(summary["by_source"], spec.source)
            self._increment(summary["by_risk"], spec.risk_level)
            self._increment(summary["by_side_effect"], spec.side_effect_level)
            domain_tags.update(spec.domain_tags)
            capability_tags.update(spec.capability_tags)
            keywords.update(getattr(spec, "keywords", []) or [])

        summary["domain_tags"] = sorted(domain_tags)
        summary["capability_tags"] = sorted(capability_tags)
        summary["keywords"] = sorted(keywords)
        return summary

    def get_inventory_payload(self):
        return {
            "summary": self.summarize_inventory(),
            "tools": self.describe_inventory(),
        }

    async def execute(self, tool_name: str, args: Optional[Dict[str, Any]] = None):
        return await self.dispatcher.execute(tool_name, args)

    @staticmethod
    def _find_tool_index(tool_name: str, tools: Iterable[Any]):
        for index, tool in enumerate(tools):
            if getattr(tool, "name", None) == tool_name:
                return index
        return None

    @staticmethod
    def _increment(counter: Dict[str, int], key: Optional[str]) -> None:
        safe_key = str(key or "unknown")
        counter[safe_key] = counter.get(safe_key, 0) + 1

    @staticmethod
    def _tokenize(text: str):
        return [token for token in re.split(r"[^a-zA-Z0-9_]+", str(text or "").lower()) if token]

    @classmethod
    def _score_spec(cls, spec, query_terms) -> int:
        if not query_terms:
            return 1

        name = str(spec.name or "").lower()
        display_name = str(spec.display_name or "").lower()
        description = str(spec.description or "").lower()
        keywords = [str(item).lower() for item in (getattr(spec, "keywords", []) or [])]
        capability_tags = [str(item).lower() for item in (getattr(spec, "capability_tags", []) or [])]
        domain_tags = [str(item).lower() for item in (getattr(spec, "domain_tags", []) or [])]
        preferred_for = [str(item).lower() for item in (spec.metadata.get("preferred_for") or [])]
        searchable = " ".join(
            [
                name,
                display_name,
                description,
                " ".join(keywords),
                " ".join(capability_tags),
                " ".join(domain_tags),
                " ".join(preferred_for),
            ]
        )

        score = cls._safe_int(spec.metadata.get("search_weight"), default=0)
        for term in query_terms:
            if term == name:
                score += 20
            if term in name:
                score += 12
            if display_name and term in display_name:
                score += 8
            if any(term in keyword for keyword in keywords):
                score += 8
            if any(term == tag or term in tag for tag in capability_tags):
                score += 6
            if any(term == tag or term in tag for tag in domain_tags):
                score += 5
            if any(term in phrase for phrase in preferred_for):
                score += 10
            if term in description:
                score += 2
            if term in searchable:
                score += 1
        if spec.risk_level == "high" and spec.side_effect_level in {"external", "execution"}:
            score -= 4
        return score

    @staticmethod
    def _safe_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except Exception:
            return default
