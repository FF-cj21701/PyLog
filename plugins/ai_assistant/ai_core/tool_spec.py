from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ToolSpec:
    name: str
    description: str
    args_schema: Dict[str, Any]
    display_name: Optional[str] = None
    source: str = "local"
    side_effect_level: str = "none"
    risk_level: str = "low"
    output_type: str = "text"
    requires_verification: bool = False
    requires_read_before_write: bool = False
    is_verification_tool: bool = False
    lifecycle_role: str = "normal"
    required_args: List[str] = field(default_factory=list)
    path_argument_names: List[str] = field(default_factory=lambda: ["filepath", "file_path"])
    capability_tags: List[str] = field(default_factory=list)
    domain_tags: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    usage_hint: str = ""
    server_name: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_model_description(self) -> str:
        parts = [self.description.strip()]

        tags = self.capability_tags + self.domain_tags
        if tags:
            parts.append(f"Tags: {', '.join(tags)}.")
        if self.keywords:
            parts.append(f"Keywords: {', '.join(self.keywords)}.")

        parts.append(f"Side effects: {self.side_effect_level}.")
        parts.append(f"Risk: {self.risk_level}.")
        parts.append(f"Output: {self.output_type}.")

        if self.requires_read_before_write:
            parts.append("Read the target before modifying it.")
        if self.requires_verification:
            parts.append("Run verification after use.")
        if self.is_verification_tool:
            parts.append("This tool is intended for verification.")
        if self.lifecycle_role != "normal":
            parts.append(f"Lifecycle role: {self.lifecycle_role}.")
        if self.server_name:
            parts.append(f"MCP server: {self.server_name}.")
        if self.usage_hint:
            parts.append(f"Usage hint: {self.usage_hint.strip()}")
        conditional_notes = self.describe_argument_rules()
        if conditional_notes:
            parts.append(conditional_notes)

        return " ".join(part for part in parts if part)

    def to_openai_tool(self) -> Dict[str, Any]:
        required = self.get_required_args()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.to_model_description(),
                "parameters": {
                    "type": "object",
                    "properties": self.args_schema,
                    "required": required,
                },
            },
        }

    def get_keywords(self) -> List[str]:
        return list(self.keywords)

    def get_required_args(self) -> List[str]:
        return list(self.required_args or self._infer_required_args())

    def get_argument_rules(self) -> List[Dict[str, Any]]:
        rules = self.metadata.get("argument_rules")
        if isinstance(rules, list):
            return [rule for rule in rules if isinstance(rule, dict)]
        return []

    def describe_argument_rules(self) -> str:
        notes: List[str] = []
        for rule in self.get_argument_rules():
            rule_type = str(rule.get("type") or "").strip()
            if rule_type == "exactly_one_of":
                fields = [str(name) for name in rule.get("fields", []) if str(name).strip()]
                if fields:
                    notes.append(f"Argument rule: provide exactly one of {', '.join(fields)}.")
            elif rule_type == "at_least_one_of":
                fields = [str(name) for name in rule.get("fields", []) if str(name).strip()]
                if fields:
                    notes.append(f"Argument rule: provide at least one of {', '.join(fields)}.")
            elif rule_type == "requires_when":
                trigger_arg = str(rule.get("arg") or "").strip()
                trigger_value = rule.get("equals")
                required_arg = str(rule.get("requires") or "").strip()
                if trigger_arg and required_arg:
                    trigger_text = "is provided" if trigger_value == "__non_empty__" else f"={trigger_value!r}"
                    notes.append(
                        f"Argument rule: when {trigger_arg} {trigger_text}, also provide {required_arg}."
                    )
        return " ".join(notes)

    def _infer_required_args(self) -> List[str]:
        required = []
        for param_name, param_schema in self.args_schema.items():
            if isinstance(param_schema, dict) and param_schema.get("nullable"):
                continue
            required.append(param_name)
        return required
