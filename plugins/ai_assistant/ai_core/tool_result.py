from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Mapping, Optional


@dataclass
class ToolResult:
    ok: bool
    tool_name: str
    source: str = "local"
    summary: str = ""
    data: Any = None
    error: Optional[str] = None
    content: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    raw_result: Any = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.update(self.metadata)
        return payload


def normalize_tool_result(tool_name: str, result: Any, source: str = "local") -> ToolResult:
    """Normalize tool outputs to a common ToolResult envelope."""
    if isinstance(result, ToolResult):
        normalized = result.to_dict()
        normalized.setdefault("tool_name", tool_name)
        normalized.setdefault("source", source)
        return _build_tool_result(normalized)

    if isinstance(result, Mapping):
        normalized = dict(result)
        normalized.setdefault("tool_name", tool_name)
        normalized.setdefault("source", source)
        ok = normalized.get("ok")
        if ok is None:
            ok = not bool(normalized.get("error"))
        normalized["ok"] = bool(ok)
        if "content" not in normalized:
            derived_content = _derive_content(normalized)
            if derived_content:
                normalized["content"] = derived_content
        if "summary" not in normalized:
            normalized["summary"] = _derive_summary(normalized)
        if "error" not in normalized and not normalized["ok"]:
            normalized["error"] = normalized.get("summary") or "Tool execution failed"
        return _build_tool_result(normalized, raw_result=result)

    if isinstance(result, str):
        stripped = result.strip()
        ok = not stripped.lower().startswith("error") and "failed" not in stripped.lower()
        return ToolResult(
            ok=ok,
            tool_name=tool_name,
            source=source,
            content=result,
            data=result,
            summary=stripped[:4000] if stripped else f"{tool_name} completed",
            error=None if ok else stripped,
            raw_result=result,
        )

    ok = result is not None
    return ToolResult(
        ok=ok,
        tool_name=tool_name,
        source=source,
        data=result,
        summary=f"{tool_name} completed" if ok else f"{tool_name} returned no result",
        error=None if ok else f"{tool_name} returned no result",
        raw_result=result,
    )


def serialize_tool_result(result: Any) -> str:
    import json

    if isinstance(result, str):
        return result
    return json.dumps(tool_result_to_dict(result), ensure_ascii=False)


def error_tool_result(tool_name: str, error: str, source: str = "local", **extra: Any) -> ToolResult:
    payload: Dict[str, Any] = {
        "ok": False,
        "tool_name": tool_name,
        "source": source,
        "error": error,
        "summary": error,
    }
    payload.update(extra)
    return _build_tool_result(payload)


def tool_result_to_dict(result: Any) -> Dict[str, Any]:
    if isinstance(result, ToolResult):
        return result.to_dict()
    return normalize_tool_result("unknown_tool", result).to_dict()


def tool_result_ok(result: Any) -> bool:
    if isinstance(result, ToolResult):
        return bool(result.ok)
    return bool(normalize_tool_result("unknown_tool", result).ok)


def tool_result_error(result: Any) -> Optional[str]:
    normalized = normalize_tool_result("unknown_tool", result)
    return normalized.error or normalized.summary


def tool_result_summary(result: Any) -> str:
    return normalize_tool_result("unknown_tool", result).summary


def tool_result_content(result: Any, *, fallback_to_summary: bool = False) -> str:
    normalized = normalize_tool_result("unknown_tool", result)
    payload = normalized.to_dict()
    for key in ("content", "final_answer", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if fallback_to_summary:
        return normalized.summary or ""
    return ""


def _build_tool_result(payload: Dict[str, Any], raw_result: Any = None) -> ToolResult:
    payload = dict(payload)
    metadata = dict(payload.pop("metadata", {}) or {})
    known = {
        "ok",
        "tool_name",
        "source",
        "summary",
        "data",
        "error",
        "content",
        "artifacts",
        "verification",
        "raw_result",
    }
    for key in list(payload.keys()):
        if key not in known:
            metadata[key] = payload.pop(key)

    return ToolResult(
        ok=bool(payload.get("ok")),
        tool_name=str(payload.get("tool_name") or "unknown_tool"),
        source=str(payload.get("source") or "local"),
        summary=str(payload.get("summary") or _derive_summary({**metadata, **payload})),
        data=payload.get("data"),
        error=payload.get("error"),
        content=payload.get("content"),
        artifacts=list(payload.get("artifacts") or []),
        verification=payload.get("verification"),
        raw_result=payload.get("raw_result", raw_result),
        metadata=metadata,
    )


def _derive_summary(result: Mapping[str, Any]) -> str:
    for key in ("summary", "message", "final_answer", "content", "error"):
        value = result.get(key)
        if value:
            return str(value)
    return "Tool execution succeeded" if result.get("ok") else "Tool execution failed"


def _derive_content(result: Mapping[str, Any]) -> Optional[str]:
    for key in ("content", "final_answer"):
        value = result.get(key)
        if value:
            return str(value)
    return None
