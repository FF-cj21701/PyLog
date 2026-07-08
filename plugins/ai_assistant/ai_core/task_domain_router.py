from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set


class TaskDomainRouter:
    """Route tool visibility by coarse task domain while keeping essential fallbacks."""

    DOMAIN_KEYWORDS = {
        "code": (
            "code",
            "source",
            "function",
            "class",
            "bug",
            "fix",
            "refactor",
            "test",
            "lint",
            "import",
            "patch",
            "filepath",
            "代码",
            "函数",
            "类",
            "修复",
            "重构",
            "测试",
            "补丁",
            "文件",
        ),
        "script": (
            "script",
            "python",
            "editor_id",
            "scripts_user",
            "run_script",
            "terminal",
            "脚本",
            "运行脚本",
            "编辑器",
            "预览",
        ),
        "geoscience": (
            "pylog",
            "well",
            "curve",
            "curves",
            "log",
            "las",
            "dlis",
            "depth",
            "formation",
            "lithology",
            "porosity",
            "saturation",
            "petrophysics",
            "geology",
            "plot well",
            "analysis",
            "stats",
            "statistics",
            "correlation",
            "crossplot",
            "histogram",
            "测井",
            "井",
            "曲线",
            "深度",
            "地学",
            "岩性",
            "孔隙度",
            "含水饱和度",
            "作图",
            "分析",
            "统计",
            "相关性",
            "计算",
            "交会图",
        ),
    }

    ALWAYS_INCLUDE_TOOL_NAMES = {
        "finish",
        "get_help",
        "create_task_plan",
        "get_task_plan",
        "update_task_plan",
    }

    ALWAYS_INCLUDE_CAPABILITY_TAGS = {
        "verification",
        "auto_strategy",
        "lifecycle",
        "planning",
        "task_planning",
        "agent_page",
    }

    def detect_domains(
        self,
        prompt: str = "",
        history: Optional[Sequence[Sequence[str]]] = None,
        state=None,
    ) -> Set[str]:
        text_parts: List[str] = []
        if prompt:
            text_parts.append(str(prompt))
        if state and getattr(state, "current_task", None):
            text_parts.append(str(state.current_task))
        if history:
            for item in history[-4:]:
                if len(item) >= 2 and item[1]:
                    text_parts.append(str(item[1]))

        text = "\n".join(text_parts).lower()
        normalized = re.sub(r"\s+", " ", text)
        detected = {
            domain
            for domain, keywords in self.DOMAIN_KEYWORDS.items()
            if any(keyword in normalized for keyword in keywords)
        }

        if not detected:
            return {"code"}
        return detected

    def route_specs(
        self,
        specs: Iterable[object],
        prompt: str = "",
        history: Optional[Sequence[Sequence[str]]] = None,
        state=None,
    ) -> List[object]:
        specs = list(specs)
        self._last_prompt = prompt or ""
        self._last_history = history or []
        self._last_state = state
        detected = self.detect_domains(prompt=prompt, history=history, state=state)
        routed = []

        for spec in specs:
            if self._should_include_spec(spec, detected):
                routed.append(spec)

        if not routed:
            return specs
        return routed

    def build_guidance(
        self,
        prompt: str = "",
        history: Optional[Sequence[Sequence[str]]] = None,
        state=None,
    ) -> Optional[str]:
        detected = sorted(self.detect_domains(prompt=prompt, history=history, state=state))
        if not detected:
            return None

        if detected == ["code"]:
            return (
                "Detected task domain: code. Prefer code navigation, patch, file edit, and verification tools "
                "before unrelated script or geoscience tools."
            )
        if detected == ["script"]:
            return (
                "Detected task domain: script. Prefer script editor, script execution, and script verification tools "
                "before unrelated project-code or geoscience tools."
            )
        if detected == ["geoscience"]:
            return (
                "Detected task domain: geoscience. Prefer PyLog well, curve, plot, and analysis tools first, "
                "then fall back to general code or script tools only if needed."
            )
        return (
            "Detected mixed task domains: "
            + ", ".join(detected)
            + ". Prefer tools that match the active domain while keeping verification and lifecycle tools available."
        )

    def _should_include_spec(self, spec, detected_domains: Set[str]) -> bool:
        name = getattr(spec, "name", "")
        if name in self.ALWAYS_INCLUDE_TOOL_NAMES:
            return True

        capability_tags = set(getattr(spec, "capability_tags", []) or [])
        if capability_tags & self.ALWAYS_INCLUDE_CAPABILITY_TAGS:
            return True

        domain_tags = set(getattr(spec, "domain_tags", []) or [])
        if not domain_tags:
            return True

        expanded_detected = set(detected_domains)
        if "geoscience" in expanded_detected:
            expanded_detected.add("pylog")

        if domain_tags & expanded_detected:
            return True

        if "script" in expanded_detected and "code" in domain_tags:
            return True

        if self._spec_keyword_matches(spec):
            return True

        return False

    def _spec_keyword_matches(self, spec) -> bool:
        keywords = [str(keyword).strip().lower() for keyword in (getattr(spec, "keywords", []) or []) if str(keyword).strip()]
        if not keywords:
            return False

        haystack_parts = []
        prompt = getattr(self, "_last_prompt", "")
        if prompt:
            haystack_parts.append(str(prompt))
        history = getattr(self, "_last_history", None) or []
        for item in history[-4:]:
            if len(item) >= 2 and item[1]:
                haystack_parts.append(str(item[1]))
        state = getattr(self, "_last_state", None)
        if state and getattr(state, "current_task", None):
            haystack_parts.append(str(state.current_task))

        if not haystack_parts:
            return False

        haystack = re.sub(r"\s+", " ", "\n".join(haystack_parts).lower())
        return any(keyword in haystack for keyword in keywords)
